"""
JSON Parser — GSTR-1 and GSTR-3B portal JSON files
====================================================
Parses the native JSON files downloaded from the GST portal.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from ..schemas.gstr1 import (
    GSTR1Filing,
    GSTR1_B2B_Recipient,
    GSTR1_B2CS_Entry,
    GSTR1_HSN_Entry,
)

logger = logging.getLogger(__name__)


def _load_json(filepath: str | Path) -> dict:
    """Load and validate a JSON file."""
    fp = Path(filepath)
    if not fp.exists():
        raise FileNotFoundError(f"JSON file not found: {fp}")
    if fp.suffix.lower() != ".json":
        raise ValueError(f"Expected .json file, got: {fp.suffix}")

    with open(fp, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object/dict.")
    return data


def parse_gstr1_json(
    filepath: str | Path,
) -> tuple[GSTR1Filing, List[dict]]:
    """
    Parse a GSTR-1 JSON file from the GST portal.

    The portal JSON structure:
    {
        "gstin": "...",
        "fp": "MMYYYY",
        "b2b": [ { "ctin": "...", "inv": [...] } ],
        "b2cs": [...],
        "hsn": { "data": [...] }
    }

    Returns:
        Tuple of (GSTR1Filing model, list of parse warnings).
    """
    data = _load_json(filepath)
    warnings: List[dict] = []

    # Extract HSN data — sometimes nested under "data" key
    hsn_raw = data.get("hsn", [])
    if isinstance(hsn_raw, dict):
        hsn_raw = hsn_raw.get("data", [])

    # Flatten B2B items structure
    b2b_raw = data.get("b2b", [])
    b2b_parsed: List[dict] = []
    for recipient in b2b_raw:
        try:
            inv_list = recipient.get("inv", [])
            for inv in inv_list:
                items_raw = inv.get("itms", [])
                flat_items = []
                for item in items_raw:
                    det = item.get("itm_det", item)
                    flat_items.append({
                        "num": item.get("num", 1),
                        **det,
                    })
                inv["itms"] = flat_items
            b2b_parsed.append(recipient)
        except Exception as exc:
            warnings.append({
                "section": "b2b",
                "ctin": recipient.get("ctin", "unknown"),
                "error": str(exc),
            })

    filing_data = {
        "gstin": data.get("gstin", ""),
        "fp": data.get("fp", ""),
        "b2b": b2b_parsed,
        "b2cs": data.get("b2cs", []),
        "hsn": hsn_raw,
    }

    try:
        filing = GSTR1Filing(**filing_data)
    except ValidationError as exc:
        logger.error("GSTR-1 validation failed: %s", exc)
        raise

    total_b2b = sum(len(r.invoices) for r in filing.b2b)
    logger.info(
        "GSTR-1 parsed: %d B2B recipients (%d invoices), "
        "%d B2CS entries, %d HSN entries.",
        len(filing.b2b), total_b2b, len(filing.b2cs), len(filing.hsn),
    )
    return filing, warnings


def parse_gstr3b_json(
    filepath: str | Path,
) -> tuple[Dict[str, Any], List[dict]]:
    """
    Parse a GSTR-3B JSON file.

    GSTR-3B is a summary return. We extract key liability
    and ITC tables without strict schema enforcement
    (structure varies across periods).

    Returns:
        Tuple of (parsed dict with standardised keys, warnings).
    """
    data = _load_json(filepath)
    warnings: List[dict] = []

    result: Dict[str, Any] = {
        "gstin": data.get("gstin", ""),
        "return_period": data.get("ret_period", data.get("fp", "")),
    }

    # Table 3.1 — Outward supplies
    sup_details = data.get("sup_details", data.get("sup_det", {}))
    if isinstance(sup_details, dict):
        result["outward_taxable"] = sup_details.get("osup_det", {})
        result["outward_zero_rated"] = sup_details.get("osup_zero", {})
        result["outward_nil_exempt"] = sup_details.get("osup_nil_exmp", {})
        result["inward_reverse_charge"] = sup_details.get("isup_rev", {})
        result["outward_non_gst"] = sup_details.get("osup_nongst", {})

    # Table 4 — ITC
    itc_elg = data.get("itc_elg", {})
    if isinstance(itc_elg, dict):
        result["itc_available"] = itc_elg.get("itc_avl", [])
        result["itc_reversed"] = itc_elg.get("itc_rev", [])
        result["itc_net"] = itc_elg.get("itc_net", {})
        result["itc_ineligible"] = itc_elg.get("itc_inelg", [])

    # Table 5 — Interest & late fee
    result["interest_late_fee"] = data.get("intr_ltfee", {})

    # Table 6 — Tax paid
    result["tax_paid"] = data.get("itc_elg", {}).get("itc_net", {})

    logger.info("GSTR-3B parsed for period: %s", result["return_period"])
    return result, warnings
