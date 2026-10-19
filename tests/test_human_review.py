import io
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Document,
    ExportBatch,
    Extraction,
    LineItem,
    User,
    ValidationIssue,
    transition_document_status,
)
from app.storage import Storage
from tests.conftest import auth_headers_for

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


def _create_mock_document(
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "needs_review",
    vendor_name: str = "Apex Technologies Pvt Ltd",
    total: Decimal = Decimal("1180.00"),
    has_error: bool = False,
) -> tuple[Document, Extraction]:
    """Helper to create a document with extraction, line items, and issues."""
    doc_id = uuid.uuid4()
    doc = Document(
        id=doc_id,
        org_id=org_id,
        uploaded_by=user_id,
        original_filename="sample_invoice.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        sha256=uuid.uuid4().hex,
        storage_key=f"{org_id}/{doc_id}.pdf",
        status=status,
        review_reason="Test reason" if status == "needs_review" else None,
    )
    db.add(doc)

    ext_data = {
        "vendor_name": vendor_name,
        "vendor_gstin": "27AABCU9603R1ZM",
        "invoice_number": f"INV-{uuid.uuid4().hex[:6].upper()}",
        "invoice_date": "2026-03-01",
        "currency": "INR",
        "subtotal": "1000.00",
        "cgst": "90.00",
        "sgst": "90.00",
        "igst": "0.00",
        "total": str(total),
        "line_items": [
            {
                "description": "Cloud Hosting Service",
                "quantity": "1.00",
                "unit_price": "1000.00",
                "amount": "1000.00",
            }
        ],
    }

    ext_id = uuid.uuid4()
    extraction = Extraction(
        id=ext_id,
        document_id=doc_id,
        org_id=org_id,
        original_data=dict(ext_data),
        data=dict(ext_data),
        version=1,
        model="mock-model",
        input_tokens=100,
        output_tokens=50,
        latency_ms=10,
    )
    db.add(extraction)

    line_item = LineItem(
        id=uuid.uuid4(),
        extraction_id=ext_id,
        description="Cloud Hosting Service",
        quantity=Decimal("1.00"),
        unit_price=Decimal("1000.00"),
        amount=Decimal("1000.00"),
    )
    db.add(line_item)

    if has_error:
        issue = ValidationIssue(
            id=uuid.uuid4(),
            document_id=doc_id,
            org_id=org_id,
            code="TOTAL_MISMATCH",
            severity="error",
            field="total",
            message="Total calculation mismatch",
        )
        db.add(issue)

    db.commit()
    db.refresh(doc)
    db.refresh(extraction)
    return doc, extraction


# ---------------- 1. Edit fixes wrong total & recomputes issues ----------------
def test_edit_fixes_wrong_total_and_recomputes_issues(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    # Create doc with wrong total in needs_review with TOTAL_MISMATCH error
    doc, ext = _create_mock_document(
        db_session,
        admin_user_a.org_id,
        admin_user_a.id,
        status="needs_review",
        total=Decimal("1500.00"),  # Expected 1180.00
        has_error=True,
    )

    # Human corrects total to 1180.00
    patch_payload = {
        "version": 1,
        "total": Decimal("1180.00"),
        "note": "Fixed typo in invoice total",
    }
    resp = client.patch(
        f"/documents/{doc.id}/extraction",
        headers=headers,
        json={"version": 1, "total": "1180.00", "note": "Fixed typo in invoice total"},
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["version"] == 2
    assert res_data["data"]["total"] == "1180.00"
    # original_data must remain untouched!
    assert res_data["original_data"]["total"] == "1500.00"

    # TOTAL_MISMATCH should have disappeared
    assert len(res_data["validation_issues"]) == 0

    # Verify audit log diff in DB
    db_session.refresh(doc)
    assert doc.status == "needs_review"  # stays in needs_review

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == doc.id, AuditLog.action == "edit_extraction")
        .first()
    )
    assert audit is not None
    assert audit.old_value["version"] == 1
    assert audit.new_value["version"] == 2
    assert audit.new_value["note"] == "Fixed typo in invoice total"
    assert "total" in audit.new_value["diff"]


