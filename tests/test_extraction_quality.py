import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.llm import (
    OllamaLLMClient,
    PermanentLLMError,
    clean_money_string,
    parse_and_validate_json,
)
from app.schemas import (
    InvoiceExtractionSchema,
    OllamaInvoiceExtractionSchema,
)
from scripts.evaluate import (
    CRITICAL_FIELDS,
    FIELDS_TO_EVALUATE,
    calculate_line_item_description_similarity,
    compare_field_for_evaluation,
    compare_line_items_numeric,
    evaluate_invoice_for_eval,
    print_console_summary,
)


# ---------------- 1. clean_money_string tests ----------------
def test_clean_money_string_valid_groupings_and_symbols():
    # Indian grouping
    assert clean_money_string("1,23,456.00") == "123456.00"
    assert clean_money_string("12,34,567.89") == "1234567.89"
    assert clean_money_string("10,00,000") == "1000000"

    # Standard grouping
    assert clean_money_string("1,234,567.89") == "1234567.89"
    assert clean_money_string("1,000.00") == "1000.00"
    assert clean_money_string("17,700.00") == "17700.00"

    # Currency symbols
    assert clean_money_string("₹ 1,23,456.00") == "123456.00"
    assert clean_money_string("₹1,23,456.00") == "123456.00"
    assert clean_money_string("$ 1,234.56") == "1234.56"
    assert clean_money_string("€ 500.00") == "500.00"
    assert clean_money_string("£ 99.99") == "99.99"
    assert clean_money_string("¥ 1000") == "1000"

    # Text prefixes / abbreviations
    assert clean_money_string("Rs. 50,000.50") == "50000.50"
    assert clean_money_string("Rs 50,000.50") == "50000.50"
    assert clean_money_string("INR 10,00,000") == "1000000"
    assert clean_money_string("USD 1,234.56") == "1234.56"

    # Whitespace and signs
    assert clean_money_string("   1234.56   ") == "1234.56"
    assert clean_money_string(" 0.00 ") == "0.00"
    assert clean_money_string("0") == "0"
    assert clean_money_string("-1,000.00") == "-1000.00"

    # Numeric inputs
    assert clean_money_string(Decimal("100.50")) == "100.50"
    assert clean_money_string(500) == "500"
    assert clean_money_string(45.5) == "45.5"


def test_clean_money_string_unparsable_fails_visibly_never_zero():
    unparsable_inputs = [
        "invalid",
        "abc",
        "₹",
        "",
        None,
        "12.34.56",
        "N/A",
        "--",
        "1,23,456..00",
        "   ",
        "Rs.",
        "$$$",
    ]
    for bad in unparsable_inputs:
        with pytest.raises(ValueError):
            clean_money_string(bad)


# ---------------- 2. parse_and_validate_json with clean_money_string ----------------
def test_parse_and_validate_json_cleans_dirty_money_strings():
    raw_output = """
    {
        "vendor_name": "Orion Hardware Foundry",
        "vendor_gstin": "07AQZPD4321K1Z8",
        "invoice_number": "OHF-101",
        "invoice_date": "2025-11-20",
        "currency": "INR",
        "subtotal": "₹ 1,23,456.00",
        "cgst": "Rs. 11,111.04",
        "sgst": "11,111.04",
        "igst": "0.00",
        "total": "INR 1,45,678.08",
        "line_items": [
            {
                "description": "Ergonomic Chairs",
                "quantity": "10.00",
                "unit_price": "₹ 12,345.60",
                "amount": "1,23,456.00"
            }
        ]
    }
    """
    data = parse_and_validate_json(raw_output)
    assert data["subtotal"] == 123456.00 or data["subtotal"] == "123456.00"
    assert data["cgst"] == 11111.04 or data["cgst"] == "11111.04"
    assert data["total"] == 145678.08 or data["total"] == "145678.08"
    assert data["line_items"][0]["unit_price"] == 12345.60 or data["line_items"][0]["unit_price"] == "12345.60"


def test_parse_and_validate_json_missing_required_key_fails_visibly():
    # missing subtotal key
    raw_missing_key = """
    {
        "vendor_name": "Orion Hardware Foundry",
        "vendor_gstin": "07AQZPD4321K1Z8",
        "invoice_number": "OHF-101",
        "invoice_date": "2025-11-20",
        "currency": "INR",
        "cgst": "0.00",
        "sgst": "0.00",
        "igst": "0.00",
        "total": "1000.00",
        "line_items": []
    }
    """
    with pytest.raises(ValueError) as excinfo:
        parse_and_validate_json(raw_missing_key)
    assert "Missing required extraction keys" in str(excinfo.value)
    assert "subtotal" in str(excinfo.value)


