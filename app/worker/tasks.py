import io
import logging
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pdfplumber
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.duplicate_detection import detect_duplicates
from app.llm import (
    LLMClient,
    PermanentLLMError,
    TransientLLMError,
    get_llm_client,
)
from app.models import (
    AuditLog,
    Document,
    Extraction,
    ExtractionAttempt,
    LineItem,
    ValidationIssue,
    transition_document_status,
)
from app.routing import decide_escalation, get_critical_fields_diff
from app.storage import LocalStorage, Storage
from app.validation import validate_extraction
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from PDF pages using pdfplumber."""
    extracted_text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    extracted_text += page_text + "\n"
    except Exception as err:
        logger.warning("Error reading PDF content: %s", err)
    return extracted_text.strip()


@celery_app.task(
    bind=True,
    max_retries=3,
    acks_late=True,
    time_limit=420,
    soft_time_limit=390,
)
def process_document(
    self,
    document_id: str,
    override_llm_client: LLMClient | None = None,
    override_storage: Storage | None = None,
    override_db: Session | None = None,
    override_tier2_llm_client: LLMClient | None = None,
    override_llm_clients: dict[str, LLMClient] | None = None,
) -> dict[str, Any] | None:
    """Process an uploaded document: extract text, call LLM, validate rules, and route."""
    db: Session = override_db or SessionLocal()
    storage: Storage = override_storage or LocalStorage(settings.UPLOAD_DIR)

    doc_uuid = uuid.UUID(str(document_id))

    try:
        # 1. Fetch document and execute state transition: uploaded -> processing
        document = db.query(Document).filter(Document.id == doc_uuid).first()
        if not document:
            logger.warning("Document %s not found in database", document_id)
            return None

        if document.status != "uploaded":
            logger.info("Document %s is not in 'uploaded' state (current: '%s'); exiting quietly", document_id, document.status)
            return None

        transition_document_status(document, "processing")
        document.attempts += 1
        db.commit()

        # 2. Read file from storage
        try:
            file_bytes = storage.read(document.storage_key)
        except Exception as err:
            logger.error("Failed to read file for document %s: %s", document_id, err)
            _mark_failed(db, document, f"Failed to read file: {err}")
            return None

        # 3. Check file type and extract text
        if document.content_type != "application/pdf":
            _mark_failed(db, document, "Scanned/image documents not supported yet")
            return None

        extracted_text = extract_text_from_pdf(file_bytes)
        if not extracted_text:
            _mark_failed(db, document, "Scanned/image documents not supported yet")
            return None

        # 4. LLM extraction and routing flow (run attempts in memory)
        start_doc_time = time.time()
        routing_enabled = settings.ROUTING_ENABLED
        models = settings.routing_models_list if routing_enabled else [settings.LLM_MODEL]
        tier1_model = models[0] if models else settings.LLM_MODEL
        tier2_model = models[1] if (routing_enabled and len(models) > 1) else None

        # Resolve tier 1 client
        if override_llm_clients and tier1_model in override_llm_clients:
            tier1_client = override_llm_clients[tier1_model]
        elif override_llm_client:
            tier1_client = override_llm_client
        else:
            tier1_client = get_llm_client(tier1_model)

        tier1_failed = False
        tier1_perm_err = None
        t1_start = time.time()

        try:
            t1_extraction_data, t1_usage = tier1_client.extract_invoice(extracted_text)
            t1_latency_ms = t1_usage.get("latency_ms") or int((time.time() - t1_start) * 1000)
            t1_rule_issues = validate_extraction(t1_extraction_data)
            t1_dup_issues = detect_duplicates(
                db=db,
                org_id=document.org_id,
                document_id=doc_uuid,
                sha256=document.sha256,
                extraction_data=t1_extraction_data,
            )
            t1_all_issues = t1_rule_issues + t1_dup_issues
            t1_issue_codes = list(dict.fromkeys(i.code for i in t1_all_issues))
        except TransientLLMError as transient_err:
            logger.warning("Transient error on document %s: %s. Scheduling retry.", document_id, transient_err)
            transition_document_status(document, "failed")
            transition_document_status(document, "uploaded")
            db.commit()
            raise self.retry(
                exc=transient_err,
                countdown=2 ** (self.request.retries or 1),
            )
        except (PermanentLLMError, Exception) as perm_err:
            if not routing_enabled:
                logger.error("Permanent extraction failure on document %s: %s", document_id, perm_err)
                _mark_failed(db, document, str(perm_err))
                return None
            tier1_failed = True
            tier1_perm_err = perm_err
            t1_extraction_data = {}
            t1_latency_ms = int((time.time() - t1_start) * 1000)
            t1_usage = {
                "model": getattr(tier1_client, "model_name", tier1_model),
                "input_tokens": None,
                "output_tokens": None,
                "latency_ms": t1_latency_ms,
            }
            t1_all_issues = []
            t1_issue_codes = ["TIER1_FAILED"]

        attempt_1_record = {
            "attempt_no": 1,
            "model": t1_usage.get("model", tier1_model),
            "input_tokens": t1_usage.get("input_tokens"),
            "output_tokens": t1_usage.get("output_tokens"),
            "latency_ms": t1_latency_ms,
            "validation_error_codes": t1_issue_codes,
            "escalation_reason": None,
            "extraction_data": t1_extraction_data,
            "usage": t1_usage,
            "issues": t1_all_issues,
            "failed": tier1_failed,
        }
        attempts_in_memory = [attempt_1_record]

        should_escalate = False
        escalation_reason = None
        audit_escalate_entry = None

        if routing_enabled and tier2_model:
            if tier1_failed:
                should_escalate = True
                escalation_reason = "tier1_failed"
            else:
                elapsed = time.time() - start_doc_time
                should_escalate, escalation_reason = decide_escalation(
                    issue_codes=t1_issue_codes,
                    attempt_number=1,
                    elapsed_seconds=elapsed,
                    config=settings,
                )

        if should_escalate:
            attempt_1_record["escalation_reason"] = escalation_reason
            audit_escalate_entry = AuditLog(
                id=uuid.uuid4(),
                org_id=document.org_id,
                user_id=None,
                action="model_escalated",
                entity_type="document",
                entity_id=doc_uuid,
                new_value={
                    "escalation_reason": escalation_reason,
                    "issue_codes": t1_issue_codes,
                },
            )

            # Resolve tier 2 client
            if override_tier2_llm_client:
                tier2_client = override_tier2_llm_client
            elif override_llm_clients and tier2_model in override_llm_clients:
                tier2_client = override_llm_clients[tier2_model]
            else:
                tier2_client = get_llm_client(tier2_model)

            tier2_unavailable = False
            tier2_err_msg = None
            t2_start = time.time()
            try:
                t2_extraction_data, t2_usage = tier2_client.extract_invoice(extracted_text)
                t2_latency_ms = t2_usage.get("latency_ms") or int((time.time() - t2_start) * 1000)
                t2_rule_issues = validate_extraction(t2_extraction_data)
                t2_dup_issues = detect_duplicates(
                    db=db,
                    org_id=document.org_id,
                    document_id=doc_uuid,
                    sha256=document.sha256,
                    extraction_data=t2_extraction_data,
                )
                t2_all_issues = t2_rule_issues + t2_dup_issues
                t2_issue_codes = list(dict.fromkeys(i.code for i in t2_all_issues))

                attempt_2_record = {
                    "attempt_no": 2,
                    "model": t2_usage.get("model", tier2_model),
                    "input_tokens": t2_usage.get("input_tokens"),
                    "output_tokens": t2_usage.get("output_tokens"),
                    "latency_ms": t2_latency_ms,
                    "validation_error_codes": t2_issue_codes,
                    "escalation_reason": None,
                    "extraction_data": t2_extraction_data,
                    "usage": t2_usage,
                    "issues": t2_all_issues,
                    "failed": False,
                }
                attempts_in_memory.append(attempt_2_record)
            except Exception as t2_err:
                logger.warning("Tier 2 extraction unavailable on document %s: %s", document_id, t2_err)
                tier2_unavailable = True
                tier2_err_msg = str(t2_err)
                t2_latency_ms = int((time.time() - t2_start) * 1000)
                attempt_2_record = {
                    "attempt_no": 2,
                    "model": getattr(tier2_client, "model_name", tier2_model),
                    "input_tokens": None,
                    "output_tokens": None,
                    "latency_ms": t2_latency_ms,
                    "validation_error_codes": ["ESCALATION_UNAVAILABLE"],
                    "escalation_reason": None,
                    "extraction_data": {},
                    "usage": {"model": tier2_model, "latency_ms": t2_latency_ms},
                    "issues": [],
                    "failed": True,
                }
                attempts_in_memory.append(attempt_2_record)

            if tier2_unavailable:
                if tier1_failed:
                    logger.error("Both tier 1 and tier 2 failed on document %s", document_id)
                    _mark_failed(db, document, f"Tier 1 failed ({tier1_perm_err}) and tier 2 unavailable ({tier2_err_msg})")
                    return None
                final_extraction_data = t1_extraction_data
                final_usage = t1_usage
                final_issues = t1_all_issues
                final_status = "needs_review"
                final_review_reason = "escalation_unavailable"
            else:
                final_extraction_data = t2_extraction_data
                final_usage = t2_usage
                final_issues = t2_all_issues

                diff_fields = []
                if not tier1_failed:
                    diff_fields = get_critical_fields_diff(t1_extraction_data, t2_extraction_data)

                has_errors = any(i.severity == "error" for i in final_issues)
                has_routed_warnings = (
                    settings.VALIDATION_WARNINGS_ROUTE_TO_REVIEW
                    and any(i.severity == "warning" for i in final_issues)
                )

                if not has_errors and not has_routed_warnings:
                    final_status = "auto_approved"
                    final_review_reason = None
                else:
                    final_status = "needs_review"
                    unique_codes = list(dict.fromkeys(i.code for i in final_issues))
                    base_reason = ", ".join(unique_codes) if unique_codes else "validation_failed"
                    if not tier1_failed:
                        if len(diff_fields) == 0:
                            final_review_reason = f"{base_reason}, models_agree: likely a document issue"
                        else:
                            final_review_reason = f"{base_reason}, models_disagree: {', '.join(diff_fields)}"
                    else:
                        final_review_reason = base_reason
        else:
            # No escalation
            final_extraction_data = t1_extraction_data
            final_usage = t1_usage
            final_issues = t1_all_issues

            has_errors = any(i.severity == "error" for i in final_issues)
            has_routed_warnings = (
                settings.VALIDATION_WARNINGS_ROUTE_TO_REVIEW
                and any(i.severity == "warning" for i in final_issues)
            )

            if not has_errors and not has_routed_warnings:
                final_status = "auto_approved"
                final_review_reason = None
            else:
                final_status = "needs_review"
                unique_codes = list(dict.fromkeys(i.code for i in final_issues))
                final_review_reason = ", ".join(unique_codes)

        # 5. Save extraction + line items + attempts in ONE atomic transaction
        try:
            existing_extraction = (
                db.query(Extraction).filter(Extraction.document_id == doc_uuid).first()
            )
            if existing_extraction:
                extraction_id = existing_extraction.id
                if existing_extraction.original_data is None:
                    existing_extraction.original_data = dict(final_extraction_data)
                existing_extraction.data = final_extraction_data
                existing_extraction.model = final_usage.get("model", "unknown")
                existing_extraction.input_tokens = final_usage.get("input_tokens")
                existing_extraction.output_tokens = final_usage.get("output_tokens")
                existing_extraction.latency_ms = final_usage.get("latency_ms", 0)
                db.query(LineItem).filter(LineItem.extraction_id == extraction_id).delete(
                    synchronize_session=False
                )
            else:
                extraction_id = uuid.uuid4()
                extraction = Extraction(
                    id=extraction_id,
                    document_id=doc_uuid,
                    org_id=document.org_id,
                    original_data=dict(final_extraction_data),
                    data=final_extraction_data,
                    version=1,
                    model=final_usage.get("model", "unknown"),
                    input_tokens=final_usage.get("input_tokens"),
                    output_tokens=final_usage.get("output_tokens"),
                    latency_ms=final_usage.get("latency_ms", 0),
                )
                db.add(extraction)
                db.flush()

            for item in final_extraction_data.get("line_items", []):
                line_item = LineItem(
                    id=uuid.uuid4(),
                    extraction_id=extraction_id,
                    description=item["description"],
                    quantity=Decimal(str(item["quantity"])),
                    unit_price=Decimal(str(item["unit_price"])),
                    amount=Decimal(str(item["amount"])),
                )
                db.add(line_item)

            # Idempotently clear prior attempts for this document and save all attempts
            db.query(ExtractionAttempt).filter(ExtractionAttempt.document_id == doc_uuid).delete(
                synchronize_session=False
            )
            for att in attempts_in_memory:
                attempt_row = ExtractionAttempt(
                    id=uuid.uuid4(),
                    document_id=doc_uuid,
                    org_id=document.org_id,
                    attempt_no=att["attempt_no"],
                    model=att["model"],
                    input_tokens=att["input_tokens"],
                    output_tokens=att["output_tokens"],
                    latency_ms=att["latency_ms"],
                    validation_error_codes=att["validation_error_codes"],
                    escalation_reason=att["escalation_reason"],
                )
                db.add(attempt_row)

            # State transition: processing -> extracted
            now = datetime.now(UTC)
            transition_document_status(document, "extracted")
            document.processed_at = now
            document.error_message = None

            if audit_escalate_entry:
                db.add(audit_escalate_entry)

            audit_extracted = AuditLog(
                id=uuid.uuid4(),
                org_id=document.org_id,
                user_id=None,
                action="document_extracted",
                entity_type="document",
                entity_id=doc_uuid,
                new_value={
                    "status": "extracted",
                    "invoice_number": final_extraction_data.get("invoice_number"),
                    "total": str(final_extraction_data.get("total")),
                    "model": final_usage.get("model"),
                },
            )
            db.add(audit_extracted)
            db.flush()

            # Idempotently replace all issues for this document
            db.query(ValidationIssue).filter(ValidationIssue.document_id == doc_uuid).delete(
                synchronize_session=False
            )
            for iss in final_issues:
                v_issue = ValidationIssue(
                    id=uuid.uuid4(),
                    document_id=doc_uuid,
                    org_id=document.org_id,
                    code=iss.code,
                    severity=iss.severity,
                    field=iss.field,
                    message=iss.message,
                )
                db.add(v_issue)

            document.validated_at = datetime.now(UTC)

            if final_status == "auto_approved":
                transition_document_status(document, "auto_approved")
                document.review_reason = None
                audit_action = "document_auto_approved"
                audit_val = {"status": "auto_approved", "issue_count": 0}
            else:
                transition_document_status(document, "needs_review")
                document.review_reason = final_review_reason
                audit_action = "document_needs_review"
                unique_codes = list(dict.fromkeys(i.code for i in final_issues))
                audit_val = {
                    "status": "needs_review",
                    "review_reason": document.review_reason,
                    "issue_count": len(final_issues),
                    "issue_codes": unique_codes,
                }

            audit_route = AuditLog(
                id=uuid.uuid4(),
                org_id=document.org_id,
                user_id=None,
                action=audit_action,
                entity_type="document",
                entity_id=doc_uuid,
                new_value=audit_val,
            )
            db.add(audit_route)

            db.commit()
            logger.info("Successfully processed and routed document %s to '%s'", document_id, document.status)
            return final_extraction_data

        except IntegrityError:
            db.rollback()
            logger.warning("Integrity error on document %s (idempotency conflict)", document_id)
            return None

    finally:
        if override_db is None:
            db.close()


def _mark_failed(db: Session, document: Document, error_message: str) -> None:
    """Mark a document as failed with a clear error message, enforcing state transition."""
    now = datetime.now(UTC)
    transition_document_status(document, "failed")
    document.error_message = error_message
    document.processed_at = now

    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=document.org_id,
        user_id=None,
        action="document_failed",
        entity_type="document",
        entity_id=document.id,
        new_value={"status": "failed", "error_message": error_message},
    )
    db.add(audit_entry)
    db.commit()
    logger.info("Marked document %s as failed: %s", document.id, error_message)
