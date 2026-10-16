from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, documents

app = FastAPI(
    title="DocFlow Backend API",
    description="DocFlow invoice processing API - Week 1: Scaffold, Auth, and File Upload",
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


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
