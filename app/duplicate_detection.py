import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, Extraction
from app.validation import Issue, _to_decimal


def normalize_vendor_identifier(vendor_name: str | None, vendor_gstin: str | None) -> str:
    """Normalize vendor identifier: prefer GSTIN if available, otherwise normalize vendor name.

    Normalization: lowercase, strip punctuation and spaces.
    """
    if vendor_gstin and str(vendor_gstin).strip():
        # Prefer GSTIN when present
        return re.sub(r"[^a-zA-Z0-9]", "", str(vendor_gstin)).upper()

    if vendor_name and str(vendor_name).strip():
        # Lowercase, strip punctuation and whitespace
        return re.sub(r"[^a-zA-Z0-9]", "", str(vendor_name)).lower()

    return ""


def normalize_invoice_number(invoice_number: str | None) -> str:
    """Normalize invoice number: lowercase, strip punctuation and whitespace."""
    if not invoice_number:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", str(invoice_number)).lower()


def detect_duplicates(
    db: Session,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    sha256: str,
    extraction_data: dict[str, Any],
) -> list[Issue]:
    """Detect exact file duplicates and semantic duplicates within the same organization.

    Guarantees strict tenant isolation by scoping all queries to org_id.
    Prevents race conditions by deterministic ordering so at least one or both get flagged.
    """
    duplicate_issues: list[Issue] = []

    # 1. Exact File Duplicate Check (same sha256 stored for this org)
    exact_match = (
        db.query(Document)
        .filter(
            Document.org_id == org_id,
            Document.sha256 == sha256,
            Document.id != document_id,
        )
        .order_by(Document.created_at.asc(), Document.id.asc())
        .first()
    )
    if exact_match:
        duplicate_issues.append(
            Issue(
                code="DUPLICATE_SUSPECTED",
                severity="warning",
                field="sha256",
                message=f"Exact file duplicate of document {exact_match.id} (identical SHA-256)",
            )
        )

    # 2. Semantic Duplicate Check
    target_invoice_num = normalize_invoice_number(extraction_data.get("invoice_number"))
    target_vendor = normalize_vendor_identifier(
        extraction_data.get("vendor_name"),
        extraction_data.get("vendor_gstin"),
    )
    target_total = _to_decimal(extraction_data.get("total"))

    if target_invoice_num and target_vendor:
        # Search extractions in the same organization
        candidate_extractions = (
            db.query(Extraction)
            .join(Document, Extraction.document_id == Document.id)
            .filter(
                Extraction.org_id == org_id,
                Extraction.document_id != document_id,
            )
            .order_by(Extraction.created_at.asc())
            .all()
        )

        for candidate in candidate_extractions:
            cand_data = candidate.data or {}
            cand_inv = normalize_invoice_number(cand_data.get("invoice_number"))
            cand_vendor = normalize_vendor_identifier(
                cand_data.get("vendor_name"),
                cand_data.get("vendor_gstin"),
            )
            cand_total = _to_decimal(cand_data.get("total"))

            if (
                cand_inv == target_invoice_num
                and cand_vendor == target_vendor
                and abs(cand_total - target_total) <= Decimal("0.01")
            ):
                duplicate_issues.append(
                    Issue(
                        code="DUPLICATE_SUSPECTED",
                        severity="warning",
                        field="invoice_number",
                        message=(
                            f"Semantic duplicate of document {candidate.document_id}: "
                            f"matching vendor, invoice number '{extraction_data.get('invoice_number')}', "
                            f"and total {target_total:.2f}"
                        ),
                    )
                )
                break  # Flag once per semantic duplicate match

    return duplicate_issues
