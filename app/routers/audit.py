import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import AuditLog, User
from app.schemas import AuditLogListResponse, AuditLogResponse

router = APIRouter()


@router.get(
    "",
    response_model=AuditLogListResponse,
    operation_id="get_audit_logs",
    summary="List organization audit log entries with filters (Admin only)",
)
def get_audit_logs(
    entity_type: str | None = Query(None, description="Filter by entity type (e.g. document, user, export_batch)"),
    entity_id: uuid.UUID | None = Query(None, description="Filter by entity UUID"),
    user_id: uuid.UUID | None = Query(None, description="Filter by actor user UUID"),
    action: str | None = Query(None, description="Filter by action name (e.g. edit_extraction, approve_document)"),
    start_date: datetime | None = Query(None, description="Filter created_at on or after this timestamp"),
    end_date: datetime | None = Query(None, description="Filter created_at on or before this timestamp"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve audit log entries for caller's organization with multi-field filtering."""
    query = (
        db.query(AuditLog, User.email)
        .outerjoin(User, AuditLog.user_id == User.id)
        .filter(AuditLog.org_id == current_user.org_id)
    )

    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if start_date:
        query = query.filter(AuditLog.created_at >= start_date)
    if end_date:
        query = query.filter(AuditLog.created_at <= end_date)

    query = query.order_by(AuditLog.created_at.desc())
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
