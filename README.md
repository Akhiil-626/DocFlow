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

### Week 4A: Human Review Workflow & Deterministic Exports
- **Immutable LLM Provenance & Optimistic Concurrency**:
  - Original model extraction is preserved immutable in `extractions.original_data` (JSONB) and never modified after initial creation.
  - Human corrections increment `extractions.version` and update `extractions.data` and `line_items`.
  - Optimistic locking: `PATCH /documents/{id}/extraction` requires current `version` in body and returns `409 Conflict` on concurrent collisions.
  - Every edit re-runs validation and duplicate detection, replacing `validation_issues`, and logs full field-level diffs in `audit_log`.
- **Review Decision Workflows**:
  - `POST /documents/{id}/approve`: transitions `needs_review` -> `approved`. If unresolved error issues exist, requires `override=True` and a non-empty `reason`.
  - `POST /documents/{id}/reject`: transitions `needs_review` -> `rejected` with mandatory human reason.
  - `POST /documents/{id}/reopen`: Admin-only transition returning `approved` or `rejected` documents back to `needs_review` (strictly forbidden once exported).
  - Race condition safe: approvals and rejections utilize row-level locking (`SELECT ... FOR UPDATE`), preventing duplicate actions.
- **Audit Trail & Document History**:
  - `GET /documents/{id}/history`: chronological paginated audit log of state changes, uploads, and extraction diffs.
  - `GET /audit-log`: Admin-only organization audit trail filterable by entity type, entity ID, user, action, and date range.
- **Accounting & ERP Exports**:
  - `POST /exports`: atomic batch creation locking eligible documents (`approved` and `auto_approved`), transitioning them to terminal `exported` status.
  - `GET /exports/{id}/download?type=summary_csv`: header-level invoice CSV with formula injection defense (`'`) and UTF-8 BOM (`\xef\xbb\xbf`) for Microsoft Excel.
  - `GET /exports/{id}/download?type=line_items_csv`: flattened line items CSV with document ID and invoice metadata.
  - `GET /exports/{id}/download?type=json`: deterministic pretty-printed JSON export.
- **Extended Analytics (`GET /stats`)**:
  - Tracks `documents_reviewed`, `approved_count`, `rejected_count`, `correction_rate`, and `top_corrected_fields` across all documents in the organization.

### Week 4B: React + TypeScript Frontend Single-Page Application
- **Tech Stack**: Vite + React 18 + TypeScript (strict mode), Tailwind CSS, TanStack Query, and typed openapi-fetch client generated from `frontend/openapi.json`.
- **Security First**: In-memory access token storage, HttpOnly refresh cookie with single-flight automatic session rotation, authenticated blob file streaming, and plain text escaping for all document-derived data.
- **Operator Workspaces**:
  - `/documents`: Paginated invoices, status filters, drag-and-drop upload, exact-duplicate alerts, and reprocess actions.
  - `/review`: FIFO human review queue.
  - `/documents/:id`: Desktop split-layout with PDF/image blob preview, issue navigation, string decimal editing, optimistic 409 conflict handling, dirty navigation guards, version comparison, and Approve/Reject/Reopen flows.
  - `/exports`: Batch listing, CSV/JSON batch creation, and authenticated downloads.
- Full details, test suite instructions, and manual browser walkthroughs are documented in [frontend/README.md](frontend/README.md).

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
                      │   uploaded    │◄────────────────┐
                      └───────┬───────┘                 │
                              │ (Worker picks up)       │
                              ▼                         │ (Reprocess /
                      ┌───────────────┐                 │  Reset Stale)
                      │  processing   │                 │
                      └───┬───────┬───┘                 │
                          │       │                     │
            (Fatal Error) │       │ (LLM Success)       │
                          ▼       ▼                     │
     ┌──────────────────────┐   ┌───────────────┐       │
     │        failed        ├───┤   extracted   │       │
     └──────────────────────┘   └───┬───────┬───┘       │
                 ▲                  │       │           │
                 │                  │       │           │
                 │ (0 Issues)       │       │ (>0 Issues)
                 │                  ▼       ▼           │
                 │   ┌────────────────┐   ┌───────────────┐
                 │   │ auto_approved  │   │ needs_review  │◄───────┐
                 │   └───────┬────────┘   └───┬───────┬───┘        │
                 │           │                │       │            │
                 └───────────┼────────────────┘       │            │
                             │         ┌──────────────┘            │
                             │         │                           │
                             │         ▼                           │
                             │   ┌───────────────┐                 │ (Reopen: Admin Only,
                             │   │   rejected    ├─────────────────┤  Forbidden once
                             │   └───────────────┘                 │  exported)
                             ▼                                     │
                     ┌───────────────┐                             │
                     │   approved    ├─────────────────────────────┘
                     └───────┬───────┘
                             │
                             ▼ (Batch Export)
                     ┌───────────────┐
                     │   exported    │ (Terminal)
                     └───────────────┘