def test_parse_and_validate_json_unparsable_fails_visibly():
    raw_bad_output = """
    {
        "vendor_name": "Orion Hardware Foundry",
        "vendor_gstin": "07AQZPD4321K1Z8",
        "invoice_number": "OHF-101",
        "invoice_date": "2025-11-20",
        "currency": "INR",
        "subtotal": "unparsable_money",
        "cgst": "0.00",
        "sgst": "0.00",
        "igst": "0.00",
        "total": "1000.00",
        "line_items": []
    }
    """
    with pytest.raises(ValueError) as excinfo:
        parse_and_validate_json(raw_bad_output)
    assert "Unparsable monetary value" in str(excinfo.value)


# ---------------- 3. Dedicated Ollama Schema Requirements ----------------
def test_ollama_dedicated_schema_properties():
    schema = OllamaInvoiceExtractionSchema.model_json_schema()
    required = schema.get("required", [])

    # subtotal, cgst, sgst, igst, total and vendor_gstin are REQUIRED keys
    for req_key in ["subtotal", "cgst", "sgst", "igst", "total", "vendor_gstin"]:
        assert req_key in required, f"{req_key} must be in required schema fields"

    # vendor_gstin may be null (anyOf string or null)
    gstin_prop = schema["properties"]["vendor_gstin"]
    assert "anyOf" in gstin_prop or gstin_prop.get("type") == "string"
    if "anyOf" in gstin_prop:
        types = [item.get("type") for item in gstin_prop["anyOf"]]
        assert "string" in types and "null" in types

    # Check descriptions seen by the model
    subtotal_desc = schema["properties"]["subtotal"]["description"]
    assert "amount before tax" in subtotal_desc.lower()
    assert "no thousands separators" in subtotal_desc.lower()

    cgst_desc = schema["properties"]["cgst"]["description"]
    assert "tax amounts exactly as printed" in cgst_desc.lower()
    assert "0.00" in cgst_desc

    vendor_gstin_desc = schema["properties"]["vendor_gstin"]["description"]
    assert "15-character gst number" in vendor_gstin_desc.lower()

    # Stored schema (InvoiceExtractionSchema) must be unchanged
    stored_schema = InvoiceExtractionSchema.model_json_schema()
    assert "subtotal" not in stored_schema.get("required", [])


# ---------------- 4. Mocked HTTP Layer Repair Tests ----------------
def test_ollama_missing_required_key_triggers_repair():
    """Verify that a missing required key (e.g. subtotal) triggers the repair retry path."""
    client = OllamaLLMClient(base_url="http://mock-ollama:11434", model_name="llama3.2:3b")

    resp_missing_subtotal = MagicMock()
    resp_missing_subtotal.status_code = 200
    resp_missing_subtotal.json.return_value = {
        "message": {
            "role": "assistant",
            "content": json.dumps({
                "vendor_name": "Orion Hardware Foundry",
                "vendor_gstin": "07AQZPD4321K1Z8",
                "invoice_number": "OHF-8823",
                "invoice_date": "2024-08-14",
                "currency": "INR",
                "cgst": "396.90",
                "sgst": "396.90",
                "igst": "0.00",
                "total": "5203.80",
                "line_items": [],
            }),
        },
    }

    resp_valid_repair = MagicMock()
    resp_valid_repair.status_code = 200
    resp_valid_repair.json.return_value = {
        "message": {
            "role": "assistant",
            "content": json.dumps({
                "vendor_name": "Orion Hardware Foundry",
                "vendor_gstin": "07AQZPD4321K1Z8",
                "invoice_number": "OHF-8823",
                "invoice_date": "2024-08-14",
                "currency": "INR",
                "subtotal": "4410.00",
                "cgst": "396.90",
                "sgst": "396.90",
                "igst": "0.00",
                "total": "5203.80",
                "line_items": [],
            }),
        },
    }

    with patch("httpx.post", side_effect=[resp_missing_subtotal, resp_valid_repair]) as mock_post:
        data, usage = client.extract_invoice("Invoice text...")

    assert mock_post.call_count == 2
    assert usage["repair_retries"] == 1
    assert data["subtotal"] == 4410.00 or data["subtotal"] == "4410.00"


def test_ollama_unparsable_money_fails_visibly_after_repair():
    """Verify that unparsable money triggers repair and raises PermanentLLMError if still invalid."""
    client = OllamaLLMClient(base_url="http://mock-ollama:11434", model_name="llama3.2:3b")

    resp_bad_money = MagicMock()
    resp_bad_money.status_code = 200
    resp_bad_money.json.return_value = {
        "message": {
            "role": "assistant",
            "content": json.dumps({
                "vendor_name": "Orion Hardware Foundry",
                "vendor_gstin": "07AQZPD4321K1Z8",
                "invoice_number": "OHF-8823",
                "invoice_date": "2024-08-14",
                "currency": "INR",
                "subtotal": "NOT_A_NUMBER",
                "cgst": "396.90",
                "sgst": "396.90",
                "igst": "0.00",
                "total": "5203.80",
                "line_items": [],
            }),
        },
    }

    with patch("httpx.post", side_effect=[resp_bad_money, resp_bad_money]) as mock_post:
        with pytest.raises(PermanentLLMError) as exc_info:
            client.extract_invoice("Invoice text...")

    assert mock_post.call_count == 2
    assert "Unparsable monetary value" in str(exc_info.value)


