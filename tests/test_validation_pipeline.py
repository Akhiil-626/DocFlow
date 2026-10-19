import json
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.llm import LLMClient, MockLLMClient
from app.models import (
    AuditLog,
    Document,
    Extraction,
    InvalidStatusTransitionError,
    User,
    ValidationIssue,
    transition_document_status,
)
from app.storage import Storage
from app.worker.tasks import process_document
from tests.conftest import auth_headers_for

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


class DynamicMockLLMClient(LLMClient):
    """Mock LLM client that returns the invoice's true data from matching .json ground truth."""

    def __init__(self, filename: str):
        self.filename = filename

    def extract_invoice(self, text: str) -> tuple[dict, dict]:
        json_path = SAMPLES_DIR / f"{Path(self.filename).stem}.json"
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            # Remove testing metadata keys if present
            clean_data = {k: v for k, v in data.items() if k not in ["expected_status", "expected_issues"]}
            return clean_data, {"model": "dynamic-mock", "input_tokens": 100, "output_tokens": 100, "latency_ms": 5}
        return MockLLMClient().extract_invoice(text)


# ---------------- 1. Clean Invoice -> auto_approved ----------------
def test_clean_invoice_auto_approved(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    pdf_path = SAMPLES_DIR / "invoice_01.pdf"

    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    with patch("app.routers.documents.process_document.delay"):
        resp = client.post(
            "/documents",
            headers=headers,
            files={"file": ("invoice_01.pdf", file_bytes, "application/pdf")},
        )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    # Process with dynamic mock returning invoice_01 valid extraction
    result = process_document(
        doc_id,
        override_llm_client=DynamicMockLLMClient("invoice_01.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )
    assert result is not None

    db_doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    assert db_doc.status == "auto_approved"
    assert db_doc.review_reason is None
    assert db_doc.validated_at is not None

    # Audit log check
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(doc_id), AuditLog.action == "document_auto_approved")
        .first()
    )
    assert audit is not None


# ---------------- 2. Wrong Total -> needs_review with TOTAL_MISMATCH ----------------
def test_wrong_total_needs_review(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    pdf_path = SAMPLES_DIR / "bad_invoice_01.pdf"

    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    with patch("app.routers.documents.process_document.delay"):
        resp = client.post(
            "/documents",
            headers=headers,
            files={"file": ("bad_invoice_01.pdf", file_bytes, "application/pdf")},
        )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    result = process_document(
        doc_id,
        override_llm_client=DynamicMockLLMClient("bad_invoice_01.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )
    assert result is not None

    db_doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    assert db_doc.status == "needs_review"
    assert "TOTAL_MISMATCH" in (db_doc.review_reason or "")

    # Validation issues table check
    issues = (
        db_session.query(ValidationIssue)
        .filter(ValidationIssue.document_id == uuid.UUID(doc_id))
        .all()
    )
    codes = [i.code for i in issues]
    assert "TOTAL_MISMATCH" in codes

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(doc_id), AuditLog.action == "document_needs_review")
        .first()
    )
    assert audit is not None


# ---------------- 3. Exact File Uploaded Twice -> Second is Flagged ----------------
def test_exact_file_duplicate_flagged(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    pdf_path = SAMPLES_DIR / "invoice_01.pdf"

    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    # Upload 1
    with patch("app.routers.documents.process_document.delay"):
        resp1 = client.post(
            "/documents",
            headers=headers,
            files={"file": ("invoice_01.pdf", file_bytes, "application/pdf")},
        )
    assert resp1.status_code == 201
    doc1_id = resp1.json()["id"]

    process_document(
        doc1_id,
        override_llm_client=DynamicMockLLMClient("invoice_01.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )
    doc1 = db_session.query(Document).filter(Document.id == uuid.UUID(doc1_id)).first()
    assert doc1.status == "auto_approved"

    # Upload 2 (exact same file)
    with patch("app.routers.documents.process_document.delay"):
        resp2 = client.post(
            "/documents",
            headers=headers,
            files={"file": ("invoice_01_duplicate.pdf", file_bytes, "application/pdf")},
        )
    assert resp2.status_code == 201
    # Uploader gets the existing document id in the response
    assert resp2.json()["existing_document_id"] == doc1_id
    doc2_id = resp2.json()["id"]

    # Process second document
    process_document(
        doc2_id,
        override_llm_client=DynamicMockLLMClient("invoice_01.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )
    doc2 = db_session.query(Document).filter(Document.id == uuid.UUID(doc2_id)).first()
    assert doc2.status == "needs_review"
    assert "DUPLICATE_SUSPECTED" in (doc2.review_reason or "")

    issues2 = (
        db_session.query(ValidationIssue)
        .filter(ValidationIssue.document_id == uuid.UUID(doc2_id))
        .all()
    )
    assert any(i.code == "DUPLICATE_SUSPECTED" and doc1_id in i.message for i in issues2)


# ---------------- 4. Semantic Duplicate -> DUPLICATE_SUSPECTED ----------------
def test_semantic_duplicate_flagged(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    pdf_base = SAMPLES_DIR / "bad_invoice_09.pdf"
    pdf_dup = SAMPLES_DIR / "bad_invoice_10.pdf"

    with open(pdf_base, "rb") as f:
        bytes_base = f.read()
    with open(pdf_dup, "rb") as f:
        bytes_dup = f.read()

    # Upload & process base invoice (bad_invoice_09)
    with patch("app.routers.documents.process_document.delay"):
        resp1 = client.post(
            "/documents",
            headers=headers,
            files={"file": ("bad_invoice_09.pdf", bytes_base, "application/pdf")},
        )
    doc1_id = resp1.json()["id"]

    process_document(
        doc1_id,
        override_llm_client=DynamicMockLLMClient("bad_invoice_09.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )

    # Upload & process second invoice (bad_invoice_10: different file, same invoice_number, vendor, total)
    with patch("app.routers.documents.process_document.delay"):
        resp2 = client.post(
            "/documents",
            headers=headers,
            files={"file": ("bad_invoice_10.pdf", bytes_dup, "application/pdf")},
        )
    doc2_id = resp2.json()["id"]

    process_document(
        doc2_id,
        override_llm_client=DynamicMockLLMClient("bad_invoice_10.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )

    doc2 = db_session.query(Document).filter(Document.id == uuid.UUID(doc2_id)).first()
    assert doc2.status == "needs_review"
    assert "DUPLICATE_SUSPECTED" in (doc2.review_reason or "")

    issues = (
        db_session.query(ValidationIssue)
        .filter(ValidationIssue.document_id == uuid.UUID(doc2_id), ValidationIssue.code == "DUPLICATE_SUSPECTED")
        .all()
    )
    assert len(issues) >= 1
    assert doc1_id in issues[0].message


# ---------------- 5. Tenant Isolation: Same Invoice in Org B is NOT Duplicate ----------------
def test_cross_tenant_duplicate_isolation(
    client: TestClient,
    admin_user_a: User,
    user_b: User,
    temp_storage: Storage,
    db_session: Session,
):
    headers_a = auth_headers_for(admin_user_a)
    headers_b = auth_headers_for(user_b)
    pdf_path = SAMPLES_DIR / "invoice_01.pdf"

    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    # Org A uploads & processes invoice_01
    with patch("app.routers.documents.process_document.delay"):
        resp_a = client.post(
            "/documents",
            headers=headers_a,
            files={"file": ("invoice_01.pdf", file_bytes, "application/pdf")},
        )
    doc_a_id = resp_a.json()["id"]
    process_document(
        doc_a_id,
        override_llm_client=DynamicMockLLMClient("invoice_01.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )

    # Org B uploads same file -> existing_document_id must NOT be disclosed
    with patch("app.routers.documents.process_document.delay"):
        resp_b = client.post(
            "/documents",
            headers=headers_b,
            files={"file": ("invoice_01.pdf", file_bytes, "application/pdf")},
        )
    assert resp_b.status_code == 201
    assert resp_b.json()["existing_document_id"] is None
    doc_b_id = resp_b.json()["id"]

    # Org B processes document
    process_document(
        doc_b_id,
        override_llm_client=DynamicMockLLMClient("invoice_01.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )
    doc_b = db_session.query(Document).filter(Document.id == uuid.UUID(doc_b_id)).first()
    # Org B document must be auto_approved and NOT flagged as duplicate
    assert doc_b.status == "auto_approved"
    assert doc_b.review_reason is None


# ---------------- 6. Re-running Task Replaces Issues (Idempotency) ----------------
def test_rerunning_task_does_not_duplicate_issues(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)
    pdf_path = SAMPLES_DIR / "bad_invoice_01.pdf"

    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    with patch("app.routers.documents.process_document.delay"):
        resp = client.post(
            "/documents",
            headers=headers,
            files={"file": ("bad_invoice_01.pdf", file_bytes, "application/pdf")},
        )
    doc_id = resp.json()["id"]

    # Run 1
    process_document(
        doc_id,
        override_llm_client=DynamicMockLLMClient("bad_invoice_01.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )
    issues_run1 = (
        db_session.query(ValidationIssue)
        .filter(ValidationIssue.document_id == uuid.UUID(doc_id))
        .all()
    )
    count1 = len(issues_run1)
    assert count1 >= 1

    # Reset to uploaded to simulate reprocessing
    doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    doc.status = "uploaded"
    db_session.commit()

    # Run 2
    process_document(
        doc_id,
        override_llm_client=DynamicMockLLMClient("bad_invoice_01.pdf"),
        override_storage=temp_storage,
        override_db=db_session,
    )
    issues_run2 = (
        db_session.query(ValidationIssue)
        .filter(ValidationIssue.document_id == uuid.UUID(doc_id))
        .all()
    )
    count2 = len(issues_run2)
    # Count should not double
    assert count2 == count1


# ---------------- 7. State Machine Invalid Transitions Raise Error ----------------
def test_invalid_status_transitions():
    doc = Document(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        original_filename="test.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="abc",
        storage_key="k",
        status="uploaded",
    )

    # uploaded -> extracted is invalid
    with pytest.raises(InvalidStatusTransitionError):
        transition_document_status(doc, "extracted")

    # uploaded -> processing is valid
    transition_document_status(doc, "processing")
    assert doc.status == "processing"

    # processing -> auto_approved is invalid
    with pytest.raises(InvalidStatusTransitionError):
        transition_document_status(doc, "auto_approved")

    # processing -> extracted is valid
    transition_document_status(doc, "extracted")
    assert doc.status == "extracted"

    # extracted -> uploaded is invalid
    with pytest.raises(InvalidStatusTransitionError):
        transition_document_status(doc, "uploaded")


# ---------------- 8. Review Queue: Oldest First & Role Access ----------------
def test_review_queue_endpoint_and_roles(
    client: TestClient,
    admin_user_a: User,
    reviewer_user_a: User,
    viewer_user_a: User,
    user_b: User,
    temp_storage: Storage,
    db_session: Session,
):
    headers_admin = auth_headers_for(admin_user_a)
    headers_reviewer = auth_headers_for(reviewer_user_a)
    headers_viewer = auth_headers_for(viewer_user_a)
    headers_b = auth_headers_for(user_b)

    # Upload bad invoice 1 and 2 for Org A
    for fname in ["bad_invoice_01.pdf", "bad_invoice_02.pdf"]:
        with open(SAMPLES_DIR / fname, "rb") as f:
            b = f.read()
        with patch("app.routers.documents.process_document.delay"):
            r = client.post("/documents", headers=headers_admin, files={"file": (fname, b, "application/pdf")})
        process_document(
            r.json()["id"],
            override_llm_client=DynamicMockLLMClient(fname),
            override_storage=temp_storage,
            override_db=db_session,
        )

    # Admin and Reviewer can access review queue
    resp_admin = client.get("/documents/review-queue", headers=headers_admin)
    assert resp_admin.status_code == 200
    queue_admin = resp_admin.json()
    assert queue_admin["total"] == 2
    # Oldest first: items[0] created_at <= items[1] created_at
    assert queue_admin["items"][0]["created_at"] <= queue_admin["items"][1]["created_at"]
    assert queue_admin["items"][0]["issue_count"] >= 1

    resp_reviewer = client.get("/documents/review-queue", headers=headers_reviewer)
    assert resp_reviewer.status_code == 200

    # Viewer role cannot access review queue (403 Forbidden)
    resp_viewer = client.get("/documents/review-queue", headers=headers_viewer)
    assert resp_viewer.status_code == 403

    # Org B sees empty queue (tenant isolation)
    resp_b = client.get("/documents/review-queue", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["total"] == 0


# ---------------- 9. GET /stats Endpoint & Role Access ----------------
def test_stats_endpoint(
    client: TestClient,
    admin_user_a: User,
    viewer_user_a: User,
    temp_storage: Storage,
    db_session: Session,
):
    headers_admin = auth_headers_for(admin_user_a)
    headers_viewer = auth_headers_for(viewer_user_a)

    # Upload 1 clean invoice (auto_approved) and 1 bad invoice (needs_review)
    for fname in ["invoice_01.pdf", "bad_invoice_01.pdf"]:
        with open(SAMPLES_DIR / fname, "rb") as f:
            b = f.read()
        with patch("app.routers.documents.process_document.delay"):
            r = client.post("/documents", headers=headers_admin, files={"file": (fname, b, "application/pdf")})
        process_document(
            r.json()["id"],
            override_llm_client=DynamicMockLLMClient(fname),
            override_storage=temp_storage,
            override_db=db_session,
        )

    # Viewer can access /stats
    resp_viewer = client.get("/stats", headers=headers_viewer)
    assert resp_viewer.status_code == 200
    stats = resp_viewer.json()
    assert stats["total"] == 2
    assert stats["counts"]["auto_approved"] == 1
    assert stats["counts"]["needs_review"] == 1
    assert stats["auto_approval_rate"] == 0.5
