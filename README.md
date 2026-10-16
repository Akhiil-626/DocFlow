# DocFlow Backend

DocFlow is a multi-tenant invoice-processing backend built with FastAPI, SQLAlchemy 2.0, and PostgreSQL.

## Features (Week 1 Scaffold)
- **Scaffold & Architecture**: FastAPI application with SQLAlchemy 2.0 (sync) + psycopg 3 and Alembic migrations.
- **Authentication & Security**: Argon2 password hashing via `pwdlib[argon2]`, PyJWT access tokens (15-min expiry), and HttpOnly refresh token cookies with automatic rotation and reuse revocation detection.
- **Role-Based Access Control (RBAC)**: Enforced via `require_role(...)` dependency:
  - `admin`: Full administrative access (can upload, view, list, download, and delete documents).
  - `reviewer`: Can upload, view, list, and download documents.
  - `viewer`: Read-only access (can view metadata, list, and download documents).
- **Tenant Isolation**: Every database query is strictly scoped to the caller's `org_id`. Cross-tenant resource access returns HTTP 404.
- **Secure File Storage**: Storage abstraction (`Storage` interface and `LocalStorage`) with path traversal protection. Files are saved at `{org_id}/{document_id}{ext}` and never use user-controlled filenames in paths.
- **File Validation**: Enforces a strict 10 MB limit and validates magic bytes / file signatures (allowing only authentic PDF, PNG, and JPEG files).
- **Audit Logging**: Structured audit entries recorded for registrations, document uploads, and document deletions.

---

## Quickstart

### 1. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 2. Start Services with Docker Compose
Run the API and PostgreSQL database containers:
```bash
docker compose up --build
```
Once healthy, the API will be available at:
- **API Base**: `http://localhost:8000`
- **Health Check**: `http://localhost:8000/health`
- **Interactive OpenAPI Documentation (Swagger UI)**: `http://localhost:8000/docs`

---

## Running Tests

Tests run against a separate, isolated PostgreSQL database `docflow_test` on the existing `db` service (never touching the development `docflow` database), with tables cleaned up via `TRUNCATE ... CASCADE` after every test.

### Run Tests Inside Docker (Recommended)
With the containers running:
```bash
docker compose exec api pytest -v
```
Or as a one-off run without persistent containers:
```bash
docker compose run --rm api pytest -v
```

### Run Tests Locally (Host Environment)
Ensure the Docker database container is running so port 5433 is available:
```bash
# Using local virtualenv
pytest -v

# Run code style and lint checks
ruff check app tests
```

---

## Example API Workflows (cURL)

### 1. Register Organization & Admin User
Creates a new tenant organization and its initial administrative user:
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
Authenticates credentials, returns an access token in the JSON body, and sets a 7-day HttpOnly cookie (`refresh_token`):
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{
    "email": "admin@acmelogistics.com",
    "password": "SuperSecretPassword123!"
  }'
```
Response:
```json
{
  "access_token": "<JWT_TOKEN>",
  "token_type": "bearer"
}
```

### 3. Check Current User (`/auth/me`)
```bash
curl -X GET http://localhost:8000/auth/me \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### 4. Upload an Invoice (PDF / PNG / JPEG)
Multipart file upload strictly restricted to `admin` and `reviewer` roles:
```bash
curl -X POST http://localhost:8000/documents \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -F "file=@/path/to/invoice.pdf"
```

### 5. List Documents (Paginated & Tenant-Scoped)
```bash
curl -X GET "http://localhost:8000/documents?limit=10&offset=0" \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### 6. Download Original Document
```bash
curl -X GET http://localhost:8000/documents/<DOCUMENT_UUID>/file \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -O -J
```

### 7. Delete Document (Admin Only)
```bash
curl -X DELETE http://localhost:8000/documents/<DOCUMENT_UUID> \
  -H "Authorization: Bearer <JWT_TOKEN>"
```
