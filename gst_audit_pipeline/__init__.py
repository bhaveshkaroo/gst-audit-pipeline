"""
GST Pre-Audit & Finalization Verification Pipeline
====================================================
Data Ingestion and Normalization layer for Indian GST compliance.

Modules:
    schemas   — Pydantic models for Sales, Purchase, GSTR-1, GSTR-2B.
    parsers   — Robust Excel/JSON parsers with messy-data handling.
    utils     — Invoice sanitization, GSTIN checksum validation.
    mock_data — Synthetic dataset generator for pipeline testing.
"""

__version__ = "0.1.0"