```

| Source Status | Allowed Target Statuses | Trigger / Responsible Component |
| :--- | :--- | :--- |
| `uploaded` | `processing` | Celery worker start (`process_document`) |
| `processing` | `extracted` | LLM client finishes extraction and line items |
| `processing` | `failed` | Unrecoverable error (e.g., corrupt PDF, no text, LLM fail) |
| `extracted` | `auto_approved` | Pure validation + duplicate check find 0 blocking issues |
| `extracted` | `needs_review` | Pure validation or duplicate check detect errors/warnings |
| `failed` | `uploaded` | Manual `POST /reprocess` or admin `POST /reset-stale` |
| `needs_review` | `approved` | Human approval (`POST /documents/{id}/approve`) |
| `needs_review` | `rejected` | Human rejection with reason (`POST /documents/{id}/reject`) |
| `approved` | `exported` | Batch export creation (`POST /exports`) |
| `auto_approved` | `exported` | Batch export creation (`POST /exports`) |
| `approved` | `needs_review` | Admin reopening (`POST /documents/{id}/reopen`) |
| `rejected` | `needs_review` | Admin reopening (`POST /documents/{id}/reopen`) |
| `exported` | *None* | **Terminal status** (cannot be reopened or re-exported) |

---

## Role-Based Access Control (RBAC) Matrix

| Endpoint | Method | Admin | Reviewer | Viewer | Notes |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `/documents/{id}/extraction` | `PATCH` | ✅ | ✅ | ❌ | Allowed only when status is `needs_review`; requires version match |
| `/documents/{id}/approve` | `POST` | ✅ | ✅ | ❌ | Requires `override=true` & reason if errors exist |
| `/documents/{id}/reject` | `POST` | ✅ | ✅ | ❌ | Requires non-empty reason |
| `/documents/{id}/reopen` | `POST` | ✅ | ❌ | ❌ | Blocked once document is `exported` (HTTP 409) |
| `/documents/{id}/history` | `GET` | ✅ | ✅ | ✅ | Paginated audit trail for document |
| `/exports` | `POST` | ✅ | ✅ | ❌ | Atomically transitions eligible docs to `exported` |
| `/exports` | `GET` | ✅ | ✅ | ✅ | List export batches |
| `/exports/{id}/download` | `GET` | ✅ | ✅ | ✅ | Download summary CSV, line items CSV, or JSON |
| `/audit-log` | `GET` | ✅ | ❌ | ❌ | Org audit log with multi-field filtering |
| `/stats` | `GET` | ✅ | ✅ | ✅ | Review metrics, correction rates, and top corrected fields |

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

### 11. Edit Extraction (Needs Review Only)
Update header fields or line items with optimistic concurrency control (`version` required):
```bash
curl -X PATCH http://localhost:8000/documents/<DOCUMENT_UUID>/extraction \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "version": 1,
    "vendor_name": "Apex Technologies Pvt Ltd",
    "total": "1180.00",
    "note": "Corrected vendor name and total per paper PO"
  }'
```

### 12. Approve an Invoice
Transition an invoice from `needs_review` to `approved`:
```bash
# Standard approval (valid when 0 unresolved error issues)
curl -X POST http://localhost:8000/documents/<DOCUMENT_UUID>/approve \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'

# Approval with override (required when unresolved error issues exist)
curl -X POST http://localhost:8000/documents/<DOCUMENT_UUID>/approve \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "override": true,
    "reason": "Total mismatch of 0.50 accepted as vendor roundoff discrepancy"
  }'
```

### 13. Reject an Invoice
Transition an invoice from `needs_review` to `rejected` with mandatory human explanation:
```bash
curl -X POST http://localhost:8000/documents/<DOCUMENT_UUID>/reject \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Duplicate billing against PO-99824; already paid in March"
  }'
```

### 14. Reopen Document (Admin Only)
Reopen an `approved` or `rejected` invoice back to `needs_review` (strictly forbidden once exported):
```bash
curl -X POST http://localhost:8000/documents/<DOCUMENT_UUID>/reopen \
  -H "Authorization: Bearer <ADMIN_JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Reopened following vendor revised credit note"
  }'
