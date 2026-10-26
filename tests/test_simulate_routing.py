"""Unit tests for the DocFlow Model Routing Simulator (scripts/simulate_routing.py).

Tests all 5 routing policies (P1-P5), critical field comparison,
useful vs wasted escalation classification, latency sum, silent error rate,
and markdown table formatting using tiny hand-made fixtures (no DB, no network).
"""

from decimal import Decimal
from typing import Any

import pytest

from scripts.simulate_routing import (
    DEFAULT_ESCALATE_CODES,
    DEFAULT_SKIP_DOCUMENT_CODES,
    format_simulation_table,
    get_critical_fields_diff,
    group_records_by_invoice,
    is_critical_fields_correct,
    is_invoice_all_correct,
    run_simulation,
    simulate_policy,
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """No-op database setup for pure offline simulator tests."""
    yield


@pytest.fixture(autouse=True)
def clean_db():
    """No-op database cleanup for pure offline simulator tests."""
    yield


@pytest.fixture
def sample_ground_truth() -> dict[str, Any]:
    return {
        "vendor_name": "Acme Supplies Ltd",
        "vendor_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-2026-001",
        "invoice_date": "2026-04-15",
        "currency": "INR",
        "subtotal": "1000.00",
        "cgst": "90.00",
        "sgst": "90.00",
        "igst": "0.00",
        "total": "1180.00",
        "line_items": [
            {"description": "Item A", "quantity": "10.00", "unit_price": "50.00", "amount": "500.00"},
            {"description": "Item B", "quantity": "2.00", "unit_price": "250.00", "amount": "500.00"},
        ],
    }


def make_raw_record(
    invoice: str,
    model: str,
    extracted_json: dict[str, Any],
    latency: float,
    status: str,
    validation_issues: list[dict[str, str]],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    return {
        "invoice": invoice,
        "model": model,
        "extracted_json": extracted_json,
        "latency": latency,
        "tokens": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        "validation_issues": validation_issues,
        "pipeline_status": status,
        "ground_truth": ground_truth,
    }


def test_critical_fields_diff_and_correctness(sample_ground_truth):
    """Verify critical field diffing across invoice_number, date, money, and line items."""
    # Identical
    identical = dict(sample_ground_truth)
    assert get_critical_fields_diff(identical, sample_ground_truth) == []
    assert is_critical_fields_correct(identical, sample_ground_truth) is True

    # Differ on total
    diff_total = dict(sample_ground_truth, total="1200.00")
    assert get_critical_fields_diff(diff_total, sample_ground_truth) == ["total"]
    assert is_critical_fields_correct(diff_total, sample_ground_truth) is False

    # Differ on line item amount
    diff_line = dict(
        sample_ground_truth,
        line_items=[
            {"description": "Item A", "quantity": "10.00", "unit_price": "50.00", "amount": "500.00"},
            {"description": "Item B", "quantity": "2.00", "unit_price": "250.00", "amount": "999.00"},
        ],
    )
    assert get_critical_fields_diff(diff_line, sample_ground_truth) == ["line_items"]

    # Non-critical difference (vendor_name, currency) should NOT show in critical fields diff
    diff_non_crit = dict(sample_ground_truth, vendor_name="Wrong Vendor Name", currency="USD")
    assert get_critical_fields_diff(diff_non_crit, sample_ground_truth) == []
    assert is_critical_fields_correct(diff_non_crit, sample_ground_truth) is True
    # But full invoice correctness MUST fail
    assert is_invoice_all_correct(diff_non_crit, sample_ground_truth) is False


def test_policy_p1_small_model_only(sample_ground_truth):
    """P1 must always use small model, never escalate, and record small model latency."""
    small_ext = dict(sample_ground_truth, total="999.00")  # incorrect
    large_ext = dict(sample_ground_truth)  # correct

    records = [
        make_raw_record("inv_1.pdf", "small-model", small_ext, 10.0, "needs_review", [{"code": "TOTAL_MISMATCH", "severity": "error"}], sample_ground_truth),
        make_raw_record("inv_1.pdf", "large-model", large_ext, 30.0, "auto_approved", [], sample_ground_truth),
    ]

    _, _, grouped = group_records_by_invoice(records, "small-model", "large-model")
    res = simulate_policy("P1", grouped, "small-model", "large-model")

    assert res["escalation_pct"] == 0.0
    assert res["useful_escalations"] == 0
    assert res["wasted_escalations"] == 0
    assert res["invoice_accuracy_pct"] == 0.0  # small model was incorrect
    assert res["total_compute_sec"] == 10.0
    assert res["median_latency"] == 10.0


def test_policy_p2_large_model_only(sample_ground_truth):
    """P2 must use large model directly for all invoices, 0% escalation."""
    small_ext = dict(sample_ground_truth, total="999.00")
    large_ext = dict(sample_ground_truth)

    records = [
        make_raw_record("inv_1.pdf", "small-model", small_ext, 10.0, "needs_review", [{"code": "TOTAL_MISMATCH", "severity": "error"}], sample_ground_truth),
        make_raw_record("inv_1.pdf", "large-model", large_ext, 30.0, "auto_approved", [], sample_ground_truth),
    ]

    _, _, grouped = group_records_by_invoice(records, "small-model", "large-model")
    res = simulate_policy("P2", grouped, "small-model", "large-model")

    assert res["escalation_pct"] == 0.0
    assert res["useful_escalations"] == 0
    assert res["wasted_escalations"] == 0
    assert res["invoice_accuracy_pct"] == 100.0
    assert res["total_compute_sec"] == 30.0
    assert res["median_latency"] == 30.0


def test_policy_p3_escalate_on_any_error(sample_ground_truth):
    """P3 must escalate on error-severity issues, but not on warning-severity issues."""
    records = [
        # Invoice 1 has error -> escalates
        make_raw_record("inv_1.pdf", "small-model", dict(sample_ground_truth, total="999.00"), 10.0, "needs_review", [{"code": "TOTAL_MISMATCH", "severity": "error"}], sample_ground_truth),
        make_raw_record("inv_1.pdf", "large-model", dict(sample_ground_truth), 30.0, "auto_approved", [], sample_ground_truth),
        # Invoice 2 has only warning -> does NOT escalate
        make_raw_record("inv_2.pdf", "small-model", dict(sample_ground_truth), 12.0, "needs_review", [{"code": "MISSING_GSTIN", "severity": "warning"}], sample_ground_truth),
        make_raw_record("inv_2.pdf", "large-model", dict(sample_ground_truth), 32.0, "needs_review", [{"code": "MISSING_GSTIN", "severity": "warning"}], sample_ground_truth),
    ]

    _, _, grouped = group_records_by_invoice(records, "small-model", "large-model")
    res = simulate_policy("P3", grouped, "small-model", "large-model")

    assert res["escalation_pct"] == 50.0  # 1 out of 2 escalated
    assert res["useful_escalations"] == 1  # inv_1 total differed and large was correct
    assert res["wasted_escalations"] == 0
    # Inv 1 latency = 10 + 30 = 40; Inv 2 latency = 12. Total compute = 52
    assert res["total_compute_sec"] == 52.0


def test_policy_p4_escalate_codes_and_wasted_escalation(sample_ground_truth):
    """P4 escalates on configured codes. Tests wasted escalation when critical fields are identical."""
    # Bad invoice: document itself has wrong total. Both models extract '999.00' correctly from the page.
    bad_gt = dict(sample_ground_truth, total="999.00")
    bad_ext = dict(sample_ground_truth, total="999.00")

    records = [
        # Both models output identical critical fields -> escalation changed nothing (WASTED)
        make_raw_record("bad_01.pdf", "small-model", bad_ext, 10.0, "needs_review", [{"code": "TOTAL_MISMATCH", "severity": "error"}], bad_gt),
        make_raw_record("bad_01.pdf", "large-model", bad_ext, 30.0, "needs_review", [{"code": "TOTAL_MISMATCH", "severity": "error"}], bad_gt),
        # Invoice with an error code NOT in DEFAULT_ESCALATE_CODES (e.g. TAX_TYPE_CONFLICT) -> does NOT escalate in P4
        make_raw_record("bad_04.pdf", "small-model", bad_ext, 10.0, "needs_review", [{"code": "TAX_TYPE_CONFLICT", "severity": "error"}], bad_gt),
        make_raw_record("bad_04.pdf", "large-model", bad_ext, 30.0, "needs_review", [{"code": "TAX_TYPE_CONFLICT", "severity": "error"}], bad_gt),
    ]

    _, _, grouped = group_records_by_invoice(records, "small-model", "large-model")
    res = simulate_policy("P4", grouped, "small-model", "large-model")

    # Only bad_01 escalated (TOTAL_MISMATCH in default list). bad_04 did not escalate.
    assert res["escalation_pct"] == 50.0
    assert res["useful_escalations"] == 0
    assert res["wasted_escalations"] == 1


def test_policy_p5_skips_document_issues(sample_ground_truth):
    """P5 behaves like P4, but skips escalation for document-level issues like FUTURE_INVOICE_DATE."""
    records = [
        # Document with FUTURE_INVOICE_DATE -> P5 skips escalation even if configured
        make_raw_record("doc_future.pdf", "small-model", sample_ground_truth, 10.0, "needs_review", [{"code": "FUTURE_INVOICE_DATE", "severity": "error"}], sample_ground_truth),
        make_raw_record("doc_future.pdf", "large-model", sample_ground_truth, 30.0, "needs_review", [{"code": "FUTURE_INVOICE_DATE", "severity": "error"}], sample_ground_truth),
        # Document with TOTAL_MISMATCH (extraction issue) -> escalates
        make_raw_record("inv_calc.pdf", "small-model", dict(sample_ground_truth, total="100.00"), 10.0, "needs_review", [{"code": "TOTAL_MISMATCH", "severity": "error"}], sample_ground_truth),
        make_raw_record("inv_calc.pdf", "large-model", sample_ground_truth, 30.0, "auto_approved", [], sample_ground_truth),
        # Document with BOTH TOTAL_MISMATCH and DUPLICATE_SUSPECTED -> P5 skips escalation because document is duplicate
        make_raw_record("doc_dup.pdf", "small-model", dict(sample_ground_truth, total="100.00"), 10.0, "needs_review", [{"code": "TOTAL_MISMATCH", "severity": "error"}, {"code": "DUPLICATE_SUSPECTED", "severity": "warning"}], sample_ground_truth),
        make_raw_record("doc_dup.pdf", "large-model", sample_ground_truth, 30.0, "needs_review", [{"code": "DUPLICATE_SUSPECTED", "severity": "warning"}], sample_ground_truth),
    ]

    _, _, grouped = group_records_by_invoice(records, "small-model", "large-model")
    res = simulate_policy("P5", grouped, "small-model", "large-model")

    # Only inv_calc.pdf escalates!
    assert res["escalation_pct"] == round(1 / 3 * 100.0, 1)
    assert res["useful_escalations"] == 1
    assert res["wasted_escalations"] == 0


def test_silent_error_rate_calculation(sample_ground_truth):
    """Verify silent error rate metric: wrong extraction auto-approved by pipeline."""
    wrong_ext = dict(sample_ground_truth, invoice_date="2020-01-01")  # wrong date, but no validation caught it

    records = [
        # Invoice 1: auto-approved but wrong extraction (silent error!)
        make_raw_record("inv_01.pdf", "small-model", wrong_ext, 10.0, "auto_approved", [], sample_ground_truth),
        make_raw_record("inv_01.pdf", "large-model", wrong_ext, 30.0, "auto_approved", [], sample_ground_truth),
        # Invoice 2: auto-approved and correct
        make_raw_record("inv_02.pdf", "small-model", sample_ground_truth, 10.0, "auto_approved", [], sample_ground_truth),
        make_raw_record("inv_02.pdf", "large-model", sample_ground_truth, 30.0, "auto_approved", [], sample_ground_truth),
    ]

    _, _, grouped = group_records_by_invoice(records, "small-model", "large-model")
    res = simulate_policy("P1", grouped, "small-model", "large-model")

    # 2 auto-approved, 1 has error -> 50.0% silent error rate
    assert res["auto_approved_pct"] == 100.0
    assert res["silent_error_rate_pct"] == 50.0


def test_run_simulation_and_table_format(tmp_path, sample_ground_truth):
    """End-to-end test of run_simulation reading from JSON file and generating table."""
    records = [
        make_raw_record("inv_01.pdf", "small-model", sample_ground_truth, 15.0, "auto_approved", [], sample_ground_truth),
        make_raw_record("inv_01.pdf", "large-model", sample_ground_truth, 40.0, "auto_approved", [], sample_ground_truth),
    ]

    raw_file = tmp_path / "raw_eval.json"
    import json
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump({"records": records}, f)

    out_md = tmp_path / "routing_simulation.md"
    results = run_simulation(
        raw_file_path=raw_file,
        small_model="small-model",
        large_model="large-model",
        output_markdown_path=out_md,
    )

    assert len(results) == 5
    policies = [r["policy"] for r in results]
    assert policies == ["P1", "P2", "P3", "P4", "P5"]

    # Verify table file was written
    assert out_md.exists()
    content = out_md.read_text(encoding="utf-8").strip()
    # Must contain the markdown table and no other commentary
    lines = content.splitlines()
    assert lines[0].startswith("| Policy |")
    assert "P1: Small model only" in content
    assert "P5: P4 + skip document issues" in content
