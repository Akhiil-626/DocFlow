# DocFlow Backend

DocFlow is a multi-tenant invoice-processing backend built with FastAPI, SQLAlchemy 2.0, PostgreSQL, Celery, and Redis.

---

## Architecture & Features

### Week 1: Scaffold, Authentication & Local Storage
- **Application Scaffold**: FastAPI application with SQLAlchemy 2.0 (sync) + psycopg 3 and Alembic migrations.
- **Authentication & Security**: Argon2 password hashing via `pwdlib[argon2]`, PyJWT access tokens (15-min expiry), and HttpOnly refresh token cookies with automatic rotation and reuse revocation detection.
- **Role-Based Access Control (RBAC)**: Enforced via `require_role(...)` dependency:
  - `admin`: Full administrative access (upload, view, list, download, reprocess, reset-stale, and delete documents).
  - `reviewer`: Can upload, view, list, download, and reprocess failed documents.
  - `viewer`: Read-only access (can view metadata, view extractions, list, and download documents).
- **Tenant Isolation**: Every database query is strictly scoped to the caller's `org_id`. Cross-tenant resource access returns HTTP 404.
- **Secure File Storage**: Storage abstraction (`Storage` interface and `LocalStorage`) with path traversal protection. Files are saved at `{org_id}/{document_id}{ext}` and never use user-controlled filenames in paths.
- **File Validation**: Enforces a strict 10 MB limit and validates magic bytes / file signatures (allowing only authentic PDF, PNG, and JPEG files).
- **Audit Logging**: Structured audit entries recorded for registrations, uploads, deletions, extractions, and reprocessing.

### Week 2: Celery Background Processing & LLM Invoice Extraction
- **Asynchronous Processing Pipeline**:
  - Redis 7 as the message broker.
  - Celery worker running `app.worker.tasks.process_document` with `acks_late=True` and time limits.
  - Background task enqueueing occurs strictly after database transaction commits.
  - Atomic idempotency transitions (`uploaded` -> `processing`) preventing concurrent race conditions and duplicate processing.
  - Automatic exponential backoff retries (max 3) for transient errors (rate limits, timeouts) and immediate termination without retry for permanent errors.
- **LLM Extraction Engine**:
  - Provider interface (`LLMClient`) supporting `MockLLMClient` (for local offline dev/testing with zero API keys), `GeminiLLMClient` (using the official Google GenAI SDK), and `OllamaLLMClient` (for local open models).
  - Prompt injection defense: untrusted document text is quarantined within explicit `<invoice_data>` tags accompanied by strict system instructions to ignore embedded instructions.
  - Automatic repair retry: single self-correction retry with the validation error fed back to the LLM if initial JSON is malformed.
  - Strict Pydantic v2 schemas enforcing exact `Decimal` precision for all money, tax, and quantity values (never floating-point).
- **Extraction Persistence**:
  - `extractions` table with unique constraint per document, tracking model, input/output tokens, and latency.
  - `line_items` table with `Numeric` columns cascading on extraction deletion.
- **Operational Endpoints**:
  - `GET /documents/{id}/extraction`: retrieve structured invoice extraction and line items.
  - `POST /documents/{id}/reprocess`: re-enqueue failed documents.
  - `POST /documents/reset-stale`: administrative recovery for documents stuck in `processing`.

### Week 3: Deterministic Validation, Duplicate Detection & Review Queue Routing
- **Pure Deterministic Validation Engine (`app/validation.py`)**:
  - Pure function `validate_extraction(extraction, context) -> list[Issue]`, free of database and network calls for high-speed unit testing.
  - Evaluates mathematical integrity with `Decimal` precision and configurable rounding tolerance (`VALIDATION_TOLERANCE=1.00`).
  - Evaluates tax rules: IGST vs CGST/SGST exclusivity, CGST/SGST equality, and allowed GST tax rates list (`VALIDATION_ALLOWED_TAX_RATES`).
  - Format checks: 15-character GSTIN regex with state code whitelist (`VALIDATION_ALLOWED_GST_STATE_CODES`). Check-character algorithm safely skipped per specification.
  - Temporal checks: future invoice dates rejected, old invoices flagged beyond configurable threshold (`VALIDATION_MAX_INVOICE_AGE_DAYS=365`).
  - Configurable review routing: warnings automatically route to review when `VALIDATION_WARNINGS_ROUTE_TO_REVIEW=True`.
