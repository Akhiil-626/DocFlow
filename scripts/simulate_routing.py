"""DocFlow Model Routing Offline Policy Simulator.

Reads raw evaluation records and simulates model routing policies:
- P1: Small model only
- P2: Large model only
- P3: Small, escalate to large on ANY error-severity issue
- P4: Small, escalate only when an issue code is in ESCALATE_CODES
- P5: Same as P4, but skip escalation for codes that describe the document itself

Performs offline simulation with no LLM, no DB, and no network.
"""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.evaluation_metrics import (
    calculate_percentiles,
    compare_date,
    compare_field,
    normalize_money,
)

DEFAULT_ESCALATE_CODES = [
    "TOTAL_MISMATCH",
    "LINE_ITEM_AMOUNT_MISMATCH",
    "LINE_ITEMS_SUM_MISMATCH",
    "MISSING_VENDOR_NAME",
    "MISSING_INVOICE_NUMBER",
    "NO_LINE_ITEMS",
]

DEFAULT_SKIP_DOCUMENT_CODES = [
    "FUTURE_INVOICE_DATE",
    "OLD_INVOICE_DATE",
    "DUPLICATE_SUSPECTED",
    "MISSING_GSTIN",
    "EXACT_DUPLICATE",
    "SEMANTIC_DUPLICATE",
]

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

CRITICAL_FIELDS = [
    "invoice_number",
    "invoice_date",
    "subtotal",
    "cgst",
    "sgst",
    "igst",
    "total",
    "line_items",
]


def compare_line_item_amounts(items1: Any, items2: Any) -> bool:
    """Compare line items purely on amount."""
    list1 = items1 if isinstance(items1, list) else []
    list2 = items2 if isinstance(items2, list) else []
    if len(list1) != len(list2):
        return False
    for i1, i2 in zip(list1, list2):
        if not isinstance(i1, dict) or not isinstance(i2, dict):
            return False
        if normalize_money(i1.get("amount")) != normalize_money(i2.get("amount")):
            return False
    return True


def compare_line_items_numeric(items1: Any, items2: Any) -> bool:
    """Compare line items on quantity, unit_price, and amount (ignoring description)."""
    list1 = items1 if isinstance(items1, list) else []
    list2 = items2 if isinstance(items2, list) else []
    if len(list1) != len(list2):
        return False
    for i1, i2 in zip(list1, list2):
        if not isinstance(i1, dict) or not isinstance(i2, dict):
            return False
        qty_match = normalize_money(i1.get("quantity")) == normalize_money(i2.get("quantity"))
        price_match = normalize_money(i1.get("unit_price")) == normalize_money(i2.get("unit_price"))
        amt_match = normalize_money(i1.get("amount")) == normalize_money(i2.get("amount"))
        if not (qty_match and price_match and amt_match):
            return False
    return True


def get_critical_fields_diff(ext1: dict[str, Any], ext2: dict[str, Any]) -> list[str]:
    """Return list of critical field names where two extractions differ."""
    diff_fields: list[str] = []

    # 1. invoice_number (trimmed, case-insensitive)
    s1 = str(ext1.get("invoice_number") or "").strip().upper()
    s2 = str(ext2.get("invoice_number") or "").strip().upper()
    if s1 != s2:
        diff_fields.append("invoice_number")

    # 2. invoice_date (parsed date)
    if not compare_date(ext1.get("invoice_date"), ext2.get("invoice_date")):
        diff_fields.append("invoice_date")

    # 3. Header money fields
    for field in ("subtotal", "cgst", "sgst", "igst", "total"):
        if normalize_money(ext1.get(field)) != normalize_money(ext2.get(field)):
            diff_fields.append(field)

    # 4. Line item amounts
    if not compare_line_item_amounts(ext1.get("line_items"), ext2.get("line_items")):
        diff_fields.append("line_items")

    return diff_fields


