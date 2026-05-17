"""
GSTR-9 Annual Return Mapper
=============================
Automated statutory compliance engine that maps reconciled ITC data buckets
straight into official GSTR-9 Annual Return Tables 6 & 8 schemas.
"""
from __future__ import annotations
import pandas as pd
from typing import Dict, Any, Tuple
from gst_audit_pipeline.reconciliation.models import MatchBucket

class GSTR9TableMapper:
    """
    Consumes the consolidated dataframe from ITCMatcher (ReconciliationResult.consolidated)
    and computes the values for GSTR-9 Tables 6B and 8.
    """
    
    def __init__(self, consolidated_df: pd.DataFrame):
        self.df = consolidated_df.copy()
        
        # Enforce numeric types for math accuracy
        self.df['books_total_tax'] = pd.to_numeric(self.df['books_total_tax'], errors='coerce').fillna(0.0)
        self.df['portal_total_tax'] = pd.to_numeric(self.df['portal_total_tax'], errors='coerce').fillna(0.0)
        
    def compile_table_6b(self) -> Dict[str, float]:
        """
        Table 6B: Inward supplies received from registered persons.
        Logic: Sum of books_total_tax for Bucket A (Perfect Match) and Bucket D (Amount Mismatch).
        """
        mask = self.df['match_bucket'].isin([
            MatchBucket.A_PERFECT_MATCH.value, 
            MatchBucket.D_AMOUNT_MISMATCH.value
        ])
        total_6b = self.df.loc[mask, 'books_total_tax'].sum()
        
        return {
            "Table_6B_Total_ITC": round(float(total_6b), 2),
            "Description": "Inward supplies received from registered persons (Excluding B2CL/Unregistered)"
        }

    def compile_table_8_matrix(self, table_6b_val: float) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        Table 8: Core ITC Reconciliation Matrix.
        Calculates rows 8A, 8B, 8C, and identifies statutory variance 8D.
        """
        # 8A: ITC as per GSTR-2B (Portal Reality Baseline)
        mask_8a = self.df['match_bucket'].isin([
            MatchBucket.A_PERFECT_MATCH.value,
            MatchBucket.C_UNCLAIMED_IN_BOOKS.value,
            MatchBucket.D_AMOUNT_MISMATCH.value
        ])
        table_8a_val = self.df.loc[mask_8a, 'portal_total_tax'].sum()
        
        # 8B: ITC credited to GSTR-3B
        table_8b_val = table_6b_val
        
        # 8C: ITC booked in current FY but claimed in subsequent FY (Timing / Deferred Differences)
        # BUG FIX 3: Strict pandas filter condition for Table 8C
        mask_8c = self.df['match_bucket'] == MatchBucket.E_TIMING_DIFFERENCE.value
        table_8c_val = self.df.loc[mask_8c, 'books_total_tax'].sum()
        
        # 8D: Statutory Variance = 8A - (8B + 8C)
        variance_8d = table_8a_val - (table_8b_val + table_8c_val)
        
        metrics = {
            "Table_8A_Portal_ITC": round(float(table_8a_val), 2),
            "Table_8B_Availed_ITC": round(float(table_8b_val), 2),
            "Table_8C_Deferred_ITC": round(float(table_8c_val), 2),
            "Table_8D_Variance": round(float(variance_8d), 2)
        }
        
        # Risk Evaluation
        risk_profile = {
            "status": "COMPLIANT",
            "exposure_value": 0.0,
            "action_item": "No systematic flags. Data is balanced and ready for submission."
        }
        
        if variance_8d < -1.0:
            bucket_b_exposure = self.df.loc[self.df['match_bucket'] == MatchBucket.B_MISSING_IN_PORTAL.value, 'books_total_tax'].sum()
            risk_profile.update({
                "status": "CRITICAL RISK EXPOSURE",
                "exposure_value": round(float(abs(variance_8d)), 2),
                "action_item": (f"ASMT-10 Threat: Books exceed portal logs by Rs. {abs(variance_8d):,.2f}. "
                                f"Isolate Bucket B defaults (Unfiled Vendor Credit total: Rs. {bucket_b_exposure:,.2f}) "
                                f"and withhold outstanding vendor payouts immediately.")
            })
        elif variance_8d > 1.0:
            risk_profile.update({
                "status": "TAX OPTIMIZATION OPPORTUNITY",
                "exposure_value": round(float(variance_8d), 2),
                "action_item": (f"Unclaimed Credit: Portal displays Rs. {variance_8d:,.2f} of unutilized eligible ITC. "
                                f"Cross-verify with Bucket C and execute catch-up claims in the upcoming GSTR-3B filing open window.")
            })
            
        return metrics, risk_profile
