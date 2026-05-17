"""
Excel Parser — Robust ingestion for ERP/Tally exports and GSTR-2B
==================================================================
Handles real-world mess of Indian accounting Excel files:
    - Merged header rows, multi-line headers
    - Inconsistent column naming across ERP vendors
    - String-formatted dates, currency symbols in amounts
    - Missing trailing zeros in GSTINs
    - Blank rows, totals rows, summary footers
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Sequence

import pandas as pd
from pydantic import ValidationError

from ..schemas.sales_register import SalesRegisterEntry, SupplyType
from ..schemas.purchase_register import PurchaseRegisterEntry
from ..schemas.gstr2b import (
    GSTR2B_B2B_Invoice,
    GSTR2B_B2B_Supplier,
    GSTR2BStatement,
    GSTR2B_ITCAvailability,
)
from ..utils.sanitizer import normalize_date, safe_decimal, fuzzy_column_match
from ..utils.gstin_validator import validate_gstin

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════════

def _detect_header_row(
    filepath: str | Path,
    sheet_name: str | int = 0,
    *,
    max_scan_rows: int = 20,
    min_non_null_cols: int = 3,
) -> int:
    """Auto-detect header row in messy ERP exports."""
    try:
        raw = pd.read_excel(
            filepath, sheet_name=sheet_name,
            header=None, nrows=max_scan_rows, dtype=str,
        )
    except Exception as exc:
        logger.warning("Header detection failed for %s: %s", filepath, exc)
        return 0

    for idx, row in raw.iterrows():
        non_null = row.dropna()
        text_cells = sum(
            1 for v in non_null
            if isinstance(v, str) and not v.replace(".", "").isdigit()
        )
        if text_cells >= min_non_null_cols:
            return int(idx)
    return 0


def _read_excel_smart(
    filepath: str | Path,
    sheet_name: str | int = 0,
    *,
    header_row: Optional[int] = None,
) -> pd.DataFrame:
    """Read Excel with intelligent header detection and cleanup."""
    fp = Path(filepath)
    if not fp.exists():
        raise FileNotFoundError(f"Excel file not found: {fp}")
    if fp.suffix.lower() not in (".xlsx", ".xls", ".xlsm"):
        raise ValueError(f"Unsupported file format: {fp.suffix}")

    if header_row is None:
        header_row = _detect_header_row(fp, sheet_name)

    logger.info("Reading %s (sheet=%s, header_row=%d)", fp, sheet_name, header_row)

    df = pd.read_excel(fp, sheet_name=sheet_name, header=header_row, dtype=str)

    # Clean column names
    df.columns = [
        str(c).strip().replace("\n", " ").replace("\r", "")
        for c in df.columns
    ]

    # Drop fully-NaN rows
    df = df.dropna(how="all").reset_index(drop=True)

    # Drop total/summary rows
    total_keywords = {"total", "grand total", "sub total", "subtotal", "sum"}
    mask = df.apply(
        lambda row: any(
            str(v).strip().lower() in total_keywords
            for v in row if pd.notna(v)
        ),
        axis=1,
    )
    df = df[~mask].reset_index(drop=True)
    logger.info("Loaded %d data rows, %d columns.", len(df), len(df.columns))
    return df


# ═══════════════════════════════════════════════════════════════
#  Column alias mappings
# ═══════════════════════════════════════════════════════════════

_SALES_ALIASES = {
    "invoice_no": ["invoice no", "inv no", "invoice number", "bill no",
                   "voucher no", "inv", "invno", "document no", "doc no"],
    "invoice_date": ["invoice date", "inv date", "date", "inv dt", "dt",
                     "bill date", "voucher date", "doc date"],
    "customer_gstin": ["gstin", "customer gstin", "gstin/uin", "party gstin",
                       "buyer gstin", "gstin of recipient"],
    "customer_name": ["customer name", "party name", "buyer name", "name",
                      "customer", "party", "buyer"],
    "place_of_supply": ["place of supply", "pos", "state"],
    "taxable_value": ["taxable value", "taxable amt", "taxable amount",
                      "assessable value", "base amount", "net amount"],
    "tax_rate": ["tax rate", "rate", "gst rate", "rate %", "gst %"],
    "cgst": ["cgst", "cgst amount", "cgst amt", "central tax"],
    "sgst": ["sgst", "sgst amount", "sgst amt", "state tax", "utgst"],
    "igst": ["igst", "igst amount", "igst amt", "integrated tax"],
    "cess": ["cess", "cess amount", "cess amt", "compensation cess"],
    "hsn_sac": ["hsn", "sac", "hsn/sac", "hsn code", "sac code",
                "hsn_sac", "hsncode", "saccode"],
    "supply_type": ["supply type", "type", "nature", "goods/services",
                    "type of supply"],
}

_PURCHASE_ALIASES = {
    "invoice_no": ["invoice no", "inv no", "invoice number", "bill no",
                   "voucher no", "supplier inv", "vendor invoice"],
    "invoice_date": ["invoice date", "inv date", "date", "bill date",
                     "voucher date"],
    "vendor_gstin": ["gstin", "vendor gstin", "supplier gstin", "gstin/uin",
                     "party gstin", "gstin of supplier"],
    "vendor_name": ["vendor name", "supplier name", "party name", "name"],
    "taxable_value": ["taxable value", "taxable amt", "taxable amount",
                      "base amount", "net amount"],
    "cgst": ["cgst", "cgst amount", "cgst amt", "central tax"],
    "sgst": ["sgst", "sgst amount", "sgst amt", "state tax", "utgst"],
    "igst": ["igst", "igst amount", "igst amt", "integrated tax"],
    "cess": ["cess", "cess amount", "cess amt"],
    "expense_head": ["expense head", "account head", "ledger", "gl account",
                     "expense account", "head of account", "account name",
                     "expense", "ledger name"],
}

_GSTR2B_ALIASES = {
    "supplier_gstin": ["gstin of supplier", "supplier gstin", "gstin",
                       "gstin/uin"],
    "supplier_name": ["trade name", "supplier name", "name of supplier",
                      "trade/legal name"],
    "invoice_no": ["invoice number", "invoice no", "inv no",
                   "document number"],
    "invoice_date": ["invoice date", "inv date", "date", "document date"],
    "invoice_value": ["invoice value", "total value", "gross value"],
    "taxable_value": ["taxable value", "taxable amt", "assessable value"],
    "tax_rate": ["rate", "tax rate", "gst rate"],
    "cgst": ["cgst", "central tax"],
    "sgst": ["sgst", "state tax", "utgst"],
    "igst": ["igst", "integrated tax"],
    "cess": ["cess", "compensation cess"],
    "place_of_supply": ["place of supply", "pos"],
    "reverse_charge": ["reverse charge", "rcm", "rchrg"],
    "itc_available": ["itc available", "itc availability", "itc"],
    "filing_period": ["filing period", "return period", "period",
                      "gstr1 period"],
}


# ═══════════════════════════════════════════════════════════════
#  Sales Register Parser
# ═══════════════════════════════════════════════════════════════

def parse_sales_register_excel(
    filepath: str | Path,
    *,
    sheet_name: str | int = 0,
    header_row: Optional[int] = None,
) -> tuple[List[SalesRegisterEntry], List[dict]]:
    """
    Parse a Sales Register Excel into validated Pydantic models.

    Returns:
        (parsed_entries, error_records)
    """
    df = _read_excel_smart(filepath, sheet_name, header_row=header_row)
    col_map = fuzzy_column_match(df.columns.tolist(), _SALES_ALIASES)

    required = ["invoice_no", "invoice_date", "taxable_value", "hsn_sac"]
    missing = [f for f in required if col_map.get(f) is None]
    if missing:
        raise ValueError(
            f"Missing required columns in Sales Register: {missing}. "
            f"Detected columns: {df.columns.tolist()}. Mapping: {col_map}"
        )

    entries: List[SalesRegisterEntry] = []
    errors: List[dict] = []

    for idx, row in df.iterrows():
        try:
            raw = {k: row.get(v) if v else None for k, v in col_map.items()}

            supply_raw = str(raw.get("supply_type", "Goods")).strip()
            supply = (SupplyType.SERVICES
                      if supply_raw.lower() in ("service", "services", "s")
                      else SupplyType.GOODS)

            entry = SalesRegisterEntry(
                invoice_no=str(raw["invoice_no"]).strip(),
                invoice_date=normalize_date(raw["invoice_date"]),
                customer_gstin=raw.get("customer_gstin"),
                customer_name=str(raw.get("customer_name", "")) or None,
                place_of_supply=(
                    str(raw.get("place_of_supply", ""))[:2] or None
                ),
                taxable_value=safe_decimal(raw["taxable_value"]),
                tax_rate=safe_decimal(
                    raw.get("tax_rate"), default=Decimal("18")
                ),
                cgst=safe_decimal(raw.get("cgst")),
                sgst=safe_decimal(raw.get("sgst")),
                igst=safe_decimal(raw.get("igst")),
                cess=safe_decimal(raw.get("cess")),
                hsn_sac=str(raw["hsn_sac"]).strip(),
                supply_type=supply,
            )
            entries.append(entry)
        except (ValidationError, Exception) as exc:
            errors.append({
                "row_index": idx,
                "raw_data": row.to_dict(),
                "errors": str(exc),
            })
            logger.warning("Row %d failed validation: %s", idx, exc)

    logger.info(
        "Sales Register: %d parsed, %d errors out of %d rows.",
        len(entries), len(errors), len(df),
    )
    return entries, errors


# ═══════════════════════════════════════════════════════════════
#  Purchase Register Parser
# ═══════════════════════════════════════════════════════════════

def parse_purchase_register_excel(
    filepath: str | Path,
    *,
    sheet_name: str | int = 0,
    header_row: Optional[int] = None,
) -> tuple[List[PurchaseRegisterEntry], List[dict]]:
    """
    Parse a Purchase Register Excel into validated Pydantic models.

    Returns:
        (parsed_entries, error_records)
    """
    df = _read_excel_smart(filepath, sheet_name, header_row=header_row)
    col_map = fuzzy_column_match(df.columns.tolist(), _PURCHASE_ALIASES)

    required = ["invoice_no", "invoice_date", "taxable_value", "expense_head"]
    missing = [f for f in required if col_map.get(f) is None]
    if missing:
        raise ValueError(
            f"Missing required columns in Purchase Register: {missing}. "
            f"Detected columns: {df.columns.tolist()}. Mapping: {col_map}"
        )

    entries: List[PurchaseRegisterEntry] = []
    errors: List[dict] = []

    for idx, row in df.iterrows():
        try:
            raw = {k: row.get(v) if v else None for k, v in col_map.items()}
            entry = PurchaseRegisterEntry(
                invoice_no=str(raw["invoice_no"]).strip(),
                invoice_date=normalize_date(raw["invoice_date"]),
                vendor_gstin=raw.get("vendor_gstin"),
                vendor_name=str(raw.get("vendor_name", "")) or None,
                taxable_value=safe_decimal(raw["taxable_value"]),
                cgst=safe_decimal(raw.get("cgst")),
                sgst=safe_decimal(raw.get("sgst")),
                igst=safe_decimal(raw.get("igst")),
                cess=safe_decimal(raw.get("cess")),
                expense_head=str(raw["expense_head"]).strip(),
            )
            entries.append(entry)
        except (ValidationError, Exception) as exc:
            errors.append({
                "row_index": idx,
                "raw_data": row.to_dict(),
                "errors": str(exc),
            })
            logger.warning("Row %d failed validation: %s", idx, exc)

    logger.info(
        "Purchase Register: %d parsed, %d errors out of %d rows.",
        len(entries), len(errors), len(df),
    )
    return entries, errors


# ═══════════════════════════════════════════════════════════════
#  GSTR-2B Excel Parser
# ═══════════════════════════════════════════════════════════════

def parse_gstr2b_excel(
    filepath: str | Path,
    *,
    recipient_gstin: str,
    return_period: str,
    sheet_name: str | int = 0,
    header_row: Optional[int] = None,
) -> tuple[GSTR2BStatement, List[dict]]:
    """
    Parse a GSTR-2B Excel download into a validated statement.

    Returns:
        (GSTR2BStatement, error_records)
    """
    df = _read_excel_smart(filepath, sheet_name, header_row=header_row)
    col_map = fuzzy_column_match(df.columns.tolist(), _GSTR2B_ALIASES)

    required = ["supplier_gstin", "invoice_no", "invoice_date",
                "taxable_value"]
    missing = [f for f in required if col_map.get(f) is None]
    if missing:
        raise ValueError(
            f"Missing required columns in GSTR-2B: {missing}. "
            f"Detected columns: {df.columns.tolist()}."
        )

    supplier_map: dict[str, GSTR2B_B2B_Supplier] = {}
    errors: List[dict] = []

    for idx, row in df.iterrows():
        try:
            raw = {k: row.get(v) if v else None for k, v in col_map.items()}

            gstin_raw = str(raw["supplier_gstin"]).strip().upper()
            if len(gstin_raw) == 14:
                gstin_raw = "0" + gstin_raw

            itc_raw = str(raw.get("itc_available", "Yes")).strip().lower()
            if itc_raw in ("yes", "y", "available"):
                itc_avail = GSTR2B_ITCAvailability.YES
            elif itc_raw in ("no", "n", "not available"):
                itc_avail = GSTR2B_ITCAvailability.NO
            else:
                itc_avail = GSTR2B_ITCAvailability.PENDING

            rcm_raw = str(raw.get("reverse_charge", "N")).strip().upper()
            is_rcm = rcm_raw in ("Y", "YES", "TRUE", "1")

            invoice = GSTR2B_B2B_Invoice(
                supplier_gstin=gstin_raw,
                supplier_name=str(raw.get("supplier_name", "")) or None,
                invoice_no=str(raw["invoice_no"]).strip(),
                invoice_date=normalize_date(raw["invoice_date"]),
                invoice_value=safe_decimal(
                    raw.get("invoice_value"), default=Decimal("0.00")
                ),
                taxable_value=safe_decimal(raw["taxable_value"]),
                tax_rate=safe_decimal(raw.get("tax_rate")),
                cgst=safe_decimal(raw.get("cgst")),
                sgst=safe_decimal(raw.get("sgst")),
                igst=safe_decimal(raw.get("igst")),
                cess=safe_decimal(raw.get("cess")),
                place_of_supply=(
                    str(raw.get("place_of_supply", ""))[:2] or None
                ),
                reverse_charge=is_rcm,
                itc_available=itc_avail,
                filing_period=str(
                    raw.get("filing_period", return_period)
                ),
            )

            if gstin_raw not in supplier_map:
                supplier_map[gstin_raw] = GSTR2B_B2B_Supplier(
                    supplier_gstin=gstin_raw,
                    supplier_name=invoice.supplier_name,
                )
            supplier_map[gstin_raw].invoices.append(invoice)

        except (ValidationError, Exception) as exc:
            errors.append({
                "row_index": idx,
                "raw_data": row.to_dict(),
                "errors": str(exc),
            })
            logger.warning("GSTR-2B row %d failed: %s", idx, exc)

    statement = GSTR2BStatement(
        recipient_gstin=recipient_gstin,
        return_period=return_period,
        b2b_suppliers=list(supplier_map.values()),
    )

    logger.info(
        "GSTR-2B: %d suppliers, %d total invoices, %d errors.",
        len(supplier_map),
        sum(len(s.invoices) for s in supplier_map.values()),
        len(errors),
    )
    return statement, errors
