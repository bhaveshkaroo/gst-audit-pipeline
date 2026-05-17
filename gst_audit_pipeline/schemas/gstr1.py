"""
GSTR-1 Portal JSON Schema
===========================
Models the official GSTR-1 JSON structure as downloaded from the
GST portal.  Covers the three most audit-critical sections:

    • B2B   (Table 4)  — Business-to-Business invoices
    • B2CS  (Table 7)  — B2C-Small (state-wise summary)
    • HSN   (Table 12) — HSN-wise summary of outward supplies

Reference: GSTN API specification v3.1
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════════
#  B2B — Table 4: Invoices for registered recipients
# ═══════════════════════════════════════════════════════════════

class GSTR1_B2B_Item(BaseModel):
    """Single line item within a B2B invoice."""
    item_number: int = Field(..., alias="num", ge=1)
    taxable_value: Decimal = Field(..., alias="txval", ge=0)
    tax_rate: Decimal = Field(..., alias="rt", ge=0)
    cgst: Decimal = Field(default=Decimal("0"), alias="camt", ge=0)
    sgst: Decimal = Field(default=Decimal("0"), alias="samt", ge=0)
    igst: Decimal = Field(default=Decimal("0"), alias="iamt", ge=0)
    cess: Decimal = Field(default=Decimal("0"), alias="csamt", ge=0)

    class Config:
        populate_by_name = True


class GSTR1_B2B_Invoice(BaseModel):
    """One B2B invoice filed under a specific recipient GSTIN."""
    invoice_no: str = Field(..., alias="inum", min_length=1)
    invoice_date: str = Field(
        ..., alias="idt",
        description="Date in DD-MM-YYYY format as per portal JSON.",
    )
    invoice_value: Decimal = Field(..., alias="val", ge=0)
    place_of_supply: str = Field(..., alias="pos", max_length=2)
    reverse_charge: str = Field(default="N", alias="rchrg")
    invoice_type: str = Field(default="R", alias="inv_typ")
    items: List[GSTR1_B2B_Item] = Field(..., alias="itms")

    @field_validator("invoice_date", mode="before")
    @classmethod
    def normalise_date(cls, v: str) -> str:
        return str(v).strip()

    class Config:
        populate_by_name = True


class GSTR1_B2B_Recipient(BaseModel):
    """Groups all B2B invoices for a single recipient GSTIN."""
    recipient_gstin: str = Field(..., alias="ctin", max_length=15)
    invoices: List[GSTR1_B2B_Invoice] = Field(..., alias="inv")

    @field_validator("recipient_gstin", mode="before")
    @classmethod
    def normalise_gstin(cls, v: str) -> str:
        cleaned = str(v).strip().upper().replace(" ", "")
        if len(cleaned) == 14:
            cleaned = "0" + cleaned
        return cleaned

    class Config:
        populate_by_name = True


# ═══════════════════════════════════════════════════════════════
#  B2CS — Table 7: B2C-Small (state-wise, rate-wise summary)
# ═══════════════════════════════════════════════════════════════

class GSTR1_B2CS_Entry(BaseModel):
    """One row in the B2C-Small summary section."""
    place_of_supply: str = Field(..., alias="pos", max_length=2)
    supply_type: str = Field(
        default="INTRA",
        description="INTRA or INTER state supply.",
    )
    tax_rate: Decimal = Field(..., alias="rt", ge=0)
    taxable_value: Decimal = Field(..., alias="txval", ge=0)
    cgst: Decimal = Field(default=Decimal("0"), alias="camt", ge=0)
    sgst: Decimal = Field(default=Decimal("0"), alias="samt", ge=0)
    igst: Decimal = Field(default=Decimal("0"), alias="iamt", ge=0)
    cess: Decimal = Field(default=Decimal("0"), alias="csamt", ge=0)

    class Config:
        populate_by_name = True


# ═══════════════════════════════════════════════════════════════
#  HSN — Table 12: HSN-wise summary of outward supplies
# ═══════════════════════════════════════════════════════════════

class GSTR1_HSN_Entry(BaseModel):
    """One row in the HSN summary table."""
    hsn_sc: str = Field(..., alias="hsn_sc", min_length=4, max_length=8)
    description: Optional[str] = Field(None, alias="desc")
    uqc: str = Field(
        default="NOS", alias="uqc",
        description="Unit Quantity Code (NOS, KGS, MTR, etc.).",
    )
    quantity: Decimal = Field(default=Decimal("0"), alias="qty", ge=0)
    taxable_value: Decimal = Field(..., alias="txval", ge=0)
    igst: Decimal = Field(default=Decimal("0"), alias="iamt", ge=0)
    cgst: Decimal = Field(default=Decimal("0"), alias="camt", ge=0)
    sgst: Decimal = Field(default=Decimal("0"), alias="samt", ge=0)
    cess: Decimal = Field(default=Decimal("0"), alias="csamt", ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), alias="rt", ge=0)

    class Config:
        populate_by_name = True


# ═══════════════════════════════════════════════════════════════
#  Top-level GSTR-1 Filing container
# ═══════════════════════════════════════════════════════════════

class GSTR1Filing(BaseModel):
    """
    Root model for a complete GSTR-1 JSON file.
    Encompasses B2B, B2CS, and HSN sections.
    """
    gstin: str = Field(..., alias="gstin", max_length=15)
    return_period: str = Field(
        ..., alias="fp",
        description="Return filing period in MMYYYY format.",
    )
    b2b: List[GSTR1_B2B_Recipient] = Field(default_factory=list, alias="b2b")
    b2cs: List[GSTR1_B2CS_Entry] = Field(default_factory=list, alias="b2cs")
    hsn: List[GSTR1_HSN_Entry] = Field(default_factory=list, alias="hsn")

    @field_validator("return_period", mode="before")
    @classmethod
    def validate_period(cls, v: str) -> str:
        v = str(v).strip()
        if len(v) != 6 or not v.isdigit():
            raise ValueError(
                f"Return period must be MMYYYY format, got '{v}'."
            )
        month = int(v[:2])
        if month < 1 or month > 12:
            raise ValueError(f"Invalid month {month} in return period.")
        return v

    class Config:
        populate_by_name = True
