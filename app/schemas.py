import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------- Auth Schemas ----------------
class RegisterRequest(BaseModel):
    org_name: str = Field(..., min_length=1, max_length=255, description="Organization name")
    email: EmailStr = Field(..., description="User's unique email address")
    password: str = Field(..., min_length=8, max_length=128, description="User's password")


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="User's password")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    role: Literal["admin", "reviewer", "viewer"]
    is_active: bool
    created_at: datetime


class MessageResponse(BaseModel):
    detail: str


# ---------------- Extraction Schemas (Validation) ----------------
class InvoiceLineItemSchema(BaseModel):
    description: str = Field(..., min_length=1, description="Item or service description")
    quantity: Decimal = Field(..., description="Quantity of items")
    unit_price: Decimal = Field(..., description="Price per unit")
    amount: Decimal = Field(..., description="Total line amount")


class InvoiceExtractionSchema(BaseModel):
    vendor_name: str = Field(..., min_length=1, description="Vendor or supplier business name")
    vendor_gstin: str | None = Field(default=None, description="Vendor GSTIN if present")
    invoice_number: str = Field(..., min_length=1, description="Invoice reference number")
    invoice_date: date | str = Field(..., description="Date of invoice")
    currency: str = Field(default="INR", description="Currency code (e.g. INR, USD)")
    subtotal: Decimal | None = Field(default=Decimal("0"), description="Pre-tax subtotal amount")
    cgst: Decimal | None = Field(default=Decimal("0"), description="Central GST amount")
    sgst: Decimal | None = Field(default=Decimal("0"), description="State GST amount")
    igst: Decimal | None = Field(default=Decimal("0"), description="Integrated GST amount")
    total: Decimal = Field(..., description="Invoice total amount")
    line_items: list[InvoiceLineItemSchema] = Field(default_factory=list, description="Extracted line items")


# ---------------- Dedicated LLM Output Schema (Ollama) ----------------
class LLMLineItemSchema(BaseModel):
    description: str = Field(..., min_length=1, description="Item or service description")
    quantity: str = Field(
        ...,
        description="Quantity of items. Plain digits with an optional decimal point, as strings, with NO thousands separators, currency symbols or spaces",
    )
    unit_price: str = Field(
        ...,
        description="Price per unit. Plain digits with an optional decimal point, as strings, with NO thousands separators, currency symbols or spaces",
    )
    amount: str = Field(
        ...,
        description="Total line amount. Plain digits with an optional decimal point, as strings, with NO thousands separators, currency symbols or spaces",
    )


class OllamaInvoiceExtractionSchema(BaseModel):
    vendor_name: str = Field(..., min_length=1, description="Vendor or supplier business name")
    vendor_gstin: str | None = Field(
        ...,
        description="the 15-character GST number if printed, otherwise null",
    )
    invoice_number: str = Field(..., min_length=1, description="Invoice reference number")
    invoice_date: str = Field(..., description="Date of invoice (YYYY-MM-DD or date string as printed)")
    currency: str = Field(default="INR", description="Currency code (default INR)")
    subtotal: str = Field(
        ...,
        description="subtotal = amount before tax; money values are strings of plain digits with an optional decimal point, as strings, with NO thousands separators, currency symbols or spaces",
    )
    cgst: str = Field(
        ...,
        description="cgst = tax amounts exactly as printed; money values are strings of plain digits with an optional decimal point, with no thousands separators, currency symbols or spaces; use '0.00' only when the invoice shows zero or no such tax",
    )
    sgst: str = Field(
        ...,
        description="sgst = tax amounts exactly as printed; money values are strings of plain digits with an optional decimal point, with no thousands separators, currency symbols or spaces; use '0.00' only when the invoice shows zero or no such tax",
    )
    igst: str = Field(
        ...,
        description="igst = tax amounts exactly as printed; money values are strings of plain digits with an optional decimal point, with no thousands separators, currency symbols or spaces; use '0.00' only when the invoice shows zero or no such tax",
    )
    total: str = Field(
        ...,
        description="total = final invoice total as printed; money values are strings of plain digits with an optional decimal point, with no thousands separators, currency symbols or spaces",
    )
    line_items: list[LLMLineItemSchema] = Field(..., description="Extracted line items")


LLMInvoiceExtractionSchema = OllamaInvoiceExtractionSchema


# ---------------- Document & Extraction Response Schemas ----------------
class LineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class ValidationIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    severity: str
    field: str | None = None
    message: str
    created_at: datetime


class ExtractionPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(..., description="Current extraction version for optimistic concurrency")
    vendor_name: str | None = Field(default=None, min_length=1)
    vendor_gstin: str | None = None
    invoice_number: str | None = Field(default=None, min_length=1)
    invoice_date: date | str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    cgst: Decimal | None = None
    sgst: Decimal | None = None
    igst: Decimal | None = None
    total: Decimal | None = None
    line_items: list[InvoiceLineItemSchema] | None = None
    note: str | None = None


class ApproveRequest(BaseModel):
    override: bool = False
    reason: str | None = None


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Reason for rejecting the document")


class ExportCreateRequest(BaseModel):
    format: Literal["csv", "json"] = Field(..., description="Export format: csv or json")


class ExportBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    created_by: uuid.UUID | None
    format: str
    row_count: int
    created_at: datetime


class ExportBatchListResponse(BaseModel):
    items: list[ExportBatchResponse]
    total: int
    limit: int
    offset: int


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID | None
    actor_email: str = "system"
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    limit: int
    offset: int


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    org_id: uuid.UUID
    original_data: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any]
    version: int = 1
    edited_at: datetime | None = None
    edited_by: uuid.UUID | None = None
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int
    created_at: datetime
    line_items: list[LineItemResponse] = Field(default_factory=list)
    validation_issues: list[ValidationIssueResponse] = Field(default_factory=list)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    uploaded_by: uuid.UUID | None
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_key: str
    status: str
    error_message: str | None = None
    review_reason: str | None = None
    validated_at: datetime | None = None
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    export_batch_id: uuid.UUID | None = None
    exported_at: datetime | None = None
    processed_at: datetime | None = None
    attempts: int = 0
    existing_document_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int


class ReviewQueueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    created_at: datetime
    validated_at: datetime | None = None
    status: str
    review_reason: str | None = None
    issue_count: int = 0
    issues: list[ValidationIssueResponse] = Field(default_factory=list)


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItemResponse]
    total: int


class TopFieldCorrection(BaseModel):
    field: str
    count: int


class StatsResponse(BaseModel):
    counts: dict[str, int]
    total: int
    auto_approval_rate: float
    documents_reviewed: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    correction_rate: float = 0.0
    top_corrected_fields: list[TopFieldCorrection] = Field(default_factory=list)

