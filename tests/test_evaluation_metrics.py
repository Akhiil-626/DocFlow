from datetime import date
from decimal import Decimal

from app.evaluation_metrics import (
    calculate_percentiles,
    calculate_repeat_consistency,
    calculate_silent_error_rate,
    compare_date,
    compare_field,
    compare_money,
    compare_vendor_name,
    evaluate_invoice_extraction,
)


def test_compare_money():
    # Exact Decimal matches
    assert compare_money(Decimal("1000.00"), "1000.00") is True
    assert compare_money("1000.00", 1000) is True
    assert compare_money("1000", "1000.00") is True
    assert compare_money("  540.25  ", Decimal("540.25")) is True
    assert compare_money(0, "0.00") is True
    assert compare_money(None, "0.00") is True

    # Mismatches
    assert compare_money("1000.00", "1000.01") is False
    assert compare_money("50.00", "500.00") is False
    assert compare_money("invalid", "10.00") is False


def test_compare_date():
    # Date matches across formats and types
    assert compare_date("2026-04-15", date(2026, 4, 15)) is True
    assert compare_date("2026-04-15", "2026-04-15") is True
    assert compare_date("15-04-2026", "2026-04-15") is True
    assert compare_date("15/04/2026", "2026-04-15") is True
    assert compare_date("  2026-04-15  ", "2026-04-15") is True

    # Mismatches
    assert compare_date("2026-04-15", "2026-04-16") is False
    assert compare_date("2025-04-15", "2026-04-15") is False


def test_compare_vendor_name():
    # Normalizes only trim and case
    assert compare_vendor_name("  Apex Technologies  ", "apex technologies") is True
    assert compare_vendor_name("ABC PVT LTD", "abc pvt ltd") is True
    assert compare_vendor_name("Acme Corp", "  Acme Corp  ") is True

    # Punctuation/characters are preserved (not stripped)
    assert compare_vendor_name("Acme, Inc.", "Acme Inc.") is False
    assert compare_vendor_name("Vendor One", "Vendor Two") is False


def test_compare_field():
    # Money fields
    assert compare_field("total", "1180.00", Decimal("1180.00")) is True
    assert compare_field("subtotal", "1000.00", "1000") is True

    # Case insensitive uppercase fields
    assert compare_field("vendor_gstin", "27aabcu9603r1zm", "27AABCU9603R1ZM") is True
    assert compare_field("invoice_number", "inv-001", "INV-001") is True
    assert compare_field("currency", "inr", "INR") is True

    # Line items
    gt_items = [
        {"description": "Item 1", "quantity": "2.00", "unit_price": "50.00", "amount": "100.00"}
    ]
    ex_items_match = [
        {"description": "  item 1 ", "quantity": 2, "unit_price": 50, "amount": 100}
    ]
    ex_items_mismatch = [
        {"description": "Item 1", "quantity": "3.00", "unit_price": "50.00", "amount": "150.00"}
    ]
    assert compare_field("line_items", ex_items_match, gt_items) is True
    assert compare_field("line_items", ex_items_mismatch, gt_items) is False


def test_evaluate_invoice_extraction():
    ground_truth = {
        "vendor_name": "Apex Technologies",
        "vendor_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-101",
        "invoice_date": "2026-04-01",
        "currency": "INR",
        "subtotal": "1000.00",
        "cgst": "90.00",
        "sgst": "90.00",
        "igst": "0.00",
        "total": "1180.00",
        "line_items": [
            {"description": "Service", "quantity": "1.00", "unit_price": "1000.00", "amount": "1000.00"}
        ],
    }

    # Perfect match
    extracted_perfect = dict(ground_truth)
    is_correct, matches, mismatches = evaluate_invoice_extraction(extracted_perfect, ground_truth)
    assert is_correct is True
    assert len(mismatches) == 0
    assert all(matches.values())

    # Flawed extraction (wrong total and vendor name)
    extracted_flawed = dict(ground_truth)
    extracted_flawed["total"] = "1200.00"
    extracted_flawed["vendor_name"] = "Different Corp"
    is_correct, matches, mismatches = evaluate_invoice_extraction(extracted_flawed, ground_truth)
    assert is_correct is False
    assert "total" in mismatches
    assert "vendor_name" in mismatches
    assert matches["total"] is False
    assert matches["vendor_name"] is False
    assert matches["invoice_number"] is True


