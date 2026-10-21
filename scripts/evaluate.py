"""DocFlow Multi-Model Evaluation Script (Week 5A).

Evaluates invoice extraction pipeline against ground truth across multiple local models
(e.g., through Ollama) or mock/cloud providers.

Measures:
- Field-level accuracy (money as Decimal, dates as dates, vendor name with trim and case only)
- Invoice-level accuracy (all fields correct)
- Pipeline routing percentages (auto_approved vs needs_review vs failed)
- Latency (median p50 and p95 in seconds)
- Average tokens per invoice
- Number of repair retries used
- Invalid-output failures
- Honesty metrics: Silent Error Rate on auto-approved invoices, caught vs missed breakdown
- Consistency across repeat runs (--repeat N)
"""

import argparse
import hashlib
import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.evaluation_metrics import (
    calculate_percentiles,
    calculate_repeat_consistency,
    calculate_silent_error_rate,
    evaluate_invoice_extraction,
)
from app.llm import LLMClient, MockLLMClient, OllamaLLMClient
from app.models import Document, Extraction, Organization, User
from app.security import hash_password
from app.storage import LocalStorage
from app.worker.tasks import process_document

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("evaluate")

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
DEFAULT_RESULTS_FILE = Path(__file__).resolve().parent.parent / "evaluation_results.md"

FIELDS_TO_EVALUATE = [
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
    "line_items",
]


def load_sample_dataset() -> list[tuple[Path, dict[str, Any]]]:
    """Load sample PDF paths and their corresponding ground truth JSON files."""
    pdf_files = sorted(SAMPLES_DIR.glob("*.pdf"))
    dataset = []
    for pdf_path in pdf_files:
        json_path = pdf_path.with_suffix(".json")
        if not json_path.exists():
            continue
        try:
            with open(json_path, encoding="utf-8") as f:
                gt = json.load(f)
            dataset.append((pdf_path, gt))
        except Exception as e:
            logger.warning("Could not read %s: %e", json_path, e)
    return dataset


def create_client(provider: str, model_name: str, base_url: str | None, timeout: float | None, num_ctx: int | None) -> LLMClient:
    """Create appropriate LLM client instance for evaluation."""
    provider_clean = provider.lower().strip()
    if provider_clean == "ollama":
        return OllamaLLMClient(
            base_url=base_url or settings.OLLAMA_BASE_URL,
            model_name=model_name,
            timeout_seconds=timeout or settings.OLLAMA_TIMEOUT_SECONDS,
            num_ctx=num_ctx or settings.OLLAMA_NUM_CTX,
        )
    if provider_clean == "mock":
        return MockLLMClient(model_name=model_name)
    raise ValueError(f"Unsupported evaluation provider: {provider}")


