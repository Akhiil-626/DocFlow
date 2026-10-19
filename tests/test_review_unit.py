import itertools
from decimal import Decimal

import pytest

from app.diff import compute_extraction_diff
from app.models import (
    ALLOWED_STATUS_TRANSITIONS,
    Document,
    InvalidStatusTransitionError,
    transition_document_status,
)
from app.sanitizer import sanitize_csv_cell


# ---------------- 1. Field-Level Diff Unit Tests ----------------
def test_diff_unchanged_data_returns_empty():
    old_data = {
        "vendor_name": "Acme Corp",
        "subtotal": "100.00",
        "total": "118.00",
        "line_items": [
            {"description": "Item 1", "quantity": "2.00", "unit_price": "50.00", "amount": "100.00"}
        ],
    }
    new_data = {
        "vendor_name": "Acme Corp",
        "subtotal": "100.00",
        "total": "118.00",
        "line_items": [
            {"description": "Item 1", "quantity": "2.00", "unit_price": "50.00", "amount": "100.00"}
        ],
    }
    diff = compute_extraction_diff(old_data, new_data)
    assert diff == {}


def test_diff_decimal_equality_no_false_positive():
    """Verify that Decimal equality (e.g. 1.0 vs 1.00 or Decimal('100.0') vs '100.00') is NOT marked as a change."""
    old_data = {
        "subtotal": "100.0",
        "total": Decimal("118.000"),
        "line_items": [
            {"description": "Item 1", "quantity": "1.0", "unit_price": "100.00", "amount": Decimal("100.0")}
        ],
    }
    new_data = {
        "subtotal": Decimal("100.00"),
        "total": "118.0",
        "line_items": [
            {"description": "Item 1", "quantity": Decimal("1.000"), "unit_price": "100.0", "amount": "100.00"}
        ],
    }
    diff = compute_extraction_diff(old_data, new_data)
    assert diff == {}


def test_diff_changed_header_fields():
    old_data = {"vendor_name": "Old Vendor", "total": "100.00"}
    new_data = {"vendor_name": "New Vendor", "total": "200.00"}
    diff = compute_extraction_diff(old_data, new_data)
    assert diff["vendor_name"] == {"old": "Old Vendor", "new": "New Vendor"}
    assert diff["total"] == {"old": "100.00", "new": "200.00"}


def test_diff_line_items_changed_added_and_removed():
    old_data = {
        "line_items": [
            {"description": "Keep Same", "quantity": "1.0", "amount": "10.00"},
            {"description": "Will Edit", "quantity": "2.0", "amount": "20.00"},
            {"description": "Will Remove", "quantity": "3.0", "amount": "30.00"},
        ]
    }
    new_data = {
        "line_items": [
            {"description": "Keep Same", "quantity": "1.00", "amount": "10.0"},
            {"description": "Edited Item", "quantity": "5.0", "amount": "50.00"},
            # "Will Remove" removed at index 2
        ]
    }
    diff = compute_extraction_diff(old_data, new_data)
    assert "line_items" in diff
    assert len(diff["line_items"]["changed"]) == 1
    assert diff["line_items"]["changed"][0]["index"] == 1
    assert diff["line_items"]["changed"][0]["changes"]["description"] == {
        "old": "Will Edit",
        "new": "Edited Item",
    }
    assert diff["line_items"]["changed"][0]["changes"]["quantity"] == {
        "old": "2.0",
        "new": "5.0",
    }
    assert len(diff["line_items"]["removed"]) == 1
    assert diff["line_items"]["removed"][0]["description"] == "Will Remove"
    assert len(diff["line_items"]["added"]) == 0

    # Test added line item
    new_data_with_add = {
        "line_items": [
            {"description": "Keep Same", "quantity": "1.0", "amount": "10.00"},
            {"description": "Will Edit", "quantity": "2.0", "amount": "20.00"},
            {"description": "Will Remove", "quantity": "3.0", "amount": "30.00"},
            {"description": "New Item Added", "quantity": "4.0", "amount": "40.00"},
        ]
    }
    diff_add = compute_extraction_diff(old_data, new_data_with_add)
    assert len(diff_add["line_items"]["added"]) == 1
    assert diff_add["line_items"]["added"][0]["description"] == "New Item Added"
    assert len(diff_add["line_items"]["removed"]) == 0
    assert len(diff_add["line_items"]["changed"]) == 0


# ---------------- 2. Extended State Machine Unit Tests ----------------
ALL_KNOWN_STATUSES = [
    "uploaded",
    "processing",
    "extracted",
    "needs_review",
    "approved",
    "rejected",
    "auto_approved",
    "failed",
    "exported",
]


def test_state_machine_every_allowed_transition_succeeds():
    """Verify that every transition explicitly listed in ALLOWED_STATUS_TRANSITIONS passes cleanly."""
    for source_status, targets in ALLOWED_STATUS_TRANSITIONS.items():
        for target_status in targets:
            doc = Document(status=source_status)
            transition_document_status(doc, target_status)
            assert doc.status == target_status


def test_state_machine_every_other_transition_raises():
    """Verify that every transition NOT in ALLOWED_STATUS_TRANSITIONS raises InvalidStatusTransitionError."""
    for source, target in itertools.product(ALL_KNOWN_STATUSES, ALL_KNOWN_STATUSES):
        allowed = ALLOWED_STATUS_TRANSITIONS.get(source, set())
        if target not in allowed:
            doc = Document(status=source)
            with pytest.raises(InvalidStatusTransitionError) as exc_info:
                transition_document_status(doc, target)
            assert exc_info.value.current_status == source
            assert exc_info.value.new_status == target


def test_state_machine_exported_is_terminal():
    """Verify that 'exported' allows 0 transitions out."""
    assert ALLOWED_STATUS_TRANSITIONS["exported"] == set()
    for target in ALL_KNOWN_STATUSES:
        doc = Document(status="exported")
        with pytest.raises(InvalidStatusTransitionError):
            transition_document_status(doc, target)


# ---------------- 3. CSV Cell Formula Injection Sanitizer Tests ----------------
def test_csv_sanitizer_neutralizes_formula_prefixes():
    dangerous_inputs = [
        ("=1+1", "'=1+1"),
        ("=CMD|' /C calc'!A0", "'=CMD|' /C calc'!A0"),
        ("+12345", "'+12345"),
        ("-100.50", "'-100.50"),
        ("@SUM(A1:A10)", "'@SUM(A1:A10)"),
        ("\tTabIndented", "'\tTabIndented"),
        ("\rCarriageReturn", "'\rCarriageReturn"),
    ]
    for raw, expected in dangerous_inputs:
        assert sanitize_csv_cell(raw) == expected


def test_csv_sanitizer_preserves_safe_content():
    safe_inputs = [
        "Acme Technologies Pvt Ltd",
        "123 Industrial Area, Phase II",
        'Item "Super" Premium',
        "हिंदी / 中文 / Español",
        "INV-2026-001",
        "100.00",
        "",
        None,
    ]
    for inp in safe_inputs:
        sanitized = sanitize_csv_cell(inp)
        if inp is None:
            assert sanitized == ""
        else:
            assert sanitized == str(inp)
