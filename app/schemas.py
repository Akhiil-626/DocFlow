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


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    org_id: uuid.UUID
    data: dict[str, Any]
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


class StatsResponse(BaseModel):
    counts: dict[str, int]
    total: int
    auto_approval_rate: float

