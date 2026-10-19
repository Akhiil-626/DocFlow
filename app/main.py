from collections import Counter

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import require_role
from app.diff import compute_extraction_diff
from app.models import Document, Extraction, User
from app.routers import audit, auth, documents, exports
from app.schemas import StatsResponse, TopFieldCorrection

app = FastAPI(
    title="DocFlow Backend API",
    description="DocFlow invoice processing API - Weeks 1-4A: Scaffold, Auth, Background Extraction, Validation, and Human Review",
    version="1.0.0",
)

# Secure CORS middleware using explicit allowed origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"], operation_id="health_check", summary="Health check endpoint")
def health_check() -> dict[str, str]:
    """Return health status of the application."""
    return {"status": "ok"}


@app.get("/stats", response_model=StatsResponse, tags=["stats"], operation_id="get_stats", summary="Get invoice processing and review statistics")
def get_stats(
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve document status counts, auto-approval rate, and human review correction metrics for caller organization."""
    status_counts = (
        db.query(Document.status, func.count(Document.id))
        .filter(Document.org_id == current_user.org_id)
        .group_by(Document.status)
        .all()
    )

    counts = {
        "uploaded": 0,
        "processing": 0,
        "extracted": 0,
        "auto_approved": 0,
        "needs_review": 0,
        "approved": 0,
        "rejected": 0,
        "failed": 0,
        "exported": 0,
    }
    for s_name, count in status_counts:
        counts[s_name] = count

    total = sum(counts.values())
    reviewed_or_approved = (
        counts["auto_approved"]
        + counts["needs_review"]
        + counts["approved"]
        + counts["rejected"]
        + counts["exported"]
    )
    rate = (counts["auto_approved"] / reviewed_or_approved) if reviewed_or_approved > 0 else 0.0

    # Human review metrics
    reviewed_docs = (
        db.query(Document)
        .filter(
            Document.org_id == current_user.org_id,
            Document.reviewed_at.is_not(None),
        )
        .all()
    )
    documents_reviewed = len(reviewed_docs)
    approved_count = len([d for d in reviewed_docs if d.status in ("approved", "exported")])
    rejected_count = len([d for d in reviewed_docs if d.status == "rejected"])

    # Compute correction rate & field frequencies from original_data vs data
    field_counter: Counter[str] = Counter()
    corrected_doc_count = 0

    all_org_extractions = (
        db.query(Extraction)
        .filter(Extraction.org_id == current_user.org_id)
        .all()
    )
    for ext in all_org_extractions:
        orig = ext.original_data or {}
        curr = ext.data or {}
        diff = compute_extraction_diff(orig, curr)
        if diff or ext.version > 1:
            corrected_doc_count += 1
            for k in diff:
                field_counter[k] += 1

    correction_rate = (
        (corrected_doc_count / documents_reviewed)
        if documents_reviewed > 0
        else 0.0
    )

    top_5 = [
        TopFieldCorrection(field=k, count=v)
        for k, v in field_counter.most_common(5)
    ]

    return {
        "counts": counts,
        "total": total,
        "auto_approval_rate": round(rate, 4),
        "documents_reviewed": documents_reviewed,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "correction_rate": round(correction_rate, 4),
        "top_corrected_fields": top_5,
    }


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(exports.router, prefix="/exports", tags=["exports"])
app.include_router(audit.router, prefix="/audit-log", tags=["audit"])
