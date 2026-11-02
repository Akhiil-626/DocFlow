import json
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.llm import LLMClient, PermanentLLMError
from app.models import (
    AuditLog,
    Document,
    Extraction,
    ExtractionAttempt,
    Organization,
    User,
    ValidationIssue,
)
from app.routing import (
    CRITICAL_FIELDS,
    DEFAULT_ROUTING_ESCALATE_CODES,
    DOCUMENT_CODES,
    WARNING_CODES,
    decide_escalation,
    get_critical_fields_diff,
)
from app.storage import Storage
from app.worker.tasks import process_document
from tests.conftest import auth_headers_for

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


class FakeLLMClient(LLMClient):
    """Configurable fake LLM client for tests."""

    def __init__(
        self,
        extraction_data: dict | None = None,
        model_name: str = "fake-model",
        latency_ms: int = 50,
        input_tokens: int = 120,
        output_tokens: int = 80,
        error_to_raise: Exception | None = None,
    ):
        self.extraction_data = extraction_data or {}
        self.model_name = model_name
        self.latency_ms = latency_ms
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.error_to_raise = error_to_raise

    def extract_invoice(self, text: str) -> tuple[dict, dict]:
        if self.error_to_raise:
            raise self.error_to_raise
        usage = {
            "model": self.model_name,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
        return dict(self.extraction_data), usage


# ---------------- 1. decide_escalation table tests ----------------

@pytest.mark.parametrize(
    "issue_code,expected_escalate",
    [
        ("TOTAL_MISMATCH", True),
        ("LINE_ITEM_AMOUNT_MISMATCH", True),
        ("LINE_ITEMS_SUM_MISMATCH", True),
        ("MISSING_VENDOR_NAME", True),
        ("MISSING_INVOICE_NUMBER", True),
        ("NO_LINE_ITEMS", True),
        ("FUTURE_INVOICE_DATE", False),
        ("MISSING_GSTIN", False),
        ("OLD_INVOICE_DATE", False),
        ("CGST_SGST_MISMATCH", False),
        ("UNEXPECTED_TAX_RATE", False),
        ("DUPLICATE_SUSPECTED", False),
        ("EXACT_DUPLICATE", False),
        ("SEMANTIC_DUPLICATE", False),
        ("UNKNOWN_CODE", False),
    ],
)
def test_decide_escalation_table_codes(issue_code: str, expected_escalate: bool):
    escalate, reason = decide_escalation(
        issue_codes=[issue_code],
        attempt_number=1,
        elapsed_seconds=10.0,
    )
    assert escalate is expected_escalate
    if expected_escalate:
        assert f"escalate_code_{issue_code}" == reason
    else:
        assert reason == "no_escalate_code"


def test_decide_escalation_never_beyond_maximum():
    # Attempt 1 escalates
    esc_1, _ = decide_escalation(["TOTAL_MISMATCH"], attempt_number=1, elapsed_seconds=10.0)
    assert esc_1 is True

    # Attempt 2 exceeds default max_escalations=1
    esc_2, reason_2 = decide_escalation(["TOTAL_MISMATCH"], attempt_number=2, elapsed_seconds=10.0)
    assert esc_2 is False
    assert reason_2 == "max_escalations_reached"


def test_decide_escalation_respects_time_cap():
    # Within 180s cap
    esc_ok, _ = decide_escalation(["TOTAL_MISMATCH"], attempt_number=1, elapsed_seconds=179.9)
    assert esc_ok is True

    # Exactly at or over 180s cap
    esc_cap, reason_cap = decide_escalation(["TOTAL_MISMATCH"], attempt_number=1, elapsed_seconds=180.0)
    assert esc_cap is False
    assert reason_cap == "time_cap_exceeded"

    esc_over, reason_over = decide_escalation(["TOTAL_MISMATCH"], attempt_number=1, elapsed_seconds=205.5)
    assert esc_over is False
    assert reason_over == "time_cap_exceeded"


def test_decide_escalation_with_objects_and_severities():
    # ValidationIssue object with error
    iss_err = ValidationIssue(code="TOTAL_MISMATCH", severity="error", message="Total mismatch")
    iss_warn = ValidationIssue(code="MISSING_GSTIN", severity="warning", message="GSTIN missing")

    assert decide_escalation([iss_err], 1, 5.0)[0] is True
    assert decide_escalation([iss_warn], 1, 5.0)[0] is False
    assert decide_escalation([iss_err, iss_warn], 1, 5.0)[0] is True

    # Dict representation
    dict_err = {"code": "LINE_ITEM_AMOUNT_MISMATCH", "severity": "error"}
    dict_warn = {"code": "OLD_INVOICE_DATE", "severity": "warning"}
    assert decide_escalation([dict_err], 1, 5.0)[0] is True
    assert decide_escalation([dict_warn], 1, 5.0)[0] is False


def test_decide_escalation_custom_config():
    custom_cfg = {
        "ROUTING_MAX_ESCALATIONS": 2,
        "ROUTING_MAX_SECONDS_PER_DOCUMENT": 60.0,
        "ROUTING_ESCALATE_CODES": ["TOTAL_MISMATCH"],
    }
    # Attempt 2 allowed when max_escalations=2
    assert decide_escalation(["TOTAL_MISMATCH"], 2, 30.0, custom_cfg)[0] is True
    # Attempt 3 blocked
    assert decide_escalation(["TOTAL_MISMATCH"], 3, 30.0, custom_cfg)[0] is False
    # Time cap at 60s
    assert decide_escalation(["TOTAL_MISMATCH"], 1, 60.1, custom_cfg)[0] is False


# ---------------- 2. Tier 1 Permanent Failure Escalates ----------------

def test_tier1_permanent_failure_escalates(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTING_MODELS", "llama3.2:3b,llama3.1:8b")

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
    doc_id = resp.json()["id"]

    # Tier 1 fails permanently; Tier 2 provides clean extraction
    tier1_client = FakeLLMClient(
        model_name="llama3.2:3b",
        error_to_raise=PermanentLLMError("LLM output is not valid JSON after repair retry"),
    )
    with open(SAMPLES_DIR / "invoice_01.json", encoding="utf-8") as f:
        valid_data = json.load(f)

    tier2_client = FakeLLMClient(
        extraction_data=valid_data,
        model_name="llama3.1:8b",
        latency_ms=2500,
    )

    result = process_document(
        doc_id,
        override_llm_client=tier1_client,
        override_tier2_llm_client=tier2_client,
        override_storage=temp_storage,
        override_db=db_session,
    )
    assert result is not None

    db_doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    assert db_doc.status == "auto_approved"

    # Verify attempts
    attempts = (
        db_session.query(ExtractionAttempt)
        .filter(ExtractionAttempt.document_id == uuid.UUID(doc_id))
        .order_by(ExtractionAttempt.attempt_no.asc())
        .all()
    )
    assert len(attempts) == 2
    assert attempts[0].attempt_no == 1
    assert attempts[0].model == "llama3.2:3b"
    assert attempts[0].escalation_reason == "tier1_failed"
    assert attempts[0].validation_error_codes == ["TIER1_FAILED"]

    assert attempts[1].attempt_no == 2
    assert attempts[1].model == "llama3.1:8b"
    assert attempts[1].escalation_reason is None

    # Verify audit log
    audit_escalated = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(doc_id), AuditLog.action == "model_escalated")
        .first()
    )
    assert audit_escalated is not None
    assert audit_escalated.new_value["escalation_reason"] == "tier1_failed"