def is_critical_fields_correct(extracted: dict[str, Any], ground_truth: dict[str, Any]) -> bool:
    """Check if all critical fields in extraction match ground truth."""
    diffs = get_critical_fields_diff(extracted, ground_truth)
    return len(diffs) == 0


def is_invoice_all_correct(extracted: dict[str, Any], ground_truth: dict[str, Any]) -> bool:
    """Check if all evaluated fields match ground truth."""
    for field in FIELDS_TO_EVALUATE:
        if field == "line_items":
            if not compare_line_items_numeric(extracted.get(field), ground_truth.get(field)):
                return False
        else:
            if not compare_field(field, extracted.get(field), ground_truth.get(field)):
                return False
    return True


def extract_issue_codes_and_severities(issues: list[Any]) -> list[tuple[str, str]]:
    """Extract list of (code, severity) tuples from validation issue representations."""
    result: list[tuple[str, str]] = []
    for iss in issues:
        if isinstance(iss, dict):
            code = str(iss.get("code") or "").strip()
            sev = str(iss.get("severity") or "warning").strip().lower()
            result.append((code, sev))
        elif isinstance(iss, str):
            result.append((iss.strip(), "error"))
    return result


def load_raw_records(file_path: Path | str) -> list[dict[str, Any]]:
    """Load raw evaluation records from JSON file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Raw evaluation file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("records") or data.get("results") or data.get("invoices") or []
    raise ValueError(f"Unexpected JSON structure in {path}")


def group_records_by_invoice(
    records: list[dict[str, Any]],
    small_model_override: str | None = None,
    large_model_override: str | None = None,
) -> tuple[str, str, dict[str, dict[str, Any]]]:
    """Group evaluation records by invoice filename and identify small/large models."""
    grouped: dict[str, dict[str, Any]] = {}
    models_seen: list[str] = []

    for r in records:
        inv = str(r.get("invoice") or r.get("filename") or "").strip()
        model = str(r.get("model") or "").strip()
        if not inv or not model:
            continue
        if model not in models_seen:
            models_seen.append(model)
        if inv not in grouped:
            grouped[inv] = {}
        grouped[inv][model] = r

    if small_model_override and large_model_override:
        small_model = small_model_override
        large_model = large_model_override
    elif len(models_seen) == 2:
        # Detect small and large: sort by typical indicator or order
        # '3b' or lower latency/size is small
        if "3b" in models_seen[0].lower() or "small" in models_seen[0].lower():
            small_model, large_model = models_seen[0], models_seen[1]
        elif "3b" in models_seen[1].lower() or "small" in models_seen[1].lower():
            small_model, large_model = models_seen[1], models_seen[0]
        else:
            small_model, large_model = models_seen[0], models_seen[1]
    elif len(models_seen) > 2:
        small_model = small_model_override or models_seen[0]
        large_model = large_model_override or models_seen[1]
    else:
        raise ValueError(f"Need at least 2 models to simulate routing; found {models_seen}")

    return small_model, large_model, grouped


def simulate_policy(
    policy_key: str,
    grouped_invoices: dict[str, dict[str, Any]],
    small_model: str,
    large_model: str,
    escalate_codes: list[str] | None = None,
    skip_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Simulate a routing policy across all invoices.

    Returns dictionary containing calculated metrics.
    """
    escalate_codes_set = set(escalate_codes or DEFAULT_ESCALATE_CODES)
    skip_codes_set = set(skip_codes or DEFAULT_SKIP_DOCUMENT_CODES)

    total_invoices = len(grouped_invoices)
    if total_invoices == 0:
        return {}

    correct_invoices = 0
    critical_correct_invoices = 0
    auto_approved_count = 0
    silent_errors_count = 0
    escalation_count = 0
    useful_escalations = 0
    wasted_escalations = 0

    invoice_latencies: list[float] = []
    total_compute_seconds: float = 0.0

    for inv_name, model_runs in grouped_invoices.items():
        small_run = model_runs.get(small_model)
        large_run = model_runs.get(large_model)

        if not small_run or not large_run:
            continue

        gt = small_run.get("ground_truth") or large_run.get("ground_truth") or {}
        small_ext = small_run.get("extracted_json") or {}
        large_ext = large_run.get("extracted_json") or {}

        small_lat = float(small_run.get("latency") or 0.0)
        large_lat = float(large_run.get("latency") or 0.0)

        small_issues = extract_issue_codes_and_severities(small_run.get("validation_issues") or [])

        # Policy escalation decision
        escalate = False
        if policy_key == "P1":
            escalate = False
        elif policy_key == "P2":
            escalate = False  # P2 routes all directly to large model
        elif policy_key == "P3":
            # Escalate on ANY error-severity issue
            escalate = any(sev == "error" for _, sev in small_issues)
        elif policy_key == "P4":
            # Escalate only when an issue code is in ESCALATE_CODES
            escalate = any(code in escalate_codes_set for code, _ in small_issues)
        elif policy_key == "P5":
            # Same as P4, but skip escalation for codes that describe document itself
            has_doc_issue = any(code in skip_codes_set for code, _ in small_issues)
            if has_doc_issue:
                escalate = False
            else:
                escalate = any(code in escalate_codes_set for code, _ in small_issues)

        # Determine chosen extraction, latency, and status
        if policy_key == "P2":
            chosen_ext = large_ext
            chosen_status = large_run.get("pipeline_status")
            inv_latency = large_lat
            total_compute_seconds += large_lat
        elif escalate:
            escalation_count += 1
            chosen_ext = large_ext
            chosen_status = large_run.get("pipeline_status")
            inv_latency = small_lat + large_lat
            total_compute_seconds += (small_lat + large_lat)

            # Evaluate Useful vs Wasted escalation
            diff_fields = get_critical_fields_diff(small_ext, large_ext)
            if len(diff_fields) == 0:
                # Identical critical fields -> wasted escalation
                wasted_escalations += 1
            else:
                # Differ on critical fields; check if large model's critical fields match ground truth
                if is_critical_fields_correct(large_ext, gt):
                    useful_escalations += 1
        else:
            chosen_ext = small_ext
            chosen_status = small_run.get("pipeline_status")
            inv_latency = small_lat
            total_compute_seconds += small_lat

        invoice_latencies.append(inv_latency)

        # Check accuracy against ground truth
        is_all_correct = is_invoice_all_correct(chosen_ext, gt)
        if is_all_correct:
            correct_invoices += 1

        is_crit_correct = is_critical_fields_correct(chosen_ext, gt)
        if is_crit_correct:
            critical_correct_invoices += 1

        if chosen_status == "auto_approved":
            auto_approved_count += 1
            if not is_all_correct:
                silent_errors_count += 1

    percentiles = calculate_percentiles(invoice_latencies, [50, 95])
    invoice_acc_pct = round((correct_invoices / total_invoices * 100.0), 1)
    critical_acc_pct = round((critical_correct_invoices / total_invoices * 100.0), 1)
    silent_rate_pct = (
        round((silent_errors_count / auto_approved_count * 100.0), 1)
        if auto_approved_count > 0
        else 0.0
    )
    auto_app_pct = round((auto_approved_count / total_invoices * 100.0), 1)
    escalation_pct = round((escalation_count / total_invoices * 100.0), 1)

    return {
        "policy": policy_key,
        "invoice_accuracy_pct": invoice_acc_pct,
        "critical_accuracy_pct": critical_acc_pct,
        "silent_error_rate_pct": silent_rate_pct,
        "auto_approved_pct": auto_app_pct,
        "escalation_pct": escalation_pct,
        "median_latency": percentiles["p50"],
        "p95_latency": percentiles["p95"],
        "total_compute_sec": round(total_compute_seconds, 2),
        "useful_escalations": useful_escalations,
        "wasted_escalations": wasted_escalations,
    }