```

### 15. View Document History
Retrieve a chronological audit log of all human edits, approvals, and rejections:
```bash
curl -X GET "http://localhost:8000/documents/<DOCUMENT_UUID>/history?limit=50" \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### 16. Create Batch Export
Atomically export all currently `approved` and `auto_approved` invoices:
```bash
curl -X POST http://localhost:8000/exports \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "format": "csv"
  }'
```
Response:
```json
{
  "id": "76ec4ecb-f117-48f8-b328-3e53d53bce7c",
  "org_id": "...",
  "created_by": "...",
  "format": "csv",
  "row_count": 5,
  "created_at": "..."
}
```

### 17. Download Export Files
Download batch summary CSV, flattened line items CSV, or JSON:
```bash
# 1. Summary CSV (UTF-8 BOM with formula injection protection)
curl -X GET "http://localhost:8000/exports/<EXPORT_UUID>/download?type=summary_csv" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -o export_summary.csv

# 2. Line Items CSV
curl -X GET "http://localhost:8000/exports/<EXPORT_UUID>/download?type=line_items_csv" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -o export_line_items.csv

# 3. Full JSON Export
curl -X GET "http://localhost:8000/exports/<EXPORT_UUID>/download?type=json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -o export_bundle.json
```

### 18. Filter Audit Log (Admin Only)
Search organization-wide audit trails by action, entity type, user, or date range:
```bash
curl -X GET "http://localhost:8000/audit-log?action=edit_extraction&limit=25" \
  -H "Authorization: Bearer <ADMIN_JWT_TOKEN>"
```

---

## Pipeline Evaluation (Week 5A)

DocFlow includes an automated evaluation harness in `scripts/evaluate.py` to benchmark end-to-end extraction accuracy, pipeline routing, and latency across real local models using [Ollama](https://ollama.com/) or mock providers.

### 1. Running Evaluation with Local Models

Ensure Ollama is running and the models you want to benchmark are pulled:
```bash
ollama pull llama3.2:3b
ollama pull qwen2.5:7b
```

Run the benchmark across multiple models:
```bash
# In Docker or local environment:
python scripts/evaluate.py \
  --models "llama3.2:3b,qwen2.5:7b" \
  --hardware "Apple M2 16GB" \
  --repeat 3 \
  --base-url "http://localhost:11434"
```

For mock provider testing (zero network / offline):
```bash
python scripts/evaluate.py \
  --models "mock-model,mock-model-v2" \
  --provider mock \
  --hardware "Local Dev Machine" \
  --repeat 2
```

### 2. Evaluated Metrics & How to Read the Results

| Metric | Definition & Significance |
| :--- | :--- |
| **Invoice Accuracy (All Fields Correct)** | Percentage of invoices where *every single field* matches ground truth. Evaluates overall extraction fidelity. |
| **Silent Error Rate** | **The Key Honesty Metric**: Percentage of **auto-approved** invoices that contain at least one wrong field. Lower is better (ideally 0.0%). Demonstrates whether bad extractions slip into downstream systems without human review. |
| **Validation Catch Rate** | Percentage of flawed extractions successfully flagged by deterministic validation rules and routed to `needs_review` or `failed` rather than auto-approved. |
| **Pipeline Routing Breakdown** | Proportion of invoices categorized as `auto_approved` vs `needs_review` vs `failed`. |
| **Latency (Median p50 / p95)** | End-to-end processing duration per invoice in seconds. p95 reveals worst-case performance under heavy prompt generation. |
| **Avg Tokens / Invoice** | Total prompt input + completion output tokens consumed per invoice. |
| **Repair Retries Used** | Number of times the LLM failed initial JSON validation and required a secondary self-correction retry with feedback. |
| **Invalid-Output Failures** | Hard failures where the model output could not be parsed into valid schema even after repair retry. |
| **Consistency across Repeats** | Fraction of invoices whose output remained 100% identical across repeat runs (at `temperature: 0`). |

### 3. Evaluation Limits & What the Numbers Do Not Prove

- **Synthetic Invoices**: All sample PDFs (`samples/*.pdf`) were synthetically generated with known layouts and fonts. They do not have scan artifacts, skew, rotation, or noise.
- **Small Sample Size**: The default benchmark dataset contains 20 invoices (10 valid, 10 bad). While sufficient for unit-level verification and regression testing, it is not a large-scale statistical benchmark.
- **Clean Text Extraction**: Invoices are evaluated using digital text extraction (`pdfplumber`). The benchmark does not assess OCR performance on handwritten, low-DPI, or degraded physical documents.
- **What Numbers Do NOT Prove**: High accuracy on this test set proves prompt compliance, schema discipline, and validation rule efficacy on tested templates. It **does not prove** zero hallucination or 100% reliability on wild, unstandardized commercial invoices.