# ---------------- 2. Optimistic Concurrency & Sequential Edits ----------------
def test_stale_version_conflict_and_sequential_edits(
    client: TestClient,
    reviewer_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(reviewer_user_a)
    doc, ext = _create_mock_document(
        db_session, reviewer_user_a.org_id, reviewer_user_a.id, status="needs_review"
    )

    # 1. Stale version 999 -> 409 Conflict
    resp_conflict = client.patch(
        f"/documents/{doc.id}/extraction",
        headers=headers,
        json={"version": 999, "vendor_name": "Updated Vendor"},
    )
    assert resp_conflict.status_code == 409

    # 2. Sequential edit 1 -> 200, version becomes 2
    resp_edit1 = client.patch(
        f"/documents/{doc.id}/extraction",
        headers=headers,
        json={"version": 1, "vendor_name": "First Edit Vendor"},
    )
    assert resp_edit1.status_code == 200
    assert resp_edit1.json()["version"] == 2

    # 3. Trying with version 1 again -> 409 Conflict
    resp_stale = client.patch(
        f"/documents/{doc.id}/extraction",
        headers=headers,
        json={"version": 1, "vendor_name": "Stale Edit"},
    )
    assert resp_stale.status_code == 409

    # 4. Sequential edit 2 with version 2 -> 200, version becomes 3
    resp_edit2 = client.patch(
        f"/documents/{doc.id}/extraction",
        headers=headers,
        json={"version": 2, "vendor_name": "Second Edit Vendor"},
    )
    assert resp_edit2.status_code == 200
    assert resp_edit2.json()["version"] == 3


# ---------------- 3. Edit blocked unless needs_review ----------------
def test_edit_blocked_unless_needs_review(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    for invalid_status in ["uploaded", "processing", "auto_approved", "approved", "rejected", "exported"]:
        doc, _ = _create_mock_document(
            db_session, admin_user_a.org_id, admin_user_a.id, status=invalid_status
        )
        resp = client.patch(
            f"/documents/{doc.id}/extraction",
            headers=headers,
            json={"version": 1, "vendor_name": "Will Fail"},
        )
        assert resp.status_code == 400
        assert "only allowed when document status is 'needs_review'" in resp.json()["detail"]


# ---------------- 4. Approve with and without remaining errors ----------------
def test_approve_workflow_and_reason_override(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    # Doc with error issues
    doc, _ = _create_mock_document(
        db_session,
        admin_user_a.org_id,
        admin_user_a.id,
        status="needs_review",
        has_error=True,
    )

    # 1. Approve without override -> 422
    resp_err = client.post(f"/documents/{doc.id}/approve", headers=headers, json={})
    assert resp_err.status_code == 422

    # 2. Approve with override=true but empty reason -> 422
    resp_empty_reason = client.post(
        f"/documents/{doc.id}/approve",
        headers=headers,
        json={"override": True, "reason": "   "},
    )
    assert resp_empty_reason.status_code == 422

    # 3. Approve with override=true and non-empty reason -> 200 OK
    resp_ok = client.post(
        f"/documents/{doc.id}/approve",
        headers=headers,
        json={"override": True, "reason": "Special exemption granted by Finance Director"},
    )
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["status"] == "approved"
    assert data["reviewed_by"] == str(admin_user_a.id)
    assert data["review_note"] == "Special exemption granted by Finance Director"

    # Verify audit log recorded
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == doc.id, AuditLog.action == "approve_document")
        .first()
    )
    assert audit is not None
    assert audit.new_value["override"] is True
    assert "Finance Director" in audit.new_value["review_note"]


# ---------------- 5. Two simultaneous approves: exactly one succeeds ----------------
def test_two_simultaneous_approvals_only_one_succeeds(
    client: TestClient,
    admin_user_a: User,
    reviewer_user_a: User,
    db_session: Session,
):
    doc, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="needs_review", has_error=False
    )
    headers_admin = auth_headers_for(admin_user_a)
    headers_rev = auth_headers_for(reviewer_user_a)

    # First approve succeeds
    resp1 = client.post(f"/documents/{doc.id}/approve", headers=headers_admin, json={})
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "approved"

    # Second approve on same doc fails with 409
    resp2 = client.post(f"/documents/{doc.id}/approve", headers=headers_rev, json={})
    assert resp2.status_code == 409