def evaluate_single_model(
    model_name: str,
    provider: str,
    dataset: list[tuple[Path, dict[str, Any]]],
    repeat: int,
    base_url: str | None,
    timeout: float | None,
    num_ctx: int | None,
) -> dict[str, Any]:
    """Run evaluation for a single model across repeat runs inside an isolated organization."""
    db: Session = SessionLocal()
    storage = LocalStorage(settings.UPLOAD_DIR)

    # 1. Create dedicated isolated test organization
    eval_org_id = uuid.uuid4()
    test_org = Organization(id=eval_org_id, name=f"EvalOrg-{uuid.uuid4().hex[:8]}")
    db.add(test_org)

    test_user = User(
        id=uuid.uuid4(),
        org_id=eval_org_id,
        email=f"eval_{uuid.uuid4().hex[:8]}@docflow-eval.test",
        password_hash=hash_password("eval_test_password"),
        role="admin",
        is_active=True,
    )
    db.add(test_user)
    db.commit()

    created_storage_keys: list[str] = []
    client = create_client(provider, model_name, base_url, timeout, num_ctx)

    # Tracking containers
    invoice_repeat_runs: dict[str, list[dict[str, Any]]] = {}
    all_run_results: list[dict[str, Any]] = []
    field_match_counts: dict[str, int] = {f: 0 for f in FIELDS_TO_EVALUATE}
    field_total_evals: dict[str, int] = {f: 0 for f in FIELDS_TO_EVALUATE}
    field_mistake_counts: dict[str, int] = {f: 0 for f in FIELDS_TO_EVALUATE}
    latencies_sec: list[float] = []
    token_counts: list[int] = []
    repair_retries_total = 0
    invalid_output_failures = 0
    status_counts = {"auto_approved": 0, "needs_review": 0, "failed": 0, "uploaded": 0}
    perfect_invoice_count = 0
    total_eval_invocations = 0

    try:
        for run_idx in range(1, repeat + 1):
            if repeat > 1:
                print(f"  -> Model {model_name}: Running repetition {run_idx}/{repeat}...")

            for pdf_path, ground_truth in dataset:
                total_eval_invocations += 1
                pdf_name = pdf_path.name
                if pdf_name not in invoice_repeat_runs:
                    invoice_repeat_runs[pdf_name] = []

                # Read and save PDF in isolated org storage
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

                doc_id = uuid.uuid4()
                storage_key = f"{eval_org_id}/{doc_id}.pdf"
                created_storage_keys.append(storage_key)
                storage.save(storage_key, pdf_bytes)
                sha256 = hashlib.sha256(pdf_bytes).hexdigest()

                doc = Document(
                    id=doc_id,
                    org_id=eval_org_id,
                    uploaded_by=test_user.id,
                    original_filename=pdf_name,
                    content_type="application/pdf",
                    size_bytes=len(pdf_bytes),
                    sha256=sha256,
                    storage_key=storage_key,
                    status="uploaded",
                )
                db.add(doc)
                db.commit()

                # Execute pipeline task
                start_t = time.time()
                try:
                    process_document(
                        str(doc_id),
                        override_llm_client=client,
                        override_storage=storage,
                        override_db=db,
                    )
                except Exception as task_err:
                    logger.error("Error executing task for %s: %s", pdf_name, task_err)

                wall_latency_sec = round(time.time() - start_t, 3)

                db.refresh(doc)
                status_counts[doc.status] = status_counts.get(doc.status, 0) + 1

                extraction = db.query(Extraction).filter(Extraction.document_id == doc_id).first()

                if doc.status == "failed" or not extraction:
                    invalid_output_failures += 1
                    latencies_sec.append(wall_latency_sec)
                    all_run_results.append({
                        "filename": pdf_name,
                        "status": doc.status,
                        "is_correct": False,
                        "latency_sec": wall_latency_sec,
                    })
                    invoice_repeat_runs[pdf_name].append({})
                    continue

                extracted_data = extraction.data or {}
                invoice_repeat_runs[pdf_name].append(extracted_data)

                # Latency & tokens
                latency_s = round((extraction.latency_ms or (wall_latency_sec * 1000)) / 1000.0, 3)
                latencies_sec.append(latency_s)
                total_tokens = (extraction.input_tokens or 0) + (extraction.output_tokens or 0)
                token_counts.append(total_tokens)

                # Check if repair retry was used
                orig_data = extraction.original_data or {}
                # If extraction recorded repair_retries or model output invalid initially
                if extraction.version > 1 or getattr(extraction, "attempts", 1) > 1:
                    repair_retries_total += 1

                # Evaluate field extraction accuracy against ground truth
                is_all_correct, field_matches, mismatches = evaluate_invoice_extraction(
                    extracted_data, ground_truth, FIELDS_TO_EVALUATE
                )

                if is_all_correct:
                    perfect_invoice_count += 1

                for field in FIELDS_TO_EVALUATE:
                    field_total_evals[field] += 1
                    if field_matches.get(field, False):
                        field_match_counts[field] += 1
                    else:
                        field_mistake_counts[field] += 1

                all_run_results.append({
                    "filename": pdf_name,
                    "status": doc.status,
                    "is_correct": is_all_correct,
                    "latency_sec": latency_s,
                    "mismatches": mismatches,
                })

    finally:
        # Guaranteed cleanup of isolated test data
        for skey in created_storage_keys:
            try:
                storage.delete(skey)
            except Exception:
                pass
        try:
            db.delete(test_org)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    # Aggregate metric calculations
    percentiles = calculate_percentiles(latencies_sec, [50, 95])
    silent_metrics = calculate_silent_error_rate(all_run_results)
    consistency_metrics = calculate_repeat_consistency(invoice_repeat_runs)

    invoice_accuracy_pct = (
        (perfect_invoice_count / total_eval_invocations * 100.0)
        if total_eval_invocations > 0
        else 0.0
    )

    auto_app_pct = (
        (status_counts["auto_approved"] / total_eval_invocations * 100.0)
        if total_eval_invocations > 0
        else 0.0
    )
    needs_rev_pct = (
        (status_counts["needs_review"] / total_eval_invocations * 100.0)
        if total_eval_invocations > 0
        else 0.0
    )
    failed_pct = (
        (status_counts["failed"] / total_eval_invocations * 100.0)
        if total_eval_invocations > 0
        else 0.0
    )

    avg_tokens = (
        round(sum(token_counts) / len(token_counts), 1)
        if token_counts
        else 0.0
    )

    # Field accuracies
    field_accuracy_pct = {}
    for f in FIELDS_TO_EVALUATE:
        tot = field_total_evals[f]
        field_accuracy_pct[f] = round((field_match_counts[f] / tot * 100.0), 1) if tot > 0 else 0.0

    return {
        "model_name": model_name,
        "provider": provider,
        "total_invocations": total_eval_invocations,
        "invoice_accuracy_pct": round(invoice_accuracy_pct, 1),
        "perfect_invoices": perfect_invoice_count,
        "auto_approved_pct": round(auto_app_pct, 1),
        "needs_review_pct": round(needs_rev_pct, 1),
        "failed_pct": round(failed_pct, 1),
        "status_counts": status_counts,
        "latency_p50": percentiles["p50"],
        "latency_p95": percentiles["p95"],
        "avg_tokens": avg_tokens,
        "repair_retries": repair_retries_total,
        "invalid_output_failures": invalid_output_failures,
        "silent_error_rate": silent_metrics["silent_error_rate"],
        "silent_errors_count": silent_metrics["silent_errors_count"],
        "total_auto_approved": silent_metrics["auto_approved_count"],
        "caught_by_validation": silent_metrics["caught_by_validation"],
        "missed_by_validation": silent_metrics["missed_by_validation"],
        "total_wrong_extractions": silent_metrics["total_wrong_extractions"],
        "catch_rate": silent_metrics["catch_rate"],
        "consistency_pct": consistency_metrics["consistency_pct"],
        "consistent_invoices": consistency_metrics["consistent_invoices"],
        "total_unique_invoices": consistency_metrics["total_invoices"],
        "field_accuracies": field_accuracy_pct,
        "field_mistakes": field_mistake_counts,
    }


