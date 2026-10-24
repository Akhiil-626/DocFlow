import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.llm import (
    OllamaLLMClient,
    PermanentLLMError,
    TransientLLMError,
)
from app.schemas import InvoiceExtractionSchema, OllamaInvoiceExtractionSchema

SAMPLE_INVOICE_TEXT = "INVOICE #INV-999\nVendor: Acme Global Inc\nTotal: 1180.00\nSubtotal: 1000.00"

VALID_EXTRACTION_JSON = {
    "vendor_name": "Acme Global Inc",
    "vendor_gstin": "27AABCU9603R1ZM",
    "invoice_number": "INV-999",
    "invoice_date": "2026-04-15",
    "currency": "INR",
    "subtotal": "1000.00",
    "cgst": "90.00",
    "sgst": "90.00",
    "igst": "0.00",
    "total": "1180.00",
    "line_items": [
        {
            "description": "Consulting Services",
            "quantity": "1.00",
            "unit_price": "1000.00",
            "amount": "1000.00",
        }
    ],
}


def test_ollama_successful_extraction():
    """Verify standard happy path extraction via Ollama /api/chat with structured output format."""
    client = OllamaLLMClient(
        base_url="http://mock-ollama:11434",
        model_name="llama3.2:3b",
        timeout_seconds=180.0,
        num_ctx=8192,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "llama3.2:3b",
        "message": {
            "role": "assistant",
            "content": json.dumps(VALID_EXTRACTION_JSON),
        },
        "prompt_eval_count": 45,
        "eval_count": 120,
    }

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        data, usage = client.extract_invoice(SAMPLE_INVOICE_TEXT)

    # 1. Verify API was called with required structure
    mock_post.assert_called_once()
    call_args, call_kwargs = mock_post.call_args
    assert call_args[0] == "http://mock-ollama:11434/api/chat"
    assert call_kwargs["timeout"] == 180.0

    payload = call_kwargs["json"]
    assert payload["model"] == "llama3.2:3b"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_ctx"] == 8192
    assert payload["format"] == OllamaInvoiceExtractionSchema.model_json_schema()

    # Safety checks on messages
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert "<invoice_data>" in payload["messages"][1]["content"]
    assert SAMPLE_INVOICE_TEXT in payload["messages"][1]["content"]

    # 2. Verify extracted data
    assert data["vendor_name"] == "Acme Global Inc"
    assert data["invoice_number"] == "INV-999"

    # 3. Verify usage mapping
    assert usage["model"] == "llama3.2:3b"
    assert usage["input_tokens"] == 45
    assert usage["output_tokens"] == 120
    assert usage["repair_retries"] == 0
    assert usage["latency_ms"] >= 0


def test_ollama_invalid_json_then_repair():
    """Verify that an initial invalid JSON output triggers a repair retry and succeeds."""
    client = OllamaLLMClient(
        base_url="http://mock-ollama:11434",
        model_name="llama3.2:3b",
    )

    # 1st call returns malformed/invalid JSON
    resp_invalid = MagicMock()
    resp_invalid.status_code = 200
    resp_invalid.json.return_value = {
        "model": "llama3.2:3b",
        "message": {
            "role": "assistant",
            "content": "Not valid json at all",
        },
        "prompt_eval_count": 30,
        "eval_count": 15,
    }

    # 2nd call (repair) returns valid JSON
    resp_valid = MagicMock()
    resp_valid.status_code = 200
    resp_valid.json.return_value = {
        "model": "llama3.2:3b",
        "message": {
            "role": "assistant",
            "content": json.dumps(VALID_EXTRACTION_JSON),
        },
        "prompt_eval_count": 50,
        "eval_count": 100,
    }

    with patch("httpx.post", side_effect=[resp_invalid, resp_valid]) as mock_post:
        data, usage = client.extract_invoice(SAMPLE_INVOICE_TEXT)

    assert mock_post.call_count == 2
    # Verify second call included validation error in user prompt
    second_payload = mock_post.call_args_list[1][1]["json"]
    second_user_msg = second_payload["messages"][1]["content"]
    assert "Your previous response was invalid" in second_user_msg

    assert data["vendor_name"] == "Acme Global Inc"
    assert usage["repair_retries"] == 1
    assert usage["input_tokens"] == 80  # 30 + 50
    assert usage["output_tokens"] == 115  # 15 + 100


def test_ollama_invalid_json_after_repair_is_permanent():
    """Verify that failing validation twice results in a PermanentLLMError."""
    client = OllamaLLMClient()

    resp_invalid = MagicMock()
    resp_invalid.status_code = 200
    resp_invalid.json.return_value = {
        "message": {"role": "assistant", "content": "Still invalid {{"},
    }

    with patch("httpx.post", return_value=resp_invalid):
        with pytest.raises(PermanentLLMError) as exc_info:
            client.extract_invoice(SAMPLE_INVOICE_TEXT)

    assert "invalid after repair retry" in str(exc_info.value).lower()


def test_ollama_timeout_is_transient():
    """Verify that an HTTP request timeout raises a TransientLLMError."""
    client = OllamaLLMClient(timeout_seconds=180.0)

    with patch("httpx.post", side_effect=httpx.ReadTimeout("Request timed out after 180s")):
        with pytest.raises(TransientLLMError) as exc_info:
            client.extract_invoice(SAMPLE_INVOICE_TEXT)

    assert "timed out" in str(exc_info.value).lower()


def test_ollama_connection_error_is_transient():
    """Verify that connection failure raises a TransientLLMError."""
    client = OllamaLLMClient()

    with patch("httpx.post", side_effect=httpx.ConnectError("Connection refused to Ollama")):
        with pytest.raises(TransientLLMError) as exc_info:
            client.extract_invoice(SAMPLE_INVOICE_TEXT)

    assert "connection error" in str(exc_info.value).lower()


def test_ollama_http_5xx_is_transient():
    """Verify that HTTP 500/503 responses raise a TransientLLMError."""
    client = OllamaLLMClient()

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable: GPU memory full"

    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(TransientLLMError) as exc_info:
            client.extract_invoice(SAMPLE_INVOICE_TEXT)

    assert "server error (http 503)" in str(exc_info.value).lower()


def test_ollama_404_model_not_found_is_permanent():
    """Verify that an HTTP 404 (model not found) raises a PermanentLLMError with instruction to pull."""
    client = OllamaLLMClient(model_name="llama3.2:3b")

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = '{"error":"model \'llama3.2:3b\' not found"}'

    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(PermanentLLMError) as exc_info:
            client.extract_invoice(SAMPLE_INVOICE_TEXT)

    err_msg = str(exc_info.value)
    assert "Model not found: run ollama pull llama3.2:3b" in err_msg


def test_ollama_no_invoice_text_logged(caplog):
    """Verify that invoice text is never logged at any severity level."""
    import logging
    caplog.set_level(logging.DEBUG)

    client = OllamaLLMClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"role": "assistant", "content": json.dumps(VALID_EXTRACTION_JSON)},
        "prompt_eval_count": 10,
        "eval_count": 20,
    }

    secret_invoice = "CONFIDENTIAL_INVOICE_BODY_SECRET_12345"
    with patch("httpx.post", return_value=mock_resp):
        client.extract_invoice(secret_invoice)

    for record in caplog.records:
        assert secret_invoice not in record.message