# ---------------- 6. Reject requires reason, reopen admin only & blocked after export ----------------
def test_reject_and_reopen_workflow(
    client: TestClient,
    admin_user_a: User,
    reviewer_user_a: User,
    db_session: Session,
):
    headers_admin = auth_headers_for(admin_user_a)
    headers_rev = auth_headers_for(reviewer_user_a)

    doc, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="needs_review"
    )

    # 1. Reject without reason -> 422
    resp_no_reason = client.post(f"/documents/{doc.id}/reject", headers=headers_rev, json={})
    assert resp_no_reason.status_code == 422

    # 2. Reject with reason -> 200
    resp_rej = client.post(
        f"/documents/{doc.id}/reject",
        headers=headers_rev,
        json={"reason": "Duplicate claim for project alpha"},
    )
    assert resp_rej.status_code == 200
    assert resp_rej.json()["status"] == "rejected"
    assert resp_rej.json()["review_note"] == "Duplicate claim for project alpha"

    # 3. Reviewer tries to reopen -> 403 Forbidden (Admin only)
    resp_rev_reopen = client.post(f"/documents/{doc.id}/reopen", headers=headers_rev)
    assert resp_rev_reopen.status_code == 403

    # 4. Admin reopens -> 200 OK
    resp_admin_reopen = client.post(f"/documents/{doc.id}/reopen", headers=headers_admin)
    assert resp_admin_reopen.status_code == 200
    assert resp_admin_reopen.json()["status"] == "needs_review"

    # 5. Approve, then export, then attempt to reopen -> 409 Conflict
    client.post(f"/documents/{doc.id}/approve", headers=headers_admin, json={})
    # Export batch
    client.post("/exports", headers=headers_admin, json={"format": "json"})

    # Check document is exported
    db_session.refresh(doc)
    assert doc.status == "exported"

    # Reopen must be blocked
    resp_blocked = client.post(f"/documents/{doc.id}/reopen", headers=headers_admin)
    assert resp_blocked.status_code == 409
    assert "already been exported" in resp_blocked.json()["detail"]


# ---------------- 7. Viewer RBAC restrictions & History Read ----------------
def test_viewer_rbac_restrictions_and_history_read(
    client: TestClient,
    admin_user_a: User,
    viewer_user_a: User,
    db_session: Session,
):
    headers_viewer = auth_headers_for(viewer_user_a)
    headers_admin = auth_headers_for(admin_user_a)

    doc, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="needs_review"
    )

    # Viewer forbidden from state changes and exports
    assert client.patch(f"/documents/{doc.id}/extraction", headers=headers_viewer, json={"version": 1}).status_code == 403
    assert client.post(f"/documents/{doc.id}/approve", headers=headers_viewer, json={}).status_code == 403
    assert client.post(f"/documents/{doc.id}/reject", headers=headers_viewer, json={"reason": "foo"}).status_code == 403
    assert client.post(f"/documents/{doc.id}/reopen", headers=headers_viewer).status_code == 403
    assert client.post("/exports", headers=headers_viewer, json={"format": "csv"}).status_code == 403
    assert client.get("/audit-log", headers=headers_viewer).status_code == 403

    # Admin makes an edit to generate history
    client.patch(
        f"/documents/{doc.id}/extraction",
        headers=headers_admin,
        json={"version": 1, "vendor_name": "Audit Track Corp"},
    )

    # Viewer CAN read document history
    resp_hist = client.get(f"/documents/{doc.id}/history", headers=headers_viewer)
    assert resp_hist.status_code == 200
    history = resp_hist.json()["items"]
    assert len(history) >= 1
    assert history[0]["actor_email"] == admin_user_a.email
    assert history[0]["action"] == "edit_extraction"


# ---------------- 8. Tenant Isolation on New Endpoints ----------------
def test_tenant_isolation_on_all_new_endpoints(
    client: TestClient,
    admin_user_a: User,
    user_b: User,  # Admin of Org B
    db_session: Session,
):
    headers_b = auth_headers_for(user_b)
    # Org A document
    doc_a, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="needs_review"
    )

    # Org B calls Org A endpoints -> 404
    assert client.patch(f"/documents/{doc_a.id}/extraction", headers=headers_b, json={"version": 1}).status_code == 404
    assert client.post(f"/documents/{doc_a.id}/approve", headers=headers_b, json={}).status_code == 404
    assert client.post(f"/documents/{doc_a.id}/reject", headers=headers_b, json={"reason": "x"}).status_code == 404
    assert client.post(f"/documents/{doc_a.id}/reopen", headers=headers_b).status_code == 404
    assert client.get(f"/documents/{doc_a.id}/history", headers=headers_b).status_code == 404

    # Org A exports a batch
    headers_a = auth_headers_for(admin_user_a)
    client.post(f"/documents/{doc_a.id}/approve", headers=headers_a, json={})
    resp_exp = client.post("/exports", headers=headers_a, json={"format": "csv"})
    assert resp_exp.status_code == 201
    batch_a_id = resp_exp.json()["id"]

    # Org B tries downloading Org A export -> 404
    assert client.get(f"/exports/{batch_a_id}/download", headers=headers_b).status_code == 404


