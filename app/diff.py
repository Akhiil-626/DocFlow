from decimal import Decimal, InvalidOperation
from typing import Any


def _is_numeric_field(field_name: str) -> bool:
    """Check if field name is a monetary or quantity field."""
    return field_name in {
        "subtotal",
        "cgst",
        "sgst",
        "igst",
        "total",
        "quantity",
        "unit_price",
        "amount",
    }


def _values_are_equal(val1: Any, val2: Any, field_name: str = "") -> bool:
    """Check equality between two values, using Decimal equality for numbers."""
    if val1 is None and val2 is None:
        return True
    if val1 is None or val2 is None:
        return False

    if _is_numeric_field(field_name) or isinstance(val1, (Decimal, int, float)) or isinstance(val2, (Decimal, int, float)):
        try:
            d1 = Decimal(str(val1))
            d2 = Decimal(str(val2))
            return d1 == d2
        except (InvalidOperation, ValueError, TypeError):
            pass

    return str(val1).strip() == str(val2).strip()


def compute_line_item_diff(old_item: dict[str, Any], new_item: dict[str, Any]) -> dict[str, Any]:
    """Compare fields of a single line item, returning changed fields."""
    all_keys = set(old_item.keys()) | set(new_item.keys())
    changes = {}
    for key in sorted(all_keys):
        old_val = old_item.get(key)
        new_val = new_item.get(key)
        if not _values_are_equal(old_val, new_val, field_name=key):
            changes[key] = {"old": old_val, "new": new_val}
    return changes


def compute_extraction_diff(
    old_data: dict[str, Any], new_data: dict[str, Any]
) -> dict[str, Any]:
    """Pure function to compute field-level differences between old and new extraction data.

    Only changed fields are included.
    Decimal equality is respected (e.g. 1.0 == 1.00 is NOT a change).
    Line items track added, removed, and changed items.
    """
    diff: dict[str, Any] = {}

    all_keys = (set(old_data.keys()) | set(new_data.keys())) - {"line_items"}
    for key in sorted(all_keys):
        old_val = old_data.get(key)
        new_val = new_data.get(key)
        if not _values_are_equal(old_val, new_val, field_name=key):
            diff[key] = {"old": old_val, "new": new_val}

    # Compare line items
    old_items: list[dict[str, Any]] = old_data.get("line_items") or []
    new_items: list[dict[str, Any]] = new_data.get("line_items") or []

    min_len = min(len(old_items), len(new_items))
    changed_items = []
    for i in range(min_len):
        item_changes = compute_line_item_diff(old_items[i], new_items[i])
        if item_changes:
            changed_items.append({"index": i, "changes": item_changes})

    added_items = new_items[min_len:]
    removed_items = old_items[min_len:]

    if changed_items or added_items or removed_items:
        diff["line_items"] = {
            "changed": changed_items,
            "added": added_items,
            "removed": removed_items,
        }

    return diff
