"""
ITC Reconciliation Demo
=========================
Generates realistic 3-way test data with intentional mismatches,
runs the ITCMatcher, and prints the audit summary.

Usage:
    python -m gst_audit_pipeline.run_reconciliation_demo
"""

from __future__ import annotations

import io
import random
import sys
from decimal import Decimal

import numpy as np
import pandas as pd

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )

from .utils.gstin_validator import gstin_checksum


# ═══════════════════════════════════════════════════════════════
#  GSTIN Generator (structurally valid with correct checksum)
# ═══════════════════════════════════════════════════════════════

_STATES = ["27", "29", "07", "33", "24", "09", "19", "36"]
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _rand_gstin(state=None):
    sc = state or random.choice(_STATES)
    pan = (
        "".join(random.choices(_LETTERS, k=5))
        + "".join(random.choices("0123456789", k=4))
        + random.choice(_LETTERS)
    )
    entity = random.choice("123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    partial = f"{sc}{pan}{entity}Z"
    return partial + gstin_checksum(partial)


# ═══════════════════════════════════════════════════════════════
#  Generate Realistic Test DataFrames
# ═══════════════════════════════════════════════════════════════

def generate_test_data():
    """
    Build 3 correlated DataFrames simulating real audit data:

    Intentional issues injected:
      - 5 invoices in books but missing from GSTR-2B (Bucket B)
      - 4 invoices in GSTR-2B but not in books (Bucket C)
      - 6 invoices with tax amount mismatches (Bucket D)
      - 3 invoices in books + GSTR-2A but not in GSTR-2B (Bucket E)
      - Invoice number variations: leading zeros, slashes vs dashes
      - Slight rounding differences within tolerance (still Bucket A)
    """
    random.seed(42)
    np.random.seed(42)

    # Generate 20 suppliers
    suppliers = [_rand_gstin() for _ in range(20)]
    supplier_names = [f"Vendor {chr(65 + i)}" for i in range(20)]

    rates = [5.0, 12.0, 18.0, 28.0]
    records = []

    for i in range(1, 61):
        sup_idx = random.randint(0, 19)
        rate = random.choice(rates)
        taxable = round(random.uniform(5000, 200000), 2)
        is_inter = random.random() < 0.3

        if is_inter:
            igst = round(taxable * rate / 100, 2)
            cgst = sgst = 0.0
        else:
            cgst = round(taxable * rate / 200, 2)
            sgst = cgst
            igst = 0.0

        inv_date = f"2024-{random.randint(4,12):02d}-{random.randint(1,28):02d}"

        records.append({
            "idx": i,
            "supplier_gstin": suppliers[sup_idx],
            "supplier_name": supplier_names[sup_idx],
            "invoice_no": f"INV/{i:04d}/2425",
            "invoice_date": inv_date,
            "taxable_value": taxable,
            "tax_rate": rate,
            "cgst": cgst,
            "sgst": sgst,
            "igst": igst,
        })

    all_df = pd.DataFrame(records)

    # ── BOOKS: All 60 records ──
    books_df = all_df.copy()

    # ── GSTR-2B: Remove some, add some, tweak some ──
    gstr2b_df = all_df.copy()

    # Remove 5 invoices (-> Bucket B for books-only)
    b_missing_idx = [3, 12, 25, 38, 50]
    gstr2b_df = gstr2b_df[~gstr2b_df["idx"].isin(b_missing_idx)].copy()

    # Add 4 portal-only invoices (-> Bucket C)
    for j in range(61, 65):
        sup_idx = random.randint(0, 19)
        rate = random.choice(rates)
        taxable = round(random.uniform(8000, 100000), 2)
        cgst = round(taxable * rate / 200, 2)
        gstr2b_df = pd.concat([gstr2b_df, pd.DataFrame([{
            "idx": j,
            "supplier_gstin": suppliers[sup_idx],
            "supplier_name": supplier_names[sup_idx],
            "invoice_no": f"INV/{j:04d}/2425",
            "invoice_date": f"2024-{random.randint(4,12):02d}-15",
            "taxable_value": taxable,
            "tax_rate": rate,
            "cgst": cgst,
            "sgst": cgst,
            "igst": 0.0,
        }])], ignore_index=True)

    # Tweak 6 invoices for amount mismatch (-> Bucket D)
    d_mismatch_idx = [5, 10, 20, 30, 40, 55]
    for midx in d_mismatch_idx:
        mask = gstr2b_df["idx"] == midx
        if mask.any():
            # Add Rs.50-500 variance (exceeds Rs.1 tolerance)
            variance = round(random.uniform(50, 500), 2)
            gstr2b_df.loc[mask, "cgst"] += variance
            gstr2b_df.loc[mask, "sgst"] += variance * 0.5

    # Change invoice number format in portal (slashes -> dashes)
    gstr2b_df["invoice_no"] = gstr2b_df["invoice_no"].str.replace("/", "-")

    # Add leading zeros to some invoice numbers in portal
    lead_zero_idx = [7, 15, 22, 35, 45]
    for lz in lead_zero_idx:
        mask = gstr2b_df["idx"] == lz
        if mask.any():
            orig = gstr2b_df.loc[mask, "invoice_no"].values[0]
            gstr2b_df.loc[mask, "invoice_no"] = "00" + orig

    # Add slight rounding differences within tolerance (still Bucket A)
    rounding_idx = [2, 8, 18, 28, 42]
    for ri in rounding_idx:
        mask = gstr2b_df["idx"] == ri
        if mask.any():
            gstr2b_df.loc[mask, "cgst"] += round(random.uniform(-0.5, 0.5), 2)

    # ── GSTR-2A: Contains the 5 missing-from-2B + 3 timing entries ──
    timing_idx = [3, 12, 25]  # 3 of the 5 missing are in GSTR-2A
    gstr2a_records = all_df[all_df["idx"].isin(timing_idx)].copy()
    # Also include some matched records to make GSTR-2A realistic
    extra_2a = all_df[all_df["idx"].isin([1, 2, 4, 5, 6, 7, 8])].copy()
    gstr2a_df = pd.concat([gstr2a_records, extra_2a], ignore_index=True)

    # Drop internal idx column
    for df in [books_df, gstr2b_df, gstr2a_df]:
        if "idx" in df.columns:
            df.drop(columns=["idx"], inplace=True)

    return books_df, gstr2b_df, gstr2a_df


# ═══════════════════════════════════════════════════════════════
#  Main Demo
# ═══════════════════════════════════════════════════════════════

def main():
    from .reconciliation import ITCMatcher

    sep = "=" * 72
    print(f"\n{sep}")
    print("  GST PRE-AUDIT: 3-Way ITC Reconciliation Engine")
    print(sep)

    # Generate test data
    print("\n  Generating realistic test data with intentional mismatches...")
    books_df, gstr2b_df, gstr2a_df = generate_test_data()
    print(f"  [OK] Purchase Register (Books) : {len(books_df):>4d} records")
    print(f"  [OK] GSTR-2B (Static Portal)   : {len(gstr2b_df):>4d} records")
    print(f"  [OK] GSTR-2A (Dynamic Portal)  : {len(gstr2a_df):>4d} records")

    # Run reconciliation
    print(f"\n  Running 3-Way ITC Matching Algorithm...")
    matcher = ITCMatcher(tax_tolerance=1.0)
    result = matcher.reconcile(books_df, gstr2b_df, gstr2a_df)

    # Print summary
    result.print_summary()

    # Show sample records from each bucket
    print(f"\n{sep}")
    print("  SAMPLE RECORDS BY BUCKET")
    print(sep)

    bucket_dfs = {
        "A_PERFECT_MATCH": result.perfect_matches,
        "B_MISSING_IN_PORTAL": result.missing_in_portal,
        "C_UNCLAIMED_IN_BOOKS": result.unclaimed_in_books,
        "D_AMOUNT_MISMATCH": result.amount_mismatches,
        "E_TIMING_DIFFERENCE": result.timing_differences,
    }

    for bucket_name, bdf in bucket_dfs.items():
        print(f"\n  --- {bucket_name} ({len(bdf)} records) ---")
        if len(bdf) == 0:
            print("    (none)")
            continue

        # Show up to 3 sample records
        display_cols = [
            c for c in [
                "books_invoice_no", "portal_invoice_no",
                "books_total_tax", "portal_total_tax",
                "tax_variance",
            ] if c in bdf.columns
        ]
        if display_cols:
            sample = bdf[display_cols].head(3)
            for _, row in sample.iterrows():
                parts = []
                for col in display_cols:
                    val = row[col]
                    if pd.notna(val):
                        label = col.replace("books_", "B:").replace("portal_", "P:")
                        if isinstance(val, float):
                            parts.append(f"{label}={val:,.2f}")
                        else:
                            parts.append(f"{label}={val}")
                print(f"    {' | '.join(parts)}")

    # Defaulting suppliers
    if result.defaulting_suppliers:
        print(f"\n{sep}")
        print(f"  DEFAULTING SUPPLIER GSTINs ({len(result.defaulting_suppliers)})")
        print(sep)
        for g in result.defaulting_suppliers:
            print(f"    {g}")

    print(f"\n{sep}")
    print("  Reconciliation complete. Ready for audit finalization.")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
