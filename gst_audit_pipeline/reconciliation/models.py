"""
ITC Reconciliation Result Models
==================================
Pydantic models and enums for the reconciliation output layer.
"""

from __future__ import annotations

from enum import Enum
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


class MatchBucket(str, Enum):
    """
    Strict reconciliation classification buckets.
    Every transaction is assigned to exactly ONE bucket.
    """
    A_PERFECT_MATCH = "A_PERFECT_MATCH"
    B_MISSING_IN_PORTAL = "B_MISSING_IN_PORTAL"
    C_UNCLAIMED_IN_BOOKS = "C_UNCLAIMED_IN_BOOKS"
    D_AMOUNT_MISMATCH = "D_AMOUNT_MISMATCH"
    E_TIMING_DIFFERENCE = "E_TIMING_DIFFERENCE"


# Human-readable descriptions for audit reports
BUCKET_DESCRIPTIONS = {
    MatchBucket.A_PERFECT_MATCH: "Safe to finalize. Present in both Books and GSTR-2B with matching amounts.",
    MatchBucket.B_MISSING_IN_PORTAL: "Vendor default - Defer credit. Present in Books but absent in GSTR-2B.",
    MatchBucket.C_UNCLAIMED_IN_BOOKS: "Potential unclaimed expense. Present in GSTR-2B but absent in Books.",
    MatchBucket.D_AMOUNT_MISMATCH: "Invoice matched but Tax Amounts or Tax Rates differ. Needs manual review.",
    MatchBucket.E_TIMING_DIFFERENCE: "Present in Books and GSTR-2A (dynamic) but missing from current GSTR-2B (static cutoff).",
}


class ReconciliationLineItem(BaseModel):
    """Single reconciliation result row for audit trail."""
    match_bucket: MatchBucket
    supplier_gstin: str
    supplier_name: Optional[str] = None
    invoice_no_books: Optional[str] = None
    invoice_no_portal: Optional[str] = None
    invoice_date_books: Optional[str] = None
    invoice_date_portal: Optional[str] = None
    taxable_value_books: Decimal = Field(default=Decimal("0.00"))
    taxable_value_portal: Decimal = Field(default=Decimal("0.00"))
    tax_books: Decimal = Field(default=Decimal("0.00"))
    tax_portal: Decimal = Field(default=Decimal("0.00"))
    variance: Decimal = Field(default=Decimal("0.00"))
    remarks: str = ""
