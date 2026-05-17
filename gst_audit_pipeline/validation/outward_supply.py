"""
Outward Supply (Sales) Validation Engine
==========================================
Implements statutory cross-verification checks for GSTR-1/3B/Books.
"""
from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from .models import (
    Severity, FindingCategory, AuditFinding,
    TrueAdjustedSupply, ValidationSummary,
)

logger = logging.getLogger(__name__)

# Valid GST rates
_VALID_RATES = {0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 18.0, 28.0}
_TAX_TOLERANCE = 1.0
_VALUE_TOLERANCE_PCT = 0.5  # 0.5% threshold for supply value variance


class OutwardSupplyValidator:
    """
    Validates outward supply data across Books, GSTR-1, and GSTR-3B.

    Three core checks:
      1. Multi-Year Overlap Equation (True Adjusted Supply)
      2. Cross-Verification (Books vs GSTR-1 vs Adjusted Supply + HSN)
      3. Tax Rate Integrity (CGST/SGST/IGST math check per txn)
    """

    def __init__(self, company_gstin: str, fy_label: str = "FY 2024-25"):
        self.company_gstin = company_gstin
        self.fy_label = fy_label
        self._finding_seq = 0

    def _next_id(self) -> str:
        self._finding_seq += 1
        return f"OSV-{self._finding_seq:03d}"

    # ================================================================
    #  PUBLIC API
    # ================================================================

    def validate(
        self,
        sales_books_df: pd.DataFrame,
        gstr1_b2b_df: pd.DataFrame,
        gstr1_hsn_df: pd.DataFrame,
        gstr3b_summary: Dict[str, float],
        amendment_data: Optional[Dict[str, float]] = None,
    ) -> ValidationSummary:
        """
        Run all outward supply validations.

        Args:
            sales_books_df: Sales register with columns:
                invoice_no, taxable_value, cgst, sgst, igst, tax_rate, hsn_sac, customer_gstin
            gstr1_b2b_df: GSTR-1 B2B section with columns:
                invoice_no, taxable_value, cgst, sgst, igst, tax_rate, recipient_gstin
            gstr1_hsn_df: GSTR-1 Table 12 HSN summary with columns:
                hsn_sc, taxable_value, cgst, sgst, igst
            gstr3b_summary: Dict with key 'total_taxable_outward' (and optionally tax components)
            amendment_data: Dict with keys:
                table10_prev_fy, table11_prev_fy, table10_curr_fy, table11_curr_fy
        """
        summary = ValidationSummary()

        # Ensure numeric columns
        for df in [sales_books_df, gstr1_b2b_df, gstr1_hsn_df]:
            for col in ["taxable_value", "cgst", "sgst", "igst", "tax_rate"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        # Step 1: Multi-Year Overlap Equation
        adj = self._compute_adjusted_supply(gstr3b_summary, amendment_data or {})
        summary.adjusted_supply = adj

        # Step 2: Cross-Verification
        self._check_supply_values(sales_books_df, gstr1_b2b_df, adj, summary)
        self._check_hsn_summary(sales_books_df, gstr1_hsn_df, summary)

        # Step 3: Tax Rate Integrity
        self._check_tax_rate_integrity(sales_books_df, "Books", summary)
        self._check_tax_rate_integrity(gstr1_b2b_df, "GSTR-1", summary)

        # Step 4: B2B GSTIN-level drill-down
        self._check_b2b_gstin_mismatch(sales_books_df, gstr1_b2b_df, summary)

        logger.info(
            "Validation complete: %d findings (%d critical, %d high).",
            summary.total_findings, summary.critical_count, summary.high_count,
        )
        return summary

    # ================================================================
    #  CHECK 1: Multi-Year Overlap Equation
    # ================================================================

    def _compute_adjusted_supply(
        self, gstr3b: Dict[str, float], amendments: Dict[str, float],
    ) -> TrueAdjustedSupply:
        adj = TrueAdjustedSupply(
            gstr3b_gross=gstr3b.get("total_taxable_outward", 0.0),
            table10_prev_fy_amendments=amendments.get("table10_prev_fy", 0.0),
            table11_prev_fy_reductions=amendments.get("table11_prev_fy", 0.0),
            table10_curr_fy_carry_forward=amendments.get("table10_curr_fy", 0.0),
            table11_curr_fy_carry_forward=amendments.get("table11_curr_fy", 0.0),
        )
        adj.compute()
        logger.info("True Adjusted Supply: Rs. %,.2f", adj.true_adjusted_supply)
        return adj

    # ================================================================
    #  CHECK 2: Cross-Verification (Books vs GSTR-1 vs Adjusted)
    # ================================================================

    def _check_supply_values(
        self,
        books: pd.DataFrame,
        gstr1: pd.DataFrame,
        adj: TrueAdjustedSupply,
        summary: ValidationSummary,
    ):
        books_total = books["taxable_value"].sum()
        gstr1_total = gstr1["taxable_value"].sum()
        adjusted_total = adj.true_adjusted_supply

        # Books vs GSTR-1
        var_bg = books_total - gstr1_total
        pct_bg = (var_bg / books_total * 100) if books_total else 0
        if abs(pct_bg) > _VALUE_TOLERANCE_PCT:
            sev = Severity.CRITICAL if abs(pct_bg) > 5 else Severity.HIGH
            summary.add_finding(AuditFinding(
                finding_id=self._next_id(),
                category=FindingCategory.SUPPLY_VALUE_MISMATCH,
                severity=sev,
                title="Books vs GSTR-1 Taxable Supply Mismatch",
                description=(
                    f"Net Books Sales (Rs. {books_total:,.2f}) differs from "
                    f"Total GSTR-1 Filed (Rs. {gstr1_total:,.2f}) by "
                    f"Rs. {var_bg:,.2f} ({pct_bg:+.2f}%)."
                ),
                recommendation=(
                    "Reconcile invoice-level differences. Check for missed "
                    "invoices in GSTR-1, credit notes not uploaded, or "
                    "duplicate entries in books. File amendments via GSTR-1A "
                    "for the relevant tax period."
                ),
                books_value=round(books_total, 2),
                portal_value=round(gstr1_total, 2),
                variance=round(var_bg, 2),
                variance_pct=round(pct_bg, 2),
                affected_period=self.fy_label,
            ))

        # Books vs True Adjusted Supply
        var_ba = books_total - adjusted_total
        pct_ba = (var_ba / books_total * 100) if books_total else 0
        if abs(pct_ba) > _VALUE_TOLERANCE_PCT:
            sev = Severity.CRITICAL if abs(pct_ba) > 5 else Severity.HIGH
            summary.add_finding(AuditFinding(
                finding_id=self._next_id(),
                category=FindingCategory.MULTI_YEAR_ADJUSTMENT,
                severity=sev,
                title="Books vs True Adjusted Supply Mismatch",
                description=(
                    f"Net Books Sales (Rs. {books_total:,.2f}) differs from "
                    f"True Adjusted Supply (Rs. {adjusted_total:,.2f}) by "
                    f"Rs. {var_ba:,.2f} ({pct_ba:+.2f}%). This accounts for "
                    f"multi-year amendments (Table 10/11)."
                ),
                recommendation=(
                    "Review Table 10 (amendments) and Table 11 (reductions) "
                    "entries. Ensure previous FY amendments are correctly "
                    "excluded and current FY carry-forwards are accounted. "
                    "Cross-check with GSTR-9 annual return workings."
                ),
                books_value=round(books_total, 2),
                portal_value=round(adjusted_total, 2),
                variance=round(var_ba, 2),
                variance_pct=round(pct_ba, 2),
                affected_period=self.fy_label,
                details={"computation": adj.computation_breakdown},
            ))

        # GSTR-1 vs True Adjusted Supply
        var_ga = gstr1_total - adjusted_total
        pct_ga = (var_ga / gstr1_total * 100) if gstr1_total else 0
        if abs(pct_ga) > _VALUE_TOLERANCE_PCT:
            summary.add_finding(AuditFinding(
                finding_id=self._next_id(),
                category=FindingCategory.SUPPLY_VALUE_MISMATCH,
                severity=Severity.MEDIUM,
                title="GSTR-1 vs True Adjusted Supply Variance",
                description=(
                    f"GSTR-1 total (Rs. {gstr1_total:,.2f}) vs Adjusted Supply "
                    f"(Rs. {adjusted_total:,.2f}): variance Rs. {var_ga:,.2f}."
                ),
                recommendation=(
                    "This variance arises from amendment/reduction adjustments. "
                    "Verify GSTR-3B Table 3.1 declarations match GSTR-1 totals "
                    "after accounting for amendments."
                ),
                books_value=round(gstr1_total, 2),
                portal_value=round(adjusted_total, 2),
                variance=round(var_ga, 2),
                variance_pct=round(pct_ga, 2),
            ))

    # ================================================================
    #  CHECK 3: HSN Summary Verification (Table 12)
    # ================================================================

    def _check_hsn_summary(
        self,
        books: pd.DataFrame,
        hsn_df: pd.DataFrame,
        summary: ValidationSummary,
    ):
        if "hsn_sac" not in books.columns and "hsn_sc" not in books.columns:
            summary.add_finding(AuditFinding(
                finding_id=self._next_id(),
                category=FindingCategory.HSN_MISSING,
                severity=Severity.MEDIUM,
                title="HSN/SAC Column Missing in Books",
                description="Books data does not contain HSN/SAC codes.",
                recommendation="Add HSN/SAC classification to all invoice lines.",
            ))
            return

        hsn_col = "hsn_sac" if "hsn_sac" in books.columns else "hsn_sc"

        # Aggregate books by HSN
        books_hsn = (
            books.groupby(books[hsn_col].astype(str).str.strip())
            .agg(books_taxable=("taxable_value", "sum"))
            .reset_index()
            .rename(columns={hsn_col: "hsn"})
        )

        # Aggregate portal HSN (Table 12)
        hsn_code_col = "hsn_sc" if "hsn_sc" in hsn_df.columns else "hsn"
        if hsn_code_col not in hsn_df.columns:
            for c in hsn_df.columns:
                if "hsn" in c.lower():
                    hsn_code_col = c
                    break

        portal_hsn = (
            hsn_df.groupby(hsn_df[hsn_code_col].astype(str).str.strip())
            .agg(portal_taxable=("taxable_value", "sum"))
            .reset_index()
            .rename(columns={hsn_code_col: "hsn"})
        )

        # Full outer merge
        merged = books_hsn.merge(portal_hsn, on="hsn", how="outer").fillna(0)

        # Total value check
        books_hsn_total = merged["books_taxable"].sum()
        portal_hsn_total = merged["portal_taxable"].sum()
        total_var = books_hsn_total - portal_hsn_total

        if abs(total_var) > _TAX_TOLERANCE:
            pct = (total_var / books_hsn_total * 100) if books_hsn_total else 0
            summary.add_finding(AuditFinding(
                finding_id=self._next_id(),
                category=FindingCategory.HSN_VALUE_MISMATCH,
                severity=Severity.HIGH if abs(pct) > 1 else Severity.MEDIUM,
                title="HSN Summary Total vs Books Aggregate Mismatch",
                description=(
                    f"Books HSN aggregate (Rs. {books_hsn_total:,.2f}) vs "
                    f"GSTR-1 Table 12 total (Rs. {portal_hsn_total:,.2f}): "
                    f"variance Rs. {total_var:,.2f}."
                ),
                recommendation=(
                    "Verify Table 12 HSN summary in GSTR-1 covers all supply "
                    "lines. Common causes: missing HSN for services, incorrect "
                    "HSN grouping, or credit notes not reflected in Table 12."
                ),
                books_value=round(books_hsn_total, 2),
                portal_value=round(portal_hsn_total, 2),
                variance=round(total_var, 2),
                variance_pct=round(pct, 2),
            ))

        # Check missing HSN codes
        missing_in_portal = merged[merged["portal_taxable"] == 0]
        for _, row in missing_in_portal.iterrows():
            if row["books_taxable"] > 0:
                summary.add_finding(AuditFinding(
                    finding_id=self._next_id(),
                    category=FindingCategory.HSN_MISSING,
                    severity=Severity.MEDIUM,
                    title=f"HSN '{row['hsn']}' Missing from GSTR-1 Table 12",
                    description=(
                        f"HSN/SAC '{row['hsn']}' has Rs. {row['books_taxable']:,.2f} "
                        f"taxable value in Books but is absent from GSTR-1 Table 12."
                    ),
                    recommendation=(
                        f"Add HSN '{row['hsn']}' to GSTR-1 Table 12 (HSN Summary). "
                        f"This is mandatory for turnover above Rs. 5 Cr."
                    ),
                    books_value=round(row["books_taxable"], 2),
                    affected_hsn=str(row["hsn"]),
                ))

        # Check per-HSN variances
        both_present = merged[
            (merged["books_taxable"] > 0) & (merged["portal_taxable"] > 0)
        ]
        for _, row in both_present.iterrows():
            var = row["books_taxable"] - row["portal_taxable"]
            if abs(var) > _TAX_TOLERANCE:
                pct = (var / row["books_taxable"] * 100) if row["books_taxable"] else 0
                if abs(pct) > 1:
                    summary.add_finding(AuditFinding(
                        finding_id=self._next_id(),
                        category=FindingCategory.HSN_VALUE_MISMATCH,
                        severity=Severity.LOW,
                        title=f"HSN '{row['hsn']}' Value Variance",
                        description=(
                            f"HSN '{row['hsn']}': Books Rs. {row['books_taxable']:,.2f} "
                            f"vs Portal Rs. {row['portal_taxable']:,.2f} "
                            f"(variance Rs. {var:,.2f}, {pct:+.1f}%)."
                        ),
                        recommendation=(
                            f"Review invoices classified under HSN '{row['hsn']}'. "
                            f"Ensure credit notes and amendments are reflected."
                        ),
                        books_value=round(row["books_taxable"], 2),
                        portal_value=round(row["portal_taxable"], 2),
                        variance=round(var, 2),
                        variance_pct=round(pct, 2),
                        affected_hsn=str(row["hsn"]),
                    ))

    # ================================================================
    #  CHECK 4: Tax Rate Integrity
    # ================================================================

    def _check_tax_rate_integrity(
        self,
        df: pd.DataFrame,
        source_label: str,
        summary: ValidationSummary,
    ):
        if "tax_rate" not in df.columns or "taxable_value" not in df.columns:
            return

        required = {"cgst", "sgst", "igst"}
        if not required.issubset(set(df.columns)):
            return

        inv_col = None
        for c in ["invoice_no", "inum", "inv_no"]:
            if c in df.columns:
                inv_col = c
                break

        gstin_col = None
        for c in ["customer_gstin", "recipient_gstin", "gstin", "ctin"]:
            if c in df.columns:
                gstin_col = c
                break

        for idx, row in df.iterrows():
            rate = float(row["tax_rate"])
            taxable = float(row["taxable_value"])
            cgst = float(row["cgst"])
            sgst = float(row["sgst"])
            igst = float(row["igst"])
            actual_tax = cgst + sgst + igst
            inv_no = str(row[inv_col]) if inv_col else f"Row-{idx}"
            gstin = str(row[gstin_col]) if gstin_col else None

            if taxable == 0:
                continue

            # Check 1: Is the rate a valid GST rate?
            if rate not in _VALID_RATES and rate > 0:
                summary.add_finding(AuditFinding(
                    finding_id=self._next_id(),
                    category=FindingCategory.TAX_RATE_INTEGRITY,
                    severity=Severity.HIGH,
                    title=f"Invalid Tax Rate {rate}% in {source_label}",
                    description=(
                        f"Invoice '{inv_no}' in {source_label} has tax rate "
                        f"{rate}% which is not a valid GST rate."
                    ),
                    recommendation=(
                        f"Correct the tax rate for invoice '{inv_no}'. "
                        f"Valid GST rates: {sorted(_VALID_RATES)}."
                    ),
                    affected_invoice=inv_no,
                    affected_gstin=gstin,
                    tax_rate=rate,
                ))

            # Check 2: Tax split math verification
            expected_tax = round(taxable * rate / 100, 2)
            tax_diff = abs(actual_tax - expected_tax)

            if tax_diff > _TAX_TOLERANCE:
                # Determine if it's intra-state (CGST+SGST) or inter-state (IGST)
                is_inter = igst > 0 and cgst == 0 and sgst == 0
                is_intra = (cgst > 0 or sgst > 0) and igst == 0

                if is_intra:
                    expected_half = round(taxable * rate / 200, 2)
                    cgst_diff = abs(cgst - expected_half)
                    sgst_diff = abs(sgst - expected_half)
                    if cgst_diff > _TAX_TOLERANCE or sgst_diff > _TAX_TOLERANCE:
                        summary.add_finding(AuditFinding(
                            finding_id=self._next_id(),
                            category=FindingCategory.TAX_SPLIT_ERROR,
                            severity=Severity.MEDIUM,
                            title=f"CGST/SGST Split Error in {source_label}",
                            description=(
                                f"Invoice '{inv_no}': Taxable Rs. {taxable:,.2f} "
                                f"@ {rate}% should yield CGST=SGST=Rs. {expected_half:,.2f} "
                                f"each, but got CGST=Rs. {cgst:,.2f}, SGST=Rs. {sgst:,.2f}."
                            ),
                            recommendation=(
                                f"Correct the tax computation for '{inv_no}'. "
                                f"For intra-state supply at {rate}%, CGST and SGST "
                                f"should each be {rate/2}% of taxable value."
                            ),
                            books_value=expected_tax,
                            portal_value=actual_tax,
                            variance=round(actual_tax - expected_tax, 2),
                            affected_invoice=inv_no,
                            affected_gstin=gstin,
                            tax_rate=rate,
                        ))
                elif is_inter:
                    igst_diff = abs(igst - expected_tax)
                    if igst_diff > _TAX_TOLERANCE:
                        summary.add_finding(AuditFinding(
                            finding_id=self._next_id(),
                            category=FindingCategory.TAX_SPLIT_ERROR,
                            severity=Severity.MEDIUM,
                            title=f"IGST Computation Error in {source_label}",
                            description=(
                                f"Invoice '{inv_no}': Taxable Rs. {taxable:,.2f} "
                                f"@ {rate}% should yield IGST=Rs. {expected_tax:,.2f}, "
                                f"but got Rs. {igst:,.2f}."
                            ),
                            recommendation=(
                                f"Correct IGST for '{inv_no}'. For inter-state "
                                f"supply at {rate}%, IGST = {rate}% of taxable value."
                            ),
                            books_value=expected_tax,
                            portal_value=igst,
                            variance=round(igst - expected_tax, 2),
                            affected_invoice=inv_no,
                            affected_gstin=gstin,
                            tax_rate=rate,
                        ))

    # ================================================================
    #  CHECK 5: B2B GSTIN-Level Mismatch
    # ================================================================

    def _check_b2b_gstin_mismatch(
        self,
        books: pd.DataFrame,
        gstr1: pd.DataFrame,
        summary: ValidationSummary,
    ):
        gstin_books = None
        for c in ["customer_gstin", "gstin"]:
            if c in books.columns:
                gstin_books = c
                break
        gstin_gstr1 = None
        for c in ["recipient_gstin", "ctin", "gstin"]:
            if c in gstr1.columns:
                gstin_gstr1 = c
                break

        if not gstin_books or not gstin_gstr1:
            return

        # Aggregate by GSTIN
        b_agg = (
            books.groupby(books[gstin_books].astype(str).str.strip().str.upper())
            .agg(books_taxable=("taxable_value", "sum"))
            .reset_index()
            .rename(columns={gstin_books: "gstin"})
        )
        g_agg = (
            gstr1.groupby(gstr1[gstin_gstr1].astype(str).str.strip().str.upper())
            .agg(portal_taxable=("taxable_value", "sum"))
            .reset_index()
            .rename(columns={gstin_gstr1: "gstin"})
        )

        merged = b_agg.merge(g_agg, on="gstin", how="outer").fillna(0)

        for _, row in merged.iterrows():
            var = row["books_taxable"] - row["portal_taxable"]
            if abs(var) <= _TAX_TOLERANCE:
                continue

            pct = (var / row["books_taxable"] * 100) if row["books_taxable"] else 100

            if row["portal_taxable"] == 0:
                summary.add_finding(AuditFinding(
                    finding_id=self._next_id(),
                    category=FindingCategory.B2B_GSTIN_MISMATCH,
                    severity=Severity.HIGH,
                    title=f"Customer {row['gstin']} Missing from GSTR-1",
                    description=(
                        f"Customer GSTIN {row['gstin']} has Rs. {row['books_taxable']:,.2f} "
                        f"in Books but no invoices filed in GSTR-1 B2B section."
                    ),
                    recommendation=(
                        f"Upload all B2B invoices for GSTIN {row['gstin']} in GSTR-1. "
                        f"If already past the due date, file amendment via GSTR-1A."
                    ),
                    books_value=round(row["books_taxable"], 2),
                    variance=round(var, 2),
                    affected_gstin=str(row["gstin"]),
                ))
            elif row["books_taxable"] == 0:
                summary.add_finding(AuditFinding(
                    finding_id=self._next_id(),
                    category=FindingCategory.B2B_GSTIN_MISMATCH,
                    severity=Severity.MEDIUM,
                    title=f"GSTIN {row['gstin']} in GSTR-1 but Not in Books",
                    description=(
                        f"GSTIN {row['gstin']} has Rs. {row['portal_taxable']:,.2f} "
                        f"in GSTR-1 but no corresponding entries in Books."
                    ),
                    recommendation=(
                        f"Verify if invoices for {row['gstin']} were omitted from "
                        f"books or filed under incorrect GSTIN in GSTR-1."
                    ),
                    portal_value=round(row["portal_taxable"], 2),
                    variance=round(var, 2),
                    affected_gstin=str(row["gstin"]),
                ))
            elif abs(pct) > 1:
                summary.add_finding(AuditFinding(
                    finding_id=self._next_id(),
                    category=FindingCategory.B2B_GSTIN_MISMATCH,
                    severity=Severity.MEDIUM,
                    title=f"B2B Value Mismatch for GSTIN {row['gstin']}",
                    description=(
                        f"GSTIN {row['gstin']}: Books Rs. {row['books_taxable']:,.2f} "
                        f"vs GSTR-1 Rs. {row['portal_taxable']:,.2f} "
                        f"(variance {pct:+.1f}%)."
                    ),
                    recommendation=(
                        f"Reconcile invoice-level data for {row['gstin']}. "
                        f"Check for missing invoices, credit notes, or "
                        f"amendments. File GSTR-1A if correction needed."
                    ),
                    books_value=round(row["books_taxable"], 2),
                    portal_value=round(row["portal_taxable"], 2),
                    variance=round(var, 2),
                    variance_pct=round(pct, 2),
                    affected_gstin=str(row["gstin"]),
                ))
