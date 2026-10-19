import csv
import io
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import AuditLog, Document, ExportBatch, User, transition_document_status
from app.sanitizer import sanitize_csv_cell
from app.schemas import (
    ExportBatchListResponse,
    ExportBatchResponse,
    ExportCreateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "",
    response_model=ExportBatchResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_export_batch",
    summary="Create an export batch for approved and auto_approved documents",
)
def create_export_batch(
    body: ExportCreateRequest,
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> ExportBatch:
    """Selects approved and auto_approved documents, marks them exported, links them to an export batch, and writes audit records all in one transaction."""
    # 1. Select approved and auto_approved documents for caller's org with row-level locks
    documents = (
        db.query(Document)
        .filter(
            Document.org_id == current_user.org_id,
            Document.status.in_(["approved", "auto_approved"]),
        )
        .with_for_update()
        .order_by(Document.created_at.asc(), Document.id.asc())
        .all()
    )

    if not documents:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No approved or auto_approved documents to export.",
        )

    now = datetime.now(UTC)
    batch_id = uuid.uuid4()
    batch = ExportBatch(
        id=batch_id,
        org_id=current_user.org_id,
        created_by=current_user.id,
        format=body.format,
        row_count=len(documents),
        created_at=now,
    )
    db.add(batch)

    # 2. Transition each document to exported and record audit logs
    for doc in documents:
        old_status = doc.status
        transition_document_status(doc, "exported")
        doc.export_batch_id = batch_id
        doc.exported_at = now

        doc_audit = AuditLog(
            id=uuid.uuid4(),
            org_id=current_user.org_id,
            user_id=current_user.id,
            action="export_document",
            entity_type="document",
            entity_id=doc.id,
            old_value={"status": old_status},
            new_value={"status": "exported", "export_batch_id": str(batch_id)},
            created_at=now,
        )
        db.add(doc_audit)

    # 3. Audit log for export batch creation
    batch_audit = AuditLog(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        action="create_export_batch",
        entity_type="export_batch",
        entity_id=batch_id,
        old_value=None,
        new_value={"format": body.format, "document_count": len(documents)},
        created_at=now,
    )
    db.add(batch_audit)

    db.commit()
    db.refresh(batch)
    return batch


@router.get(
    "",
    response_model=ExportBatchListResponse,
    operation_id="list_export_batches",
    summary="List export batches for caller organization",
)
def list_export_batches(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List historical export batches scoped strictly to caller's org."""
    query = (
        db.query(ExportBatch)
        .filter(ExportBatch.org_id == current_user.org_id)
        .order_by(ExportBatch.created_at.desc())
    )
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/{export_id}/download",
    operation_id="download_export_batch",
    summary="Download export batch file (CSV or JSON with formula protection)",
)
def download_export_batch(
    export_id: uuid.UUID,
    view: Literal["summary", "line_items"] = Query("summary", description="View type for CSV exports"),
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> Response:
    """Regenerate export file deterministically from documents linked to that batch."""
    batch = (
        db.query(ExportBatch)
        .filter(ExportBatch.id == export_id, ExportBatch.org_id == current_user.org_id)
        .first()
    )
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export batch not found",
        )

    documents = (
        db.query(Document)
        .filter(Document.export_batch_id == batch.id, Document.org_id == current_user.org_id)
        .order_by(Document.created_at.asc(), Document.id.asc())
        .all()
    )

    if batch.format == "json":
        payload = []
        for doc in documents:
            ex_data = doc.extraction.data if doc.extraction else {}
            line_items_data = []
            if doc.extraction and doc.extraction.line_items:
                for li in doc.extraction.line_items:
                    line_items_data.append({
                        "description": li.description,
                        "quantity": str(li.quantity),
                        "unit_price": str(li.unit_price),
                        "amount": str(li.amount),
                    })
            payload.append({
                "document_id": str(doc.id),
                "original_filename": doc.original_filename,
                "status": doc.status,
                "exported_at": doc.exported_at.isoformat() if doc.exported_at else None,
                "data": ex_data,
                "line_items": line_items_data,
            })
        content_str = json.dumps(payload, indent=2, ensure_ascii=False)
        return Response(
            content=content_str,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="export_{batch.id}.json"'},
        )

    # CSV Format
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    if view == "line_items":
        # One row per line item
        headers = [
            "document_id",
            "invoice_number",
            "vendor_name",
            "line_item_description",
            "quantity",
            "unit_price",
            "amount",
        ]
        writer.writerow(headers)

        for doc in documents:
            ex_data = doc.extraction.data if doc.extraction else {}
            inv_num = sanitize_csv_cell(ex_data.get("invoice_number", ""))
            vendor = sanitize_csv_cell(ex_data.get("vendor_name", ""))
            if doc.extraction and doc.extraction.line_items:
                for li in doc.extraction.line_items:
                    writer.writerow([
                        str(doc.id),
                        inv_num,
                        vendor,
                        sanitize_csv_cell(li.description),
                        str(li.quantity),
                        str(li.unit_price),
                        str(li.amount),
                    ])
            elif doc.extraction and ex_data.get("line_items"):
                for item in ex_data.get("line_items", []):
                    writer.writerow([
                        str(doc.id),
                        inv_num,
                        vendor,
                        sanitize_csv_cell(item.get("description", "")),
                        str(item.get("quantity", "")),
                        str(item.get("unit_price", "")),
                        str(item.get("amount", "")),
                    ])
            else:
                writer.writerow([str(doc.id), inv_num, vendor, "", "0", "0.00", "0.00"])

    else:
        # Default Summary View: One row per invoice
        headers = [
            "document_id",
            "vendor_name",
            "vendor_gstin",
            "invoice_number",
            "invoice_date",
            "currency",
            "subtotal",
            "cgst",
            "sgst",
            "igst",
            "total",
            "status",
        ]
        writer.writerow(headers)

        for doc in documents:
            ex_data = doc.extraction.data if doc.extraction else {}
            writer.writerow([
                str(doc.id),
                sanitize_csv_cell(ex_data.get("vendor_name", "")),
                sanitize_csv_cell(ex_data.get("vendor_gstin", "")),
                sanitize_csv_cell(ex_data.get("invoice_number", "")),
                sanitize_csv_cell(ex_data.get("invoice_date", "")),
                sanitize_csv_cell(ex_data.get("currency", "INR")),
                str(ex_data.get("subtotal", "0.00")),
                str(ex_data.get("cgst", "0.00")),
                str(ex_data.get("sgst", "0.00")),
                str(ex_data.get("igst", "0.00")),
                str(ex_data.get("total", "0.00")),
                sanitize_csv_cell(doc.status),
            ])

    # Encode with UTF-8 BOM so Excel opens it with correct encoding
    csv_bytes = output.getvalue().encode("utf-8-sig")
    filename = f"export_{batch.id}_{view}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
