"""
End-to-End Integration Diagnostics for GST Audit Pipeline
========================================================
This script performs a standalone verification of the core backend pipeline,
passing synthetic data through ITCMatcher, GSTR9TableMapper, and the PDF Generator.
"""

import io
import pandas as pd

from gst_audit_pipeline.reconciliation.itc_matcher import ITCMatcher
from gst_audit_pipeline.reporting.gstr9_mapper import GSTR9TableMapper
from gst_audit_pipeline.reporting.pdf_generator import generate_pdf_report

def main():
    print("================================================================")
    print("  GST AUDIT PIPELINE: END-TO-END VERIFICATION SEQUENCE")
    print("================================================================\n")
    
    # 1. Synthetic Data Generation
    print("[1/4] Generating Mock 5-Bucket Dataset...")
    
    # Shared Data
    gstin_shared = "27AABCT1234F1Z1"
    
    books_data = [
        # Bucket A: Perfect Match (matched in 2B)
        {"supplier_gstin": gstin_shared, "invoice_no": "INV/01/A", "invoice_date": "2024-05-10", "cgst": 1000.0, "sgst": 1000.0, "igst": 0.0, "tax_rate": 18, "taxable_value": 11111.0},
        # Bucket B: Missing in Portal (Not in 2B or 2A)
        {"supplier_gstin": gstin_shared, "invoice_no": "INV/02/B", "invoice_date": "2024-05-11", "cgst": 5000.0, "sgst": 5000.0, "igst": 0.0, "tax_rate": 18, "taxable_value": 55555.0},
        # Bucket D: Mismatched Values (Amounts differ in 2B)
        {"supplier_gstin": gstin_shared, "invoice_no": "INV/04/D", "invoice_date": "2024-05-12", "cgst": 3000.0, "sgst": 3000.0, "igst": 0.0, "tax_rate": 18, "taxable_value": 33333.0},
        # Bucket E: Timing Difference (Exists in 2A, missing from 2B)
        {"supplier_gstin": gstin_shared, "invoice_no": "INV/05/E", "invoice_date": "2024-05-13", "cgst": 8000.0, "sgst": 8000.0, "igst": 0.0, "tax_rate": 18, "taxable_value": 88888.0},
    ]
    
    gstr2b_data = [
        # Bucket A: Perfect Match
        {"supplier_gstin": gstin_shared, "invoice_no": "INV/01/A", "invoice_date": "2024-05-10", "cgst": 1000.0, "sgst": 1000.0, "igst": 0.0, "tax_rate": 18, "taxable_value": 11111.0},
        # Bucket C: Unclaimed in Books (Only in 2B)
        {"supplier_gstin": gstin_shared, "invoice_no": "INV/03/C", "invoice_date": "2024-05-14", "cgst": 2000.0, "sgst": 2000.0, "igst": 0.0, "tax_rate": 18, "taxable_value": 22222.0},
        # Bucket D: Mismatched Values (Variance here)
        {"supplier_gstin": gstin_shared, "invoice_no": "INV/04/D", "invoice_date": "2024-05-12", "cgst": 2500.0, "sgst": 2500.0, "igst": 0.0, "tax_rate": 18, "taxable_value": 27777.0},
    ]
    
    gstr2a_data = [
        # Bucket E: Timing Difference
        {"supplier_gstin": gstin_shared, "invoice_no": "INV/05/E", "invoice_date": "2024-05-13", "cgst": 8000.0, "sgst": 8000.0, "igst": 0.0, "tax_rate": 18, "taxable_value": 88888.0},
    ]
    
    df_books = pd.DataFrame(books_data)
    df_2b = pd.DataFrame(gstr2b_data)
    df_2a = pd.DataFrame(gstr2a_data)
    
    # 2. Phase 2 Execution (ITCMatcher)
    print("[2/4] Executing Phase 2: Vectorized 3-Way ITC Matching...")
    matcher = ITCMatcher(tax_tolerance=1.0)
    result = matcher.reconcile(df_books, df_2b, df_2a)
    
    assert len(result.perfect_matches) == 1, f"Bucket A failed, found {len(result.perfect_matches)}"
    assert len(result.missing_in_portal) == 1, f"Bucket B failed, found {len(result.missing_in_portal)}"
    assert len(result.unclaimed_in_books) == 1, f"Bucket C failed, found {len(result.unclaimed_in_books)}"
    assert len(result.amount_mismatches) == 1, f"Bucket D failed, found {len(result.amount_mismatches)}"
    assert len(result.timing_differences) == 1, f"Bucket E failed, found {len(result.timing_differences)}"
    
    # 3. Phase 5 Execution (GSTR9TableMapper)
    print("[3/4] Executing Phase 5: GSTR-9 Statutory Array Mapping...")
    mapper = GSTR9TableMapper(result.consolidated, result.summary.get('total_books_itc', 0.0), result.summary.get('total_portal_itc', 0.0))
    t6b = mapper.compile_table_6b()
    t8_metrics, t8_risk = mapper.compile_table_8_matrix(t6b["Table_6B_Total_ITC"])
    
    # 4. Phase 4 Execution (PDF Generator)
    print("[4/4] Executing Phase 4: ReportLab Audit Report Compilation...")
    pdf_buffer = io.BytesIO()
    
    try:
        generate_pdf_report(
            reco_summary=result.summary,
            df_bucket_b=result.missing_in_portal,
            df_bucket_d=result.amount_mismatches,
            output_path=pdf_buffer,
            gstr9_t6b=t6b,
            gstr9_t8_metrics=t8_metrics,
            gstr9_risk=t8_risk,
            company_name="LedgerAI Diagnostic Testing",
            gstin="27AABCT1234F1Z1",
            fy="FY 2024-25"
        )
        pdf_bytes = pdf_buffer.getvalue()
        assert len(pdf_bytes) > 0, "PDF buffer is empty"
    except Exception as e:
        print(f"\n[!] PDF Generation Failed: {str(e)}")
        raise
        
    print("\n================================================================")
    print("  SUCCESS: ALL PIPELINE PHASES ARE OPERATIONAL")
    print("================================================================")
    print(f" -> ITCMatcher buckets populated accurately (A, B, C, D, E)")
    print(f" -> Table 8D Statutory Variance Computed: Rs. {t8_metrics['Table_8D_Variance']:,.2f}")
    print(f" -> Risk Profile Generated: {t8_risk['status']}")
    print(f" -> Finalized ReportLab PDF Binary Length: {len(pdf_bytes):,} bytes")
    print("================================================================\n")

if __name__ == "__main__":
    main()
