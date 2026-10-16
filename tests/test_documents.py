import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AuditLog, Document, Organization, User
from tests.conftest import auth_headers_for

# Valid magic byte sample payloads
VALID_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF"
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00"


def test_role_permissions_viewer_cannot_upload_reviewer_can(
    client: TestClient,
    viewer_user_a: User,
    reviewer_user_a: User,
):
    """Test viewer cannot upload (403 Forbidden), reviewer can upload (201 Created)."""
    # 1. Viewer tries to upload -> 403
    viewer_headers = auth_headers_for(viewer_user_a)
    viewer_res = client.post(
        "/documents",
        headers=viewer_headers,
        files={"file": ("invoice.pdf", VALID_PDF_BYTES, "application/pdf")},
    )
    assert viewer_res.status_code == 403

    # 2. Reviewer uploads -> 201
    reviewer_headers = auth_headers_for(reviewer_user_a)
    reviewer_res = client.post(
        "/documents",
        headers=reviewer_headers,
        files={"file": ("invoice.pdf", VALID_PDF_BYTES, "application/pdf")},
    )
    assert reviewer_res.status_code == 201
    doc_data = reviewer_res.json()
    assert doc_data["status"] == "uploaded"
    assert doc_data["original_filename"] == "invoice.pdf"


def test_role_permissions_only_admin_can_delete(
    client: TestClient,
    admin_user_a: User,
    reviewer_user_a: User,
    viewer_user_a: User,
):
    """Test only admin can delete; reviewer and viewer get 403 Forbidden."""
    admin_headers = auth_headers_for(admin_user_a)
    upload_res = client.post(
        "/documents",
        headers=admin_headers,
        files={"file": ("doc.pdf", VALID_PDF_BYTES, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # Viewer cannot delete
    viewer_headers = auth_headers_for(viewer_user_a)
    viewer_del = client.delete(f"/documents/{doc_id}", headers=viewer_headers)
    assert viewer_del.status_code == 403

    # Reviewer cannot delete
    reviewer_headers = auth_headers_for(reviewer_user_a)
    reviewer_del = client.delete(f"/documents/{doc_id}", headers=reviewer_headers)
    assert reviewer_del.status_code == 403

    # Admin CAN delete
    admin_del = client.delete(f"/documents/{doc_id}", headers=admin_headers)
    assert admin_del.status_code == 204

    # Verify document is gone
    get_res = client.get(f"/documents/{doc_id}", headers=admin_headers)
    assert get_res.status_code == 404


def test_tenant_isolation_org_b_cannot_access_or_modify_org_a_documents(
    client: TestClient,
    admin_user_a: User,
    user_b: User,
):
    """Test tenant isolation: user from Org B cannot read, download, list, or delete Org A's documents."""
    headers_a = auth_headers_for(admin_user_a)
    headers_b = auth_headers_for(user_b)

    # 1. Org A uploads a document
    upload_res = client.post(
        "/documents",
        headers=headers_a,
        files={"file": ("secret_plan.pdf", VALID_PDF_BYTES, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # 2. Org B tries to read metadata -> MUST return 404
    get_res_b = client.get(f"/documents/{doc_id}", headers=headers_b)
    assert get_res_b.status_code == 404
    assert get_res_b.json()["detail"] == "Document not found"

    # 3. Org B tries to download file -> MUST return 404
    file_res_b = client.get(f"/documents/{doc_id}/file", headers=headers_b)
    assert file_res_b.status_code == 404

    # 4. Org B lists documents -> MUST NOT see Org A's document
    list_res_b = client.get("/documents", headers=headers_b)
    assert list_res_b.status_code == 200
    doc_ids_in_b = [item["id"] for item in list_res_b.json()["items"]]
    assert doc_id not in doc_ids_in_b

    # 5. Org B tries to delete Org A's document -> MUST return 404
    del_res_b = client.delete(f"/documents/{doc_id}", headers=headers_b)
    assert del_res_b.status_code == 404

    # 6. Verify Org A can still access its document
    get_res_a = client.get(f"/documents/{doc_id}", headers=headers_a)
    assert get_res_a.status_code == 200
    assert get_res_a.json()["id"] == doc_id


def test_upload_rejects_files_over_10mb(client: TestClient, admin_user_a: User):
    """Test file upload rejects files over 10 MB."""
    headers = auth_headers_for(admin_user_a)
    # Generate content over 10 MB (10 MB + 1 byte)
    oversized_bytes = VALID_PDF_BYTES + b"0" * (10 * 1024 * 1024 + 1)

    res = client.post(
        "/documents",
        headers=headers,
        files={"file": ("large.pdf", oversized_bytes, "application/pdf")},
    )
    assert res.status_code == 400
    assert "exceeds maximum allowed limit" in res.json()["detail"]


def test_upload_rejects_fake_pdf_wrong_magic_bytes(client: TestClient, admin_user_a: User):
    """Test file with wrong magic bytes is rejected even if named .pdf and has application/pdf header."""
    headers = auth_headers_for(admin_user_a)
    fake_pdf = b"This is just plain text, not a real PDF file!"

    res = client.post(
        "/documents",
        headers=headers,
        files={"file": ("fake.pdf", fake_pdf, "application/pdf")},
    )
    assert res.status_code == 400
    assert "Invalid file signature" in res.json()["detail"]


def test_upload_valid_png_and_jpeg(client: TestClient, admin_user_a: User):
    """Test valid PNG and JPEG files upload successfully."""
    headers = auth_headers_for(admin_user_a)

    png_res = client.post(
        "/documents",
        headers=headers,
        files={"file": ("image.png", VALID_PNG_BYTES, "image/png")},
    )
    assert png_res.status_code == 201
    assert png_res.json()["content_type"] == "image/png"
    assert png_res.json()["storage_key"].endswith(".png")

    jpeg_res = client.post(
        "/documents",
        headers=headers,
        files={"file": ("image.jpg", VALID_JPEG_BYTES, "image/jpeg")},
    )
    assert jpeg_res.status_code == 201
    assert jpeg_res.json()["content_type"] == "image/jpeg"
    assert jpeg_res.json()["storage_key"].endswith(".jpg")


def test_malicious_filename_does_not_escape_upload_directory(
    client: TestClient,
    admin_user_a: User,
    temp_storage,
    db_session: Session,
):
    """Test path traversal in filename (e.g. '../../etc/passwd') is stored safely as metadata and does not escape."""
    headers = auth_headers_for(admin_user_a)
    malicious_filename = "../../etc/passwd"

    res = client.post(
        "/documents",
        headers=headers,
        files={"file": (malicious_filename, VALID_PDF_BYTES, "application/pdf")},
    )
    assert res.status_code == 201
    data = res.json()

    # The storage key must NOT contain the malicious path
    assert "../../" not in data["storage_key"]
    assert data["storage_key"].startswith(f"{admin_user_a.org_id}/")

    # Filename stored as metadata must have had path traversal elements stripped
    assert "/" not in data["original_filename"]
    assert "\\" not in data["original_filename"]

    # File on disk must reside inside base_dir
    file_path = temp_storage._resolve_path(data["storage_key"])
    assert file_path.is_file()
    assert file_path.is_relative_to(temp_storage.base_dir)


def test_audit_log_created_on_upload_and_delete(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    """Test that audit log entries are properly created on document upload and deletion."""
    headers = auth_headers_for(admin_user_a)

    # Upload
    upload_res = client.post(
        "/documents",
        headers=headers,
        files={"file": ("audit_test.pdf", VALID_PDF_BYTES, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = uuid.UUID(upload_res.json()["id"])

    upload_audit = (
        db_session.query(AuditLog).filter(AuditLog.entity_id == doc_id, AuditLog.action == "document_upload").first()
    )
    assert upload_audit is not None
    assert upload_audit.org_id == admin_user_a.org_id
    assert upload_audit.user_id == admin_user_a.id

    # Delete
    del_res = client.delete(f"/documents/{doc_id}", headers=headers)
    assert del_res.status_code == 204

    delete_audit = (
        db_session.query(AuditLog).filter(AuditLog.entity_id == doc_id, AuditLog.action == "document_delete").first()
    )
    assert delete_audit is not None
    assert delete_audit.org_id == admin_user_a.org_id
    assert delete_audit.user_id == admin_user_a.id
