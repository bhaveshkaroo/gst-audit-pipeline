"""Pydantic schemas for all GST data structures."""

from .sales_register import SalesRegisterEntry
from .purchase_register import PurchaseRegisterEntry
from .gstr1 import (
    GSTR1_B2B_Invoice,
    GSTR1_B2B_Item,
    GSTR1_B2B_Recipient,
    GSTR1_B2CS_Entry,
    GSTR1_HSN_Entry,
    GSTR1Filing,
)
from .gstr2b import GSTR2B_B2B_Invoice, GSTR2B_B2B_Supplier, GSTR2BStatement

__all__ = [
    "SalesRegisterEntry",
    "PurchaseRegisterEntry",
    "GSTR1_B2B_Invoice",
    "GSTR1_B2B_Item",
    "GSTR1_B2B_Recipient",
    "GSTR1_B2CS_Entry",
    "GSTR1_HSN_Entry",
    "GSTR1Filing",
    "GSTR2B_B2B_Invoice",
    "GSTR2B_B2B_Supplier",
    "GSTR2BStatement",
]