- **Duplicate Detection Pipeline (`app/duplicate_detection.py`)**:
  - **Exact File Duplicate**: Matches exact `sha256` within the same organization. The uploader receives the existing document ID immediately without rejecting the upload.
  - **Semantic Duplicate**: Matches normalized vendor (`vendor_gstin` preferred, or lowercase stripped alphanumeric vendor name), exact `invoice_number`, and matching `total` within the same organization. Concurrency-safe against race conditions via database index and deterministic ordering.
- **Strict Document Status State Machine (`transition_document_status`)**:
  - Guaranteed valid transitions:
    - `uploaded` -> `processing`
    - `processing` -> `extracted` or `failed`
    - `extracted` -> `auto_approved` or `needs_review`
    - `failed` -> `uploaded` (via reprocessing or stale reset)
  - Invalid transitions raise `ValueError`, ensuring pipeline integrity.
- **Review Queue & Operations**:
  - `GET /documents/review-queue`: paginated FIFO review queue (oldest first) restricted to `admin` and `reviewer`.
  - `GET /stats`: organization-level counts for all statuses, total documents, and auto-approval percentage.
  - `GET /documents?status=...&has_issues=...`: multi-criteria filtering on document lists.
  - `GET /documents/{id}/extraction`: returns structured extraction along with all persisted validation issues.

---

## Quickstart

### 1. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Key settings:
- `LLM_PROVIDER`: `mock` (default for local development and offline testing) or `gemini`.
- `LLM_API_KEY`: Required only when `LLM_PROVIDER=gemini`.
- `LLM_MODEL`: e.g. `gemini-2.5-flash`.
- `CELERY_BROKER_URL`: `redis://localhost:6379/0` (host) or `redis://redis:6379/0` (Docker).

### 2. Start Services with Docker Compose
Run all services (PostgreSQL, Redis, API, and Celery Worker):
```bash
docker compose up --build
```
Once healthy, services will be accessible at:
- **API Base**: `http://localhost:8000`
- **Health Check**: `http://localhost:8000/health`
- **Interactive Swagger UI**: `http://localhost:8000/docs`
- **PostgreSQL**: Port 5433 (host mapped to avoid port 5432 collisions)
- **Redis**: Port 6379

---

## Running Tests

Tests run against a separate, isolated PostgreSQL database `docflow_test` on the database service (never touching the development `docflow` database), with tables cleaned up via `TRUNCATE ... CASCADE` after every test.

### Run Tests Inside Docker
```bash
docker compose exec api pytest -v
```

### Run Tests Locally (Host Environment)
Ensure the Docker database and Redis containers are running:
```bash
# Run full pytest test suite (54 tests)
pytest -v

# Run Week 3 validation & pipeline integration tests specifically
pytest tests/test_validation.py tests/test_validation_pipeline.py -v

# Run code style and lint checks
ruff check app tests scripts
```

---

## Validation Rules Engine

All validation rules are pure deterministic functions implemented in `app/validation.py` using `Decimal` arithmetic. The GSTIN check-character verification was safely skipped per the specification in favor of a 15-character structural regex with state code whitelist verification.

