from datetime import date, timedelta
from decimal import Decimal

from app.validation import ValidationContext, validate_extraction

# Static reference context for deterministic unit tests
FIXED_TODAY = date(2026, 4, 15)
DEFAULT_CONTEXT = ValidationContext(
    today=FIXED_TODAY,
    tolerance=Decimal("1.00"),
    max_invoice_age_days=180,
    allowed_tax_rates=[Decimal("0.00"), Decimal("0.05"), Decimal("0.12"), Decimal("0.18"), Decimal("0.28")],
    allowed_gst_state_codes=[f"{i:02d}" for i in range(1, 38)] + ["38", "97", "99"],
    warnings_route_to_review=True,
)


def make_clean_invoice() -> dict:
    """Returns a completely valid invoice extraction."""
    return {
        "vendor_name": "Apex Cloud Services Pvt Ltd",
        "vendor_gstin": "29AABCU9603R1ZM",
        "invoice_number": "INV-2026-001",
        "invoice_date": "2026-04-01",
        "currency": "INR",
        "subtotal": Decimal("10000.00"),
        "cgst": Decimal("900.00"),
        "sgst": Decimal("900.00"),
        "igst": Decimal("0.00"),
        "total": Decimal("11800.00"),
        "line_items": [
            {
                "description": "Cloud Hosting Service",
                "quantity": Decimal("2.00"),
                "unit_price": Decimal("5000.00"),
                "amount": Decimal("10000.00"),
            }
        ],
    }


# ---------------- 1. Fully Valid Invoice ----------------
def test_valid_invoice_has_zero_issues():
    inv = make_clean_invoice()
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    assert len(issues) == 0


# ---------------- 2. Missing Header Fields ----------------
def test_missing_vendor_name():
    inv = make_clean_invoice()
    inv["vendor_name"] = ""
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    codes = [i.code for i in issues]
    assert "MISSING_VENDOR_NAME" in codes


def test_missing_invoice_number():
    inv = make_clean_invoice()
    inv["invoice_number"] = "   "
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    codes = [i.code for i in issues]
    assert "MISSING_INVOICE_NUMBER" in codes


def test_no_line_items():
    inv = make_clean_invoice()
    inv["line_items"] = []
    inv["subtotal"] = Decimal("0.00")
    inv["cgst"] = Decimal("0.00")
    inv["sgst"] = Decimal("0.00")
    inv["total"] = Decimal("0.00")
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    codes = [i.code for i in issues]
    assert "NO_LINE_ITEMS" in codes


# ---------------- 3. Line Item Calculation & Tolerance Boundary ----------------
def test_line_item_amount_tolerance_boundary():
    # 2.00 * 5000.00 = 10000.00
    # Boundary tests with tolerance = 1.00:
    # 10000.00 + 1.00 = 10001.00 (difference 1.00 <= tolerance) -> PASS
    inv_pass = make_clean_invoice()
    inv_pass["line_items"][0]["amount"] = Decimal("10001.00")
    inv_pass["subtotal"] = Decimal("10001.00")
    inv_pass["total"] = Decimal("11801.00")
    issues_pass = validate_extraction(inv_pass, DEFAULT_CONTEXT)
    codes_pass = [i.code for i in issues_pass]
    assert "LINE_ITEM_AMOUNT_MISMATCH" not in codes_pass

    # 10000.00 + 1.01 = 10001.01 (difference 1.01 > tolerance 1.00) -> FAIL
    inv_fail = make_clean_invoice()
    inv_fail["line_items"][0]["amount"] = Decimal("10001.01")
    issues_fail = validate_extraction(inv_fail, DEFAULT_CONTEXT)
    codes_fail = [i.code for i in issues_fail]
    assert "LINE_ITEM_AMOUNT_MISMATCH" in codes_fail


# ---------------- 4. Line Items Sum vs Subtotal Boundary ----------------
def test_line_items_sum_vs_subtotal_boundary():
    # Line items sum = 10000.00
    # Subtotal = 10000.99 (diff 0.99 <= 1.00) -> PASS
    inv_pass = make_clean_invoice()
    inv_pass["subtotal"] = Decimal("10000.99")
    inv_pass["total"] = Decimal("11800.99")
    issues_pass = validate_extraction(inv_pass, DEFAULT_CONTEXT)
    assert "LINE_ITEMS_SUM_MISMATCH" not in [i.code for i in issues_pass]

    # Subtotal = 10001.50 (diff 1.50 > 1.00) -> FAIL
    inv_fail = make_clean_invoice()
    inv_fail["subtotal"] = Decimal("10001.50")
    issues_fail = validate_extraction(inv_fail, DEFAULT_CONTEXT)
    assert "LINE_ITEMS_SUM_MISMATCH" in [i.code for i in issues_fail]


# ---------------- 5. Total Mismatch Boundary ----------------
def test_total_mismatch_boundary():
    # Calculated total = 10000 + 900 + 900 = 11800.00
    # Stated total = 11800.80 (diff 0.80 <= 1.00) -> PASS
    inv_pass = make_clean_invoice()
    inv_pass["total"] = Decimal("11800.80")
    issues_pass = validate_extraction(inv_pass, DEFAULT_CONTEXT)
    assert "TOTAL_MISMATCH" not in [i.code for i in issues_pass]

    # Stated total = 11802.00 (diff 2.00 > 1.00) -> FAIL
    inv_fail = make_clean_invoice()
    inv_fail["total"] = Decimal("11802.00")
    issues_fail = validate_extraction(inv_fail, DEFAULT_CONTEXT)
    assert "TOTAL_MISMATCH" in [i.code for i in issues_fail]