def format_markdown_report(
    eval_results: list[dict[str, Any]],
    hardware_note: str,
    repeat: int,
) -> str:
    """Format full evaluation markdown report without containing any invoice text."""
    date_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    model_names_str = ", ".join(f"`{r['model_name']}`" for r in eval_results)

    lines = [
        "# DocFlow Local Model Pipeline Evaluation (Week 5A)",
        "",
        f"- **Date**: {date_str}",
        f"- **Models Evaluated**: {model_names_str}",
        f"- **Hardware Specification**: {hardware_note}",
        f"- **Repetitions per Invoice**: {repeat}",
        "",
        "## Model Comparison Matrix",
        "",
        "| Metric | " + " | ".join(f"**{r['model_name']}**" for r in eval_results) + " |",
        "| :--- | " + " | ".join(":---:" for _ in eval_results) + " |",
        "| **Invoice Accuracy (All Fields Correct)** | " + " | ".join(f"{r['invoice_accuracy_pct']}% ({r['perfect_invoices']}/{r['total_invocations']})" for r in eval_results) + " |",
        "| **Silent Error Rate (Wrong in Auto-Approved)** | " + " | ".join(f"**{r['silent_error_rate']}%** ({r['silent_errors_count']}/{r['total_auto_approved']})" for r in eval_results) + " |",
        "| **Validation Catch Rate (Caught / Total Wrong)** | " + " | ".join(f"{r['catch_rate']}% ({r['caught_by_validation']}/{r['total_wrong_extractions']})" for r in eval_results) + " |",
        "| **Pipeline Routing (Auto / Review / Fail)** | " + " | ".join(f"{r['auto_approved_pct']}% / {r['needs_review_pct']}% / {r['failed_pct']}%" for r in eval_results) + " |",
        "| **Latency (Median p50 / p95)** | " + " | ".join(f"{r['latency_p50']}s / {r['latency_p95']}s" for r in eval_results) + " |",
        "| **Avg Tokens / Invoice** | " + " | ".join(f"{r['avg_tokens']}" for r in eval_results) + " |",
        "| **Repair Retries Used** | " + " | ".join(f"{r['repair_retries']}" for r in eval_results) + " |",
        "| **Invalid Output Failures** | " + " | ".join(f"{r['invalid_output_failures']}" for r in eval_results) + " |",
        "| **Consistency across Repeats** | " + " | ".join(f"{r['consistency_pct']}% ({r['consistent_invoices']}/{r['total_unique_invoices']})" for r in eval_results) + " |",
        "",
        "---",
        "",
        "## Field-by-Field Extraction Accuracy",
        "",
        "| Field | " + " | ".join(f"**{r['model_name']}**" for r in eval_results) + " |",
        "| :--- | " + " | ".join(":---:" for _ in eval_results) + " |",
    ]

    for field in FIELDS_TO_EVALUATE:
        row = f"| `{field}` | " + " | ".join(f"{r['field_accuracies'].get(field, 0.0)}%" for r in eval_results) + " |"
        lines.append(row)

    lines.extend([
        "",
        "---",
        "",
        "## Most Common Mistakes per Model",
        "",
    ])

    for r in eval_results:
        lines.append(f"### Model: `{r['model_name']}`")
        sorted_mistakes = sorted(
            r["field_mistakes"].items(), key=lambda item: item[1], reverse=True
        )
        has_mistakes = False
        for field, count in sorted_mistakes:
            if count > 0:
                pct = round(count / r["total_invocations"] * 100.0, 1)
                lines.append(f"- **`{field}`**: {count} errors ({pct}% of samples)")
                has_mistakes = True
        if not has_mistakes:
            lines.append("- No field extraction errors recorded across tested sample invoices.")
        lines.append("")

    return "\n".join(lines)


