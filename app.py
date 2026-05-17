import io
import streamlit as st
import pandas as pd
import plotly.express as px
from gst_audit_pipeline.reconciliation.itc_matcher import ITCMatcher
from gst_audit_pipeline.run_reconciliation_demo import generate_test_data
from gst_audit_pipeline.reporting.pdf_generator import generate_pdf_report
from gst_audit_pipeline.reporting.gstr9_mapper import GSTR9TableMapper


# Must be the first Streamlit command
st.set_page_config(
    page_title="LedgerAI | GST Pre-Audit",
    page_icon="⬛",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 1. Custom CSS Theme Overrides (Linear/Apple Aesthetic)
st.markdown("""
<style>
    /* Global Background and Typography */
    .stApp {
        background-color: #121212 !important;
        color: #F2F2F2;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #181818 !important;
        border-right: 1px solid #2D2D2D;
    }
    
    /* Remove unnecessary padding */
    .block-container {
        padding-top: 3rem !important;
        padding-bottom: 3rem !important;
        max-width: 1200px;
    }

    /* Headers */
    h1, h2, h3, h4 {
        color: #FFFFFF !important;
        font-weight: 500 !important;
        letter-spacing: -0.5px;
    }
    
    /* Minimalist Custom KPI Cards */
    .kpi-card {
        background-color: #181818;
        border: 1px solid #2D2D2D;
        border-radius: 8px;
        padding: 24px;
        display: flex;
        flex-direction: column;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .kpi-card:hover {
        border-color: #404040;
    }
    .kpi-value {
        color: #FFFFFF;
        font-size: 32px;
        font-weight: 600;
        margin-bottom: 4px;
        letter-spacing: -0.5px;
    }
    .kpi-label {
        color: #8A8A8A;
        font-size: 13px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    /* Clean Uploaders */
    .stFileUploader > div > div {
        background-color: #121212 !important;
        border: 1px dashed #2D2D2D !important;
        border-radius: 6px !important;
        color: #8A8A8A !important;
    }
    
    /* Action Button (High Contrast) */
    .stButton > button {
        width: 100%;
        background-color: #FFFFFF !important;
        color: #000000 !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        border: none !important;
        border-radius: 6px !important;
        padding: 0.75rem !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button:hover {
        background-color: #E5E5E5 !important;
        transform: translateY(-1px);
    }
    .stButton > button:active {
        transform: translateY(0px);
    }

    /* Secondary Button (Demo Data) */
    .demo-btn > div > .stButton > button {
        background-color: #181818 !important;
        color: #FFFFFF !important;
        border: 1px solid #2D2D2D !important;
    }
    .demo-btn > div > .stButton > button:hover {
        background-color: #2D2D2D !important;
        color: #FFFFFF !important;
    }

    /* DataFrame Styling */
    [data-testid="stDataFrame"] {
        background-color: #181818;
        border: 1px solid #2D2D2D;
        border-radius: 8px;
    }

    /* Empty State */
    .empty-state {
        text-align: center;
        padding: 80px 20px;
        background-color: #181818;
        border: 1px dashed #2D2D2D;
        border-radius: 8px;
        margin-top: 2rem;
    }
    .empty-icon {
        margin-bottom: 16px;
        opacity: 0.7;
    }
    .empty-title {
        color: #FFFFFF;
        font-size: 18px;
        font-weight: 500;
        margin-bottom: 8px;
    }
    .empty-subtitle {
        color: #8A8A8A;
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)


# --- UI HEADER ---
st.title("GST Pre-Audit & Finalization Engine")
st.markdown("<p style='color: #8A8A8A; margin-top: -10px; margin-bottom: 30px;'>Institutional-grade 3-way ITC reconciliation and anomaly detection.</p>", unsafe_allow_html=True)


# --- 2. SIDEBAR UPLOAD HUB ---
with st.sidebar:
    st.markdown("<h3 style='margin-bottom: 20px;'>Data Ingestion</h3>", unsafe_allow_html=True)
    
    books_file = st.file_uploader(
        label="📥 Drop Purchase Register / Books Ledger Here (.xlsx)",
        type=["xlsx"]
    )
    
    gstr2b_file = st.file_uploader(
        label="🏛️ Drop Government GSTR-2B Portal Export Here (.xlsx)",
        type=["xlsx"]
    )
    
    gstr2a_file = st.file_uploader(
        label="⏳ Optional: Drop GSTR-2A Ledger Here (For Timing Differences) (.xlsx)",
        type=["xlsx"]
    )
    
    st.markdown("<br/>", unsafe_allow_html=True)
    run_engine = st.button("RUN PRE-AUDIT ENGINE")
    
    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("<div style='height: 1px; background-color: #2D2D2D; margin: 10px 0;'></div>", unsafe_allow_html=True)
    
    st.markdown("<div class='demo-btn'>", unsafe_allow_html=True)
    load_demo = st.button("Load Demo Synthetic Data")
    st.markdown("</div>", unsafe_allow_html=True)


# --- 6. STATE MANAGEMENT ---
if run_engine or load_demo:
    st.session_state.run_triggered = True
    st.session_state.is_demo = load_demo
    # Clear previous cached results when running a new audit
    if 'pdf_bytes' in st.session_state:
        del st.session_state['pdf_bytes']

if not st.session_state.get("run_triggered", False):
    # Empty State Display
    st.markdown("""
        <div class="empty-state">
            <div class="empty-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#8A8A8A" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="3" y1="9" x2="21" y2="9"></line>
                    <line x1="9" y1="21" x2="9" y2="9"></line>
                </svg>
            </div>
            <div class="empty-title">Awaiting Data Ingestion</div>
            <div class="empty-subtitle">Upload Books, GSTR-2A, and GSTR-2B in the sidebar to begin reconciliation.<br/>Or click "Load Demo Synthetic Data" to preview.</div>
        </div>
    """, unsafe_allow_html=True)

else:
    # Execution Block
    try:
        with st.spinner("Executing Vectorized 3-Way ITC Matching..."):
            
            # --- DATA LOADING ---
            if st.session_state.get("is_demo", False):
                df_books, df_2b, df_2a = generate_test_data()
                if "pdf_bytes" not in st.session_state:
                    st.toast("Loaded 60 synthetic records with intentional anomalies.", icon="✅")
            else:
                if not (books_file and gstr2a_file and gstr2b_file):
                    st.warning("Please upload all three files to run the engine.")
                    st.stop()
                    
                def load_df(f):
                    return pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
                    
                df_books = load_df(books_file)
                df_2a = load_df(gstr2a_file)
                df_2b = load_df(gstr2b_file)

            # --- ENGINE EXECUTION & CACHING ---
            if 'pdf_bytes' not in st.session_state:
                matcher = ITCMatcher(tax_tolerance=1.0)
                result = matcher.reconcile(df_books, df_2b, df_2a)
                st.session_state.result = result
                
                # Execute GSTR-9 Mapper for PDF and UI
                gstr9_mapper = GSTR9TableMapper(result.consolidated, result.summary.get('total_books_itc', 0.0), result.summary.get('total_portal_itc', 0.0))
                st.session_state.t6b = gstr9_mapper.compile_table_6b()
                st.session_state.t8_metrics, st.session_state.t8_risk = gstr9_mapper.compile_table_8_matrix(st.session_state.t6b["Table_6B_Total_ITC"])
                
                # In-Memory PDF Generation Hook
                pdf_buffer = io.BytesIO()
                generate_pdf_report(
                    reco_summary=result.summary,
                    df_bucket_b=result.missing_in_portal,
                    df_bucket_c=result.unclaimed_in_books,
                    df_bucket_d=result.amount_mismatches,
                    output_path=pdf_buffer,
                    gstr9_t6b=st.session_state.t6b,
                    gstr9_t8_metrics=st.session_state.t8_metrics,
                    gstr9_risk=st.session_state.t8_risk,
                    company_name="LedgerAI Client Entity",
                    gstin="27AABCT1234F1ZP",
                    fy="FY 2024-25"
                )
                st.session_state.pdf_bytes = pdf_buffer.getvalue()
            
            result = st.session_state.result
            
            # Extract Core Metrics
            summary = result.summary
            total_books = summary.get('total_books_itc', 0.0)
            total_portal = summary.get('total_portal_itc', 0.0)
            net_variance = summary.get('total_variance', 0.0)
            itc_at_risk = summary.get('itc_at_risk', 0.0)
            
            # --- 3. MINIMALIST KPI CARDS ---
            cols = st.columns(4)
            kpis = [
                ("Total ITC in Books", f"₹ {total_books:,.2f}"),
                ("Portal Eligible ITC", f"₹ {total_portal:,.2f}"),
                ("Net Tax Variance", f"₹ {net_variance:,.2f}"),
                ("Critical Risk Exposure", f"₹ {itc_at_risk:,.2f}")
            ]
            
            for i, (label, val) in enumerate(kpis):
                with cols[i]:
                    st.markdown(f"""
                        <div class="kpi-card">
                            <div class="kpi-value">{val}</div>
                            <div class="kpi-label">{label}</div>
                        </div>
                    """, unsafe_allow_html=True)
            
            st.markdown("<br/><br/>", unsafe_allow_html=True)
            
            # --- TABS LAYOUT ---
            tab1, tab2 = st.tabs(["Dashboard & Anomalies", "GSTR-9 Annual Return Mandate"])
            
            with tab1:
                # --- 4. MONOCHROMATIC ANALYTICS RENDER & BUCKET B ---
                col_chart, col_data = st.columns([1, 1.8])
                
                with col_chart:
                    st.markdown("#### Match Distribution")
                    
                    # Prepare Donut Chart Data
                    bucket_counts = summary.get('bucket_counts', {})
                    df_chart = pd.DataFrame({
                        "Bucket": list(bucket_counts.keys()),
                        "Count": list(bucket_counts.values())
                    })
                    df_chart = df_chart[df_chart["Count"] > 0]
                    
                    # Plotly Donut (Monochromatic Grayscale)
                    fig = px.pie(
                        df_chart, 
                        names="Bucket", 
                        values="Count", 
                        hole=0.65,
                        color_discrete_sequence=['#FFFFFF', '#D3D3D3', '#808080', '#404040', '#262626']
                    )
                    
                    fig.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        margin=dict(t=10, b=10, l=10, r=10),
                        showlegend=True,
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=-0.2,
                            xanchor="center",
                            x=0.5,
                            font=dict(color="#8A8A8A")
                        ),
                        annotations=[dict(
                            text=f"{summary.get('total_records', 0)}<br>Records", 
                            x=0.5, y=0.5, 
                            font_size=20, 
                            showarrow=False, 
                            font_color="#FFFFFF"
                        )]
                    )
                    
                    fig.update_traces(
                        textposition='inside', 
                        textinfo='percent',
                        marker=dict(line=dict(color='#121212', width=2)),
                        hovertemplate="<b>%{label}</b><br>Count: %{value}<extra></extra>"
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                    
                with col_data:
                    st.markdown("#### Missing in Portal (Bucket B)")
                    st.markdown("<p style='color:#8A8A8A; font-size:13px; margin-top:-10px;'>Vendor defaulted on filing GSTR-1. High risk of ITC denial.</p>", unsafe_allow_html=True)
                    
                    b_df = result.missing_in_portal
                    display_cols_b = [c for c in ['books_invoice_no', 'books_invoice_date', 'books_gstin', 'books_total_tax'] if c in b_df.columns]
                    
                    if len(b_df) > 0:
                        st.dataframe(b_df[display_cols_b], use_container_width=True, hide_index=True)
                    else:
                        st.markdown("<div style='padding:20px; background-color:#181818; border:1px solid #2D2D2D; border-radius:8px; color:#8A8A8A; text-align:center;'>No missing portal entries detected.</div>", unsafe_allow_html=True)
                        
                st.markdown("<br/>", unsafe_allow_html=True)
                
                # --- 5. DATA INSPECTION GRIDS (BUCKET D) ---
                st.markdown("#### Value Mismatches (Bucket D)")
                st.markdown("<p style='color:#8A8A8A; font-size:13px; margin-top:-10px;'>Invoice matched, but tax values deviate between Books and Portal.</p>", unsafe_allow_html=True)
                
                d_df = result.amount_mismatches
                d_cols = [c for c in ['books_invoice_no', 'portal_invoice_no', 'books_total_tax', 'portal_total_tax', 'tax_variance'] if c in d_df.columns]
                
                if len(d_df) > 0:
                    st.dataframe(d_df[d_cols], use_container_width=True, hide_index=True)
                else:
                    st.markdown("<div style='padding:20px; background-color:#181818; border:1px solid #2D2D2D; border-radius:8px; color:#8A8A8A; text-align:center;'>No value mismatches detected.</div>", unsafe_allow_html=True)
                
                st.markdown("<br/>", unsafe_allow_html=True)
                
                # --- 5.5 DATA INSPECTION GRIDS (BUCKET C) ---
                st.markdown("#### Unclaimed in Books (Bucket C)")
                st.markdown("<p style='color:#8A8A8A; font-size:13px; margin-top:-10px;'>Vendor filed GSTR-1, but invoice is missing from Books. Tax Optimization Opportunity.</p>", unsafe_allow_html=True)
                
                c_df = result.unclaimed_in_books
                c_cols = [c for c in ['invoice_no', 'invoice_date_portal', 'supplier_gstin', 'portal_total_tax'] if c in c_df.columns]
                
                if len(c_df) > 0:
                    st.dataframe(c_df[c_cols], use_container_width=True, hide_index=True)
                else:
                    st.markdown("<div style='padding:20px; background-color:#181818; border:1px solid #2D2D2D; border-radius:8px; color:#8A8A8A; text-align:center;'>No unclaimed entries detected in this category.</div>", unsafe_allow_html=True)

            
            with tab2:
                # --- 5.5 GSTR-9 ANNUAL RETURN MAPPING ---
                st.markdown("### GSTR-9 Annual Return Mandate")
                st.markdown("<p style='color:#8A8A8A; font-size:13px; margin-top:-10px;'>Automated statutory compilation for Tables 6 & 8 based on reconciled buckets.</p>", unsafe_allow_html=True)
                
                # Fetch GSTR-9 Mapper values from session state
                t6b = st.session_state.t6b
                t8_metrics = st.session_state.t8_metrics
                t8_risk = st.session_state.t8_risk
                
                # Custom HTML/CSS Table for GSTR-9
                table_html = f"""
                <style>
                .gstr9-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 15px;
                    margin-bottom: 25px;
                    border: 1px solid #2D2D2D;
                    background-color: #181818;
                    border-radius: 6px;
                    overflow: hidden;
                }}
                .gstr9-table th {{
                    background-color: #1A1A1A;
                    color: #FFFFFF;
                    font-weight: 500;
                    text-align: left;
                    padding: 14px 20px;
                    border-bottom: 1px solid #2D2D2D;
                    font-size: 14px;
                }}
                .gstr9-table th.right-align {{
                    text-align: right;
                }}
                .gstr9-table td {{
                    padding: 14px 20px;
                    border-bottom: 1px solid #2D2D2D;
                    color: #F2F2F2;
                    font-size: 14px;
                }}
                .gstr9-table td.val {{
                    text-align: right;
                    font-family: 'SF Mono', Consolas, monospace;
                    font-size: 14px;
                }}
                </style>
                <table class="gstr9-table">
                    <tr>
                        <th>Statutory Table Reference</th>
                        <th class="right-align">Computed Value (₹)</th>
                    </tr>
                    <tr>
                        <td>Table 6B (Availed Inward Supplies ITC)</td>
                        <td class="val">{t6b['Table_6B_Total_ITC']:,.2f}</td>
                    </tr>
                    <tr>
                        <td>Table 8A (Portal Baseline)</td>
                        <td class="val">{t8_metrics['Table_8A_Portal_ITC']:,.2f}</td>
                    </tr>
                    <tr>
                        <td>Table 8B (Availed ITC - Matches 6B)</td>
                        <td class="val">{t8_metrics['Table_8B_Availed_ITC']:,.2f}</td>
                    </tr>
                    <tr>
                        <td>Table 8C (Deferred ITC / Timing Lag)</td>
                        <td class="val">{t8_metrics['Table_8C_Deferred_ITC']:,.2f}</td>
                    </tr>
                    <tr>
                        <td style="font-weight:600; color:#FFFFFF;">Table 8D (Statutory Variance)</td>
                        <td class="val" style="font-weight:600; color:#FFFFFF;">{t8_metrics['Table_8D_Variance']:,.2f}</td>
                    </tr>
                </table>
                """
                st.markdown(table_html, unsafe_allow_html=True)
                
                # Systemic Risk Banner Injection
                st.markdown("#### Statutory Risk Assessment")
                if "CRITICAL" in t8_risk["status"]:
                    st.markdown(f"""
                    <div style="background-color: #1A1A1A; border: 1px solid #2D2D2D; border-left: 4px solid #E53935; border-radius: 4px; padding: 20px;">
                        <h3 style="color: #FFFFFF !important; margin-top: 0; font-size: 16px; margin-bottom: 8px;">CRITICAL RISK EXPOSURE</h3>
                        <p style="color: #FFFFFF; font-size: 14px; margin-bottom: 0px;">{t8_risk['action_item']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                elif "OPTIMIZATION" in t8_risk["status"]:
                    st.markdown(f"""
                    <div style="background-color: #1A1A1A; border: 1px solid #2D2D2D; border-left: 4px solid #43A047; border-radius: 4px; padding: 20px;">
                        <h3 style="color: #FFFFFF !important; margin-top: 0; font-size: 16px; margin-bottom: 8px;">TAX OPTIMIZATION OPPORTUNITY</h3>
                        <p style="color: #FFFFFF; font-size: 14px; margin-bottom: 0px;">{t8_risk['action_item']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style="background-color: #1A1A1A; border: 1px solid #2D2D2D; border-left: 4px solid #8A8A8A; border-radius: 4px; padding: 20px;">
                        <h3 style="color: #FFFFFF !important; margin-top: 0; font-size: 16px; margin-bottom: 8px;">COMPLIANT</h3>
                        <p style="color: #8A8A8A; font-size: 14px; margin-bottom: 0px;">{t8_risk['action_item']}</p>
                    </div>
                    """, unsafe_allow_html=True)

            
            # --- 6. EXPORT ARTIFACTS TAB/SECTION ---
            st.markdown("### Export Artifacts")
            st.markdown("<p style='color:#8A8A8A; font-size:14px; margin-top:-10px;'>Download the formal CA-ready audit report for client delivery.</p>", unsafe_allow_html=True)
            
            # High-Contrast Download Trigger
            st.download_button(
                label="DOWNLOAD PDF AUDIT REPORT",
                data=st.session_state.pdf_bytes,
                file_name="GST_Audit_Report_27AABCT1234F1ZP_FY2425.pdf",
                mime="application/pdf",
                use_container_width=True
            )


    except Exception as e:
        st.error(f"Error during execution: {str(e)}")
