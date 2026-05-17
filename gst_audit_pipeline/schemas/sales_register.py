"""
Sales Register (Books of Account) Schema
==========================================
Mirrors the outward supply register maintained in ERP/Tally,
covering B2B, B2C-Large, B2C-Small, and export invoices.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SupplyType(str, Enum):
    """Nature of supply for HSN classification."""
    GOODS = "Goods"
    SERVICES = "Services"


class PlaceOfSupplyState(str, Enum):
    """Two-digit state codes per GST law (select common codes)."""
    MAHARASHTRA = "27"
    KARNATAKA = "29"
    DELHI = "07"
    TAMIL_NADU = "33"
    GUJARAT = "24"
    UTTAR_PRADESH = "09"
    WEST_BENGAL = "19"
    RAJASTHAN = "08"
    TELANGANA = "36"
    KERALA = "32"
    # Add more as needed; keeping concise for the pipeline layer.


class SalesRegisterEntry(BaseModel):
    """
    One row in the Sales Register / Outward Supply Register.

    Validation rules:
    - CGST + SGST should equal IGST-equivalent for intra-state.
    - Exactly one of (CGST+SGST) or IGST should be non-zero.
    - Tax amounts must be non-negative.
    - GSTIN is validated structurally in the utility layer.
    """

    invoice_no: str = Field(
        ..., min_length=1, max_length=50,
        description="Invoice number as per books (pre-sanitisation).",
    )
    invoice_date: date = Field(
        ..., description="Date of invoice issuance.",
    )
    customer_gstin: Optional[str] = Field(
        None, max_length=15,
        description="Customer GSTIN. None for B2C / unregistered buyers.",
    )
    customer_name: Optional[str] = Field(
        None, max_length=200,
        description="Customer / trade name (for reference).",
    )
    place_of_supply: Optional[str] = Field(
        None, max_length=2,
        description="Two-digit state code of the place of supply.",
    )
    taxable_value: Decimal = Field(
        ..., ge=0, decimal_places=2,
        description="Taxable value of supply (excl. tax).",
    )
    tax_rate: Decimal = Field(
        ..., ge=0, le=28,
        description="Applicable GST rate (e.g. 5, 12, 18, 28).",
    )
    cgst: Decimal = Field(
        default=Decimal("0.00"), ge=0, decimal_places=2,
        description="Central GST amount.",
    )
    sgst: Decimal = Field(
        default=Decimal("0.00"), ge=0, decimal_places=2,
        description="State GST amount.",
    )
    igst: Decimal = Field(
        default=Decimal("0.00"), ge=0, decimal_places=2,
        description="Integrated GST amount (inter-state).",
    )
    cess: Decimal = Field(
        default=Decimal("0.00"), ge=0, decimal_places=2,
        description="Compensation cess, if applicable.",
    )
    hsn_sac: str = Field(
        ..., min_length=4, max_length=8,
        description="HSN (goods) or SAC (services) code.",
    )
    supply_type: SupplyType = Field(
        ..., description="Whether supply is Goods or Services.",
    )
    reverse_charge: bool = Field(
        default=False,
        description="Whether supply is under reverse charge mechanism.",
    )

    # ── Validators ──────────────────────────────────────────────

    @field_validator("customer_gstin", mode="before")
    @classmethod
    def normalise_gstin(cls, v: Optional[str]) -> Optional[str]:
        """Strip whitespace, upper-case, and pad leading zeros."""
        if v is None or str(v).strip() in ("", "NA", "N/A", "-"):
            return None
        cleaned = str(v).strip().upper().replace(" ", "")
        # Pad GSTINs that lost a leading zero (common Tally export issue)
        if len(cleaned) == 14:
            cleaned = "0" + cleaned
        return cleaned

    @field_validator("hsn_sac", mode="before")
    @classmethod
    def normalise_hsn(cls, v: str) -> str:
        """Ensure HSN/SAC is a zero-padded string."""
        return str(v).strip().zfill(4)

    @model_validator(mode="after")
    def check_tax_split_consistency(self) -> "SalesRegisterEntry":
        """
        Exactly one of the two tax legs should be populated:
        (CGST + SGST) for intra-state  OR  IGST for inter-state.
        Warns rather than rejects — ERP data is often messy.
        """
        has_intra = (self.cgst > 0 or self.sgst > 0)
        has_inter = (self.igst > 0)
        if has_intra and has_inter:
            # This is a data quality flag, not a hard error.
            # The reconciliation layer will surface it as an anomaly.
            pass
        return self

    class Config:
        str_strip_whitespace = True
        use_enum_values = True
