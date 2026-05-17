"""
Outward Supply Validation Demo
================================
Usage: python -c "from gst_audit_pipeline.run_outward_validation_demo import main; main()"
"""
from __future__ import annotations
import io, sys, random
import numpy as np, pandas as pd

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from .utils.gstin_validator import gstin_checksum

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
def _rand_gstin(sc="27"):
    pan = "".join(random.choices(_LETTERS, k=5)) + "".join(random.choices("0123456789", k=4)) + random.choice(_LETTERS)
    p = f"{sc}{pan}1Z"
    return p + gstin_checksum(p)

def _generate_test_data():
    random.seed(99); np.random.seed(99)
    customers = [_rand_gstin() for _ in range(12)]
    rates = [5.0, 12.0, 18.0, 28.0]
    hsn_codes = ["84713000", "99831", "8471", "30049099", "9988", "8528", "998314"]
    books_rows, gstr1_rows = [], []

    for i in range(1, 81):
        cust = random.choice(customers)
        rate = random.choice(rates)
        taxable = round(random.uniform(10000, 500000), 2)
        is_inter = random.random() < 0.3
        hsn = random.choice(hsn_codes)
        inv_no = f"INV/{i:04d}/2425"
        inv_date = f"2024-{random.randint(4,12):02d}-{random.randint(1,28):02d}"

        if is_inter:
            igst = round(taxable * rate / 100, 2); cgst = sgst = 0.0
        else:
            cgst = round(taxable * rate / 200, 2); sgst = cgst; igst = 0.0

        books_rows.append(dict(invoice_no=inv_no, invoice_date=inv_date,
            customer_gstin=cust, taxable_value=taxable, tax_rate=rate,
            cgst=cgst, sgst=sgst, igst=igst, hsn_sac=hsn))

        # GSTR-1: skip some, tweak some
        if i in (15, 30, 45):  # Missing from GSTR-1
            continue
        g1_taxable = taxable
        g1_cgst, g1_sgst, g1_igst = cgst, sgst, igst
        if i in (10, 25, 50):  # Amount mismatch
            g1_taxable += round(random.uniform(500, 5000), 2)
            if is_inter: g1_igst = round(g1_taxable * rate / 100, 2)
            else: g1_cgst = round(g1_taxable * rate / 200, 2); g1_sgst = g1_cgst
        if i == 60:  # Wrong tax rate
            g1_cgst = round(taxable * 14 / 200, 2)  # 14% instead of correct rate
            g1_sgst = g1_cgst
        if i == 70:  # IGST split error
            g1_igst = round(taxable * rate / 100, 2) + 150  # off by Rs.150

        gstr1_rows.append(dict(invoice_no=inv_no, recipient_gstin=cust,
            taxable_value=g1_taxable, tax_rate=rate, cgst=g1_cgst, sgst=g1_sgst, igst=g1_igst))

    # Add 3 invoices only in GSTR-1 (not in books)
    for j in range(81, 84):
        cust = random.choice(customers)
        gstr1_rows.append(dict(invoice_no=f"INV/{j:04d}/2425", recipient_gstin=cust,
            taxable_value=round(random.uniform(20000, 80000), 2), tax_rate=18.0,
            cgst=round(random.uniform(1000, 5000), 2), sgst=round(random.uniform(1000, 5000), 2), igst=0.0))

    books_df = pd.DataFrame(books_rows)
    gstr1_df = pd.DataFrame(gstr1_rows)

    # HSN summary (Table 12) — intentionally omit one HSN
    hsn_df = (gstr1_df.assign(hsn_sc=books_df["hsn_sac"].iloc[:len(gstr1_df)].values
        if len(gstr1_df) <= len(books_df) else
        list(books_df["hsn_sac"]) + [random.choice(hsn_codes) for _ in range(len(gstr1_df)-len(books_df))])
        .groupby("hsn_sc").agg(taxable_value=("taxable_value","sum"),
            cgst=("cgst","sum"), sgst=("sgst","sum"), igst=("igst","sum"))
        .reset_index())
    # Drop one HSN to simulate missing
    if len(hsn_df) > 2:
        hsn_df = hsn_df.iloc[:-1]

    # GSTR-3B summary with slight variance
    gstr3b = {"total_taxable_outward": books_df["taxable_value"].sum() + 125000}

    # Amendment data
    amendments = {
        "table10_prev_fy": 75000.0,
        "table11_prev_fy": 22000.0,
        "table10_curr_fy": 45000.0,
        "table11_curr_fy": 18000.0,
    }

    return books_df, gstr1_df, hsn_df, gstr3b, amendments


def main():
    from .validation import OutwardSupplyValidator

    sep = "=" * 72
    print(f"\n{sep}")
    print("  OUTWARD SUPPLY (SALES) VALIDATION ENGINE")
    print(sep)

    books, gstr1, hsn, gstr3b, amendments = _generate_test_data()
    print(f"\n  [OK] Books Sales Register:   {len(books):>4d} invoices")
    print(f"  [OK] GSTR-1 B2B Section:     {len(gstr1):>4d} invoices")
    print(f"  [OK] GSTR-1 HSN Table 12:    {len(hsn):>4d} HSN codes")
    print(f"  [OK] GSTR-3B Summary loaded")
    print(f"  [OK] Amendment data (Table 10/11) loaded")

    validator = OutwardSupplyValidator(company_gstin="27AABCT1234F1ZP", fy_label="FY 2024-25")
    result = validator.validate(books, gstr1, hsn, gstr3b, amendments)

    # Print True Adjusted Supply
    if result.adjusted_supply:
        print(f"\n{sep}")
        print("  MULTI-YEAR OVERLAP EQUATION")
        print(sep)
        print(f"\n{result.adjusted_supply.computation_breakdown}")

    # Print findings by severity
    print(f"\n{sep}")
    print(f"  AUDIT FINDINGS: {result.total_findings} total")
    print(f"  CRITICAL: {result.critical_count}  |  HIGH: {result.high_count}  "
          f"|  MEDIUM: {result.medium_count}  |  LOW: {result.low_count}  |  INFO: {result.info_count}")
    print(sep)

    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        findings = [f for f in result.findings if f.severity.value == sev]
        if not findings:
            continue
        print(f"\n  --- {sev} ({len(findings)}) ---")
        for f in findings[:5]:  # Show max 5 per severity
            print(f"\n  [{f.finding_id}] {f.title}")
            print(f"    {f.description}")
            if f.variance:
                print(f"    Variance: Rs. {f.variance:,.2f} ({f.variance_pct:+.2f}%)")
            print(f"    >> {f.recommendation}")
        if len(findings) > 5:
            print(f"\n    ... and {len(findings) - 5} more {sev} findings.")

    # Summary
    print(f"\n{sep}")
    print("  VALIDATION COMPLETE")
    print(sep)
    books_total = books["taxable_value"].sum()
    gstr1_total = gstr1["taxable_value"].sum()
    adj_total = result.adjusted_supply.true_adjusted_supply if result.adjusted_supply else 0
    print(f"  Books Net Sales:        Rs. {books_total:>14,.2f}")
    print(f"  GSTR-1 Total Filed:     Rs. {gstr1_total:>14,.2f}")
    print(f"  True Adjusted Supply:   Rs. {adj_total:>14,.2f}")
    print(f"  Findings to resolve:    {result.total_findings}")
    print(sep)


if __name__ == "__main__":
    main()
