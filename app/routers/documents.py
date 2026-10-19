import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_storage, require_role
from app.diff import compute_extraction_diff
from app.duplicate_detection import detect_duplicates
from app.models import (
    AuditLog,
    Document,
    Extraction,
    LineItem,
    User,
    ValidationIssue,
    transition_document_status,
)
from app.schemas import (
    ApproveRequest,
    AuditLogListResponse,
    AuditLogResponse,
    DocumentListResponse,
    DocumentResponse,
    ExtractionPatchRequest,
    ExtractionResponse,
    InvoiceExtractionSchema,
    RejectRequest,
    ReviewQueueResponse,
)
from app.storage import Storage
from app.validation import validate_extraction
from app.worker.tasks import process_document

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_file_signature(data: bytes) -> tuple[str, str]:
    """Verify magic bytes (file signature) and return (content_type, extension).

    Supported formats:
    - PDF: starts with %PDF-
    - PNG: starts with 0x89 0x50 0x4E 0x47 0x0D 0x0A 0x1A 0x0A
    - JPEG: starts with 0xFF 0xD8 0xFF
    """
    if data.startswith(b"%PDF-"):
        return ("application/pdf", ".pdf")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ("image/png", ".png")
    if data.startswith(b"\xff\xd8\xff"):
        return ("image/jpeg", ".jpg")

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid file signature. Only valid PDF, PNG, and JPEG files are allowed.",
    )


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new document (Admin and Reviewer only)",
)
def upload_document(
    file: UploadFile = File(..., description="Document file (PDF, PNG, JPEG, max 10MB)"),
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Document:
    """Upload document, compute SHA-256, store in local storage, save DB metadata, and enqueue extraction."""
    # 1. Read file bytes
    try:
        content = file.file.read()
    except Exception as err:
        logger.error("Failed to read uploaded file: %s", err)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read uploaded file content.",
        ) from err

    # 2. Enforce 10 MB limit
    if len(content) > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_BYTES} bytes (10 MB).",
        )

    # 3. Verify magic bytes / file signature
    content_type, ext = verify_file_signature(content)

    # 4. Compute SHA-256 hash
    sha256_hash = hashlib.sha256(content).hexdigest()

    # Check for existing exact file duplicate in this organization
    existing_file_doc = (
        db.query(Document)
        .filter(Document.org_id == current_user.org_id, Document.sha256 == sha256_hash)
        .order_by(Document.created_at.asc())
        .first()
    )
    existing_doc_id = existing_file_doc.id if existing_file_doc else None

    # 5. Generate secure document ID and storage key: {org_id}/{document_id}{ext}
    # NEVER use user-supplied filename in storage path
    doc_id = uuid.uuid4()
    storage_key = f"{current_user.org_id}/{doc_id}{ext}"

    # 6. Save file through storage abstraction
    storage.save(storage_key, content)

    # 7. Store user filename strictly as metadata
    raw_filename = file.filename or "document"
    safe_metadata_filename = Path(raw_filename).name or "document"

    document = Document(
        id=doc_id,
        org_id=current_user.org_id,
        uploaded_by=current_user.id,
        original_filename=safe_metadata_filename,
        content_type=content_type,
        size_bytes=len(content),
        sha256=sha256_hash,
        storage_key=storage_key,
        status="uploaded",
    )
    db.add(document)
    db.flush()

    # 8. Write audit log entry
    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="document_upload",
        entity_type="document",
        entity_id=doc_id,
        new_value={
            "original_filename": safe_metadata_filename,
            "content_type": content_type,
            "size_bytes": len(content),
            "sha256": sha256_hash,
            "storage_key": storage_key,
            "status": "uploaded",
        },
    )
    db.add(audit_entry)

    # 9. Commit DB transaction first
    db.commit()
    db.refresh(document)

    # 10. Enqueue background extraction task strictly AFTER commit succeeds
    try:
        process_document.delay(str(doc_id))
    except Exception as err:
        logger.warning(
            "Failed to enqueue background processing for document %s: %s",
            doc_id,
            err,
        )

    # Attach existing_document_id for response if an exact duplicate existed
    document.existing_document_id = existing_doc_id
    return document


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents for current organization",
)
def list_documents(
    limit: int = Query(default=10, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    status: str | None = Query(default=None, description="Filter by status"),
    has_issues: bool | None = Query(default=None, description="Filter by presence of validation issues"),
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve paginated list of documents isolated to the caller's organization."""
    query = db.query(Document).filter(Document.org_id == current_user.org_id)
    if status:
        query = query.filter(Document.status == status)
    if has_issues is not None:
        if has_issues:
            query = query.filter(Document.validation_issues.any())
        else:
            query = query.filter(~Document.validation_issues.any())

    total = query.count()
    items = (
        query.order_by(Document.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# Static subroutes defined BEFORE /{document_id} to prevent path parsing conflicts
@router.get(
    "/review-queue",
    response_model=ReviewQueueResponse,
    summary="Get review queue documents (Admin and Reviewer only)",
)
def get_review_queue(
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve documents in 'needs_review' status for caller's org, oldest first, with issue counts."""
    docs = (
        db.query(Document)
        .filter(
            Document.org_id == current_user.org_id,
            Document.status == "needs_review",
        )
        .order_by(Document.created_at.asc())
        .all()
    )

    items = []
    for doc in docs:
        issues = doc.validation_issues or []
        items.append({
            "id": doc.id,
            "original_filename": doc.original_filename,
            "created_at": doc.created_at,
            "validated_at": doc.validated_at,
            "status": doc.status,
            "review_reason": doc.review_reason,
            "issue_count": len(issues),
            "issues": issues,
        })

    return {
        "items": items,
        "total": len(items),
    }


@router.post(
    "/reset-stale",
    summary="Reset stale processing documents (Admin only)",
)
def reset_stale_documents(
    stale_minutes: int = Query(default=10, ge=0, le=1440),
    timeout_seconds: int | None = Query(default=None, ge=0),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Reset documents stuck in 'processing' state back to 'uploaded'."""
    seconds = timeout_seconds if timeout_seconds is not None else (stale_minutes * 60)
    cutoff = datetime.now(UTC) - timedelta(seconds=seconds)
    stale_docs = (
        db.query(Document)
        .filter(
            Document.org_id == current_user.org_id,
            Document.status == "processing",
            Document.updated_at <= cutoff,
        )
        .all()
    )

    reset_count = 0
    for doc in stale_docs:
        transition_document_status(doc, "failed")
        transition_document_status(doc, "uploaded")
        reset_count += 1
        try:
            process_document.delay(str(doc.id))
        except Exception as err:
            logger.warning(
                "Failed to re-enqueue stale document %s: %s", doc.id, err
            )

    if reset_count > 0:
        db.commit()

    return {"reset_count": reset_count}


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document metadata",
)
def get_document_metadata(
    document_id: uuid.UUID,
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> Document:
    """Retrieve document metadata. Returns 404 if not found or belongs to another organization."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return document


@router.get(
    "/{document_id}/file",
    summary="Download original document file",
)
def get_document_file(
    document_id: uuid.UUID,
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """Stream document binary content. Returns 404 if not found or belongs to another organization."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    try:
        content = storage.read(document.storage_key)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File content not found in storage",
        )

    safe_filename = Path(document.original_filename).name or "document"
    return Response(
        content=content,
        media_type=document.content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.get(
    "/{document_id}/extraction",
    response_model=ExtractionResponse,
    operation_id="get_document_extraction",
    summary="Get document extraction, line items, and validation issues",
)
def get_document_extraction(
    document_id: uuid.UUID,
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve extraction, line items, and validation issues for a document."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    extraction = (
        db.query(Extraction)
        .filter(
            Extraction.document_id == document_id,
            Extraction.org_id == current_user.org_id,
        )
        .first()
    )
    if not extraction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction not found for this document",
        )

    issues = (
        db.query(ValidationIssue)
        .filter(ValidationIssue.document_id == document.id)
        .order_by(ValidationIssue.created_at.asc())
        .all()
    )

    return {
        "id": extraction.id,
        "document_id": extraction.document_id,
        "org_id": extraction.org_id,
        "original_data": extraction.original_data or extraction.data,
        "data": extraction.data,
        "version": extraction.version,
        "edited_at": extraction.edited_at,
        "edited_by": extraction.edited_by,
        "model": extraction.model,
        "input_tokens": extraction.input_tokens,
        "output_tokens": extraction.output_tokens,
        "latency_ms": extraction.latency_ms,
        "created_at": extraction.created_at,
        "line_items": extraction.line_items,
        "validation_issues": issues,
    }


@router.patch(
    "/{document_id}/extraction",
    response_model=ExtractionResponse,
    operation_id="patch_document_extraction",
    summary="Edit document extraction data (Admin and Reviewer only)",
)
def patch_document_extraction(
    document_id: uuid.UUID,
    body: ExtractionPatchRequest,
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Apply human corrections to extraction data, re-run validation and duplicate checks, and record an audit diff."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .with_for_update()
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document.status != "needs_review":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Extraction editing is only allowed when document status is 'needs_review' "
                f"(current status: '{document.status}')"
            ),
        )

    extraction = (
        db.query(Extraction)
        .filter(
            Extraction.document_id == document_id,
            Extraction.org_id == current_user.org_id,
        )
        .with_for_update()
        .first()
    )
    if not extraction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction not found for this document",
        )

    # Optimistic concurrency check
    if extraction.version != body.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version mismatch. Document extraction is at version {extraction.version}, got {body.version}.",
        )

    old_data = dict(extraction.data)
    merged_data = dict(old_data)

    updates = body.model_dump(exclude={"version", "note"}, exclude_unset=True)
    for k, v in updates.items():
        if k == "line_items" and v is not None:
            merged_data["line_items"] = [
                item.model_dump() if hasattr(item, "model_dump") else item for item in v
            ]
        elif v is not None:
            merged_data[k] = str(v) if isinstance(v, (Decimal, date)) else v

    # Re-validate shape with InvoiceExtractionSchema
    try:
        validated_obj = InvoiceExtractionSchema.model_validate(merged_data)
    except Exception as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid extraction data shape: {val_err}",
        )
    new_validated_data = json.loads(validated_obj.model_dump_json())

    # Field-level diff calculation
    diff = compute_extraction_diff(old_data, new_validated_data)

    # Update extraction metadata
    old_version = extraction.version
    extraction.data = new_validated_data
    extraction.version += 1
    extraction.edited_at = datetime.now(UTC)
    extraction.edited_by = current_user.id

    # Update line_items table
    db.query(LineItem).filter(LineItem.extraction_id == extraction.id).delete(
        synchronize_session=False
    )
    for item in new_validated_data.get("line_items", []):
        li = LineItem(
            id=uuid.uuid4(),
            extraction_id=extraction.id,
            description=item["description"],
            quantity=Decimal(str(item["quantity"])),
            unit_price=Decimal(str(item["unit_price"])),
            amount=Decimal(str(item["amount"])),
        )
        db.add(li)

    # Re-run pure validation and duplicate check
    rule_issues = validate_extraction(new_validated_data)
    dup_issues = detect_duplicates(
        db=db,
        org_id=document.org_id,
        document_id=document.id,
        sha256=document.sha256,
        extraction_data=new_validated_data,
    )
    all_issues = rule_issues + dup_issues

    # Replace validation_issues
    db.query(ValidationIssue).filter(
        ValidationIssue.document_id == document.id
    ).delete(synchronize_session=False)

    new_db_issues = []
    for iss in all_issues:
        v_issue = ValidationIssue(
            id=uuid.uuid4(),
            document_id=document.id,
            org_id=document.org_id,
            code=iss.code,
            severity=iss.severity,
            field=iss.field,
            message=iss.message,
        )
        db.add(v_issue)
        new_db_issues.append(v_issue)

    # Update review_reason
    if any(i.severity == "error" for i in all_issues):
        error_codes = [i.code for i in all_issues if i.severity == "error"]
        document.review_reason = f"Unresolved errors: {', '.join(error_codes)}"
    elif all_issues:
        warn_codes = [i.code for i in all_issues]
        document.review_reason = f"Review warnings: {', '.join(warn_codes)}"
    else:
        document.review_reason = None

    # Write audit entry with field-level diff
    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="edit_extraction",
        entity_type="document",
        entity_id=document.id,
        old_value={"version": old_version, "diff": diff},
        new_value={
            "version": extraction.version,
            "diff": diff,
            "note": body.note,
        },
    )
    db.add(audit_entry)

    db.commit()
    db.refresh(extraction)

    return {
        "id": extraction.id,
        "document_id": extraction.document_id,
        "org_id": extraction.org_id,
        "original_data": extraction.original_data,
        "data": extraction.data,
        "version": extraction.version,
        "edited_at": extraction.edited_at,
        "edited_by": extraction.edited_by,
        "model": extraction.model,
        "input_tokens": extraction.input_tokens,
        "output_tokens": extraction.output_tokens,
        "latency_ms": extraction.latency_ms,
        "created_at": extraction.created_at,
        "line_items": extraction.line_items,
        "validation_issues": new_db_issues,
    }


@router.post(
    "/{document_id}/approve",
    response_model=DocumentResponse,
    operation_id="approve_document",
    summary="Approve an invoice from needs_review (Admin and Reviewer only)",
)
def approve_document(
    document_id: uuid.UUID,
    body: ApproveRequest = ApproveRequest(),
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> Document:
    """Approve document atomically from needs_review status.

    If error-level issues remain, override=true and a non-empty reason are required.
    """
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .with_for_update()
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document.status != "needs_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only documents in 'needs_review' status can be approved (current status: '{document.status}')",
        )

    # Check for unresolved error-level issues
    error_issues = (
        db.query(ValidationIssue)
        .filter(
            ValidationIssue.document_id == document.id,
            ValidationIssue.severity == "error",
        )
        .all()
    )

    if error_issues:
        if not body.override or not (body.reason and body.reason.strip()):
            codes = ", ".join(i.code for i in error_issues)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot approve document with unresolved error issues ({codes}). "
                    "Provide override=true and a non-empty reason."
                ),
            )
        document.review_note = body.reason.strip()
    elif body.reason and body.reason.strip():
        document.review_note = body.reason.strip()

    transition_document_status(document, "approved")
    document.reviewed_by = current_user.id
    document.reviewed_at = datetime.now(UTC)

    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="approve_document",
        entity_type="document",
        entity_id=document.id,
        old_value={"status": "needs_review"},
        new_value={
            "status": "approved",
            "override": body.override,
            "review_note": document.review_note,
        },
    )
    db.add(audit_entry)

    db.commit()
    db.refresh(document)
    return document


@router.post(
    "/{document_id}/reject",
    response_model=DocumentResponse,
    operation_id="reject_document",
    summary="Reject an invoice from needs_review (Admin and Reviewer only)",
)
def reject_document(
    document_id: uuid.UUID,
    body: RejectRequest,
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> Document:
    """Reject document from needs_review status with a mandatory non-empty reason."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .with_for_update()
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document.status != "needs_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only documents in 'needs_review' status can be rejected (current status: '{document.status}')",
        )

    transition_document_status(document, "rejected")
    document.reviewed_by = current_user.id
    document.reviewed_at = datetime.now(UTC)
    document.review_note = body.reason.strip()

    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="reject_document",
        entity_type="document",
        entity_id=document.id,
        old_value={"status": "needs_review"},
        new_value={"status": "rejected", "reason": document.review_note},
    )
    db.add(audit_entry)

    db.commit()
    db.refresh(document)
    return document


@router.post(
    "/{document_id}/reopen",
    response_model=DocumentResponse,
    operation_id="reopen_document",
    summary="Reopen an approved or rejected document back to needs_review (Admin only)",
)
def reopen_document(
    document_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> Document:
    """Reopen an approved or rejected document back to needs_review. Admin only. Blocked if document was exported."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .with_for_update()
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document.status == "exported" or document.export_batch_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot reopen document: document has already been exported.",
        )

    if document.status not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only approved or rejected documents can be reopened (current status: '{document.status}')",
        )

    old_status = document.status
    transition_document_status(document, "needs_review")

    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="reopen_document",
        entity_type="document",
        entity_id=document.id,
        old_value={"status": old_status},
        new_value={"status": "needs_review"},
    )
    db.add(audit_entry)

    db.commit()
    db.refresh(document)
    return document


@router.get(
    "/{document_id}/history",
    response_model=AuditLogListResponse,
    operation_id="get_document_history",
    summary="Get document audit history (All roles)",
)
def get_document_history(
    document_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve audit history entries for a document ordered newest first, with actor email or 'system'."""
    doc_exists = (
        db.query(Document.id)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .scalar()
    )
    if not doc_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    query = (
        db.query(AuditLog, User.email)
        .outerjoin(User, AuditLog.user_id == User.id)
        .filter(
            AuditLog.org_id == current_user.org_id,
            AuditLog.entity_type == "document",
            AuditLog.entity_id == document_id,
        )
        .order_by(AuditLog.created_at.desc())
    )

    total = query.count()
    rows = query.offset(offset).limit(limit).all()

    items = []
    for log_entry, actor_email in rows:
        items.append(
            AuditLogResponse(
                id=log_entry.id,
                org_id=log_entry.org_id,
                user_id=log_entry.user_id,
                actor_email=actor_email or "system",
                action=log_entry.action,
                entity_type=log_entry.entity_type,
                entity_id=log_entry.entity_id,
                old_value=log_entry.old_value,
                new_value=log_entry.new_value,
                created_at=log_entry.created_at,
            )
        )

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentResponse,
    summary="Reprocess a failed document (Admin and Reviewer only)",
)
def reprocess_document(
    document_id: uuid.UUID,
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> Document:
    """Reset a failed document to 'uploaded' and re-enqueue for background extraction."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only failed documents can be reprocessed (current status: '{document.status}')",
        )

    transition_document_status(document, "uploaded")
    document.error_message = None
    document.review_reason = None

    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="document_reprocessed",
        entity_type="document",
        entity_id=document.id,
        new_value={"status": "uploaded", "reprocessed_by": str(current_user.id)},
    )
    db.add(audit_entry)
    db.commit()
    db.refresh(document)

    try:
        process_document.delay(str(document.id))
    except Exception as err:
        logger.warning(
            "Failed to enqueue background reprocessing for document %s: %s",
            document.id,
            err,
        )

    return document


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document (Admin only)",
)
def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """Delete document metadata and storage file. Admin only. Scoped strictly to caller's org."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.org_id == current_user.org_id)
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    try:
        storage.delete(document.storage_key)
    except Exception as err:
        logger.warning(
            "Storage file deletion failed for key %s: %s",
            document.storage_key,
            err,
        )

    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="document_delete",
        entity_type="document",
        entity_id=document_id,
        old_value={
            "original_filename": document.original_filename,
            "storage_key": document.storage_key,
            "status": document.status,
        },
        new_value=None,
    )
    db.add(audit_entry)

    db.delete(document)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
