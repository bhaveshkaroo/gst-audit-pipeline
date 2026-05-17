"""
3-Way ITC Matching Algorithm
==============================
High-performance vectorized reconciliation engine using pandas/numpy.

Matches: PurchaseRegisterBooks x GSTR-2B (static) x GSTR-2A (dynamic)
Key:     Normalized GSTIN + Fuzzy Invoice Number
Tolerance: +/- Rs.1 on total tax amounts
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set

import numpy as np
import pandas as pd

from .models import MatchBucket, BUCKET_DESCRIPTIONS

logger = logging.getLogger(__name__)

_TAX_TOLERANCE = 1.0

# ═══════════════════════════════════════════════════════════════
#  Result Container
# ═══════════════════════════════════════════════════════════════

@dataclass
class ReconciliationResult:
    """Container for the complete reconciliation output."""
    consolidated: pd.DataFrame = field(default_factory=pd.DataFrame)
    perfect_matches: pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_in_portal: pd.DataFrame = field(default_factory=pd.DataFrame)
    unclaimed_in_books: pd.DataFrame = field(default_factory=pd.DataFrame)
    amount_mismatches: pd.DataFrame = field(default_factory=pd.DataFrame)
    timing_differences: pd.DataFrame = field(default_factory=pd.DataFrame)
    defaulting_suppliers: List[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def print_summary(self):
        sep = "=" * 72
        print(f"\n{sep}")
        print("  ITC RECONCILIATION SUMMARY")
        print(sep)
        for bucket, count in self.summary.get("bucket_counts", {}).items():
            desc = BUCKET_DESCRIPTIONS.get(MatchBucket(bucket), "")[:60]
            print(f"  {bucket:30s} : {count:>6d}  | {desc}")
        print(f"  {'':30s}   {'------':>6s}")
        print(f"  {'TOTAL':30s} : {self.summary.get('total_records', 0):>6d}")
        
        print(f"\n  Total Books ITC               : Rs. {self.summary.get('total_books_itc', 0):>12,.2f}")
        print(f"  Total Portal Eligible ITC     : Rs. {self.summary.get('total_portal_itc', 0):>12,.2f}")
        
        total_var = self.summary.get("total_variance", 0)
        print(f"\n  Total Tax Variance (D bucket) : Rs. {total_var:>12,.2f}")
        print(f"  Defaulting Suppliers          : {len(self.defaulting_suppliers):>6d}")
        itc_at_risk = self.summary.get("itc_at_risk", 0)
        print(f"\n  ITC at Risk (B+D+E buckets)   : Rs. {itc_at_risk:>12,.2f}")
        print(sep)


# ═══════════════════════════════════════════════════════════════
#  Core ITC Matcher
# ═══════════════════════════════════════════════════════════════

class ITCMatcher:
    def __init__(self, tax_tolerance: float = _TAX_TOLERANCE):
        self.tax_tolerance = tax_tolerance

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize core columns for the outer merge."""
        out = df.copy()
        
        # Ensure base columns exist
        for col in ["supplier_gstin", "invoice_no", "cgst", "sgst", "igst"]:
            if col not in out.columns:
                out[col] = "" if col in ["supplier_gstin", "invoice_no"] else 0.0
                
        # Numeric parsing
        for col in ["cgst", "sgst", "igst"]:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
            
        # Total Tax sum BEFORE any filters (Bug 3 prep)
        out['total_tax'] = out['cgst'] + out['sgst'] + out['igst']

        # Non-destructive DQ: Strip spaces & uppercase
        out['supplier_gstin'] = out['supplier_gstin'].astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        out['invoice_no'] = out['invoice_no'].astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        
        return out

    def reconcile(
        self,
        books_df: pd.DataFrame,
        gstr2b_df: pd.DataFrame,
        gstr2a_df: Optional[pd.DataFrame] = None,
    ) -> ReconciliationResult:
        logger.info("Starting ITC reconciliation")

        books = self._prepare(books_df)
        portal = self._prepare(gstr2b_df)
        
        # BUG 1 & 2 FIX: True Outer Merge exposing all 5 buckets directly
        merged = pd.merge(
            books, 
            portal, 
            on=['supplier_gstin', 'invoice_no'], 
            how='outer', 
            suffixes=('_books', '_portal')
        )
        
        # Extract tax totals and identify missing values
        merged['books_total_tax'] = merged['total_tax_books'].fillna(0.0)
        merged['portal_total_tax'] = merged['total_tax_portal'].fillna(0.0)
        merged['tax_variance'] = merged['portal_total_tax'] - merged['books_total_tax']
        
        is_books_missing = merged['total_tax_books'].isna()
        is_portal_missing = merged['total_tax_portal'].isna()
        
        # Classification Engine
        merged['match_bucket'] = MatchBucket.D_AMOUNT_MISMATCH.value  # Default fallback
        
        # Bucket C: Unclaimed in Books (Books isna)
        merged.loc[is_books_missing, 'match_bucket'] = MatchBucket.C_UNCLAIMED_IN_BOOKS.value
        
        # Bucket B: Missing in Portal (Portal isna)
        merged.loc[is_portal_missing, 'match_bucket'] = MatchBucket.B_MISSING_IN_PORTAL.value
        
        # Bucket A and D: Both present
        both_present = ~is_books_missing & ~is_portal_missing
        perfect = both_present & (merged['tax_variance'].abs() <= self.tax_tolerance)
        merged.loc[perfect, 'match_bucket'] = MatchBucket.A_PERFECT_MATCH.value
        
        # Bucket E: Timing Differences (Verify Bucket B against GSTR-2A)
        if gstr2a_df is not None:
            g2a = self._prepare(gstr2a_df)
            g2a_keys = set(zip(g2a['supplier_gstin'], g2a['invoice_no']))
            
            b_mask = merged['match_bucket'] == MatchBucket.B_MISSING_IN_PORTAL.value
            for idx, row in merged[b_mask].iterrows():
                if (row['supplier_gstin'], row['invoice_no']) in g2a_keys:
                    merged.at[idx, 'match_bucket'] = MatchBucket.E_TIMING_DIFFERENCE.value

        # Descriptive remarks
        merged["remarks"] = merged["match_bucket"].map(
            {b.value: d for b, d in BUCKET_DESCRIPTIONS.items()}
        ).fillna("")

        # ── Build Result ──
        return self._build_result(merged)

    def _build_result(self, consolidated: pd.DataFrame) -> ReconciliationResult:
        buckets = {}
        for b in MatchBucket:
            buckets[b] = consolidated[consolidated["match_bucket"] == b.value].copy()

        bucket_counts = {b.value: len(buckets[b]) for b in MatchBucket}

        b_df = buckets[MatchBucket.B_MISSING_IN_PORTAL]
        defaulting = sorted(b_df['supplier_gstin'].dropna().unique().tolist()) if 'supplier_gstin' in b_df.columns else []

        at_risk = sum(
            buckets[b]["books_total_tax"].sum()
            for b in [MatchBucket.B_MISSING_IN_PORTAL, MatchBucket.D_AMOUNT_MISMATCH, MatchBucket.E_TIMING_DIFFERENCE]
        )

        total_var = buckets[MatchBucket.D_AMOUNT_MISMATCH]["tax_variance"].sum()
        
        total_books_itc = consolidated["books_total_tax"].sum()
        total_portal_itc = consolidated["portal_total_tax"].sum()

        return ReconciliationResult(
            consolidated=consolidated,
            perfect_matches=buckets[MatchBucket.A_PERFECT_MATCH],
            missing_in_portal=buckets[MatchBucket.B_MISSING_IN_PORTAL],
            unclaimed_in_books=buckets[MatchBucket.C_UNCLAIMED_IN_BOOKS],
            amount_mismatches=buckets[MatchBucket.D_AMOUNT_MISMATCH],
            timing_differences=buckets[MatchBucket.E_TIMING_DIFFERENCE],
            defaulting_suppliers=defaulting,
            summary={
                "total_records": len(consolidated),
                "bucket_counts": bucket_counts,
                "total_variance": round(float(total_var), 2),
                "itc_at_risk": round(float(at_risk), 2),
                "total_books_itc": round(float(total_books_itc), 2),
                "total_portal_itc": round(float(total_portal_itc), 2),
                "defaulting_supplier_count": len(defaulting),
            },
        )
