"""
Purchase Register (Books of Account) Schema
=============================================
Models the inward supply register for ITC tracking.
Maps to GSTR-2B for reconciliation in the next layer.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ITCEligibility(str, Enum):
    """ITC eligibility categories per Section 16/17 of CGST Act."""
    ELIGIBLE = "Eligible"
    INELIGIBLE = "Ineligible"
    PARTIAL = "Partial"
    REVERSE_CHARGE = "Reverse Charge"


class PurchaseRegisterEntry(BaseModel):
    """
    One row in the Purchase Register / Inward Supply Register.

    Each row represents a single vendor invoice line, including the
    GL expense head for ledger-level reconciliation.
    """

    invoice_no: str = Field(
        ..., min_length=1, max_length=50,
        description="Vendor invoice number as per books.",
    )
    invoice_date: date = Field(
        ..., description="Date on the vendor invoice.",
    )
    booking_date: Optional[date] = Field(
        None,
        description="Date when the invoice was booked in books. "
                     "Used to detect late ITC claims.",
    )
    vendor_gstin: Optional[str] = Field(
        None, max_length=15,
        description="Supplier GSTIN. None for unregistered / import entries.",
    )
    vendor_name: Optional[str] = Field(
        None, max_length=200,
        description="Supplier trade name.",
    )
    taxable_value: Decimal = Field(
        ..., ge=0, decimal_places=2,
        description="Taxable value before GST.",
    )
    cgst: Decimal = Field(
        default=Decimal("0.00"), ge=0, decimal_places=2,
    )
    sgst: Decimal = Field(
        default=Decimal("0.00"), ge=0, decimal_places=2,
    )
    igst: Decimal = Field(
        default=Decimal("0.00"), ge=0, decimal_places=2,
    )
    cess: Decimal = Field(
        default=Decimal("0.00"), ge=0, decimal_places=2,
    )
    total_invoice_value: Optional[Decimal] = Field(
        None, ge=0,
        description="Gross invoice value (taxable + tax). "
                     "Auto-calculated if not supplied.",
    )
    expense_head: str = Field(
        ..., min_length=1, max_length=200,
        description="GL / Expense-head account string from ERP "
                     "(e.g. 'Office Supplies', 'Professional Fees').",
    )
    itc_eligibility: ITCEligibility = Field(
        default=ITCEligibility.ELIGIBLE,
        description="ITC eligibility classification.",
    )
    reverse_charge: bool = Field(
        default=False,
        description="Whether purchase falls under RCM.",
    )
    tds_applicable: bool = Field(
        default=False,
        description="Whether TDS under GST (Section 51) applies.",
    )

    # ── Validators ──────────────────────────────────────────────

    @field_validator("vendor_gstin", mode="before")
    @classmethod
    def normalise_gstin(cls, v: Optional[str]) -> Optional[str]:
        if v is None or str(v).strip() in ("", "NA", "N/A", "-", "URD"):
            return None
        cleaned = str(v).strip().upper().replace(" ", "")
        if len(cleaned) == 14:
            cleaned = "0" + cleaned
        return cleaned

    @field_validator("expense_head", mode="before")
    @classmethod
    def normalise_expense_head(cls, v: str) -> str:
        """Trim and title-case the expense head for consistency."""
        return str(v).strip().title()

    @field_validator("total_invoice_value", mode="before")
    @classmethod
    def coerce_total(cls, v):
        if v is None or v == "":
            return None
        return Decimal(str(v))

    def compute_total(self) -> Decimal:
        """Calculate gross invoice value from components."""
        return self.taxable_value + self.cgst + self.sgst + self.igst + self.cess

    class Config:
        str_strip_whitespace = True
        use_enum_values = True