# ---------------- 3. Tier 2 Unavailable Falls Back to Tier 1 ----------------

def test_tier2_unavailable_falls_back_to_tier1(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTING_MODELS", "llama3.2:3b,llama3.1:8b")

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

    with open(SAMPLES_DIR / "bad_invoice_01.json", encoding="utf-8") as f:
        bad_data = json.load(f)

    tier1_client = FakeLLMClient(
        extraction_data=bad_data,
        model_name="llama3.2:3b",
        latency_ms=1200,
    )
    tier2_client = FakeLLMClient(
        model_name="llama3.1:8b",
        error_to_raise=RuntimeError("Ollama model llama3.1:8b not found"),
    )

    result = process_document(
        doc_id,
        override_llm_client=tier1_client,
        override_tier2_llm_client=tier2_client,
        override_storage=temp_storage,
        override_db=db_session,
    )
    assert result is not None

    db_doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    assert db_doc.status == "needs_review"
    assert db_doc.review_reason == "escalation_unavailable"

    # Extraction model is tier 1
    ext = db_session.query(Extraction).filter(Extraction.document_id == uuid.UUID(doc_id)).first()
    assert ext.model == "llama3.2:3b"

    # Validation issues are tier 1 issues
    issues = (
        db_session.query(ValidationIssue)
        .filter(ValidationIssue.document_id == uuid.UUID(doc_id))
        .all()
    )
    codes = [i.code for i in issues]
    assert "TOTAL_MISMATCH" in codes


# ---------------- 4. Idempotent Re-run ----------------

def test_idempotent_rerun(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTING_MODELS", "llama3.2:3b,llama3.1:8b")

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
    doc_id = resp.json()["id"]

    # Run 1: Tier 1 has TOTAL_MISMATCH, escalates to Tier 2 which succeeds
    with open(SAMPLES_DIR / "bad_invoice_01.json", encoding="utf-8") as f:
        bad_data = json.load(f)
    with open(SAMPLES_DIR / "invoice_01.json", encoding="utf-8") as f:
        good_data = json.load(f)

    t1 = FakeLLMClient(extraction_data=bad_data, model_name="llama3.2:3b")
    t2 = FakeLLMClient(extraction_data=good_data, model_name="llama3.1:8b")

    res1 = process_document(
        doc_id,
        override_llm_client=t1,
        override_tier2_llm_client=t2,
        override_storage=temp_storage,
        override_db=db_session,
    )
    assert res1 is not None

    # Assert exactly 1 extraction and 2 attempts
    ext_count = db_session.query(Extraction).filter(Extraction.document_id == uuid.UUID(doc_id)).count()
    att_count = db_session.query(ExtractionAttempt).filter(ExtractionAttempt.document_id == uuid.UUID(doc_id)).count()
    assert ext_count == 1
    assert att_count == 2

    # Reset status to uploaded and run task a second time
    db_doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    db_doc.status = "uploaded"
    db_session.commit()

    res2 = process_document(
        doc_id,
        override_llm_client=t1,
        override_tier2_llm_client=t2,
        override_storage=temp_storage,
        override_db=db_session,
    )
    assert res2 is not None

    # Check database again: still exactly 1 extraction and 2 attempts
    ext_count_after = db_session.query(Extraction).filter(Extraction.document_id == uuid.UUID(doc_id)).count()
    att_count_after = db_session.query(ExtractionAttempt).filter(ExtractionAttempt.document_id == uuid.UUID(doc_id)).count()
    assert ext_count_after == 1
    assert att_count_after == 2


# ---------------- 5. ROUTING_ENABLED=false Matches Old Behavior ----------------

def test_routing_disabled_matches_old_behavior(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ROUTING_ENABLED", False)

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

    with open(SAMPLES_DIR / "bad_invoice_01.json", encoding="utf-8") as f:
        bad_data = json.load(f)

    t1 = FakeLLMClient(extraction_data=bad_data, model_name="llama3.2:3b")
    # Tier 2 client provided but should NOT be called
    t2 = FakeLLMClient(extraction_data=bad_data, model_name="llama3.1:8b")

    result = process_document(
        doc_id,
        override_llm_client=t1,
        override_tier2_llm_client=t2,
        override_storage=temp_storage,
        override_db=db_session,
    )
    assert result is not None

    db_doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    assert db_doc.status == "needs_review"
    assert "TOTAL_MISMATCH" in db_doc.review_reason
    assert "models_agree" not in db_doc.review_reason
    assert "models_disagree" not in db_doc.review_reason

    # No model_escalated audit log
    audit_escalated = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(doc_id), AuditLog.action == "model_escalated")
        .first()
    )
    assert audit_escalated is None

    # Only 1 attempt recorded
    attempts = (
        db_session.query(ExtractionAttempt)
        .filter(ExtractionAttempt.document_id == uuid.UUID(doc_id))
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].attempt_no == 1
    assert attempts[0].escalation_reason is None


# ---------------- 6. models_agree and models_disagree Notes ----------------

def test_models_agree_note(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTING_MODELS", "llama3.2:3b,llama3.1:8b")

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

    with open(SAMPLES_DIR / "bad_invoice_01.json", encoding="utf-8") as f:
        bad_data = json.load(f)

    # Both models output the identical bad extraction
    t1 = FakeLLMClient(extraction_data=bad_data, model_name="llama3.2:3b")
    t2 = FakeLLMClient(extraction_data=bad_data, model_name="llama3.1:8b")

    process_document(
        doc_id,
        override_llm_client=t1,
        override_tier2_llm_client=t2,
        override_storage=temp_storage,
        override_db=db_session,
    )

    db_doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    assert db_doc.status == "needs_review"
    assert "models_agree: likely a document issue" in db_doc.review_reason


def test_models_disagree_note(
    client: TestClient,
    admin_user_a: User,
    temp_storage: Storage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTING_MODELS", "llama3.2:3b,llama3.1:8b")

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

    with open(SAMPLES_DIR / "bad_invoice_01.json", encoding="utf-8") as f:
        bad_data_1 = json.load(f)

    # Second model returns different invoice_number and total, but still fails validation
    bad_data_2 = dict(bad_data_1)
    bad_data_2["total"] = "9999.99"
    bad_data_2["invoice_number"] = "DIFF-INV-002"

    t1 = FakeLLMClient(extraction_data=bad_data_1, model_name="llama3.2:3b")
    t2 = FakeLLMClient(extraction_data=bad_data_2, model_name="llama3.1:8b")

    process_document(
        doc_id,
        override_llm_client=t1,
        override_tier2_llm_client=t2,
        override_storage=temp_storage,
        override_db=db_session,
    )

    db_doc = db_session.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    assert db_doc.status == "needs_review"
    assert "models_disagree:" in db_doc.review_reason
    assert "invoice_number" in db_doc.review_reason
    assert "total" in db_doc.review_reason


# ---------------- 7. New Stats Fields & API Endpoint ----------------

def test_stats_model_routing_fields(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)

    # Create 2 documents for org_a: 1 non-escalated, 1 escalated
    doc1 = Document(
        id=uuid.uuid4(),
        org_id=admin_user_a.org_id,
        original_filename="d1.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="sha1",
        storage_key="k1",
        status="auto_approved",
    )
    doc2 = Document(
        id=uuid.uuid4(),
        org_id=admin_user_a.org_id,
        original_filename="d2.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="sha2",
        storage_key="k2",
        status="needs_review",
    )
    db_session.add_all([doc1, doc2])
    db_session.flush()

    # Doc1: 1 attempt with llama3.2:3b, latency 1000
    att1_d1 = ExtractionAttempt(
        id=uuid.uuid4(),
        document_id=doc1.id,
        org_id=admin_user_a.org_id,
        attempt_no=1,
        model="llama3.2:3b",
        latency_ms=1000,
        validation_error_codes=[],
    )
    # Doc2: 2 attempts (escalated)
    att1_d2 = ExtractionAttempt(
        id=uuid.uuid4(),
        document_id=doc2.id,
        org_id=admin_user_a.org_id,
        attempt_no=1,
        model="llama3.2:3b",
        latency_ms=1200,
        validation_error_codes=["TOTAL_MISMATCH"],
        escalation_reason="TOTAL_MISMATCH",
    )
    att2_d2 = ExtractionAttempt(
        id=uuid.uuid4(),
        document_id=doc2.id,
        org_id=admin_user_a.org_id,
        attempt_no=2,
        model="llama3.1:8b",
        latency_ms=4000,
        validation_error_codes=["TOTAL_MISMATCH"],
    )
    db_session.add_all([att1_d1, att1_d2, att2_d2])
    db_session.commit()

    resp = client.get("/stats", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Escalation rate: 1 escalated out of 2 docs = 0.5
    assert data["escalation_rate"] == 0.5

    # Attempts by model: 2 for llama3.2:3b, 1 for llama3.1:8b
    assert data["attempts_by_model"] == {"llama3.2:3b": 2, "llama3.1:8b": 1}

    # Average latency: llama3.2:3b = (1000 + 1200) / 2 = 1100.0, llama3.1:8b = 4000.0
    assert data["average_latency_by_model"] == {"llama3.2:3b": 1100.0, "llama3.1:8b": 4000.0}


# ---------------- 8. Tenant Isolation on Attempts ----------------

def test_tenant_isolation_on_attempts(
    client: TestClient,
    admin_user_a: User,
    user_b: User,
    db_session: Session,
):
    headers_a = auth_headers_for(admin_user_a)
    headers_b = auth_headers_for(user_b)

    # Document in Org A
    doc_a = Document(
        id=uuid.uuid4(),
        org_id=admin_user_a.org_id,
        original_filename="doc_a.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="shaa",
        storage_key="ka",
        status="auto_approved",
    )
    # Document in Org B
    doc_b = Document(
        id=uuid.uuid4(),
        org_id=user_b.org_id,
        original_filename="doc_b.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="shab",
        storage_key="kb",
        status="auto_approved",
    )
    db_session.add_all([doc_a, doc_b])
    db_session.flush()

    att_a = ExtractionAttempt(
        id=uuid.uuid4(),
        document_id=doc_a.id,
        org_id=admin_user_a.org_id,
        attempt_no=1,
        model="model-a-only",
        latency_ms=800,
        validation_error_codes=[],
    )
    att_b = ExtractionAttempt(
        id=uuid.uuid4(),
        document_id=doc_b.id,
        org_id=user_b.org_id,
        attempt_no=1,
        model="model-b-only",
        latency_ms=1500,
        validation_error_codes=[],
    )
    db_session.add_all([att_a, att_b])
    db_session.commit()

    # User A cannot access Doc B's extraction
    resp_cross = client.get(f"/documents/{doc_b.id}/extraction", headers=headers_a)
    assert resp_cross.status_code == 404

    # User B's stats must only show model-b-only
    resp_stats_b = client.get("/stats", headers=headers_b)
    assert resp_stats_b.status_code == 200
    stats_b = resp_stats_b.json()
    assert "model-b-only" in stats_b["attempts_by_model"]
    assert "model-a-only" not in stats_b["attempts_by_model"]


# ---------------- 9. GET /documents/{id}/extraction returns attempts ----------------

def test_get_document_extraction_attempts(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    headers = auth_headers_for(admin_user_a)

    doc = Document(
        id=uuid.uuid4(),
        org_id=admin_user_a.org_id,
        original_filename="doc_attempts.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="shax",
        storage_key="kx",
        status="needs_review",
    )
    db_session.add(doc)
    db_session.flush()

    ext = Extraction(
        id=uuid.uuid4(),
        document_id=doc.id,
        org_id=admin_user_a.org_id,
        original_data={"invoice_number": "INV-100", "total": "500.00"},
        data={"invoice_number": "INV-100", "total": "500.00"},
        model="llama3.1:8b",
        version=1,
        latency_ms=3000,
    )
    db_session.add(ext)

    att1 = ExtractionAttempt(
        id=uuid.uuid4(),
        document_id=doc.id,
        org_id=admin_user_a.org_id,
        attempt_no=1,
        model="llama3.2:3b",
        latency_ms=1000,
        validation_error_codes=["TOTAL_MISMATCH"],
        escalation_reason="TOTAL_MISMATCH",
    )
    att2 = ExtractionAttempt(
        id=uuid.uuid4(),
        document_id=doc.id,
        org_id=admin_user_a.org_id,
        attempt_no=2,
        model="llama3.1:8b",
        latency_ms=3000,
        validation_error_codes=["TOTAL_MISMATCH"],
    )
    db_session.add_all([att1, att2])
    db_session.commit()

    resp = client.get(f"/documents/{doc.id}/extraction", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "attempts" in data
    assert len(data["attempts"]) == 2
    assert data["attempts"][0]["attempt_no"] == 1
    assert data["attempts"][0]["model"] == "llama3.2:3b"
    assert data["attempts"][0]["escalation_reason"] == "TOTAL_MISMATCH"
    assert data["attempts"][1]["attempt_no"] == 2
    assert data["attempts"][1]["model"] == "llama3.1:8b"
    assert data["attempts"][1]["escalation_reason"] is None
