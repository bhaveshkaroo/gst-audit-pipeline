"""
Data Sanitization Helpers
==========================
Utility functions for normalizing messy ERP / Tally export data
before it enters the validated Pydantic models.

Key capabilities:
    • Invoice number stripping (special chars, spaces, dashes)
    • Multi-format date parsing (DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, etc.)
    • Numeric coercion from string/float with rounding
    • Column name fuzzy matching for header detection
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

import pandas as pd


# ═══════════════════════════════════════════════════════════════
#  Invoice Number Sanitization
# ═══════════════════════════════════════════════════════════════

# Characters to strip for fuzzy invoice matching
_INVOICE_STRIP_RE = re.compile(r"[^A-Z0-9]", re.IGNORECASE)


def sanitize_invoice_number(invoice_no: str) -> str:
    """
    Strip all special characters, spaces, slashes, and dashes from
    an invoice number to produce a canonical form for matching.

    Examples:
        "INV/24-25/01"  →  "INV242501"
        "GST - 001/23"  →  "GST00123"
        " inv#456 "     →  "INV456"

    Args:
        invoice_no: Raw invoice number string.

    Returns:
        Upper-cased, alphanumeric-only canonical form.
    """
    if not invoice_no:
        return ""
    return _INVOICE_STRIP_RE.sub("", str(invoice_no).strip()).upper()


def invoice_numbers_match(inv_a: str, inv_b: str) -> bool:
    """
    Compare two invoice numbers after sanitization.

    Useful for matching books entries against portal entries where
    the same invoice may be recorded with different formatting.
    """
    return sanitize_invoice_number(inv_a) == sanitize_invoice_number(inv_b)


# ═══════════════════════════════════════════════════════════════
#  Date Parsing
# ═══════════════════════════════════════════════════════════════

# Common date formats encountered in Indian ERP exports
_DATE_FORMATS = [
    "%d-%m-%Y",     # 17-05-2025
    "%d/%m/%Y",     # 17/05/2025
    "%d-%b-%Y",     # 17-May-2025
    "%d-%b-%y",     # 17-May-25
    "%d/%m/%y",     # 17/05/25
    "%d-%m-%y",     # 17-05-25
    "%Y-%m-%d",     # 2025-05-17 (ISO)
    "%m/%d/%Y",     # 05/17/2025 (US — rare but seen in Excel)
    "%d.%m.%Y",     # 17.05.2025 (European)
    "%d %b %Y",     # 17 May 2025
    "%d %B %Y",     # 17 May 2025
    "%Y%m%d",       # 20250517 (compact)
]


def normalize_date(
    value: str | date | datetime | pd.Timestamp | float | int,
    *,
    dayfirst: bool = True,
) -> Optional[date]:
    """
    Parse a date from virtually any format encountered in Indian
    ERP/Tally exports.

    Handles:
    - String dates in multiple formats (DD/MM/YYYY, DD-MMM-YY, etc.)
    - Python date/datetime objects (pass-through)
    - Pandas Timestamps
    - Excel serial date numbers (float/int)

    Args:
        value: The raw date value.
        dayfirst: If True (default for India), parse DD/MM ambiguous
                  dates with day first.

    Returns:
        A `datetime.date` object, or None if parsing fails.
    """
    if value is None:
        return None

    # Already a date
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()

    # Excel serial date number (e.g. 45429 → 2024-05-17)
    if isinstance(value, (int, float)):
        try:
            if 30000 < float(value) < 60000:
                # Excel epoch is 1899-12-30
                return (
                    pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(value))
                ).date()
        except (ValueError, OverflowError):
            pass

    # String parsing
    raw = str(value).strip()
    if not raw or raw.upper() in ("NA", "N/A", "-", "NIL", "NULL", ""):
        return None

    # Try explicit formats first (more reliable than pd.to_datetime)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # Fallback: pandas fuzzy parser
    try:
        return pd.to_datetime(raw, dayfirst=dayfirst).date()
    except (ValueError, pd.errors.ParserError):
        return None


# ═══════════════════════════════════════════════════════════════
#  Numeric Coercion
# ═══════════════════════════════════════════════════════════════

def safe_decimal(
    value,
    *,
    default: Decimal = Decimal("0.00"),
    places: int = 2,
) -> Decimal:
    """
    Safely coerce a value to Decimal with rounding.

    Handles:
    - Strings with commas ("1,23,456.78" → 123456.78)
    - Strings with currency symbols ("₹ 1,000.00")
    - Empty / None / NaN values → default
    - Float precision issues via string intermediary

    Args:
        value: Raw value from Excel/ERP.
        default: Value to return on failure.
        places: Decimal places for rounding.

    Returns:
        Rounded Decimal value.
    """
    if value is None:
        return default

    if isinstance(value, Decimal):
        return round(value, places)

    raw = str(value).strip()

    # Remove currency symbols, spaces, and Indian-style commas
    raw = re.sub(r"[₹$€£\s]", "", raw)

    # Handle negative in parentheses: (1000.00) → -1000.00
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]

    # Remove commas (Indian: 1,23,456.78 or Western: 123,456.78)
    raw = raw.replace(",", "")

    if not raw or raw.upper() in ("NAN", "NA", "N/A", "-", "NIL", "NULL"):
        return default

    try:
        return round(Decimal(raw), places)
    except InvalidOperation:
        return default


# ═══════════════════════════════════════════════════════════════
#  Column Name Fuzzy Matching
# ═══════════════════════════════════════════════════════════════

def fuzzy_column_match(
    actual_columns: Sequence[str],
    target_aliases: dict[str, list[str]],
) -> dict[str, str | None]:
    """
    Match messy DataFrame column names to expected field names
    using a dictionary of aliases.

    This handles ERP exports where headers may be:
    - "Inv. No.", "Invoice Number", "InvNo", "INVOICE_NO"
    - "GSTIN/UIN", "Vendor GSTIN", "GSTIN of Supplier"

    Args:
        actual_columns: List of column names from the DataFrame.
        target_aliases: Dict mapping canonical field name →
                        list of possible aliases (case-insensitive).

    Returns:
        Dict mapping canonical field name → matched column name
        (or None if no match found).

    Example:
        >>> fuzzy_column_match(
        ...     ["Inv. No.", "Dt", "GSTIN/UIN", "Taxable Amt"],
        ...     {
        ...         "invoice_no": ["inv", "invoice", "bill no"],
        ...         "date": ["dt", "date", "inv date"],
        ...     }
        ... )
        {'invoice_no': 'Inv. No.', 'date': 'Dt'}
    """
    result: dict[str, str | None] = {}
    # Pre-process: lowercase and strip actual columns
    normalised_actuals = {
        re.sub(r"[^a-z0-9]", "", col.lower()): col
        for col in actual_columns
    }

    for canonical, aliases in target_aliases.items():
        matched = None
        for alias in aliases:
            norm_alias = re.sub(r"[^a-z0-9]", "", alias.lower())
            for norm_col, orig_col in normalised_actuals.items():
                if norm_alias in norm_col or norm_col in norm_alias:
                    matched = orig_col
                    break
            if matched:
                break
        result[canonical] = matched

    return result
