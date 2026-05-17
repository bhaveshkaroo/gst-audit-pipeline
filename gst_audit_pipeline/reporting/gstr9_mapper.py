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
    def __init__(self, consolidated_df: pd.DataFrame, raw_books_itc: float, raw_portal_itc: float):
        self.df = consolidated_df.copy()
        self.raw_books_itc = raw_books_itc
        self.raw_portal_itc = raw_portal_itc
        
        self.df['books_total_tax'] = pd.to_numeric(self.df['books_total_tax'], errors='coerce').fillna(0.0)
        self.df['portal_total_tax'] = pd.to_numeric(self.df['portal_total_tax'], errors='coerce').fillna(0.0)
        
    def compile_table_6b(self) -> Dict[str, float]:
        """
        Table 6B: Inward supplies received from registered persons.
        BUG 3 FIX: Calculate sum on the raw books input.
        """
        return {
            "Table_6B_Total_ITC": round(float(self.raw_books_itc), 2),
            "Description": "Inward supplies received from registered persons (Excluding B2CL/Unregistered)"
        }

    def compile_table_8_matrix(self, table_6b_val: float) -> Tuple[Dict[str, float], Dict[str, Any]]:
        # Table 8A: Portal Reality Baseline (Raw portal ITC)
        table_8a_val = self.raw_portal_itc
        
        # Table 8B: ITC credited to GSTR-3B
        table_8b_val = table_6b_val
        
        # Table 8C: Deferred Timing Differences (Only Bucket E)
        mask_8c = self.df['match_bucket'] == MatchBucket.E_TIMING_DIFFERENCE.value
        table_8c_val = self.df.loc[mask_8c, 'books_total_tax'].sum()
        
        # BUG 4 FIX: Statutory Variance = 6B - 8A
        variance_8d = table_6b_val - table_8a_val
        
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
        
        if variance_8d > 0.0:
            risk_profile.update({
                "status": "CRITICAL RISK EXPOSURE",
                "exposure_value": round(float(variance_8d), 2),
                "action_item": f"ASMT-10 Threat: Books exceed portal logs by Rs. {variance_8d:,.2f}."
            })
        elif variance_8d < 0.0:
            risk_profile.update({
                "status": "TAX OPTIMIZATION OPPORTUNITY",
                "exposure_value": round(float(abs(variance_8d)), 2),
                "action_item": f"Unclaimed Credit: Portal displays Rs. {abs(variance_8d):,.2f} of unutilized eligible ITC."
            })
            
        return metrics, risk_profile