def print_console_summary(eval_results: list[dict[str, Any]], hardware_note: str):
    """Print clean terminal comparison table."""
    print("\n" + "=" * 90)
    print(f"{'DOCFLOW PIPELINE EVALUATION SUMMARY (WEEK 5A)':^90}")
    print(f"{'Hardware: ' + hardware_note:^90}")
    print("=" * 90)

    header = f"{'Metric':<42} | " + " | ".join(f"{r['model_name'][:20]:<20}" for r in eval_results)
    print(header)
    print("-" * 90)

    rows = [
        ("Invoice Accuracy (All Fields Correct)", [f"{r['invoice_accuracy_pct']}%" for r in eval_results]),
        ("Silent Error Rate (Wrong in Auto-Approved)", [f"{r['silent_error_rate']}%" for r in eval_results]),
        ("Validation Catch Rate (Caught / Wrong)", [f"{r['catch_rate']}%" for r in eval_results]),
        ("Auto-Approved %", [f"{r['auto_approved_pct']}%" for r in eval_results]),
        ("Needs Review %", [f"{r['needs_review_pct']}%" for r in eval_results]),
        ("Pipeline Failures %", [f"{r['failed_pct']}%" for r in eval_results]),
        ("Median Latency (p50)", [f"{r['latency_p50']}s" for r in eval_results]),
        ("p95 Latency", [f"{r['latency_p95']}s" for r in eval_results]),
        ("Average Tokens / Invoice", [f"{r['avg_tokens']}" for r in eval_results]),
        ("Repair Retries Used", [f"{r['repair_retries']}" for r in eval_results]),
        ("Invalid-Output Failures", [f"{r['invalid_output_failures']}" for r in eval_results]),
        ("Consistency across Repeats", [f"{r['consistency_pct']}%" for r in eval_results]),
    ]

    for label, vals in rows:
        line = f"{label:<42} | " + " | ".join(f"{v:<20}" for v in vals)
        print(line)

    print("-" * 90)
    print("Most Common Mistakes:")
    for r in eval_results:
        sorted_mistakes = sorted(
            r["field_mistakes"].items(), key=lambda item: item[1], reverse=True
        )
        mistakes_summary = [
            f"{f} ({c}x)" for f, c in sorted_mistakes if c > 0
        ][:4]
        mistakes_str = ", ".join(mistakes_summary) or "None (100% field accuracy)"
        print(f"  - {r['model_name']}: {mistakes_str}")
    print("=" * 90 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Evaluate DocFlow extraction pipeline with local models.")
    parser.add_argument(
        "--models",
        type=str,
        default="mock-model",
        help="Comma-separated model names (e.g. 'llama3.2:3b,qwen2.5:7b')",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Provider to use: 'ollama' or 'mock' (default: ollama if multiple models given, else settings.LLM_PROVIDER)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of times to run each invoice through each model (default: 1)",
    )
    parser.add_argument(
        "--hardware",
        type=str,
        default="Local Hardware (unspecified)",
        help="Hardware description string (e.g. 'NVIDIA RTX 4090 24GB', 'Apple M2 16GB')",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Ollama base URL (default: OLLAMA_BASE_URL from settings)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Ollama timeout in seconds (default: OLLAMA_TIMEOUT_SECONDS from settings)",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=None,
        help="Ollama context window size (default: OLLAMA_NUM_CTX from settings)",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default=str(DEFAULT_RESULTS_FILE),
        help="Path to write evaluation markdown report",
    )

    args = parser.parse_args()

    models_list = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models_list:
        print("Error: No models specified. Pass --models 'modelA,modelB'")
        sys.exit(1)

    provider = args.provider
    if not provider:
        if any("mock" in m.lower() for m in models_list):
            provider = "mock"
        else:
            provider = "ollama"

    dataset = load_sample_dataset()
    if not dataset:
        print(f"Error: No sample files found in {SAMPLES_DIR}")
        sys.exit(1)

    print(f"\nLoaded {len(dataset)} invoice samples ({len([p for p, _ in dataset if 'bad' in p.name])} bad, {len([p for p, _ in dataset if 'bad' not in p.name])} valid)")
    print(f"Evaluating {len(models_list)} model(s) via provider '{provider}': {', '.join(models_list)}")
    print(f"Repeat per invoice: {args.repeat} | Hardware: {args.hardware}\n")

    results_all_models: list[dict[str, Any]] = []

    for idx, model_name in enumerate(models_list, 1):
        print(f"[{idx}/{len(models_list)}] Evaluating model: {model_name}...")
        res = evaluate_single_model(
            model_name=model_name,
            provider=provider,
            dataset=dataset,
            repeat=args.repeat,
            base_url=args.base_url,
            timeout=args.timeout,
            num_ctx=args.num_ctx,
        )
        results_all_models.append(res)
        print(f"    Done: Invoice Accuracy: {res['invoice_accuracy_pct']}% | Silent Error Rate: {res['silent_error_rate']}% | Median Latency: {res['latency_p50']}s")

    # Console output
    print_console_summary(results_all_models, args.hardware)

    # Markdown report output
    md_report = format_markdown_report(results_all_models, args.hardware, args.repeat)
    out_path = Path(args.output_file)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"Detailed evaluation markdown report written to: {out_path.resolve()}\n")


if __name__ == "__main__":
    main()
