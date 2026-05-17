"""
GSTR-2B (Auto-drafted ITC Statement) Schema
=============================================
Models the GSTR-2B statement as downloaded from the GST portal
in Excel format.  This is the static, system-generated ITC
statement used to verify input tax credit eligibility.

Key sections modelled:
    • B2B — Invoices from registered suppliers
    • Supplier-level grouping for reconciliation
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class GSTR2B_ITCAvailability(str, Enum):
    """ITC availability status as per GSTR-2B."""
    YES = "Yes"
    NO = "No"
    PENDING = "Pending"


class GSTR2B_ActionType(str, Enum):
    """Action status on the supplier's filing."""
    FILED = "Filed"
    NOT_FILED = "Not Filed"
    CANCELLED = "Cancelled"


class GSTR2B_B2B_Invoice(BaseModel):
    """
    Single invoice line from GSTR-2B B2B section.
    Maps to a row in the downloaded Excel statement.
    """

    supplier_gstin: str = Field(
        ..., max_length=15,
        description="Supplier's GSTIN.",
    )
    supplier_name: Optional[str] = Field(
        None, max_length=200,
        description="Supplier trade name.",
    )
    invoice_no: str = Field(
        ..., min_length=1, max_length=50,
        description="Supplier's invoice number.",
    )
    invoice_date: date = Field(
        ..., description="Invoice date.",
    )
    invoice_value: Decimal = Field(
        ..., ge=0,
        description="Total invoice value including tax.",
    )
    taxable_value: Decimal = Field(
        ..., ge=0,
        description="Taxable value (base amount).",
    )
    tax_rate: Optional[Decimal] = Field(
        None, ge=0,
        description="Applicable tax rate.",
    )
    cgst: Decimal = Field(default=Decimal("0.00"), ge=0)
    sgst: Decimal = Field(default=Decimal("0.00"), ge=0)
    igst: Decimal = Field(default=Decimal("0.00"), ge=0)
    cess: Decimal = Field(default=Decimal("0.00"), ge=0)
    place_of_supply: Optional[str] = Field(
        None, max_length=2,
        description="Two-digit state code.",
    )
    reverse_charge: bool = Field(
        default=False,
        description="Whether RCM applies.",
    )
    itc_available: GSTR2B_ITCAvailability = Field(
        default=GSTR2B_ITCAvailability.YES,
        description="ITC availability as determined by the portal.",
    )
    filing_period: Optional[str] = Field(
        None, max_length=6,
        description="Return period (MMYYYY) in which supplier filed.",
    )
    action_status: GSTR2B_ActionType = Field(
        default=GSTR2B_ActionType.FILED,
        description="Filing action status of the supplier.",
    )

    # ── Validators ──────────────────────────────────────────────

    @field_validator("supplier_gstin", mode="before")
    @classmethod
    def normalise_gstin(cls, v: str) -> str:
        cleaned = str(v).strip().upper().replace(" ", "")
        if len(cleaned) == 14:
            cleaned = "0" + cleaned
        return cleaned

    class Config:
        str_strip_whitespace = True
        use_enum_values = True


class GSTR2B_B2B_Supplier(BaseModel):
    """Groups all GSTR-2B invoices under a single supplier."""
    supplier_gstin: str = Field(..., max_length=15)
    supplier_name: Optional[str] = None
    invoices: List[GSTR2B_B2B_Invoice] = Field(default_factory=list)


class GSTR2BStatement(BaseModel):
    """
    Root model for a GSTR-2B statement.
    Typically parsed from the Excel download.
    """
    recipient_gstin: str = Field(
        ..., max_length=15,
        description="Assessee GSTIN (the company being audited).",
    )
    return_period: str = Field(
        ..., max_length=6,
        description="GSTR-2B period in MMYYYY format.",
    )
    b2b_suppliers: List[GSTR2B_B2B_Supplier] = Field(default_factory=list)

    @field_validator("return_period", mode="before")
    @classmethod
    def validate_period(cls, v: str) -> str:
        v = str(v).strip()
        if len(v) != 6 or not v.isdigit():
            raise ValueError(
                f"Return period must be MMYYYY format, got '{v}'."
            )
        return v

    class Config:
        str_strip_whitespace = True
