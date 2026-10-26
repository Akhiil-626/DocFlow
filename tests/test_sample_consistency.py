"""Test consistency between sample ground truth JSON and generated PDF text.

Extracts text from each sample PDF with pdfplumber and asserts that the truth values
for vendor_name, vendor_gstin (when present), invoice_number, invoice_date, subtotal,
cgst, sgst, igst, total, and each line-item description and amount appear in the text.
Accepts money printed with thousands separators (e.g. 1,000.00 for 1000.00).
On failure, the assertion message names the file and the field.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
SAMPLE_JSON_FILES = sorted(SAMPLES_DIR.glob("*.json"))


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """No-op database setup for sample consistency tests (no DB required)."""
    yield


@pytest.fixture(autouse=True)
def clean_db():
    """No-op database cleanup for sample consistency tests (no DB required)."""
    yield


def get_money_variants(val: Any) -> list[str]:
    """Return standard decimal representation and thousands-separated representation."""
    d = Decimal(str(val))
    return [f"{d:.2f}", f"{d:,.2f}"]


def get_date_variants(date_str: str) -> list[str]:
    """Return supported string representations of the date in the PDF text."""
    variants = [date_str]
    parts = date_str.split("-")
    if len(parts) == 3:
        # DD/MM/YYYY
        variants.append(f"{parts[2]}/{parts[1]}/{parts[0]}")
        # DD-MM-YYYY
        variants.append(f"{parts[2]}-{parts[1]}-{parts[0]}")
    return variants


@pytest.mark.parametrize("json_path", SAMPLE_JSON_FILES, ids=lambda p: p.name)
def test_sample_pdf_and_json_consistency(json_path: Path):
    pdf_path = json_path.with_suffix(".pdf")
    assert pdf_path.exists(), f"{pdf_path.name}: PDF file does not exist"

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    with pdfplumber.open(pdf_path) as pdf:
        pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # 1. vendor_name
    vendor_name = str(data.get("vendor_name") or "")
    assert vendor_name in pdf_text, f"{json_path.name}: vendor_name"

    # 2. vendor_gstin (when present)
    vendor_gstin = data.get("vendor_gstin")
    if vendor_gstin:
        assert str(vendor_gstin) in pdf_text, f"{json_path.name}: vendor_gstin"

    # 3. invoice_number
    invoice_number = str(data.get("invoice_number") or "")
    assert invoice_number in pdf_text, f"{json_path.name}: invoice_number"

    # 4. invoice_date
    invoice_date = str(data.get("invoice_date") or "")
    date_variants = get_date_variants(invoice_date)
    assert any(dv in pdf_text for dv in date_variants), f"{json_path.name}: invoice_date"

    # 5. subtotal, cgst, sgst, igst, total
    for field in ("subtotal", "cgst", "sgst", "igst", "total"):
        val = data.get(field)
        assert val is not None, f"{json_path.name}: {field} missing from JSON"
        money_variants = get_money_variants(val)
        assert any(mv in pdf_text for mv in money_variants), f"{json_path.name}: {field}"

    # 6. line items (each description and amount)
    line_items = data.get("line_items") or []
    for idx, item in enumerate(line_items):
        desc = item.get("description", "")
        assert desc in pdf_text, f"{json_path.name}: line_items[{idx}].description"

        amt = item.get("amount")
        assert amt is not None, f"{json_path.name}: line_items[{idx}].amount missing from JSON"
        amt_variants = get_money_variants(amt)
        assert any(av in pdf_text for av in amt_variants), f"{json_path.name}: line_items[{idx}].amount"