def format_simulation_table(results: list[dict[str, Any]]) -> str:
    """Format markdown table containing the simulation metrics only."""
    policy_names = {
        "P1": "P1: Small model only",
        "P2": "P2: Large model only",
        "P3": "P3: Escalate on ANY error",
        "P4": "P4: Escalate on ESCALATE_CODES",
        "P5": "P5: P4 + skip document issues",
    }

    headers = [
        "Policy",
        "Invoice Accuracy",
        "Critical-Fields Accuracy",
        "Silent Error Rate",
        "Auto-Approved %",
        "Escalation %",
        "Median Latency (s)",
        "p95 Latency (s)",
        "Total Compute (s)",
        "Useful Escalations",
        "Wasted Escalations",
    ]

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" if i == 0 else ":---:" for i in range(len(headers))) + " |",
    ]

    for r in results:
        p_label = policy_names.get(r["policy"], r["policy"])
        row = [
            p_label,
            f"{r['invoice_accuracy_pct']}%",
            f"{r['critical_accuracy_pct']}%",
            f"{r['silent_error_rate_pct']}%",
            f"{r['auto_approved_pct']}%",
            f"{r['escalation_pct']}%",
            f"{r['median_latency']}s",
            f"{r['p95_latency']}s",
            f"{r['total_compute_sec']}s",
            str(r["useful_escalations"]),
            str(r["wasted_escalations"]),
        ]
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def run_simulation(
    raw_file_path: Path | str,
    small_model: str | None = None,
    large_model: str | None = None,
    escalate_codes: list[str] | None = None,
    skip_codes: list[str] | None = None,
    output_markdown_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Run full simulation over all 5 policies and optionally write markdown table."""
    records = load_raw_records(raw_file_path)
    sm, lm, grouped = group_records_by_invoice(records, small_model, large_model)

    results: list[dict[str, Any]] = []
    for p in ("P1", "P2", "P3", "P4", "P5"):
        res = simulate_policy(
            policy_key=p,
            grouped_invoices=grouped,
            small_model=sm,
            large_model=lm,
            escalate_codes=escalate_codes,
            skip_codes=skip_codes,
        )
        results.append(res)

    table_md = format_simulation_table(results)

    if output_markdown_path:
        out_p = Path(output_markdown_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            f.write(table_md + "\n")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate model routing policies on raw evaluation data.")
    parser.add_argument(
        "raw_file",
        nargs="?",
        default="eval_raw/eval_raw.json",
        help="Path to raw evaluation JSON file (default: eval_raw/eval_raw.json)",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default="routing_simulation.md",
        help="Path to write simulation markdown table (default: routing_simulation.md)",
    )
    parser.add_argument(
        "--small-model",
        type=str,
        default=None,
        help="Name of small model in dataset",
    )
    parser.add_argument(
        "--large-model",
        type=str,
        default=None,
        help="Name of large model in dataset",
    )
    parser.add_argument(
        "--escalate-codes",
        type=str,
        default=None,
        help="Comma-separated list of issue codes that trigger escalation for P4/P5",
    )
    parser.add_argument(
        "--skip-codes",
        type=str,
        default=None,
        help="Comma-separated list of document-level codes skipped for P5",
    )

    args = parser.parse_args()

    esc_codes = [c.strip() for c in args.escalate_codes.split(",")] if args.escalate_codes else None
    sk_codes = [c.strip() for c in args.skip_codes.split(",")] if args.skip_codes else None

    raw_path = Path(args.raw_file)
    if not raw_path.exists():
        print(f"Error: Raw file not found: {raw_path}")
        print("Run scripts/evaluate.py --save-raw <path> first, or specify a valid file path.")
        sys.exit(1)

    results = run_simulation(
        raw_file_path=raw_path,
        small_model=args.small_model,
        large_model=args.large_model,
        escalate_codes=esc_codes,
        skip_codes=sk_codes,
        output_markdown_path=args.output_file,
    )

    table_md = format_simulation_table(results)
    print("\n" + table_md + "\n")
    print(f"Simulation table written to: {Path(args.output_file).resolve()}\n")


if __name__ == "__main__":
    main()
