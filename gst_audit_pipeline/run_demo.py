"""
GST Audit Pipeline -- Demo Runner
==================================
Generates mock data, runs the full ingestion pipeline, and prints
a diagnostic summary.

Usage:
    python -m gst_audit_pipeline.run_demo
"""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace"
    )

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gst_audit_pipeline.demo")


def main():
    """Run the full ingestion pipeline demo."""
    from .mock_data.generator import generate_all_mock_data
    from .parsers.excel_parser import (
        parse_sales_register_excel,
        parse_purchase_register_excel,
        parse_gstr2b_excel,
    )
    from .parsers.json_parser import parse_gstr1_json
    from .utils.sanitizer import sanitize_invoice_number, invoice_numbers_match
    from .utils.gstin_validator import validate_gstin

    output_dir = Path("mock_output")
    sep = "=" * 70

    # -- Step 1: Generate Mock Data --------------------------------
    print(f"\n{sep}")
    print("  STEP 1: Generating Synthetic Mock Data")
    print(sep)

    paths = generate_all_mock_data(output_dir)
    for name, path in paths.items():
        print(f"  [OK] {name:25s} -> {path}")

    # -- Step 2: Parse Sales Register ------------------------------
    print(f"\n{sep}")
    print("  STEP 2: Parsing Sales Register (Books)")
    print(sep)

    sales_entries, sales_errors = parse_sales_register_excel(paths["sales_register"])
    print(f"  [OK] Parsed:  {len(sales_entries)} entries")
    print(f"  [!!] Errors:  {len(sales_errors)} rows")
    if sales_entries:
        entry = sales_entries[0]
        print(f"  Sample: Inv={entry.invoice_no}, Date={entry.invoice_date}, "
              f"Taxable=Rs.{entry.taxable_value:,.2f}, Rate={entry.tax_rate}%")

    # -- Step 3: Parse Purchase Register ---------------------------
    print(f"\n{sep}")
    print("  STEP 3: Parsing Purchase Register (Books)")
    print(sep)

    purchase_entries, purchase_errors = parse_purchase_register_excel(
        paths["purchase_register"]
    )
    print(f"  [OK] Parsed:  {len(purchase_entries)} entries")
    print(f"  [!!] Errors:  {len(purchase_errors)} rows")
    if purchase_entries:
        entry = purchase_entries[0]
        print(f"  Sample: Inv={entry.invoice_no}, Vendor={entry.vendor_gstin}, "
              f"Head={entry.expense_head}")

    # -- Step 4: Parse GSTR-1 JSON ---------------------------------
    print(f"\n{sep}")
    print("  STEP 4: Parsing GSTR-1 Portal JSON")
    print(sep)

    gstr1, gstr1_warnings = parse_gstr1_json(paths["gstr1_json"])
    total_b2b = sum(len(r.invoices) for r in gstr1.b2b)
    print(f"  [OK] GSTIN:          {gstr1.gstin}")
    print(f"  [OK] Period:         {gstr1.return_period}")
    print(f"  [OK] B2B Recipients: {len(gstr1.b2b)}")
    print(f"  [OK] B2B Invoices:   {total_b2b}")
    print(f"  [OK] B2CS Entries:   {len(gstr1.b2cs)}")
    print(f"  [OK] HSN Entries:    {len(gstr1.hsn)}")
    print(f"  [WW] Warnings:       {len(gstr1_warnings)}")

    # -- Step 5: Parse GSTR-2B Excel -------------------------------
    print(f"\n{sep}")
    print("  STEP 5: Parsing GSTR-2B Portal Excel")
    print(sep)

    gstr2b, gstr2b_errors = parse_gstr2b_excel(
        paths["gstr2b_excel"],
        recipient_gstin="27AABCT1234F1ZP",
        return_period="032025",
    )
    total_2b_inv = sum(len(s.invoices) for s in gstr2b.b2b_suppliers)
    print(f"  [OK] Suppliers:      {len(gstr2b.b2b_suppliers)}")
    print(f"  [OK] Invoices:       {total_2b_inv}")
    print(f"  [!!] Parse Errors:   {len(gstr2b_errors)}")

    # -- Step 6: Utility Demos -------------------------------------
    print(f"\n{sep}")
    print("  STEP 6: Utility Function Demos")
    print(sep)

    # Invoice sanitization
    test_invoices = [
        ("INV/24-25/01", "INV-2425-01"),
        ("GST - 001/23", "GST001/23"),
        ("  inv#456  ", "INV456"),
    ]
    print("\n  Invoice Number Sanitization:")
    for a, b in test_invoices:
        sa, sb = sanitize_invoice_number(a), sanitize_invoice_number(b)
        match = "[MATCH]" if sa == sb else "[NO MATCH]"
        print(f"    '{a}' -> '{sa}'  |  '{b}' -> '{sb}'  |  {match}")

    # GSTIN validation
    print("\n  GSTIN Validation:")
    test_gstins = [
        "27AABCU9603R1ZM",  # Example
        "29AALCB549R1Z5",   # Missing leading zero
        "99AAACB0000A1Z5",  # Invalid state code
        "INVALID",
    ]
    # Also validate GSTINs from parsed data
    if sales_entries:
        for entry in sales_entries[:3]:
            if entry.customer_gstin:
                test_gstins.append(entry.customer_gstin)

    for gstin in test_gstins:
        is_valid, msg = validate_gstin(gstin)
        status = "[PASS]" if is_valid else "[FAIL]"
        print(f"    {status} {gstin:20s} -> {msg}")

    # -- Summary ---------------------------------------------------
    print(f"\n{sep}")
    print("  PIPELINE SUMMARY")
    print(sep)
    print(f"  Sales Register:     {len(sales_entries):>5d} entries  ({len(sales_errors)} errors)")
    print(f"  Purchase Register:  {len(purchase_entries):>5d} entries  ({len(purchase_errors)} errors)")
    print(f"  GSTR-1 B2B:         {total_b2b:>5d} invoices")
    print(f"  GSTR-2B:            {total_2b_inv:>5d} invoices ({len(gstr2b.b2b_suppliers)} suppliers)")
    print(f"\n  All mock files saved to: {output_dir.resolve()}")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