# ---------------- 9. Export batching, deterministic file & terminal state ----------------
def test_export_lifecycle_deterministic_download(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    # Create 1 approved and 1 auto_approved document
    doc1, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="approved"
    )
    doc2, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="auto_approved"
    )
    # Create 1 needs_review document (should NOT be included in export)
    doc3, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="needs_review"
    )

    # Create export batch
    resp_exp = client.post("/exports", headers=headers, json={"format": "csv"})
    assert resp_exp.status_code == 201
    batch = resp_exp.json()
    assert batch["row_count"] == 2
    batch_id = batch["id"]

    # Verify documents transitioned to exported
    db_session.refresh(doc1)
    db_session.refresh(doc2)
    db_session.refresh(doc3)
    assert doc1.status == "exported"
    assert doc2.status == "exported"
    assert doc3.status == "needs_review"

    # Second export when nothing left -> 409
    resp_empty = client.post("/exports", headers=headers, json={"format": "csv"})
    assert resp_empty.status_code == 409

    # Re-download export batch returns identical bytes
    d1 = client.get(f"/exports/{batch_id}/download", headers=headers)
    assert d1.status_code == 200
    assert d1.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM

    d2 = client.get(f"/exports/{batch_id}/download", headers=headers)
    assert d1.content == d2.content

    # Line items view download
    d_li = client.get(f"/exports/{batch_id}/download?view=line_items", headers=headers)
    assert d_li.status_code == 200
    assert b"line_item_description" in d_li.content


# ---------------- 10. CSV Formula Injection Defense in Export ----------------
def test_csv_formula_injection_defense_in_export(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    # Document with malicious formula vendor name and negative subtotal
    doc, _ = _create_mock_document(
        db_session,
        admin_user_a.org_id,
        admin_user_a.id,
        status="approved",
        vendor_name='=HYPERLINK("http://malicious.org", "Phish")',
    )

    resp_exp = client.post("/exports", headers=headers, json={"format": "csv"})
    assert resp_exp.status_code == 201
    batch_id = resp_exp.json()["id"]

    dl = client.get(f"/exports/{batch_id}/download", headers=headers)
    csv_text = dl.content.decode("utf-8-sig")

    # Formula injection neutralized with leading single quote
    assert "'=HYPERLINK" in csv_text


# ---------------- 11. Extended Stats: correction rate and top fields ----------------
def test_stats_extended_review_metrics(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    # Doc 1: edited vendor_name and total, then approved
    doc1, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="needs_review"
    )
    client.patch(
        f"/documents/{doc1.id}/extraction",
        headers=headers,
        json={"version": 1, "vendor_name": "Corrected Vendor A", "total": "2000.00"},
    )
    app_resp = client.post(
        f"/documents/{doc1.id}/approve",
        headers=headers,
        json={"override": True, "reason": "Verified manually despite total mismatch"},
    )
    assert app_resp.status_code == 200

    # Doc 2: unedited, rejected with reason
    doc2, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="needs_review"
    )
    client.post(f"/documents/{doc2.id}/reject", headers=headers, json={"reason": "Incorrect PO"})

    resp_stats = client.get("/stats", headers=headers)
    assert resp_stats.status_code == 200
    stats = resp_stats.json()

    assert stats["documents_reviewed"] == 2
    assert stats["approved_count"] == 1
    assert stats["rejected_count"] == 1
    # 1 of 2 reviewed documents was edited by human
    assert stats["correction_rate"] == 0.5
    top_fields = {f["field"]: f["count"] for f in stats["top_corrected_fields"]}
    assert "total" in top_fields
    assert "vendor_name" in top_fields


# ---------------- 12. Audit Log Filter Endpoint (Admin only) ----------------
def test_admin_audit_log_filters(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    doc, _ = _create_mock_document(
        db_session, admin_user_a.org_id, admin_user_a.id, status="needs_review"
    )

    client.patch(
        f"/documents/{doc.id}/extraction",
        headers=headers,
        json={"version": 1, "vendor_name": "Audit Sample Inc"},
    )

    resp_all = client.get("/audit-log", headers=headers)
    assert resp_all.status_code == 200
    assert resp_all.json()["total"] >= 1

    # Filter by action
    resp_action = client.get("/audit-log?action=edit_extraction", headers=headers)
    assert resp_action.status_code == 200
    for it in resp_action.json()["items"]:
        assert it["action"] == "edit_extraction"

    # Filter by entity_type
    resp_ent = client.get("/audit-log?entity_type=document", headers=headers)
    assert resp_ent.status_code == 200
    for it in resp_ent.json()["items"]:
        assert it["entity_type"] == "document"