# ---------------- 6. Tax Type Conflict: IGST with CGST/SGST ----------------
def test_tax_type_conflict_igst_combined_with_cgst_sgst():
    inv = make_clean_invoice()
    inv["cgst"] = Decimal("900.00")
    inv["sgst"] = Decimal("900.00")
    inv["igst"] = Decimal("1800.00")
    inv["total"] = Decimal("13600.00")
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    codes = [i.code for i in issues]
    assert "TAX_TYPE_CONFLICT" in codes


def test_pure_igst_no_conflict():
    inv = make_clean_invoice()
    inv["cgst"] = Decimal("0.00")
    inv["sgst"] = Decimal("0.00")
    inv["igst"] = Decimal("1800.00")
    inv["total"] = Decimal("11800.00")
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    codes = [i.code for i in issues]
    assert "TAX_TYPE_CONFLICT" not in codes


# ---------------- 7. Negative Amounts ----------------
def test_negative_amounts():
    inv = make_clean_invoice()
    inv["total"] = Decimal("-100.00")
    inv["line_items"][0]["quantity"] = Decimal("-1.00")
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    codes = [i.code for i in issues]
    assert "NEGATIVE_AMOUNT" in codes


# ---------------- 8. GSTIN Validation ----------------
def test_gstin_validation():
    # Valid GSTIN
    inv_valid = make_clean_invoice()
    inv_valid["vendor_gstin"] = "29AABCU9603R1ZM"
    assert "INVALID_GSTIN" not in [i.code for i in validate_extraction(inv_valid, DEFAULT_CONTEXT)]

    # Missing GSTIN (Warning)
    inv_missing = make_clean_invoice()
    inv_missing["vendor_gstin"] = None
    issues_missing = validate_extraction(inv_missing, DEFAULT_CONTEXT)
    assert "MISSING_GSTIN" in [i.code for i in issues_missing]

    # Wrong length (14 chars)
    inv_short = make_clean_invoice()
    inv_short["vendor_gstin"] = "29AABCU9603R1Z"
    issues_short = validate_extraction(inv_short, DEFAULT_CONTEXT)
    assert "INVALID_GSTIN" in [i.code for i in issues_short]

    # Lowercase letters
    inv_lower = make_clean_invoice()
    inv_lower["vendor_gstin"] = "29aabcu9603r1zm"
    issues_lower = validate_extraction(inv_lower, DEFAULT_CONTEXT)
    assert "INVALID_GSTIN" in [i.code for i in issues_lower]

    # Bad state code (98 is invalid)
    inv_state = make_clean_invoice()
    inv_state["vendor_gstin"] = "98AABCU9603R1ZM"
    issues_state = validate_extraction(inv_state, DEFAULT_CONTEXT)
    assert "INVALID_GSTIN" in [i.code for i in issues_state]


# ---------------- 9. Invoice Date (Future & Old) ----------------
def test_future_invoice_date():
    inv = make_clean_invoice()
    inv["invoice_date"] = (FIXED_TODAY + timedelta(days=5)).isoformat()
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    assert "FUTURE_INVOICE_DATE" in [i.code for i in issues]


def test_old_invoice_date():
    inv = make_clean_invoice()
    inv["invoice_date"] = (FIXED_TODAY - timedelta(days=200)).isoformat()
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    assert "OLD_INVOICE_DATE" in [i.code for i in issues]


# ---------------- 10. CGST vs SGST Mismatch ----------------
def test_cgst_sgst_mismatch():
    inv = make_clean_invoice()
    inv["cgst"] = Decimal("900.00")
    inv["sgst"] = Decimal("800.00")
    inv["total"] = Decimal("11700.00")
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    assert "CGST_SGST_MISMATCH" in [i.code for i in issues]


# ---------------- 11. Unexpected Tax Rate ----------------
def test_unexpected_tax_rate():
    inv = make_clean_invoice()
    # 7% tax rate (700 / 10000) is not in [0%, 5%, 12%, 18%, 28%]
    inv["cgst"] = Decimal("350.00")
    inv["sgst"] = Decimal("350.00")
    inv["total"] = Decimal("10700.00")
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    assert "UNEXPECTED_TAX_RATE" in [i.code for i in issues]


# ---------------- 12. Decimal Precision (0.1 + 0.2 No False Mismatches) ----------------
def test_decimal_precision_no_float_drift():
    # 0.10 + 0.20 = 0.30 in Decimal arithmetic
    inv = {
        "vendor_name": "Precision Tech",
        "vendor_gstin": "27AABCU9603R1ZM",
        "invoice_number": "DEC-001",
        "invoice_date": "2026-04-10",
        "currency": "INR",
        "subtotal": Decimal("0.30"),
        "cgst": Decimal("0.00"),
        "sgst": Decimal("0.00"),
        "igst": Decimal("0.00"),
        "total": Decimal("0.30"),
        "line_items": [
            {
                "description": "Item 1",
                "quantity": Decimal("1.00"),
                "unit_price": Decimal("0.10"),
                "amount": Decimal("0.10"),
            },
            {
                "description": "Item 2",
                "quantity": Decimal("1.00"),
                "unit_price": Decimal("0.20"),
                "amount": Decimal("0.20"),
            },
        ],
    }
    issues = validate_extraction(inv, DEFAULT_CONTEXT)
    assert len(issues) == 0
