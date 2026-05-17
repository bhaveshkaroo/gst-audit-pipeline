"""
Formal PDF Audit Report Generator
====================================
Generates a CA-ready, unalterable PDF of the 3-Way ITC Matching results.
Adheres strictly to the Editorial Monochrome Aesthetic (Black, Charcoal, Gray).
"""

from __future__ import annotations

import os
from datetime import datetime
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that intercepts save execution to stamp "Page X of Y"
    and a subtle confidentiality disclaimer on every page.
    """
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        """Save state of current page before starting a new one."""
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        """Add page info to each page before actually saving."""
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count: int):
        """Draw the disclaimer and page number in the bottom margin."""
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#808080"))
        
        # Bottom-left: Confidentiality Disclaimer
        disclaimer = "STRICTLY CONFIDENTIAL: GST Pre-Audit Working Paper - For Internal Use Only"
        self.drawString(inch, 0.5 * inch, disclaimer)
        
        # Bottom-right: Page X of Y
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(A4[0] - inch, 0.5 * inch, page_str)
        
        self.restoreState()


def _format_currency(val: float | int) -> str:
    """Format numeric values as Indian Rupees."""
    try:
        return f"Rs. {float(val):,.2f}"
    except (ValueError, TypeError):
        return str(val)


def generate_pdf_report(
    reco_summary: dict,
    df_bucket_b: pd.DataFrame,
    df_bucket_c: pd.DataFrame,
    df_bucket_d: pd.DataFrame,
    output_path: str,
    gstr9_t6b: dict = None,
    gstr9_t8_metrics: dict = None,
    gstr9_risk: dict = None,
    company_name: str = "Client Company Ltd.",
    gstin: str = "27AABCT1234F1ZP",
    fy: str = "FY 2024-25"
) -> str:
    """
    Compiles summary dictionaries and anomaly dataframes into a premium PDF.
    
    Args:
        reco_summary: Dictionary of total metrics from the ITCMatcher.
        df_bucket_b: DataFrame containing "Missing in Portal" exceptions.
        df_bucket_c: DataFrame containing "Unclaimed in Books" exceptions.
        df_bucket_d: DataFrame containing "Value Mismatches" exceptions.
        output_path: Absolute or relative path to save the generated PDF.
        company_name: Name of the audited entity.
        gstin: Legal GSTIN of the entity.
        fy: Financial year being audited.
        
    Returns:
        str: Path to the generated PDF.
    """
    
    # ── Document Setup ──
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch
    )
    
    elements = []
    base_styles = getSampleStyleSheet()
    
    # ── Premium Monochrome Styles ──
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=base_styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        textColor=colors.HexColor('#000000'),
        spaceAfter=14,
        alignment=1  # Center
    )
    
    h2_style = ParagraphStyle(
        'H2Style',
        parent=base_styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.HexColor('#000000'),
        spaceAfter=10,
        spaceBefore=15
    )
    
    header_cell_style = ParagraphStyle(
        'HeaderCellStyle',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=colors.HexColor('#FFFFFF'),
        alignment=0  # Left
    )
    
    data_cell_style = ParagraphStyle(
        'DataCellStyle',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        textColor=colors.HexColor('#000000'),
        alignment=0,
        wordWrap='CJK'  # Ensures long strings break properly inside cells
    )
    
    data_cell_right = ParagraphStyle(
        'DataCellRight',
        parent=data_cell_style,
        alignment=2  # Right align for numbers
    )
    
    # ════════════════════════════════════════════════════════════════
    # PAGE 1: EXECUTIVE AUDIT CERTIFICATE
    # ════════════════════════════════════════════════════════════════
    
    elements.append(Paragraph("GST ITC RECONCILIATION AUDIT REPORT", title_style))
    elements.append(Spacer(1, 0.3 * inch))
    
    # ── Metadata Block ──
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta_data = [
        [Paragraph("<b>Company Legal Name:</b>", data_cell_style), Paragraph(company_name, data_cell_style)],
        [Paragraph("<b>Entity GSTIN:</b>", data_cell_style), Paragraph(gstin, data_cell_style)],
        [Paragraph("<b>Financial Year:</b>", data_cell_style), Paragraph(fy, data_cell_style)],
        [Paragraph("<b>Verification Timestamp:</b>", data_cell_style), Paragraph(timestamp, data_cell_style)],
    ]
    
    meta_table = Table(meta_data, colWidths=[2 * inch, 4 * inch])
    meta_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#E0E0E0')), # Subtle dividers
    ]))
    
    elements.append(meta_table)
    elements.append(Spacer(1, 0.6 * inch))
    
    # ── Executive Metrics Box ──
    total_books = reco_summary.get('total_books_itc', 0)
    total_portal = reco_summary.get('total_portal_itc', 0)
    net_var = reco_summary.get('net_variance', 0)
    exposure = reco_summary.get('itc_at_risk', 0)
    
    metrics_data = [
        [Paragraph("EXECUTIVE METRICS SUMMARY", header_cell_style), ""],
        [Paragraph("Total Books ITC (Internal Register)", data_cell_style), Paragraph(_format_currency(total_books), data_cell_style)],
        [Paragraph("Total Portal Approved ITC (GSTR-2B)", data_cell_style), Paragraph(_format_currency(total_portal), data_cell_style)],
        [Paragraph("Net Tax Variance", data_cell_style), Paragraph(_format_currency(net_var), data_cell_style)],
        [Paragraph("Total Discrepancy Exposure (At Risk)", ParagraphStyle('', parent=data_cell_style, fontName='Helvetica-Bold')), 
         Paragraph(_format_currency(exposure), ParagraphStyle('', parent=data_cell_style, fontName='Helvetica-Bold'))],
    ]
    
    metrics_table = Table(metrics_data, colWidths=[4 * inch, 2.5 * inch])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#1A1A1A')), # Deep Charcoal Header
        ('SPAN', (0, 0), (1, 0)),
        ('ALIGN', (0, 0), (1, 0), 'CENTER'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#FFFFFF')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E0E0E0')),
        ('GRID', (0, 1), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
    ]))
    
    elements.append(metrics_table)
    elements.append(PageBreak())
    
    # ════════════════════════════════════════════════════════════════
    # PAGE 2+: DETAILED EXCEPTION SCHEDULES
    # ════════════════════════════════════════════════════════════════
    
    def _build_schedule(title: str, df: pd.DataFrame, columns: list, col_headers: list, col_widths: list):
        """Helper to generate clean, wrapped tables from Pandas DataFrames."""
        elements.append(Paragraph(title, h2_style))
        
        if df is None or df.empty:
            elements.append(Spacer(1, 0.1 * inch))
            elements.append(Paragraph("<i>No material anomalies detected in this category.</i>", data_cell_style))
            elements.append(Spacer(1, 0.4 * inch))
            return
            
        # Header Row
        table_data = [[Paragraph(h, header_cell_style) for h in col_headers]]
        
        # Data Rows
        for _, row in df.iterrows():
            row_data = []
            for col in columns:
                val = row.get(col, "")
                if pd.isna(val):
                    val = ""
                    
                # Format numerics
                if isinstance(val, (int, float)):
                    row_data.append(Paragraph(f"{val:,.2f}", data_cell_right))
                else:
                    # Wrap strings into Paragraphs to prevent overflow
                    row_data.append(Paragraph(str(val), data_cell_style))
            table_data.append(row_data)
            
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        
        # Alternating row colors and borders
        t_style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1A1A1A')),
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E0E0E0')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]
        
        # Apply alternating #F9F9F9 background
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                t_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F9F9F9')))
                
        t.setStyle(TableStyle(t_style))
        elements.append(t)
        elements.append(Spacer(1, 0.4 * inch))

    # ── Schedule A: Missing in Portal (Bucket B) ──
    b_cols = ['display_invoice_no', 'display_date', 'display_gstin', 'display_tax']
    b_headers = ['Invoice Number', 'Date', 'Supplier GSTIN', 'Tax at Risk (Rs.)']
    b_widths = [1.8 * inch, 1.0 * inch, 1.7 * inch, 1.5 * inch]
    
    _build_schedule(
        title="Schedule A: Missing in Portal (Bucket B)",
        df=df_bucket_b,
        columns=b_cols,
        col_headers=b_headers,
        col_widths=b_widths
    )
    
    # ── Schedule B: Value Mismatches (Bucket D) ──
    d_cols = ['display_invoice_no', 'display_tax', 'portal_total_tax', 'tax_variance']
    d_headers = ['Matched Invoice', 'Books Tax (Rs.)', 'Portal Tax (Rs.)', 'Variance (Rs.)']
    d_widths = [1.8 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch]
    
    _build_schedule(
        title="Schedule B: Tax Value Mismatches (Bucket D)",
        df=df_bucket_d,
        columns=d_cols,
        col_headers=d_headers,
        col_widths=d_widths
    )
    
    # ── Schedule C: Unclaimed in Books (Bucket C) ──
    c_cols = ['invoice_no', 'invoice_date_portal', 'supplier_gstin', 'portal_total_tax']
    c_headers = ['Invoice Number', 'Date', 'Supplier GSTIN', 'Portal Tax (Rs.)']
    c_widths = [1.8 * inch, 1.0 * inch, 1.7 * inch, 1.5 * inch]
    
    _build_schedule(
        title="Schedule C: Unclaimed in Books (Bucket C)",
        df=df_bucket_c,
        columns=c_cols,
        col_headers=c_headers,
        col_widths=c_widths
    )
    
    # ════════════════════════════════════════════════════════════════
    # APPENDIX: STATUTORY FORM GSTR-9 MAPPING LEDGER
    # ════════════════════════════════════════════════════════════════
    if gstr9_t6b and gstr9_t8_metrics and gstr9_risk:
        elements.append(PageBreak())
        elements.append(Paragraph("APPENDIX: STATUTORY FORM GSTR-9 MAPPING LEDGER", title_style))
        elements.append(Spacer(1, 0.3 * inch))
        
        # Build the Table Rows
        appendix_data = [
            [Paragraph("<b>Statutory Table Reference</b>", header_cell_style), 
             Paragraph("<b>Computed Value (Rs.)</b>", ParagraphStyle('', parent=header_cell_style, alignment=2))],
            [Paragraph("Table 6B (Inward Supplies Registered Persons)", data_cell_style), 
             Paragraph(f"{gstr9_t6b['Table_6B_Total_ITC']:,.2f}", data_cell_right)],
            [Paragraph("Table 8A (Portal-Visible GSTR-2B Baseline Credit)", data_cell_style), 
             Paragraph(f"{gstr9_t8_metrics['Table_8A_Portal_ITC']:,.2f}", data_cell_right)],
            [Paragraph("Table 8B (Dynamic Availed Inward Credit)", data_cell_style), 
             Paragraph(f"{gstr9_t8_metrics['Table_8B_Availed_ITC']:,.2f}", data_cell_right)],
            [Paragraph("Table 8C (Deferred Timing Differences / Bucket E)", data_cell_style), 
             Paragraph(f"{gstr9_t8_metrics['Table_8C_Deferred_ITC']:,.2f}", data_cell_right)],
            [Paragraph("<b>Table 8D (Computed Systemic Filing Variance)</b>", data_cell_style), 
             Paragraph(f"<b>{gstr9_t8_metrics['Table_8D_Variance']:,.2f}</b>", data_cell_right)],
        ]
        
        appendix_table = Table(appendix_data, colWidths=[4.5 * inch, 2 * inch])
        appendix_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#1A1A1A')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TEXTCOLOR', (0, 0), (1, 0), colors.HexColor('#FFFFFF')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#000000')),  # Strict Solid Black Tracking Border
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#F9F9F9')),
            ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor('#F9F9F9')),
        ]))
        
        elements.append(appendix_table)
        elements.append(Spacer(1, 0.4 * inch))
        
        # Integrated Auditor Disclaimer
        elements.append(Paragraph("<b>STATUTORY RISK ASSESSMENT & AUDITOR ACTION PLAN:</b>", h2_style))
        elements.append(Spacer(1, 0.1 * inch))
        
        disclaimer_html = (
            f"<b>Status:</b> {gstr9_risk['status']}<br/>"
            f"<b>Value at Risk / Opportunity:</b> Rs. {gstr9_risk['exposure_value']:,.2f}<br/><br/>"
            f"<b>Action Item:</b> {gstr9_risk['action_item']}"
        )
        elements.append(Paragraph(disclaimer_html, data_cell_style))
        
    # ── Build and Save ──
    doc.build(elements, canvasmaker=NumberedCanvas)
    return output_path
