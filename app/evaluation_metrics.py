import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def normalize_money(val: Any) -> Decimal:
    """Convert input into an exact Decimal, defaulting to Decimal('0.00')."""
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val
    s = str(val).strip()
    if not s:
        return Decimal("0.00")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0.00")


def compare_money(val1: Any, val2: Any) -> bool:
    """Compare two monetary values as exact Decimals."""
    return normalize_money(val1) == normalize_money(val2)


def parse_date_value(val: Any) -> date | None:
    """Parse string or date representation into a date object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    # Try ISO formats
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def compare_date(val1: Any, val2: Any) -> bool:
    """Compare two dates as date objects, falling back to trimmed strings if unparseable."""
    d1 = parse_date_value(val1)
    d2 = parse_date_value(val2)
    if d1 is not None and d2 is not None:
        return d1 == d2
    return str(val1 or "").strip() == str(val2 or "").strip()


def normalize_vendor_name(val: Any) -> str:
    """Normalize vendor name strictly with trim and lower-case only."""
    return str(val or "").strip().lower()


def compare_vendor_name(val1: Any, val2: Any) -> bool:
    """Compare vendor names with trim and case only."""
    return normalize_vendor_name(val1) == normalize_vendor_name(val2)


def compare_field(field_name: str, extracted_val: Any, ground_truth_val: Any) -> bool:
    """Compare an extracted field value against ground truth according to specification rules."""
    if field_name == "vendor_name":
        return compare_vendor_name(extracted_val, ground_truth_val)

    if field_name == "invoice_date":
        return compare_date(extracted_val, ground_truth_val)

    if field_name in ("subtotal", "cgst", "sgst", "igst", "total", "unit_price", "amount", "quantity"):
        return compare_money(extracted_val, ground_truth_val)

    if field_name in ("vendor_gstin", "invoice_number", "currency"):
        s1 = str(extracted_val or "").strip().upper()
        s2 = str(ground_truth_val or "").strip().upper()
        return s1 == s2

    if field_name == "line_items":
        # Compare line items list
        gt_items = ground_truth_val if isinstance(ground_truth_val, list) else []
        ex_items = extracted_val if isinstance(extracted_val, list) else []
        if len(gt_items) != len(ex_items):
            return False
        for gt_i, ex_i in zip(gt_items, ex_items):
            if not isinstance(gt_i, dict) or not isinstance(ex_i, dict):
                return False
            desc_match = str(ex_i.get("description") or "").strip().lower() == str(gt_i.get("description") or "").strip().lower()
            qty_match = compare_money(ex_i.get("quantity"), gt_i.get("quantity"))
            price_match = compare_money(ex_i.get("unit_price"), gt_i.get("unit_price"))
            amt_match = compare_money(ex_i.get("amount"), gt_i.get("amount"))
            if not (desc_match and qty_match and price_match and amt_match):
                return False
        return True

    # Generic string comparison
    return str(extracted_val or "").strip() == str(ground_truth_val or "").strip()


def calculate_percentiles(values: list[float | int], percentiles: list[float | int]) -> dict[str, float]:
    """Calculate percentiles (e.g., [50, 95]) for a list of values (e.g. latencies)."""
    if not values:
        return {f"p{p}": 0.0 for p in percentiles}
    sorted_vals = sorted(float(v) for v in values)
    n = len(sorted_vals)
    results = {}
    for p in percentiles:
        if n == 1:
            results[f"p{p}"] = sorted_vals[0]
            continue
        k = (len(sorted_vals) - 1) * (p / 100.0)
        f = int(k)
        c = f + 1
        if c < len(sorted_vals):
            val = sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
        else:
            val = sorted_vals[f]
        results[f"p{p}"] = round(val, 3)
    return results


def evaluate_invoice_extraction(
    extracted_data: dict[str, Any],
    ground_truth: dict[str, Any],
    fields_to_check: list[str] | None = None,
) -> tuple[bool, dict[str, bool], list[str]]:
    """Evaluate extracted invoice against ground truth.

    Returns:
        (is_all_correct, field_matches_dict, list_of_mismatched_fields)
    """
    if fields_to_check is None:
        fields_to_check = [
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

    field_matches: dict[str, bool] = {}
    mismatched_fields: list[str] = []

    for field in fields_to_check:
        ex_val = extracted_data.get(field)
        gt_val = ground_truth.get(field)
        matched = compare_field(field, ex_val, gt_val)
        field_matches[field] = matched
        if not matched:
            mismatched_fields.append(field)

    is_all_correct = len(mismatched_fields) == 0
    return is_all_correct, field_matches, mismatched_fields


def calculate_silent_error_rate(
    results: list[dict[str, Any]]
) -> dict[str, Any]:
    """Calculate honesty metrics: silent error rate and caught vs missed breakdown.

    An invoice has a 'silent error' if it was auto-approved by the pipeline
    BUT contains at least one extraction error (is_correct is False).

    Wrong extractions are:
    - 'caught' if status is 'needs_review' or 'failed'
    - 'missed' if status is 'auto_approved'
    """
    auto_approved_count = 0
    silent_errors_count = 0
    total_wrong_extractions = 0
    caught_by_validation = 0
    missed_by_validation = 0

    for res in results:
        status = res.get("status")
        is_correct = res.get("is_correct", False)

        if status == "auto_approved":
            auto_approved_count += 1
            if not is_correct:
                silent_errors_count += 1
                missed_by_validation += 1

        if not is_correct:
            total_wrong_extractions += 1
            if status != "auto_approved":
                caught_by_validation += 1

    silent_error_rate = (
        (silent_errors_count / auto_approved_count * 100.0)
        if auto_approved_count > 0
        else 0.0
    )

    catch_rate = (
        (caught_by_validation / total_wrong_extractions * 100.0)
        if total_wrong_extractions > 0
        else 100.0
    )

    return {
        "auto_approved_count": auto_approved_count,
        "silent_errors_count": silent_errors_count,
        "silent_error_rate": round(silent_error_rate, 2),
        "total_wrong_extractions": total_wrong_extractions,
        "caught_by_validation": caught_by_validation,
        "missed_by_validation": missed_by_validation,
        "catch_rate": round(catch_rate, 2),
    }


def calculate_repeat_consistency(
    invoice_repeat_runs: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Calculate consistency across repeat runs for each invoice.

    For each invoice, checks if the output across runs is identical.
    """
    if not invoice_repeat_runs:
        return {"consistent_invoices": 0, "total_invoices": 0, "consistency_pct": 100.0}

    consistent_count = 0
    total_invoices = len(invoice_repeat_runs)

    for _, runs in invoice_repeat_runs.items():
        if len(runs) <= 1:
            consistent_count += 1
            continue

        first_run = runs[0]
        all_matched = True
        for subsequent in runs[1:]:
            # Compare key extraction fields
            for key in ["vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "total", "subtotal"]:
                if str(subsequent.get(key, "")).strip() != str(first_run.get(key, "")).strip():
                    all_matched = False
                    break
            if not all_matched:
                break

        if all_matched:
            consistent_count += 1

    consistency_pct = (consistent_count / total_invoices * 100.0) if total_invoices > 0 else 100.0
    return {
        "consistent_invoices": consistent_count,
        "total_invoices": total_invoices,
        "consistency_pct": round(consistency_pct, 2),
    }