| Rule Code | Severity | Description | Configurable Setting |
| :--- | :--- | :--- | :--- |
| `LINE_ITEM_AMOUNT_MISMATCH` | `error` | Line item `quantity * unit_price != amount` | `VALIDATION_TOLERANCE` (default: `1.00`) |
| `LINE_ITEMS_SUM_MISMATCH` | `error` | Sum of line item amounts `!= subtotal` | `VALIDATION_TOLERANCE` (default: `1.00`) |
| `TOTAL_MISMATCH` | `error` | `subtotal + cgst + sgst + igst != total` | `VALIDATION_TOLERANCE` (default: `1.00`) |
| `TAX_TYPE_CONFLICT` | `error` | IGST combined with CGST/SGST (intra vs inter-state) | Deterministic |
| `NEGATIVE_AMOUNT` | `error` | Negative money, tax, or quantity value | Deterministic |
| `MISSING_INVOICE_NUMBER` | `error` | Empty or null invoice number | Deterministic |
| `MISSING_VENDOR_NAME` | `error` | Empty or null vendor name | Deterministic |
| `NO_LINE_ITEMS` | `error` | Invoice has zero line items | Deterministic |
| `INVALID_GSTIN` | `error` | 15-char regex mismatch or invalid state code | `VALIDATION_ALLOWED_GST_STATE_CODES` |
| `FUTURE_INVOICE_DATE` | `error` | Invoice date is ahead of current UTC date | Deterministic |
| `CGST_SGST_MISMATCH` | `warning` | CGST amount != SGST amount | Deterministic |
| `UNEXPECTED_TAX_RATE` | `warning` | Effective tax rate `(tax / subtotal)` not in whitelist | `VALIDATION_ALLOWED_TAX_RATES` (e.g. `0.0, 0.05, 0.12, 0.18, 0.28`) |
| `OLD_INVOICE_DATE` | `warning` | Invoice date older than configured max days | `VALIDATION_MAX_INVOICE_AGE_DAYS` (default: `365`) |
| `MISSING_GSTIN` | `warning` | Vendor GSTIN missing on invoice | Deterministic |
| `DUPLICATE_SUSPECTED` | `warning` | Semantic match (same org, vendor, invoice #, and total) | Deterministic (scoped to org) |

> When `VALIDATION_WARNINGS_ROUTE_TO_REVIEW=True` (default), documents with any warnings route to `needs_review`. If set to `False`, documents with warnings only are routed to `auto_approved`. Any document with at least one `error` always routes to `needs_review`.

---

## Document Status State Machine

DocFlow enforces a strict status lifecycle via `transition_document_status(document, new_status)`:

```
                      ┌───────────────┐
                      │   uploaded    │◄───────────────┐
                      └───────┬───────┘                │
                              │ (Worker picks up)      │
                              ▼                        │ (Reprocess /
                      ┌───────────────┐                │  Reset Stale)
                      │  processing   │                │
                      └───┬───────┬───┘                │
                          │       │                    │
            (Fatal Error) │       │ (LLM Success)      │
                          ▼       ▼                    │
     ┌──────────────────────┐   ┌───────────────┐      │
     │        failed        ├───┤   extracted   │      │
     └──────────────────────┘   └───┬───────┬───┘      │
                 ▲                  │       │          │
                 │                  │       │          │
                 │ (0 Issues)       │       │ (>0 Issues)
                 │                  ▼       ▼          │
                 │   ┌────────────────┐   ┌───────────────┐
                 │   │ auto_approved  │   │ needs_review  │
                 │   └────────────────┘   └───────┬───────┘
                 │                                │
                 └────────────────────────────────┘
```

| Source Status | Allowed Target Statuses | Trigger / Responsible Component |
| :--- | :--- | :--- |
| `uploaded` | `processing` | Celery worker start (`process_document`) |
| `processing` | `extracted` | LLM client finishes extraction and line items |
| `processing` | `failed` | Unrecoverable error (e.g., corrupt PDF, no text, LLM fail) |
| `extracted` | `auto_approved` | Pure validation + duplicate check find 0 blocking issues |
| `extracted` | `needs_review` | Pure validation or duplicate check detect errors/warnings |
| `failed` | `uploaded` | Manual `POST /reprocess` or admin `POST /reset-stale` |

---

## Sample Invoices & Pipeline Evaluation

### Generate 20 Evaluation Samples
Generates 10 clean GST invoices and 10 bad invoices testing specific validation boundaries and duplicate detection:
```bash
python scripts/generate_sample_invoices.py
```

### Run End-to-End Evaluation
Executes the full pipeline against all 20 invoices, audits extraction accuracy, and records issue detection into `evaluation_results.md`:
```bash
python scripts/evaluate.py
```

---

## Example API Workflows (cURL)

### 1. Register Organization & Admin User
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "org_name": "Acme Logistics",
    "email": "admin@acmelogistics.com",
    "password": "SuperSecretPassword123!"
  }'