# ---------------- 5. Line items numeric comparison & description similarity ----------------
def test_line_items_comparison_and_description_similarity():
    gt_items = [
        {"description": "2 Developer Workstations at 5000 each", "quantity": "2.00", "unit_price": "5000.00", "amount": "10000.00"}
    ]
    # Numbers match, description phrased differently
    ex_items_similar_desc = [
        {"description": "Developer Workstations", "quantity": "2.00", "unit_price": "5000.00", "amount": "10000.00"}
    ]
    # Numbers mismatch
    ex_items_bad_amount = [
        {"description": "2 Developer Workstations at 5000 each", "quantity": "2.00", "unit_price": "5000.00", "amount": "9999.00"}
    ]

    # Numeric comparison matches even if description differs
    assert compare_line_items_numeric(ex_items_similar_desc, gt_items) is True
    # Field comparison using compare_field_for_evaluation
    assert compare_field_for_evaluation("line_items", ex_items_similar_desc, gt_items) is True
    # Numeric mismatch fails
    assert compare_line_items_numeric(ex_items_bad_amount, gt_items) is False
    assert compare_field_for_evaluation("line_items", ex_items_bad_amount, gt_items) is False

    # Looser description similarity metric
    sim = calculate_line_item_description_similarity(ex_items_similar_desc, gt_items)
    assert 60.0 <= sim <= 100.0


# ---------------- 6. Critical-fields accuracy metric ----------------
def test_critical_fields_accuracy_metric():
    gt = {
        "vendor_name": "Calculus Glitch Labs",
        "vendor_gstin": "29AABCU9603R1ZM",
        "invoice_number": "BAD-TOTAL-001",
        "invoice_date": "2026-03-01",
        "currency": "INR",
        "subtotal": "10000.00",
        "cgst": "900.00",
        "sgst": "900.00",
        "igst": "0.00",
        "total": "15000.00",
        "line_items": [
            {"description": "Server Maintenance Contract", "quantity": "1.00", "unit_price": "10000.00", "amount": "10000.00"}
        ],
    }

    # Differ only in vendor_name (vendor_name is NOT in critical fields)
    extracted = dict(gt)
    extracted["vendor_name"] = "Different Vendor Name LLC"

    is_all_correct, field_matches, mismatches = evaluate_invoice_for_eval(extracted, gt)
    assert is_all_correct is False
    assert field_matches["vendor_name"] is False

    # All critical fields must match
    is_critical_correct = all(field_matches.get(f, False) for f in CRITICAL_FIELDS)
    assert is_critical_correct is True


# ---------------- 7. Console Summary Output ----------------
def test_console_summary_prints_per_field_and_critical_accuracy(capsys):
    dummy_results = [
        {
            "model_name": "test-model",
            "provider": "mock",
            "total_invocations": 10,
            "invoice_accuracy_pct": 90.0,
            "perfect_invoices": 9,
            "critical_accuracy_pct": 100.0,
            "perfect_critical_invoices": 10,
            "desc_similarity_pct": 98.5,
            "auto_approved_pct": 80.0,
            "needs_review_pct": 20.0,
            "failed_pct": 0.0,
            "status_counts": {"auto_approved": 8, "needs_review": 2, "failed": 0, "uploaded": 0},
            "latency_p50": 0.05,
            "latency_p95": 0.10,
            "avg_tokens": 200.0,
            "repair_retries": 0,
            "invalid_output_failures": 0,
            "silent_error_rate": 0.0,
            "silent_errors_count": 0,
            "total_auto_approved": 8,
            "caught_by_validation": 1,
            "missed_by_validation": 0,
            "total_wrong_extractions": 1,
            "catch_rate": 100.0,
            "consistency_pct": 100.0,
            "consistent_invoices": 10,
            "total_unique_invoices": 10,
            "field_accuracies": {f: 100.0 for f in FIELDS_TO_EVALUATE},
            "field_mistakes": {f: 0 for f in FIELDS_TO_EVALUATE},
        }
    ]

    print_console_summary(dummy_results, "Test Hardware Specification")
    captured = capsys.readouterr().out

    assert "Critical-Fields Accuracy" in captured
    assert "Line Item Description Similarity" in captured
    assert "PER-FIELD EXTRACTION ACCURACY" in captured
    for f in FIELDS_TO_EVALUATE:
        assert f in captured
