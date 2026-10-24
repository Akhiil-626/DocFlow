import argparse
from datetime import date
from decimal import Decimal

from scripts.evaluate import (
    FIELDS_TO_EVALUATE,
    format_markdown_report,
    normalize_field_for_debug,
    print_console_summary,
    print_debug_invoice_fields,
)


def test_normalize_field_for_debug():
    # 1. vendor_name (trim and lowercase)
    norm, rule = normalize_field_for_debug("vendor_name", "  Apex Technologies Pvt Ltd  ")
    assert norm == "apex technologies pvt ltd"
    assert "trim" in rule.lower() and "lower" in rule.lower()

    # 2. invoice_date (parsed as date)
    norm_date, rule_date = normalize_field_for_debug("invoice_date", "2026-04-15")
    assert norm_date == date(2026, 4, 15)
    assert "date" in rule_date.lower()

    # Fallback for unparseable date
    norm_bad_date, rule_bad_date = normalize_field_for_debug("invoice_date", "not-a-date")
    assert norm_bad_date == "not-a-date"

    # 3. Money fields (exact Decimal)
    for field in ("subtotal", "cgst", "sgst", "igst", "total"):
        norm_m, rule_m = normalize_field_for_debug(field, " 1180.00 ")
        assert norm_m == Decimal("1180.00")
        assert "decimal" in rule_m.lower()

    # 4. Uppercase fields (trim and uppercase)
    for field in ("vendor_gstin", "invoice_number", "currency"):
        norm_u, rule_u = normalize_field_for_debug(field, "  abc123xyz  ")
        assert norm_u == "ABC123XYZ"
        assert "uppercase" in rule_u.lower()

    # 5. Line items
    items = [
        {"description": "  Widget A ", "quantity": "2", "unit_price": "50.00", "amount": "100.00"}
    ]
    norm_items, rule_items = normalize_field_for_debug("line_items", items)
    assert len(norm_items) == 1
    assert norm_items[0]["description"] == "widget a"
    assert norm_items[0]["quantity"] == Decimal("2")
    assert norm_items[0]["unit_price"] == Decimal("50.00")
    assert norm_items[0]["amount"] == Decimal("100.00")
    assert "line items" in rule_items.lower() or "items" in rule_items.lower()


def test_print_debug_invoice_fields_output(capsys):
    expected_data = {
        "vendor_name": "Apex Technologies Pvt Ltd",
        "vendor_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-001",
        "invoice_date": "2026-04-15",
        "currency": "INR",
        "subtotal": "1000.00",
        "cgst": "90.00",
        "sgst": "90.00",
        "igst": "0.00",
        "total": "1180.00",
        "line_items": [
            {"description": "Widget", "quantity": "1", "unit_price": "1000.00", "amount": "1000.00"}
        ],
    }

    # Actual data with matching fields except total (mismatch)
    actual_data = dict(expected_data)
    actual_data["total"] = "1200.00"

    print_debug_invoice_fields(
        invoice_name="sample_test.pdf",
        invoice_index=1,
        total_debug_invoices=1,
        char_count=450,
        expected_data=expected_data,
        actual_data=actual_data,
        fields=FIELDS_TO_EVALUATE,
    )

    captured = capsys.readouterr().out

    # Verify character count sent to model is printed
    assert "Number of characters of invoice text sent to model: 450" in captured
    assert "sample_test.pdf" in captured

    # Verify every required component is printed for fields
    assert "Field: vendor_name" in captured
    assert "Expected value: 'Apex Technologies Pvt Ltd'" in captured
    assert "Actual value:   'Apex Technologies Pvt Ltd'" in captured
    assert "How expected was normalized: 'apex technologies pvt ltd'" in captured
    assert "How actual was normalized:   'apex technologies pvt ltd'" in captured
    assert "Match or mismatch: MATCH" in captured

    # Verify mismatch is printed for the differing total field
    assert "Field: total" in captured
    assert "Expected value: '1180.00'" in captured
    assert "Actual value:   '1200.00'" in captured
    assert "Decimal('1180.00')" in captured
    assert "Decimal('1200.00')" in captured
    assert "Match or mismatch: MISMATCH" in captured


def test_debug_arg_parsing():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug",
        type=int,
        nargs="?",
        const=1,
        default=0,
        metavar="N",
    )

    # Not supplied -> 0
    args_default = parser.parse_args([])
    assert args_default.debug == 0

    # Supplied without value -> 1
    args_flag = parser.parse_args(["--debug"])
    assert args_flag.debug == 1

    # Supplied with N -> N
    args_n = parser.parse_args(["--debug", "4"])
    assert args_n.debug == 4


