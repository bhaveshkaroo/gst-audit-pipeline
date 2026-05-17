"""
Synthetic Mock Data Generator
===============================
Generates realistic test datasets for the GST audit pipeline.

Intentionally injects real-world data quality issues:
    • Mismatched invoice numbers (slashes vs. no slashes)
    • Different date formats across files
    • Missing vendor filings in GSTR-2B
    • GSTINs with stripped leading zeros
    • Currency-formatted amounts with commas
    • Merged header rows and blank rows in Excel
    • Slight taxable value discrepancies between books and portal
"""

from __future__ import annotations

import json
import random
import string
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

import pandas as pd

from ..utils.gstin_validator import gstin_checksum


# ═══════════════════════════════════════════════════════════════
#  GSTIN Generator (structurally valid)
# ═══════════════════════════════════════════════════════════════

_STATE_CODES = ["27", "29", "07", "33", "24", "09", "19", "36"]
_PAN_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _random_pan() -> str:
    """Generate a random but structurally valid PAN."""
    return (
        "".join(random.choices(_PAN_LETTERS, k=5))
        + "".join(random.choices("0123456789", k=4))
        + random.choice(_PAN_LETTERS)
    )


def _random_gstin(state_code: str = None) -> str:
    """Generate a structurally valid GSTIN with correct checksum."""
    sc = state_code or random.choice(_STATE_CODES)
    pan = _random_pan()
    entity = random.choice("123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    partial = f"{sc}{pan}{entity}Z"
    check = gstin_checksum(partial)
    return partial + check


def _random_date(
    start: date = date(2024, 4, 1),
    end: date = date(2025, 3, 31),
) -> date:
    """Random date within Indian FY 2024-25."""
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def _format_date_messy(d: date) -> str:
    """Return date in a random messy format."""
    formats = [
        d.strftime("%d-%m-%Y"),
        d.strftime("%d/%m/%Y"),
        d.strftime("%d-%b-%Y"),
        d.strftime("%d-%b-%y"),
        d.strftime("%Y-%m-%d"),
        d.strftime("%d.%m.%Y"),
    ]
    return random.choice(formats)


# ═══════════════════════════════════════════════════════════════
#  Common test data
# ═══════════════════════════════════════════════════════════════

_HSN_CODES = ["84713000", "99831", "8471", "30049099", "9988", "8528"]
_SAC_CODES = ["998314", "997212", "998599", "995411"]
_EXPENSE_HEADS = [
    "Office Supplies", "Professional Fees", "Rent Expense",
    "Electricity Charges", "Raw Materials", "Packing Materials",
    "Freight Inward", "Repairs & Maintenance", "Software Licenses",
    "Legal & Professional", "Advertising Expense", "Travel Expense",
]
_COMPANY_GSTIN = _random_gstin("27")  # Maharashtra
_TAX_RATES = [Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28")]


# ═══════════════════════════════════════════════════════════════
#  Sales Register Generator
# ═══════════════════════════════════════════════════════════════

def generate_mock_sales_register(
    num_rows: int = 50,
    output_path: Optional[str | Path] = None,
    *,
    include_messy_headers: bool = True,
) -> pd.DataFrame:
    """
    Generate a realistic Sales Register Excel with intentional messiness.

    Injected issues:
        - Mixed date formats
        - Invoice numbers with various separators
        - Some GSTINs missing leading zero
        - Currency-formatted taxable values
        - A few blank rows and a "Total" row
    """
    customers = [_random_gstin() for _ in range(15)]
    rows = []

    for i in range(1, num_rows + 1):
        inv_date = _random_date()
        rate = random.choice(_TAX_RATES)
        taxable = Decimal(str(random.randint(5000, 500000)))
        is_inter = random.random() < 0.3
        customer_gstin = random.choice(customers)

        # Intentionally strip leading zero from some GSTINs
        if random.random() < 0.15 and customer_gstin.startswith("0"):
            customer_gstin = customer_gstin[1:]

        # Invoice number with varying formats
        inv_formats = [
            f"INV/24-25/{i:04d}",
            f"INV-2425-{i:04d}",
            f"INV{i:04d}",
            f"SI/{i:04d}/{inv_date.strftime('%m%y')}",
        ]
        inv_no = random.choice(inv_formats)

        if is_inter:
            igst = round(taxable * rate / 100, 2)
            cgst = sgst = Decimal("0")
        else:
            cgst = round(taxable * rate / 200, 2)
            sgst = cgst
            igst = Decimal("0")

        hsn = random.choice(_HSN_CODES + _SAC_CODES)
        supply = "Services" if hsn in _SAC_CODES else "Goods"

        # Format taxable value messily sometimes
        if random.random() < 0.2:
            taxable_str = f"₹ {taxable:,.2f}"
        else:
            taxable_str = str(taxable)

        rows.append({
            "Inv. No.": inv_no,
            "Invoice Date": _format_date_messy(inv_date),
            "Customer GSTIN": customer_gstin,
            "Customer Name": f"Customer {random.randint(1, 100)}",
            "Place of Supply": customer_gstin[:2] if len(customer_gstin) >= 2 else "27",
            "Taxable Amt": taxable_str,
            "GST Rate (%)": str(rate),
            "CGST Amount": str(cgst),
            "SGST Amount": str(sgst),
            "IGST Amount": str(igst),
            "HSN/SAC": hsn,
            "Type": supply,
        })

    # Insert blank rows
    for pos in random.sample(range(len(rows)), min(3, len(rows))):
        rows.insert(pos, {k: "" for k in rows[0]})

    # Add total row
    rows.append({
        "Inv. No.": "Total",
        "Taxable Amt": "99,99,999.00",
        **{k: "" for k in list(rows[0].keys()) if k not in ("Inv. No.", "Taxable Amt")},
    })

    df = pd.DataFrame(rows)

    if output_path:
        fp = Path(output_path)
        with pd.ExcelWriter(fp, engine="openpyxl") as writer:
            if include_messy_headers:
                # Add merged-style header rows
                header_df = pd.DataFrame([
                    ["Company: Test Corp Pvt Ltd"] + [""] * (len(df.columns) - 1),
                    ["Sales Register — FY 2024-25"] + [""] * (len(df.columns) - 1),
                    [""] * len(df.columns),
                ], columns=df.columns)
                combined = pd.concat([header_df, df], ignore_index=True)
                combined.to_excel(writer, index=False)
            else:
                df.to_excel(writer, index=False)

    return df


# ═══════════════════════════════════════════════════════════════
#  Purchase Register Generator
# ═══════════════════════════════════════════════════════════════

def generate_mock_purchase_register(
    num_rows: int = 40,
    output_path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """Generate a realistic Purchase Register with data quality issues."""
    vendors = [_random_gstin() for _ in range(12)]
    rows = []

    for i in range(1, num_rows + 1):
        inv_date = _random_date()
        rate = random.choice(_TAX_RATES)
        taxable = Decimal(str(random.randint(2000, 300000)))
        is_inter = random.random() < 0.25
        vendor_gstin = random.choice(vendors)

        # Strip leading zero sometimes
        if random.random() < 0.1 and vendor_gstin.startswith("0"):
            vendor_gstin = vendor_gstin[1:]

        inv_no = f"VINV/{random.randint(1000, 9999)}/{inv_date.strftime('%m%y')}"

        if is_inter:
            igst = round(taxable * rate / 100, 2)
            cgst = sgst = Decimal("0")
        else:
            cgst = round(taxable * rate / 200, 2)
            sgst = cgst
            igst = Decimal("0")

        rows.append({
            "Voucher No": inv_no,
            "Voucher Date": _format_date_messy(inv_date),
            "GSTIN/UIN": vendor_gstin,
            "Party Name": f"Vendor {random.choice(string.ascii_uppercase)}{random.randint(1, 50)}",
            "Taxable Value": str(taxable),
            "CGST": str(cgst),
            "SGST": str(sgst),
            "IGST": str(igst),
            "Ledger Name": random.choice(_EXPENSE_HEADS),
        })

    # Insert blank rows
    for pos in random.sample(range(len(rows)), min(2, len(rows))):
        rows.insert(pos, {k: "" for k in rows[0]})

    df = pd.DataFrame(rows)

    if output_path:
        fp = Path(output_path)
        with pd.ExcelWriter(fp, engine="openpyxl") as writer:
            header_df = pd.DataFrame([
                ["Purchase Register — Test Corp Pvt Ltd"] + [""] * (len(df.columns) - 1),
                ["Period: Apr 2024 to Mar 2025"] + [""] * (len(df.columns) - 1),
                [""] * len(df.columns),
            ], columns=df.columns)
            combined = pd.concat([header_df, df], ignore_index=True)
            combined.to_excel(writer, index=False)

    return df


# ═══════════════════════════════════════════════════════════════
#  GSTR-1 JSON Generator
# ═══════════════════════════════════════════════════════════════

def generate_mock_gstr1_json(
    sales_df: pd.DataFrame = None,
    output_path: Optional[str | Path] = None,
    *,
    mismatch_rate: float = 0.15,
) -> dict:
    """
    Generate a GSTR-1 JSON file, optionally based on a sales register.

    Injected mismatches (controlled by mismatch_rate):
        - Some invoices present in books but missing from GSTR-1
        - Slight taxable value differences (rounding discrepancies)
        - Different invoice number formatting
    """
    if sales_df is None:
        sales_df = generate_mock_sales_register(30)

    b2b_map: dict[str, list] = {}
    b2cs_list = []
    hsn_map: dict[str, dict] = {}

    for _, row in sales_df.iterrows():
        inv_no = str(row.get("Inv. No.", "")).strip()
        if not inv_no or inv_no.lower() == "total":
            continue

        # Skip some invoices to simulate missing filings
        if random.random() < mismatch_rate:
            continue

        gstin = str(row.get("Customer GSTIN", "")).strip()
        taxable_raw = str(row.get("Taxable Amt", "0"))
        taxable_raw = taxable_raw.replace("₹", "").replace(",", "").strip()

        try:
            taxable = float(taxable_raw)
        except ValueError:
            continue

        # Introduce slight rounding differences
        if random.random() < 0.1:
            taxable = round(taxable + random.uniform(-10, 10), 2)

        rate_str = str(row.get("GST Rate (%)", "18")).strip()
        try:
            rate = float(rate_str)
        except ValueError:
            rate = 18.0

        cgst = float(str(row.get("CGST Amount", "0")).replace(",", "") or "0")
        sgst = float(str(row.get("SGST Amount", "0")).replace(",", "") or "0")
        igst = float(str(row.get("IGST Amount", "0")).replace(",", "") or "0")
        inv_value = taxable + cgst + sgst + igst

        inv_date_raw = str(row.get("Invoice Date", "01-04-2024"))
        # Normalize to DD-MM-YYYY for portal format
        from ..utils.sanitizer import normalize_date as nd
        parsed = nd(inv_date_raw)
        inv_date_str = parsed.strftime("%d-%m-%Y") if parsed else "01-04-2024"

        hsn = str(row.get("HSN/SAC", "9988")).strip()

        # Build invoice item
        item = {
            "num": 1,
            "txval": taxable,
            "rt": rate,
            "camt": cgst,
            "samt": sgst,
            "iamt": igst,
            "csamt": 0,
        }

        if gstin and len(gstin) >= 14:
            # B2B
            if len(gstin) == 14:
                gstin = "0" + gstin

            inv_obj = {
                "inum": inv_no.replace("/", "-"),  # Portal reformats
                "idt": inv_date_str,
                "val": round(inv_value, 2),
                "pos": gstin[:2],
                "rchrg": "N",
                "inv_typ": "R",
                "itms": [item],
            }
            b2b_map.setdefault(gstin, []).append(inv_obj)
        else:
            # B2CS
            b2cs_list.append({
                "pos": "27",
                "typ": "OE",
                "rt": rate,
                "txval": taxable,
                "camt": cgst,
                "samt": sgst,
                "iamt": igst,
                "csamt": 0,
            })

        # HSN accumulation
        if hsn not in hsn_map:
            hsn_map[hsn] = {
                "hsn_sc": hsn,
                "desc": f"HSN {hsn}",
                "uqc": "NOS",
                "qty": 0,
                "txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0,
                "rt": rate,
            }
        hsn_map[hsn]["qty"] += 1
        hsn_map[hsn]["txval"] += taxable
        hsn_map[hsn]["camt"] += cgst
        hsn_map[hsn]["samt"] += sgst
        hsn_map[hsn]["iamt"] += igst

    # Build GSTR-1 structure
    b2b_section = [
        {"ctin": gstin, "inv": invoices}
        for gstin, invoices in b2b_map.items()
    ]

    gstr1 = {
        "gstin": _COMPANY_GSTIN,
        "fp": "032025",  # March 2025
        "b2b": b2b_section,
        "b2cs": b2cs_list,
        "hsn": {"data": list(hsn_map.values())},
    }

    if output_path:
        fp = Path(output_path)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(gstr1, f, indent=2, default=str)

    return gstr1


# ═══════════════════════════════════════════════════════════════
#  GSTR-2B Excel Generator
# ═══════════════════════════════════════════════════════════════

def generate_mock_gstr2b_excel(
    purchase_df: pd.DataFrame = None,
    output_path: Optional[str | Path] = None,
    *,
    missing_filing_rate: float = 0.2,
) -> pd.DataFrame:
    """
    Generate GSTR-2B Excel, optionally based on purchase register.

    Injected issues:
        - Some vendor invoices missing (simulating non-filing)
        - Date format standardized to DD/MM/YYYY (portal style)
        - ITC marked as "No" for some entries
    """
    if purchase_df is None:
        purchase_df = generate_mock_purchase_register(30)

    rows = []
    for _, row in purchase_df.iterrows():
        inv_no = str(row.get("Voucher No", "")).strip()
        if not inv_no:
            continue

        # Skip some to simulate missing vendor filings
        if random.random() < missing_filing_rate:
            continue

        gstin = str(row.get("GSTIN/UIN", "")).strip()
        if not gstin or len(gstin) < 10:
            continue

        taxable_raw = str(row.get("Taxable Value", "0"))
        try:
            taxable = float(taxable_raw.replace(",", ""))
        except ValueError:
            continue

        # Slight discrepancy in some values
        if random.random() < 0.08:
            taxable = round(taxable + random.uniform(-5, 5), 2)

        cgst = float(str(row.get("CGST", "0")).replace(",", "") or "0")
        sgst = float(str(row.get("SGST", "0")).replace(",", "") or "0")
        igst = float(str(row.get("IGST", "0")).replace(",", "") or "0")

        inv_date_raw = str(row.get("Voucher Date", "01/04/2024"))
        from ..utils.sanitizer import normalize_date as nd
        parsed = nd(inv_date_raw)
        inv_date_str = parsed.strftime("%d/%m/%Y") if parsed else "01/04/2024"

        itc = "Yes" if random.random() > 0.1 else "No"

        rows.append({
            "GSTIN of Supplier": gstin,
            "Trade Name": str(row.get("Party Name", "")),
            "Invoice Number": inv_no.replace("/", "-"),
            "Invoice Date": inv_date_str,
            "Invoice Value": round(taxable + cgst + sgst + igst, 2),
            "Taxable Value": taxable,
            "Rate": random.choice([5.0, 12.0, 18.0, 28.0]),
            "Central Tax": cgst,
            "State Tax": sgst,
            "Integrated Tax": igst,
            "Cess": 0.0,
            "Place of Supply": gstin[:2] if len(gstin) >= 2 else "27",
            "Reverse Charge": "N",
            "ITC Available": itc,
            "Filing Period": "032025",
        })

    df = pd.DataFrame(rows)

    if output_path:
        fp = Path(output_path)
        df.to_excel(fp, index=False, engine="openpyxl")

    return df


# ═══════════════════════════════════════════════════════════════
#  Generate All Mock Data
# ═══════════════════════════════════════════════════════════════

def generate_all_mock_data(
    output_dir: str | Path = "mock_output",
) -> dict[str, Path]:
    """
    Generate a complete set of mock data files for pipeline testing.

    Creates:
        - sales_register.xlsx   (messy ERP export)
        - purchase_register.xlsx (messy ERP export)
        - gstr1.json            (portal JSON with mismatches)
        - gstr2b.xlsx           (portal Excel with missing filings)

    Returns:
        Dict mapping file type → output path.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths = {}

    # 1. Sales Register
    sales_path = out / "sales_register.xlsx"
    sales_df = generate_mock_sales_register(50, sales_path)
    paths["sales_register"] = sales_path

    # 2. Purchase Register
    purchase_path = out / "purchase_register.xlsx"
    purchase_df = generate_mock_purchase_register(40, purchase_path)
    paths["purchase_register"] = purchase_path

    # 3. GSTR-1 JSON (derived from sales with mismatches)
    gstr1_path = out / "gstr1.json"
    generate_mock_gstr1_json(sales_df, gstr1_path, mismatch_rate=0.15)
    paths["gstr1_json"] = gstr1_path

    # 4. GSTR-2B Excel (derived from purchases with missing filings)
    gstr2b_path = out / "gstr2b.xlsx"
    generate_mock_gstr2b_excel(purchase_df, gstr2b_path, missing_filing_rate=0.2)
    paths["gstr2b_excel"] = gstr2b_path

    return paths
