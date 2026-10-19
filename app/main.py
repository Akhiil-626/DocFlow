from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import Document, User
from app.routers import auth, documents
from app.schemas import StatsResponse

app = FastAPI(
    title="DocFlow Backend API",
    description="DocFlow invoice processing API - Weeks 1-3: Scaffold, Auth, Background Extraction, and Validation",
    version="1.0.0",
)

# Optional CORS middleware for flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"], summary="Health check endpoint")
def health_check() -> dict[str, str]:
    """Return health status of the application."""
    return {"status": "ok"}


@app.get("/stats", response_model=StatsResponse, tags=["stats"], summary="Get invoice processing statistics")
def get_stats(
    current_user: User = Depends(require_role("admin", "reviewer", "viewer")),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve document status counts and auto-approval rate for the caller's organization."""
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
        "failed": 0,
    }
    for s_name, count in status_counts:
        counts[s_name] = count

    total = sum(counts.values())
    reviewed_or_approved = counts["auto_approved"] + counts["needs_review"]
    rate = (counts["auto_approved"] / reviewed_or_approved) if reviewed_or_approved > 0 else 0.0

    return {
        "counts": counts,
        "total": total,
        "auto_approval_rate": round(rate, 4),
    }


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