def test_markdown_report_never_includes_debug_values():
    eval_results = [
        {
            "model_name": "mock-model",
            "provider": "mock",
            "total_invocations": 1,
            "invoice_accuracy_pct": 100.0,
            "perfect_invoices": 1,
            "auto_approved_pct": 100.0,
            "needs_review_pct": 0.0,
            "failed_pct": 0.0,
            "status_counts": {"auto_approved": 1, "needs_review": 0, "failed": 0, "uploaded": 0},
            "latency_p50": 0.01,
            "latency_p95": 0.01,
            "avg_tokens": 100.0,
            "repair_retries": 0,
            "invalid_output_failures": 0,
            "silent_error_rate": 0.0,
            "silent_errors_count": 0,
            "total_auto_approved": 1,
            "caught_by_validation": 0,
            "missed_by_validation": 0,
            "total_wrong_extractions": 0,
            "catch_rate": 100.0,
            "consistency_pct": 100.0,
            "consistent_invoices": 1,
            "total_unique_invoices": 1,
            "field_accuracies": {f: 100.0 for f in FIELDS_TO_EVALUATE},
            "field_mistakes": {f: 0 for f in FIELDS_TO_EVALUATE},
        }
    ]

    report = format_markdown_report(eval_results, "Test Hardware", 1)
    assert "[DEBUG]" not in report
    assert "Number of characters of invoice text sent to model" not in report
    assert "How expected was normalized" not in report
    assert "How actual was normalized" not in report


def test_per_invoice_table_in_console_and_markdown(capsys):
    eval_results = [
        {
            "model_name": "llama3.2:3b",
            "provider": "ollama",
            "total_invocations": 3,
            "invoice_accuracy_pct": 33.3,
            "perfect_invoices": 1,
            "critical_accuracy_pct": 66.7,
            "perfect_critical_invoices": 2,
            "desc_similarity_pct": 95.0,
            "auto_approved_pct": 66.7,
            "needs_review_pct": 33.3,
            "failed_pct": 0.0,
            "status_counts": {"auto_approved": 2, "needs_review": 1, "failed": 0, "uploaded": 0},
            "latency_p50": 0.5,
            "latency_p95": 1.2,
            "avg_tokens": 150.0,
            "repair_retries": 0,
            "invalid_output_failures": 0,
            "silent_error_rate": 50.0,
            "silent_errors_count": 1,
            "total_auto_approved": 2,
            "caught_by_validation": 1,
            "missed_by_validation": 1,
            "total_wrong_extractions": 2,
            "catch_rate": 50.0,
            "consistency_pct": 100.0,
            "consistent_invoices": 3,
            "total_unique_invoices": 3,
            "field_accuracies": {f: 90.0 for f in FIELDS_TO_EVALUATE},
            "field_mistakes": {f: 0 for f in FIELDS_TO_EVALUATE},
            "invoice_results": [
                {
                    "filename": "invoice_01.pdf",
                    "model": "llama3.2:3b",
                    "status": "auto_approved",
                    "validation_issues": [],
                    "wrong_fields": [],
                    "is_correct": True,
                },
                {
                    "filename": "bad_invoice_01.pdf",
                    "model": "llama3.2:3b",
                    "status": "needs_review",
                    "validation_issues": ["TOTAL_MISMATCH"],
                    "wrong_fields": ["total"],
                    "is_correct": False,
                },
                {
                    "filename": "bad_invoice_02.pdf",
                    "model": "llama3.2:3b",
                    "status": "auto_approved",
                    "validation_issues": [],
                    "wrong_fields": ["subtotal", "cgst"],
                    "is_correct": False,
                },
            ],
        }
    ]

    # 1. Test Markdown report
    report = format_markdown_report(eval_results, "Test Hardware", 1)
    assert "## Per-Invoice Extraction Results" in report
    assert "| File Name | Model | Pipeline Status | Validation Issues | Wrong Fields | Flag |" in report
    assert "invoice_01.pdf" in report
    assert "bad_invoice_01.pdf" in report
    assert "bad_invoice_02.pdf" in report
    assert "TOTAL_MISMATCH" in report
    assert "subtotal, cgst" in report
    # Ensure silent error is flagged
    assert "[FLAG: SILENT ERROR]" in report

    # Ensure never their values:
    for forbidden_val in ("1000.00", "1180.00", "15000.00", "12000.00"):
        assert forbidden_val not in report

    # 2. Test Console summary
    print_console_summary(eval_results, "Test Hardware")
    captured = capsys.readouterr().out
    assert "PER-INVOICE RESULTS" in captured
    assert "File Name" in captured
    assert "Pipeline Status" in captured
    assert "Validation Issues" in captured
    assert "Wrong Fields" in captured
    assert "Flag" in captured
    assert "invoice_01.pdf" in captured
    assert "bad_invoice_01.pdf" in captured
    assert "bad_invoice_02.pdf" in captured
    assert "TOTAL_MISMATCH" in captured
    assert "subtotal, cgst" in captured
    assert "[FLAG: SILENT ERROR]" in captured