```

### 2. Login
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{
    "email": "admin@acmelogistics.com",
    "password": "SuperSecretPassword123!"
  }'
```

### 3. Check Current User
```bash
curl -X GET http://localhost:8000/auth/me \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### 4. Upload an Invoice (PDF)
Multipart upload automatically enqueues the document for background processing:
```bash
curl -X POST http://localhost:8000/documents \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -F "file=@samples/invoice_01.pdf"
```
Response:
```json
{
  "id": "e96b52c0-87a1-43e5-82ee-06b5d63f0340",
  "org_id": "...",
  "original_filename": "invoice_01.pdf",
  "content_type": "application/pdf",
  "size_bytes": 2293,
  "status": "uploaded",
  "error_message": null,
  "processed_at": null,
  "attempts": 0,
  "created_at": "...",
  "updated_at": "...",
  "existing_document_id": null
}
```

### 5. Review Queue (Oldest First)
Reviewers and Admins can query the review queue for documents requiring attention:
```bash
curl -X GET "http://localhost:8000/documents/review-queue?skip=0&limit=20" \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### 6. Organization Processing Statistics
Retrieve real-time processing counts and auto-approval rates for the caller's organization:
```bash
curl -X GET http://localhost:8000/stats \
  -H "Authorization: Bearer <JWT_TOKEN>"
```
Response:
```json
{
  "total_documents": 20,
  "status_counts": {
    "auto_approved": 8,
    "needs_review": 12,
    "failed": 0,
    "uploaded": 0,
    "processing": 0,
    "extracted": 0
  },
  "auto_approved_count": 8,
  "needs_review_count": 12,
  "failed_count": 0,
  "auto_approval_rate_percent": 40.0
}
```

### 7. Filter Documents
List documents filtered by status and whether they contain validation issues:
```bash
curl -X GET "http://localhost:8000/documents?status=needs_review&has_issues=true" \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### 8. Get Document Extraction & Validation Issues
```bash
curl -X GET http://localhost:8000/documents/<DOCUMENT_UUID>/extraction \
  -H "Authorization: Bearer <JWT_TOKEN>"
```
Response includes both structured extraction data and all detected validation issues:
```json
{
  "id": "76ec4ecb-f117-48f8-b328-3e53d53bce7c",
  "document_id": "e96b52c0-87a1-43e5-82ee-06b5d63f0340",
  "data": {
    "vendor_name": "Calculus Glitch Labs",
    "vendor_gstin": "29AABCU9603R1ZM",
    "invoice_number": "BAD-TOTAL-001",
    "invoice_date": "2026-03-01",
    "currency": "INR",
    "subtotal": "10000.00",
    "cgst": "900.00",
    "sgst": "900.00",
    "igst": "0.00",
    "total": "15000.00"
  },
  "model": "mock-model",
  "input_tokens": 120,
  "output_tokens": 85,
  "latency_ms": 5,
  "created_at": "...",
  "line_items": [...],
  "validation_issues": [
    {
      "id": "...",
      "code": "TOTAL_MISMATCH",
      "severity": "error",
      "field": "total",
      "message": "Subtotal (10000.00) + taxes (1800.00) = 11800.00, does not match total (15000.00).",
      "created_at": "..."
    }
  ]
}
```

### 9. Reprocess a Failed Document
Admin and Reviewer can re-enqueue any failed document:
```bash
curl -X POST http://localhost:8000/documents/<DOCUMENT_UUID>/reprocess \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### 10. Reset Stale Processing Documents
Admin can reset any document stuck in `processing` back to `uploaded`:
```bash
curl -X POST "http://localhost:8000/documents/reset-stale?stale_minutes=10" \
  -H "Authorization: Bearer <JWT_TOKEN>"
```
