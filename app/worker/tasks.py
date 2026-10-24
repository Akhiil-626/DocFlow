import io
import logging
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
    LineItem,
    ValidationIssue,
    transition_document_status,
)
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
) -> dict[str, Any] | None:
    """Process an uploaded document: extract text, call LLM, validate rules, and route."""
    db: Session = override_db or SessionLocal()
    storage: Storage = override_storage or LocalStorage(settings.UPLOAD_DIR)
    llm_client: LLMClient = override_llm_client or get_llm_client()

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

        # 4. Call LLM extraction with repair retry capability
        try:
            extraction_data, usage = llm_client.extract_invoice(extracted_text)
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
            logger.error("Permanent extraction failure on document %s: %s", document_id, perm_err)
            _mark_failed(db, document, str(perm_err))
            return None

        # 5. Save extraction + line items in one atomic transaction
        try:
            existing_extraction = (
                db.query(Extraction).filter(Extraction.document_id == doc_uuid).first()
            )
            if existing_extraction:
                extraction_id = existing_extraction.id
                if existing_extraction.original_data is None:
                    existing_extraction.original_data = dict(extraction_data)
                existing_extraction.data = extraction_data
                existing_extraction.model = usage.get("model", "unknown")
                existing_extraction.input_tokens = usage.get("input_tokens")
                existing_extraction.output_tokens = usage.get("output_tokens")
                existing_extraction.latency_ms = usage.get("latency_ms", 0)
                db.query(LineItem).filter(LineItem.extraction_id == extraction_id).delete(
                    synchronize_session=False
                )
            else:
                extraction_id = uuid.uuid4()
                extraction = Extraction(
                    id=extraction_id,
                    document_id=doc_uuid,
                    org_id=document.org_id,
                    original_data=dict(extraction_data),
                    data=extraction_data,
                    version=1,
                    model=usage.get("model", "unknown"),
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    latency_ms=usage.get("latency_ms", 0),
                )
                db.add(extraction)
                db.flush()

            for item in extraction_data.get("line_items", []):
                line_item = LineItem(
                    id=uuid.uuid4(),
                    extraction_id=extraction_id,
                    description=item["description"],
                    quantity=Decimal(str(item["quantity"])),
                    unit_price=Decimal(str(item["unit_price"])),
                    amount=Decimal(str(item["amount"])),
                )
                db.add(line_item)

            # State transition: processing -> extracted
            now = datetime.now(UTC)
            transition_document_status(document, "extracted")
            document.processed_at = now
            document.error_message = None

            audit_extracted = AuditLog(
                id=uuid.uuid4(),
                org_id=document.org_id,
                user_id=None,
                action="document_extracted",
                entity_type="document",
                entity_id=doc_uuid,
                new_value={
                    "status": "extracted",
                    "invoice_number": extraction_data.get("invoice_number"),
                    "total": str(extraction_data.get("total")),
                    "model": usage.get("model"),
                },
            )
            db.add(audit_extracted)
            db.flush()

            # 6. Run validation rules + duplicate detection
            rule_issues = validate_extraction(extraction_data)
            duplicate_issues = detect_duplicates(
                db=db,
                org_id=document.org_id,
                document_id=doc_uuid,
                sha256=document.sha256,
                extraction_data=extraction_data,
            )
            all_issues = rule_issues + duplicate_issues

            # Idempotently replace all issues for this document
            db.query(ValidationIssue).filter(ValidationIssue.document_id == doc_uuid).delete(
                synchronize_session=False
            )
            for iss in all_issues:
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

            # 7. Routing logic: auto_approved vs needs_review
            has_errors = any(i.severity == "error" for i in all_issues)
            has_routed_warnings = (
                settings.VALIDATION_WARNINGS_ROUTE_TO_REVIEW
                and any(i.severity == "warning" for i in all_issues)
            )

            document.validated_at = datetime.now(UTC)

            if not has_errors and not has_routed_warnings:
                transition_document_status(document, "auto_approved")
                document.review_reason = None
                audit_action = "document_auto_approved"
                audit_val = {"status": "auto_approved", "issue_count": 0}
            else:
                transition_document_status(document, "needs_review")
                unique_codes = list(dict.fromkeys(i.code for i in all_issues))
                document.review_reason = ", ".join(unique_codes)
                audit_action = "document_needs_review"
                audit_val = {
                    "status": "needs_review",
                    "review_reason": document.review_reason,
                    "issue_count": len(all_issues),
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
            return extraction_data

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