def test_calculate_percentiles():
    # Empty list
    empty_p = calculate_percentiles([], [50, 95])
    assert empty_p["p50"] == 0.0
    assert empty_p["p95"] == 0.0

    # Single item
    single_p = calculate_percentiles([2.5], [50, 95])
    assert single_p["p50"] == 2.5
    assert single_p["p95"] == 2.5

    # 5 items: [1.0, 2.0, 3.0, 4.0, 5.0]
    latencies = [5.0, 1.0, 4.0, 2.0, 3.0]
    p = calculate_percentiles(latencies, [50, 95])
    assert p["p50"] == 3.0
    assert p["p95"] == 4.8


def test_calculate_silent_error_rate():
    # 10 invoices:
    # 4 auto-approved: 3 correct, 1 erroneous (SILENT ERROR)
    # 5 needs_review: 1 correct, 4 erroneous (CAUGHT)
    # 1 failed: 1 erroneous (CAUGHT)
    results = [
        {"id": "inv-1", "status": "auto_approved", "is_correct": True},
        {"id": "inv-2", "status": "auto_approved", "is_correct": True},
        {"id": "inv-3", "status": "auto_approved", "is_correct": True},
        {"id": "inv-4", "status": "auto_approved", "is_correct": False},  # Silent error!
        {"id": "inv-5", "status": "needs_review", "is_correct": False},
        {"id": "inv-6", "status": "needs_review", "is_correct": False},
        {"id": "inv-7", "status": "needs_review", "is_correct": False},
        {"id": "inv-8", "status": "needs_review", "is_correct": False},
        {"id": "inv-9", "status": "needs_review", "is_correct": True},
        {"id": "inv-10", "status": "failed", "is_correct": False},
    ]

    metrics = calculate_silent_error_rate(results)

    # 4 auto_approved, 1 had wrong field -> silent error rate = 1/4 = 25.0%
    assert metrics["auto_approved_count"] == 4
    assert metrics["silent_errors_count"] == 1
    assert metrics["silent_error_rate"] == 25.0

    # Total wrong = 6 (inv-4, 5, 6, 7, 8, 10)
    # Caught by validation (needs_review or failed) = 5
    # Missed by validation (slipped into auto_approved) = 1
    assert metrics["total_wrong_extractions"] == 6
    assert metrics["caught_by_validation"] == 5
    assert metrics["missed_by_validation"] == 1
    assert metrics["catch_rate"] == round(5 / 6 * 100.0, 2)


def test_calculate_repeat_consistency():
    # Invoice 1: identical across 3 runs
    # Invoice 2: run 3 produced a different total
    # Invoice 3: single run (always consistent)
    repeat_data = {
        "inv-01": [
            {"vendor_name": "Acme", "invoice_number": "100", "total": "500"},
            {"vendor_name": "Acme", "invoice_number": "100", "total": "500"},
            {"vendor_name": "Acme", "invoice_number": "100", "total": "500"},
        ],
        "inv-02": [
            {"vendor_name": "Beta", "invoice_number": "200", "total": "600"},
            {"vendor_name": "Beta", "invoice_number": "200", "total": "600"},
            {"vendor_name": "Beta", "invoice_number": "200", "total": "650"},
        ],
        "inv-03": [
            {"vendor_name": "Gamma", "invoice_number": "300", "total": "700"},
        ],
    }

    consistency = calculate_repeat_consistency(repeat_data)
    assert consistency["total_invoices"] == 3
    assert consistency["consistent_invoices"] == 2  # inv-01 and inv-03
    assert consistency["consistency_pct"] == round(2 / 3 * 100.0, 2)
