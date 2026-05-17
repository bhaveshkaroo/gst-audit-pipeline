"""
GSTIN Structure Validator
==========================
Validates the 15-character GSTIN format per the GST law:

    Position  | Content
    ----------|-------------------------------------------
    1-2       | State code (01–37, 97 for Other Territory)
    3-12      | PAN (AAAAA9999A pattern)
    13        | Entity number (1-9, then A-Z)
    14        | 'Z' by default (reserved)
    15        | Check digit (Luhn mod-36 checksum)

Uses the official Mod-36 checksum algorithm published by GSTN.
"""

from __future__ import annotations

import re
from typing import Tuple

# Valid two-digit state codes as per GST notification
_VALID_STATE_CODES = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
    "31", "32", "33", "34", "35", "36", "37",
    "38",  # Ladakh (added post-2019)
    "97",  # Other Territory
}

# Characters allowed in GSTIN (digits 0-9 + letters A-Z = 36 chars)
_GSTIN_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_CHAR_TO_VALUE = {c: i for i, c in enumerate(_GSTIN_CHARSET)}

# PAN pattern: 5 letters, 4 digits, 1 letter
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Full GSTIN structural regex
_GSTIN_RE = re.compile(
    r"^[0-9]{2}"       # State code
    r"[A-Z]{5}[0-9]{4}[A-Z]"  # PAN
    r"[1-9A-Z]"        # Entity number
    r"[A-Z]"           # Reserved (usually Z)
    r"[0-9A-Z]$"       # Check digit
)


def gstin_checksum(gstin_14: str) -> str:
    """
    Compute the Mod-36 check character for the first 14 characters
    of a GSTIN.

    Algorithm (GSTN official):
        1. For each character at position i (0-indexed):
           - Get its value from the charset (0–35).
           - If position is odd (1-indexed), multiply value by 2.
           - Compute: factor = value * (1 + (i % 2))
           - Add (factor // 36) + (factor % 36) to running total.
        2. Remainder = total % 36
        3. Check digit = charset[(36 - remainder) % 36]

    Args:
        gstin_14: First 14 characters of GSTIN (upper-case, no spaces).

    Returns:
        Single check-digit character.

    Raises:
        ValueError: If input is not exactly 14 valid characters.
    """
    if len(gstin_14) != 14:
        raise ValueError(
            f"Expected 14 characters for checksum, got {len(gstin_14)}."
        )

    total = 0
    for i, char in enumerate(gstin_14):
        if char not in _CHAR_TO_VALUE:
            raise ValueError(f"Invalid character '{char}' at position {i}.")
        value = _CHAR_TO_VALUE[char]
        # Multiply by 2 for odd positions (1-indexed)
        factor = value * (2 if (i + 1) % 2 == 0 else 1)
        total += (factor // 36) + (factor % 36)

    remainder = total % 36
    check_index = (36 - remainder) % 36
    return _GSTIN_CHARSET[check_index]


def validate_gstin(gstin: str) -> Tuple[bool, str]:
    """
    Validate a GSTIN string comprehensively.

    Checks performed:
        1. Length = 15 characters.
        2. Structural regex match.
        3. Valid state code (positions 1-2).
        4. Valid PAN structure (positions 3-12).
        5. Mod-36 checksum verification (position 15).

    Args:
        gstin: The GSTIN string to validate (whitespace is stripped).

    Returns:
        Tuple of (is_valid: bool, message: str).
        On success, message = "Valid GSTIN".
        On failure, message describes the specific error.
    """
    if gstin is None:
        return False, "GSTIN is None."

    cleaned = str(gstin).strip().upper().replace(" ", "")

    # Pad leading zero if lost
    if len(cleaned) == 14:
        cleaned = "0" + cleaned

    if len(cleaned) != 15:
        return False, f"Invalid length: {len(cleaned)} (expected 15)."

    if not _GSTIN_RE.match(cleaned):
        return False, (
            f"Structural format mismatch. Expected pattern: "
            f"SSAAAAADDDDAZZC (state+PAN+entity+reserved+check)."
        )

    # State code check
    state_code = cleaned[:2]
    if state_code not in _VALID_STATE_CODES:
        return False, f"Invalid state code: '{state_code}'."

    # PAN check
    pan = cleaned[2:12]
    if not _PAN_RE.match(pan):
        return False, f"Invalid PAN structure: '{pan}'."

    # Checksum
    expected_check = gstin_checksum(cleaned[:14])
    actual_check = cleaned[14]
    if actual_check != expected_check:
        return False, (
            f"Checksum mismatch: expected '{expected_check}', "
            f"got '{actual_check}'."
        )

    return True, "Valid GSTIN."


def extract_state_code(gstin: str) -> str | None:
    """Extract two-digit state code from a valid GSTIN."""
    is_valid, _ = validate_gstin(gstin)
    if is_valid:
        cleaned = str(gstin).strip().upper().replace(" ", "")
        if len(cleaned) == 14:
            cleaned = "0" + cleaned
        return cleaned[:2]
    return None


def extract_pan(gstin: str) -> str | None:
    """Extract PAN from a valid GSTIN."""
    is_valid, _ = validate_gstin(gstin)
    if is_valid:
        cleaned = str(gstin).strip().upper().replace(" ", "")
        if len(cleaned) == 14:
            cleaned = "0" + cleaned
        return cleaned[2:12]
    return None
