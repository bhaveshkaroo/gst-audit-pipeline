"""
Advisory & Validation Result Models
======================================
Structured output types for the Outward Supply Validation Module.
"""

from __future__ import annotations

from enum import Enum
from decimal import Decimal
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Audit finding severity classification."""
    CRITICAL = "CRITICAL"    # Material misstatement, must rectify before filing
    HIGH = "HIGH"            # Significant variance, likely needs amendment
    MEDIUM = "MEDIUM"        # Moderate issue, review recommended
    LOW = "LOW"              # Minor / rounding discrepancy
    INFO = "INFO"            # Informational observation


class FindingCategory(str, Enum):
    """Classification of the type of audit finding."""
    SUPPLY_VALUE_MISMATCH = "SUPPLY_VALUE_MISMATCH"
    HSN_MISSING = "HSN_MISSING"
    HSN_VALUE_MISMATCH = "HSN_VALUE_MISMATCH"
    TAX_RATE_INTEGRITY = "TAX_RATE_INTEGRITY"
    TAX_SPLIT_ERROR = "TAX_SPLIT_ERROR"
    AMENDMENT_OVERLAP = "AMENDMENT_OVERLAP"
    B2B_GSTIN_MISMATCH = "B2B_GSTIN_MISMATCH"
    MULTI_YEAR_ADJUSTMENT = "MULTI_YEAR_ADJUSTMENT"


class AuditFinding(BaseModel):
    """
    A single structured audit finding with human-readable advisory.

    Each finding explains WHAT went wrong, WHERE it occurred,
    the VARIANCE amount, and a RECOMMENDATION for correction.
    """
    finding_id: str = Field(
        ..., description="Unique finding identifier (e.g., 'OSV-001').",
    )
    category: FindingCategory
    severity: Severity
    title: str = Field(
        ..., description="Short descriptive title of the finding.",
    )
    description: str = Field(
        ..., description="Detailed explanation of the issue.",
    )
    recommendation: str = Field(
        ..., description="Human-readable advisory for correction.",
    )

    # Quantitative details
    books_value: float = Field(default=0.0)
    portal_value: float = Field(default=0.0)
    variance: float = Field(default=0.0)
    variance_pct: float = Field(
        default=0.0,
        description="Variance as percentage of books value.",
    )

    # Context references
    affected_gstin: Optional[str] = None
    affected_invoice: Optional[str] = None
    affected_hsn: Optional[str] = None
    affected_period: Optional[str] = None
    tax_rate: Optional[float] = None

    # Additional metadata
    details: Dict[str, Any] = Field(default_factory=dict)

    def to_advisory_dict(self) -> dict:
        """Export as a flat dictionary for reporting."""
        return {
            "Finding ID": self.finding_id,
            "Severity": self.severity.value,
            "Category": self.category.value,
            "Title": self.title,
            "Description": self.description,
            "Books Value": f"Rs. {self.books_value:,.2f}",
            "Portal Value": f"Rs. {self.portal_value:,.2f}",
            "Variance": f"Rs. {self.variance:,.2f}",
            "Variance %": f"{self.variance_pct:.2f}%",
            "Recommendation": self.recommendation,
            "Affected GSTIN": self.affected_gstin or "N/A",
            "Affected Invoice": self.affected_invoice or "N/A",
            "Affected HSN": self.affected_hsn or "N/A",
        }


class TrueAdjustedSupply(BaseModel):
    """
    Result of the Multi-Year Overlap Equation (Statutory Formula).

    True Adjusted Supply =
        Current FY GSTR-3B Summary
      - Table 10 (Previous FY Amendments filed in current FY)
      + Table 11 (Previous FY Reductions filed in current FY)
      + Table 10 (Current FY Amendments to be carried forward)
      - Table 11 (Current FY Reductions to be carried forward)
    """
    gstr3b_gross: float = Field(
        ..., description="Current FY GSTR-3B gross outward supply.",
    )
    table10_prev_fy_amendments: float = Field(
        default=0.0,
        description="Table 10: Previous FY amendments filed in current FY.",
    )
    table11_prev_fy_reductions: float = Field(
        default=0.0,
        description="Table 11: Previous FY reductions filed in current FY.",
    )
    table10_curr_fy_carry_forward: float = Field(
        default=0.0,
        description="Table 10: Current FY amendments to carry forward.",
    )
    table11_curr_fy_carry_forward: float = Field(
        default=0.0,
        description="Table 11: Current FY reductions to carry forward.",
    )
    true_adjusted_supply: float = Field(
        default=0.0,
        description="Computed true adjusted supply value.",
    )
    computation_breakdown: str = Field(
        default="",
        description="Human-readable breakdown of the computation.",
    )

    def compute(self) -> float:
        """Execute the statutory multi-year overlap equation."""
        result = (
            self.gstr3b_gross
            - self.table10_prev_fy_amendments
            + self.table11_prev_fy_reductions
            + self.table10_curr_fy_carry_forward
            - self.table11_curr_fy_carry_forward
        )
        self.true_adjusted_supply = round(result, 2)
        self.computation_breakdown = (
            f"GSTR-3B Gross:            Rs. {self.gstr3b_gross:>14,.2f}\n"
            f"(-) Prev FY Amendments:   Rs. {self.table10_prev_fy_amendments:>14,.2f}\n"
            f"(+) Prev FY Reductions:   Rs. {self.table11_prev_fy_reductions:>14,.2f}\n"
            f"(+) Curr FY Amendments:   Rs. {self.table10_curr_fy_carry_forward:>14,.2f}\n"
            f"(-) Curr FY Reductions:   Rs. {self.table11_curr_fy_carry_forward:>14,.2f}\n"
            f"{'=' * 50}\n"
            f"True Adjusted Supply:     Rs. {self.true_adjusted_supply:>14,.2f}"
        )
        return self.true_adjusted_supply


class ValidationSummary(BaseModel):
    """Top-level summary of the outward supply validation."""
    total_findings: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    findings: List[AuditFinding] = Field(default_factory=list)
    adjusted_supply: Optional[TrueAdjustedSupply] = None

    def add_finding(self, finding: AuditFinding):
        self.findings.append(finding)
        self.total_findings += 1
        match finding.severity:
            case Severity.CRITICAL: self.critical_count += 1
            case Severity.HIGH: self.high_count += 1
            case Severity.MEDIUM: self.medium_count += 1
            case Severity.LOW: self.low_count += 1
            case Severity.INFO: self.info_count += 1
