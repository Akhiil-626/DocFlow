import json
import sys
from decimal import Decimal
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber

from app.llm import get_llm_client

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


def run_benchmark():
    client = get_llm_client()
    print(f"=== DocFlow Extraction Benchmark (Provider: {type(client).__name__}) ===")

    pdf_files = sorted(SAMPLES_DIR.glob("*.pdf"))
    if not pdf_files:
        print("No sample PDFs found.")
        return

    fields = [
        "vendor_name",
        "vendor_gstin",
        "invoice_number",
        "invoice_date",
        "currency",
        "subtotal",
        "cgst",
        "sgst",
        "igst",
        "total",
        "line_items_count",
    ]
    field_matches = {f: 0 for f in fields}
    total_samples = len(pdf_files)

    for pdf_path in pdf_files:
        json_path = pdf_path.with_suffix(".json")
        if not json_path.exists():
            continue

        with open(json_path, encoding="utf-8") as f:
            ground_truth = json.load(f)

        # Extract text using pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        # For MockLLMClient, mock returns a sample invoice or we can adapt for testing
        try:
            result, usage = client.extract_invoice(text)
            extracted_dict = result
        except Exception as e:
            print(f"[{pdf_path.name}] Extraction failed: {e}")
            continue

        print(f"\n--- {pdf_path.name} ---")
        print(f"Model: {usage.get('model')} | Latency: {usage.get('latency_ms')}ms")

        # Compare fields
        for field in fields:
            if field == "line_items_count":
                gt_val = len(ground_truth.get("line_items", []))
                ex_val = len(extracted_dict.get("line_items", []))
                matched = (gt_val == ex_val)
            elif field in ["subtotal", "cgst", "sgst", "igst", "total"]:
                gt_val = Decimal(str(ground_truth.get(field, 0) or 0))
                ex_val = Decimal(str(extracted_dict.get(field, 0) or 0))
                matched = (gt_val == ex_val)
            else:
                gt_val = str(ground_truth.get(field) or "").strip()
                ex_val = str(extracted_dict.get(field) or "").strip()
                matched = (gt_val.lower() == ex_val.lower())

            if matched:
                field_matches[field] += 1
            status = "MATCH" if matched else f"MISMATCH (GT: {gt_val} vs EXTRACTED: {ex_val})"
            print(f"  {field:18}: {status}")

    print("\n" + "=" * 50)
    print("ACCURACY SUMMARY")
    print("=" * 50)
    for field in fields:
        rate = (field_matches[field] / total_samples) * 100
        print(f"{field:20}: {field_matches[field]}/{total_samples} ({rate:.1f}%)")
    print("=" * 50)


if __name__ == "__main__":
    run_benchmark()
