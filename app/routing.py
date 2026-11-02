"""Cost-aware model routing policies and escalation logic for DocFlow.

Provides deterministic, offline, and pure functions for escalation decisions
and critical-field extraction comparison.
"""

from decimal import Decimal
from typing import Any

from app.evaluation_metrics import compare_date, normalize_money

# Real error codes from app/validation.py used for escalation under policy P4
DEFAULT_ROUTING_ESCALATE_CODES: list[str] = [
    "TOTAL_MISMATCH",
    "LINE_ITEM_AMOUNT_MISMATCH",
    "LINE_ITEMS_SUM_MISMATCH",
    "MISSING_VENDOR_NAME",
    "MISSING_INVOICE_NUMBER",
    "NO_LINE_ITEMS",
]

# Codes that describe the document itself rather than model extraction errors
DOCUMENT_CODES: set[str] = {
    "FUTURE_INVOICE_DATE",
    "OLD_INVOICE_DATE",
    "DUPLICATE_SUSPECTED",
    "MISSING_GSTIN",
    "EXACT_DUPLICATE",
    "SEMANTIC_DUPLICATE",
}

# Warning-severity validation codes that must never trigger escalation
WARNING_CODES: set[str] = {
    "MISSING_GSTIN",
    "OLD_INVOICE_DATE",
    "CGST_SGST_MISMATCH",
    "UNEXPECTED_TAX_RATE",
    "DUPLICATE_SUSPECTED",
}

CRITICAL_FIELDS: list[str] = [
    "invoice_number",
    "invoice_date",
    "subtotal",
    "cgst",
    "sgst",
    "igst",
    "total",
    "line_items",
]


def _extract_code(item: Any) -> str:
    """Normalize issue item into code string."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("code") or "").strip()
    if hasattr(item, "code"):
        return str(getattr(item, "code") or "").strip()
    return str(item).strip()


def _is_warning_issue(item: Any) -> bool:
    """Check if an issue item has warning severity."""
    if isinstance(item, dict):
        return str(item.get("severity") or "").lower() == "warning"
    if hasattr(item, "severity"):
        return str(getattr(item, "severity") or "").lower() == "warning"
    return False


def decide_escalation(
    issue_codes: list[Any],
    attempt_number: int,
    elapsed_seconds: float,
    config: Any = None,
) -> tuple[bool, str]:
    """Pure decision function for model routing escalation (Policy P4).

    Args:
        issue_codes: List of issue code strings, dicts, or ValidationIssue objects.
        attempt_number: 1-based attempt index (1 = tier 1 attempt).
        elapsed_seconds: Wall-clock seconds spent so far on this document.
        config: Application settings or configuration dictionary/object.

    Returns:
        (should_escalate, reason)
    """
    if config is not None:
        if isinstance(config, dict):
            max_escalations = config.get("ROUTING_MAX_ESCALATIONS", 1)
            max_seconds = float(config.get("ROUTING_MAX_SECONDS_PER_DOCUMENT", 180.0))
            escalate_codes = config.get("ROUTING_ESCALATE_CODES", DEFAULT_ROUTING_ESCALATE_CODES)
        else:
            max_escalations = getattr(config, "ROUTING_MAX_ESCALATIONS", 1)
            max_seconds = float(getattr(config, "ROUTING_MAX_SECONDS_PER_DOCUMENT", 180.0))
            escalate_codes = getattr(config, "ROUTING_ESCALATE_CODES", DEFAULT_ROUTING_ESCALATE_CODES)
    else:
        max_escalations = 1
        max_seconds = 180.0
        escalate_codes = DEFAULT_ROUTING_ESCALATE_CODES

    escalate_codes_set = set(escalate_codes)

    # 1. Wall-clock cap: skip escalation once exceeded
    if elapsed_seconds >= max_seconds:
        return False, "time_cap_exceeded"

    # 2. Maximum attempts: never escalate beyond the maximum configured escalations
    if attempt_number > max_escalations:
        return False, "max_escalations_reached"

    # 3. Identify valid escalation codes:
    # Never escalate on warning-severity codes or document-describing codes (future date, old date, duplicate, missing GSTIN).
    matching_codes: list[str] = []
    for item in issue_codes:
        if not item:
            continue
        code = _extract_code(item)
        if not code:
            continue
        if _is_warning_issue(item) or code in WARNING_CODES or code in DOCUMENT_CODES:
            continue
        if code in escalate_codes_set:
            matching_codes.append(code)

    if matching_codes:
        return True, f"escalate_code_{matching_codes[0]}"

    return False, "no_escalate_code"


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


def get_critical_fields_diff(ext1: dict[str, Any], ext2: dict[str, Any]) -> list[str]:
    """Return list of critical field names where two extractions differ.

    Critical fields evaluated: invoice_number, invoice_date, subtotal,
    cgst, sgst, igst, total, and line-item amounts.
    """
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
