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

_STRIP_RE = re.compile(r"[^A-Z0-9]", re.IGNORECASE)
_TAX_TOLERANCE = 1.0

# Canonical columns expected in each source
_CANONICAL_COLS = {
    "gstin": "supplier_gstin",
    "invoice_no": "invoice_no",
    "invoice_date": "invoice_date",
    "taxable_value": "taxable_value",
    "cgst": "cgst",
    "sgst": "sgst",
    "igst": "igst",
    "supplier_name": "supplier_name",
    "tax_rate": "tax_rate",
}

_NUMERIC_COLS = {"cgst", "sgst", "igst", "taxable_value", "tax_rate"}


# ═══════════════════════════════════════════════════════════════
#  Vectorized Normalization
# ═══════════════════════════════════════════════════════════════

def _norm_gstin(s: pd.Series) -> pd.Series:
    out = s.astype(str).str.strip().str.upper().str.replace(" ", "", regex=False)
    mask = out.str.len() == 14
    out = out.where(~mask, "0" + out)
    return out


def _norm_invoice(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper().str.replace(
        r"[^A-Z0-9]", "", regex=True
    )


def _strip_zeros(s: pd.Series) -> pd.Series:
    return s.str.lstrip("0")


# ═══════════════════════════════════════════════════════════════
#  Column Standardizer
# ═══════════════════════════════════════════════════════════════

def _standardize(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Rename to canonical names; add missing columns with defaults."""
    out = df.copy()
    rename_map = {}
    for canonical, default in _CANONICAL_COLS.items():
        if default in out.columns:
            rename_map[default] = canonical
        else:
            for col in out.columns:
                if col.lower().replace(" ", "_") == canonical:
                    rename_map[col] = canonical
                    break
            else:
                out[canonical] = 0.0 if canonical in _NUMERIC_COLS else ""
    out = out.rename(columns=rename_map)
    for canonical in _CANONICAL_COLS:
        if canonical not in out.columns:
            out[canonical] = 0.0 if canonical in _NUMERIC_COLS else ""
    return out


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
        total_var = self.summary.get("total_variance", 0)
        print(f"\n  Total Tax Variance (D bucket) : Rs. {total_var:>12,.2f}")
        print(f"  Defaulting Suppliers          : {len(self.defaulting_suppliers):>6d}")
        if self.defaulting_suppliers:
            print(f"\n  Top Defaulting GSTINs:")
            for g in self.defaulting_suppliers[:10]:
                print(f"    - {g}")
        itc_at_risk = self.summary.get("itc_at_risk", 0)
        print(f"\n  ITC at Risk (B+D+E buckets)   : Rs. {itc_at_risk:>12,.2f}")
        print(sep)


# ═══════════════════════════════════════════════════════════════
#  Core ITC Matcher
# ═══════════════════════════════════════════════════════════════

class ITCMatcher:
    """
    High-performance 3-Way ITC Matching Engine.

    Strategy (vectorized — no row-level iteration):
        1. Normalize GSTINs and invoice numbers for all sources.
        2. Create composite match keys (GSTIN|normalized_invoice).
        3. Pass 1: outer merge Books <-> GSTR-2B on primary key.
        4. Pass 2: re-match unmatched on zero-stripped fallback key.
        5. Classify every row into exactly one of 5 buckets.
        6. Cross-check books-only against GSTR-2A for timing diffs.
    """

    def __init__(self, tax_tolerance: float = _TAX_TOLERANCE):
        self.tax_tolerance = tax_tolerance

    def reconcile(
        self,
        books_df: pd.DataFrame,
        gstr2b_df: pd.DataFrame,
        gstr2a_df: Optional[pd.DataFrame] = None,
    ) -> ReconciliationResult:
        logger.info(
            "Starting ITC reconciliation: Books=%d, 2B=%d, 2A=%s",
            len(books_df), len(gstr2b_df),
            len(gstr2a_df) if gstr2a_df is not None else "N/A",
        )

        # Prepare sources with prefixed columns
        books = self._prepare(books_df, "books")
        portal = self._prepare(gstr2b_df, "portal")
        gstr2a = self._prepare(gstr2a_df, "g2a") if gstr2a_df is not None else None

        # Two-pass merge
        matched, unmatched_b, unmatched_p = self._two_pass_merge(books, portal)

        # Classify
        classified = self._classify(matched, unmatched_b, unmatched_p, gstr2a)

        return self._build_result(classified)

    # ── Prepare ─────────────────────────────────────────────────

    def _prepare(self, df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        out = _standardize(df, prefix)

        # Match keys (internal, unprefixed)
        out["_gstin"] = _norm_gstin(out["gstin"])
        out["_inv"] = _norm_invoice(out["invoice_no"])
        out["_inv_stripped"] = _strip_zeros(out["_inv"])
        out["_key1"] = out["_gstin"] + "|" + out["_inv"]
        out["_key2"] = out["_gstin"] + "|" + out["_inv_stripped"]

        # Numerics
        for col in _NUMERIC_COLS:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
        out["_tax"] = out["cgst"] + out["sgst"] + out["igst"]

        # Prefix user-visible columns
        rename = {c: f"{prefix}_{c}" for c in out.columns if not c.startswith("_")}
        out = out.rename(columns=rename)

        logger.info("Prepared %s: %d rows.", prefix, len(out))
        return out

    # ── Two-Pass Merge ──────────────────────────────────────────

    def _two_pass_merge(
        self, books: pd.DataFrame, portal: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Pass 1: Exact match on _key1 (GSTIN + full normalized invoice).
        Pass 2: Match remaining on _key2 (GSTIN + zero-stripped invoice).

        Returns: (matched_df, unmatched_books_df, unmatched_portal_df)
        """
        # ── Pass 1: exact key ──
        p1 = books.merge(
            portal, left_on="_key1", right_on="_key1",
            how="outer", indicator=True, suffixes=("", "_p"),
        )

        matched = p1[p1["_merge"] == "both"].drop(columns=["_merge"]).copy()
        left_only = p1[p1["_merge"] == "left_only"].drop(columns=["_merge"]).copy()
        right_only = p1[p1["_merge"] == "right_only"].drop(columns=["_merge"]).copy()

        logger.info(
            "Pass 1: %d matched, %d books-only, %d portal-only.",
            len(matched), len(left_only), len(right_only),
        )

        if len(left_only) == 0 or len(right_only) == 0:
            return matched, left_only, right_only

        # ── Pass 2: stripped key ──
        # Extract clean books-side and portal-side records
        b_cols = [c for c in left_only.columns
                  if c.startswith("books_") or c.startswith("_")]
        p_cols = [c for c in right_only.columns
                  if c.startswith("portal_") or c.startswith("_")]

        ub = left_only[b_cols].copy()
        up = right_only[p_cols].copy()

        # The portal _key2 may be suffixed from pass-1 outer merge
        ub_key2 = ub["_key2"]
        # For portal side after outer merge, _key2 might be _key2_p
        if "_key2_p" in up.columns:
            up_key2 = up["_key2_p"]
        else:
            up_key2 = up["_key2"]

        ub["_join2"] = ub_key2
        up["_join2"] = up_key2

        p2 = ub.merge(up, on="_join2", how="inner", suffixes=("", "_p2"))

        if len(p2) > 0:
            logger.info("Pass 2: %d additional matches via stripped key.", len(p2))

            # Remove matched records from unmatched pools
            matched_b_keys = set(p2["_key1"].dropna())
            p_key1_col = "_key1_p" if "_key1_p" in p2.columns else "_key1_p2"
            matched_p_keys = set()
            if p_key1_col in p2.columns:
                matched_p_keys = set(p2[p_key1_col].dropna())

            left_only = left_only[~left_only["_key1"].isin(matched_b_keys)]

            if "_key1_p" in right_only.columns:
                right_only = right_only[~right_only["_key1_p"].isin(matched_p_keys)]
            elif "_key1" in right_only.columns:
                right_only = right_only[~right_only["_key1"].isin(matched_p_keys)]

            matched = pd.concat([matched, p2], ignore_index=True, sort=False)

        return matched, left_only, right_only

    # ── Classification ──────────────────────────────────────────

    def _classify(
        self,
        matched: pd.DataFrame,
        unmatched_books: pd.DataFrame,
        unmatched_portal: pd.DataFrame,
        gstr2a: Optional[pd.DataFrame],
    ) -> pd.DataFrame:
        """Assign exactly one bucket to every record."""

        # ── Matched records: A (perfect) vs D (mismatch) ──
        if len(matched) > 0:
            b_tax = self._get_tax(matched, "books")
            p_tax = self._get_tax(matched, "portal")
            matched["books_total_tax"] = b_tax
            matched["portal_total_tax"] = p_tax
            matched["tax_variance"] = p_tax - b_tax
            matched["abs_variance"] = matched["tax_variance"].abs()

            perfect = matched["abs_variance"] <= self.tax_tolerance
            matched.loc[perfect, "match_bucket"] = MatchBucket.A_PERFECT_MATCH.value
            matched.loc[~perfect, "match_bucket"] = MatchBucket.D_AMOUNT_MISMATCH.value
        else:
            matched["books_total_tax"] = []
            matched["portal_total_tax"] = []
            matched["tax_variance"] = []
            matched["abs_variance"] = []
            matched["match_bucket"] = []

        # ── Books-only: B (missing) vs E (timing) ──
        if len(unmatched_books) > 0:
            b_tax = self._get_tax(unmatched_books, "books")
            unmatched_books["books_total_tax"] = b_tax
            unmatched_books["portal_total_tax"] = 0.0
            unmatched_books["tax_variance"] = -b_tax
            unmatched_books["abs_variance"] = b_tax.abs()

            if gstr2a is not None and len(gstr2a) > 0:
                g2a_keys = set(gstr2a["_key1"].dropna()) | set(gstr2a["_key2"].dropna())
                ub_key1 = unmatched_books["_key1"].fillna("")
                ub_key2 = unmatched_books["_key2"].fillna("")
                in_2a = ub_key1.isin(g2a_keys) | ub_key2.isin(g2a_keys)

                unmatched_books.loc[in_2a, "match_bucket"] = MatchBucket.E_TIMING_DIFFERENCE.value
                unmatched_books.loc[~in_2a, "match_bucket"] = MatchBucket.B_MISSING_IN_PORTAL.value
            else:
                unmatched_books["match_bucket"] = MatchBucket.B_MISSING_IN_PORTAL.value
        else:
            unmatched_books["books_total_tax"] = []
            unmatched_books["portal_total_tax"] = []
            unmatched_books["tax_variance"] = []
            unmatched_books["abs_variance"] = []
            unmatched_books["match_bucket"] = []

        # ── Portal-only: C (unclaimed) ──
        if len(unmatched_portal) > 0:
            p_tax = self._get_tax(unmatched_portal, "portal")
            unmatched_portal["books_total_tax"] = 0.0
            unmatched_portal["portal_total_tax"] = p_tax
            unmatched_portal["tax_variance"] = p_tax
            unmatched_portal["abs_variance"] = p_tax.abs()
            unmatched_portal["match_bucket"] = MatchBucket.C_UNCLAIMED_IN_BOOKS.value
        else:
            unmatched_portal["books_total_tax"] = []
            unmatched_portal["portal_total_tax"] = []
            unmatched_portal["tax_variance"] = []
            unmatched_portal["abs_variance"] = []
            unmatched_portal["match_bucket"] = []

        # ── Remarks ──
        for df in [matched, unmatched_books, unmatched_portal]:
            if len(df) > 0:
                df["remarks"] = df["match_bucket"].map(
                    {b.value: d for b, d in BUCKET_DESCRIPTIONS.items()}
                ).fillna("")

        combined = pd.concat(
            [matched, unmatched_books, unmatched_portal],
            ignore_index=True, sort=False,
        )
        return combined

    # ── Build Result ────────────────────────────────────────────

    def _build_result(self, classified: pd.DataFrame) -> ReconciliationResult:
        out_cols = self._output_cols(classified)
        consolidated = classified[out_cols].copy()

        buckets = {}
        for b in MatchBucket:
            buckets[b] = consolidated[consolidated["match_bucket"] == b.value].copy()

        # Defaulting suppliers
        gstin_col = None
        for c in ["books_gstin", "_gstin"]:
            if c in consolidated.columns:
                gstin_col = c
                break
        b_df = buckets[MatchBucket.B_MISSING_IN_PORTAL]
        defaulting = (
            sorted(b_df[gstin_col].dropna().unique().tolist())
            if gstin_col and gstin_col in b_df.columns else []
        )

        bucket_counts = {b.value: len(buckets[b]) for b in MatchBucket}

        at_risk = sum(
            buckets[b]["books_total_tax"].sum()
            for b in [MatchBucket.B_MISSING_IN_PORTAL,
                      MatchBucket.D_AMOUNT_MISMATCH,
                      MatchBucket.E_TIMING_DIFFERENCE]
            if "books_total_tax" in buckets[b].columns and len(buckets[b]) > 0
        )

        d_df = buckets[MatchBucket.D_AMOUNT_MISMATCH]
        total_var = d_df["tax_variance"].sum() if len(d_df) > 0 else 0

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
                "defaulting_supplier_count": len(defaulting),
            },
        )

    # ── Helpers ─────────────────────────────────────────────────

    def _get_tax(self, df: pd.DataFrame, prefix: str) -> pd.Series:
        """Get total tax for a prefix, trying _tax then individual cols."""
        # Direct _tax column (pre-computed)
        for cand in ["_tax", "_tax_p", "_tax_p2"]:
            if cand in df.columns:
                is_books = prefix == "books"
                is_portal = prefix == "portal"
                if (is_books and cand == "_tax") or \
                   (is_portal and cand in ("_tax_p", "_tax_p2")):
                    return pd.to_numeric(df[cand], errors="coerce").fillna(0.0)

        # Fallback: sum component columns
        total = pd.Series(0.0, index=df.index)
        for suffix in ["cgst", "sgst", "igst"]:
            for col in df.columns:
                if col == f"{prefix}_{suffix}":
                    total += pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        return total

    def _output_cols(self, df: pd.DataFrame) -> list:
        priority = [
            "match_bucket",
            "books_gstin", "books_supplier_name",
            "books_invoice_no", "portal_invoice_no",
            "books_invoice_date", "portal_invoice_date",
            "books_taxable_value", "portal_taxable_value",
            "books_cgst", "books_sgst", "books_igst",
            "portal_cgst", "portal_sgst", "portal_igst",
            "books_total_tax", "portal_total_tax",
            "tax_variance", "abs_variance",
            "books_tax_rate", "portal_tax_rate",
            "remarks",
            "_gstin", "_gstin_p", "_key1", "_merge_status",
        ]
        return [c for c in priority if c in df.columns]
