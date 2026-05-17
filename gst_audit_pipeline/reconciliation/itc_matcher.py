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

class ITCMatcher:
    def __init__(self, tax_tolerance: float = _TAX_TOLERANCE):
        self.tax_tolerance = tax_tolerance

    def _validate_books(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 2: Validate books with strict DQ rules."""
        out = df.copy()
        for col in ["supplier_gstin", "invoice_no"]:
            if col not in out.columns: out[col] = ""
        for col in ["cgst", "sgst", "igst", "taxable_value"]:
            if col not in out.columns: out[col] = 0.0
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
            
        if 'invoice_date' in out.columns:
            out['invoice_date'] = pd.to_datetime(out['invoice_date'], errors='coerce')
        else:
            out['invoice_date'] = pd.NaT

        date_cutoff = pd.Timestamp('2025-03-31')
        gstin_re = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'

        # Standardize string for reliable regex
        out['supplier_gstin'] = out['supplier_gstin'].astype(str).str.strip().str.upper()

        mask = (
            (out['invoice_date'] <= date_cutoff) &
            out['supplier_gstin'].str.match(gstin_re) &
            (out['taxable_value'] > 0) &
            ((out['cgst'] + out['sgst'] + out['igst']) <= out['taxable_value'])
        )
        return out[mask].copy()

    def _validate_portal(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 2: Validate portal with strict DQ rules."""
        out = df.copy()
        for col in ["supplier_gstin", "invoice_no"]:
            if col not in out.columns: out[col] = ""
        for col in ["cgst", "sgst", "igst"]:
            if col not in out.columns: out[col] = 0.0
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
            
        if 'invoice_date' in out.columns:
            out['invoice_date'] = pd.to_datetime(out['invoice_date'], errors='coerce')
        else:
            out['invoice_date'] = pd.NaT

        date_cutoff = pd.Timestamp('2025-03-31')
        mask = (out['invoice_date'] <= date_cutoff)
        return out[mask].copy()

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out['total_tax'] = out['cgst'] + out['sgst'] + out['igst']
        out['supplier_gstin'] = out['supplier_gstin'].astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        out['invoice_no'] = out['invoice_no'].astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        return out

    def reconcile(
        self,
        books_raw: pd.DataFrame,
        portal_raw: pd.DataFrame,
        gstr2a_df: Optional[pd.DataFrame] = None,
    ) -> ReconciliationResult:
        logger.info("Starting ITC reconciliation")

        # Layer 2: Validated
        books_valid = self._validate_books(books_raw)
        portal_valid = self._validate_portal(portal_raw)
        
        # All aggregations run on _valid frames only
        total_books_itc = (books_valid['cgst'] + books_valid['sgst'] + books_valid['igst']).sum()
        total_portal_itc = (portal_valid['cgst'] + portal_valid['sgst'] + portal_valid['igst']).sum()

        books = self._prepare(books_valid)
        portal = self._prepare(portal_valid)

        # Bug 1 & 8: Outer Merge and Bucket C Blind Spot
        merged = pd.merge(
            books, 
            portal, 
            on=['supplier_gstin', 'invoice_no'], 
            how='outer', 
            suffixes=('_books', '_portal')
        )
        
        # Bug 8: Standardize Display GSTIN
        merged['display_gstin'] = merged['supplier_gstin']

        # Bug 1: Classification checks BEFORE fillna
        is_bucket_c = merged['total_tax_books'].isna()
        is_bucket_b = merged['total_tax_portal'].isna()
        
        # Bug 2: Bucket D (Delta on actual tax amounts)
        delta = merged['total_tax_books'].fillna(0.0) - merged['total_tax_portal'].fillna(0.0)
        is_bucket_d = (delta.abs() > self.tax_tolerance) & ~is_bucket_b & ~is_bucket_c
        
        is_bucket_a = (delta.abs() <= self.tax_tolerance) & ~is_bucket_b & ~is_bucket_c

        merged['match_bucket'] = ""
        merged.loc[is_bucket_c, 'match_bucket'] = MatchBucket.C_UNCLAIMED_IN_BOOKS.value
        merged.loc[is_bucket_b, 'match_bucket'] = MatchBucket.B_MISSING_IN_PORTAL.value
        merged.loc[is_bucket_d, 'match_bucket'] = MatchBucket.D_AMOUNT_MISMATCH.value
        merged.loc[is_bucket_a, 'match_bucket'] = MatchBucket.A_PERFECT_MATCH.value

        merged['books_total_tax'] = merged['total_tax_books'].fillna(0.0)
        merged['portal_total_tax'] = merged['total_tax_portal'].fillna(0.0)
        merged['tax_variance'] = delta
        merged['abs_variance'] = delta.abs()

        # Bucket E: Timing Differences
        if gstr2a_df is not None:
            g2a = self._validate_portal(gstr2a_df)
            g2a = self._prepare(g2a)
            g2a_keys = set(zip(g2a['supplier_gstin'], g2a['invoice_no']))
            
            b_mask = merged['match_bucket'] == MatchBucket.B_MISSING_IN_PORTAL.value
            for idx, row in merged[b_mask].iterrows():
                if (row['supplier_gstin'], row['invoice_no']) in g2a_keys:
                    merged.at[idx, 'match_bucket'] = MatchBucket.E_TIMING_DIFFERENCE.value

        merged["remarks"] = merged["match_bucket"].map(
            {b.value: d for b, d in BUCKET_DESCRIPTIONS.items()}
        ).fillna("")

        return self._build_result(merged, total_books_itc, total_portal_itc)

    def _build_result(self, consolidated: pd.DataFrame, total_books_itc: float, total_portal_itc: float) -> ReconciliationResult:
        buckets = {}
        for b in MatchBucket:
            buckets[b] = consolidated[consolidated["match_bucket"] == b.value].copy()

        bucket_counts = {b.value: len(buckets[b]) for b in MatchBucket}

        b_df = buckets[MatchBucket.B_MISSING_IN_PORTAL]
        defaulting = sorted(b_df['display_gstin'].dropna().unique().tolist()) if 'display_gstin' in b_df.columns else []

        # Bug 5: Exposure Total Over-inflation (Timing Diffs excluded)
        at_risk = (
            buckets[MatchBucket.B_MISSING_IN_PORTAL]["books_total_tax"].sum() +
            buckets[MatchBucket.C_UNCLAIMED_IN_BOOKS]["portal_total_tax"].sum() +
            buckets[MatchBucket.D_AMOUNT_MISMATCH]["abs_variance"].sum()
        )

        total_var = buckets[MatchBucket.D_AMOUNT_MISMATCH]["tax_variance"].sum()

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
