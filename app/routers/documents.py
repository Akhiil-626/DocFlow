import hashlib
import uuid
from pathlib import Path

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
from app.models import AuditLog, Document, User
from app.schemas import DocumentListResponse, DocumentResponse
from app.storage import Storage

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
    summary="Upload a document (PDF, PNG, JPEG)",
)
def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Document:
    """Upload a document, validate signature and size, save via storage, and write audit log."""
    # 1. Read file content
    content = file.file.read()

    # 2. Enforce file size limit (Max 10 MB)
    if len(content) > settings.MAX_FILE_SIZE_BYTES:
        max_mb = settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum allowed limit of {max_mb} MB",
        )

    # 3. Verify magic bytes / file signature
    content_type, ext = verify_file_signature(content)

    # 4. Compute SHA-256 hash
    sha256_hash = hashlib.sha256(content).hexdigest()

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

    db.commit()
    db.refresh(document)
    return document


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents for current organization",
)
def list_documents(
    limit: int = Query(default=10, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve paginated list of documents isolated to the caller's organization."""
    query = db.query(Document).filter(Document.org_id == current_user.org_id)
    total = query.count()
    items = query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
    document = db.query(Document).filter(Document.id == document_id, Document.org_id == current_user.org_id).first()
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
    document = db.query(Document).filter(Document.id == document_id, Document.org_id == current_user.org_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    try:
        data = storage.read(document.storage_key)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file data not found on disk",
        )

    return Response(
        content=data,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{document.original_filename}"',
        },
    )


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
) -> None:
    """Delete document and its physical file. Admin role required. Returns 404 for other orgs."""
    document = db.query(Document).filter(Document.id == document_id, Document.org_id == current_user.org_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # 1. Delete physical file
    storage.delete(document.storage_key)

    # 2. Record audit log
    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="document_delete",
        entity_type="document",
        entity_id=document.id,
        old_value={
            "original_filename": document.original_filename,
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
            "sha256": document.sha256,
            "storage_key": document.storage_key,
            "status": document.status,
        },
    )
    db.add(audit_entry)

    # 3. Delete database record
    db.delete(document)
    db.commit()
