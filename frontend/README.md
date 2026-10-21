# DocFlow Frontend (Week 4B)

Production-ready React 18 + TypeScript single-page application for the **DocFlow** intelligent document extraction and human review system.

Built strictly against `frontend/openapi.json` without modifying any backend code.

---

## 🚀 Tech Stack

- **Framework**: [React 18](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/) (strict mode)
- **Build & Dev Tool**: [Vite](https://vitejs.dev/)
- **Routing**: [React Router v6](https://reactrouter.com/)
- **Server State & Caching**: [TanStack Query v5](https://tanstack.com/query/latest)
- **API Client**: [openapi-fetch](https://openapi-ts.dev/openapi-fetch/) typed with schemas generated via [openapi-typescript](https://openapi-ts.dev/openapi-typescript/)
- **Styling**: [Tailwind CSS v3](https://tailwindcss.com/) with pure reusable components
- **Icons**: [Lucide React](https://lucide.dev/)
- **Testing**: [Vitest](https://vitest.dev/) + [React Testing Library](https://testing-library.com/) + [MSW (Mock Service Worker)](https://mswjs.io/)
- **Linting & Formatting**: [ESLint](https://eslint.org/) + [Prettier](https://prettier.io/)

---

## 🔒 Security & Architecture Principles

1. **In-Memory Access Tokens Only**:
   - Access tokens are stored **strictly in JavaScript memory** via an in-memory module closure (`src/api/client.ts`).
   - Tokens are **never** persisted in `localStorage`, `sessionStorage`, or window objects.
   - Page refreshes (F5) automatically restore the session via `POST /auth/refresh` using the secure `HttpOnly` refresh token cookie.
   - Multiple concurrent 401 responses trigger a **single-flight refresh promise**, preventing token churn and race conditions.

2. **Decimal Precision For Money & Quantities**:
   - All financial and quantity fields (`subtotal`, `cgst`, `sgst`, `igst`, `total`, `unit_price`, `quantity`, `amount`) are handled strictly as **strings** end-to-end.
   - Client-side validation uses the decimal regex `^-?\d+(\.\d+)?$` to validate inputs before submitting to the backend, completely avoiding JavaScript floating-point rounding errors.

3. **XSS & Injection Protection**:
   - Untrusted document data, filenames, and vendor names are rendered strictly as plain text nodes.
   - `dangerouslySetInnerHTML` is prohibited across the codebase.
   - Formula-like strings (e.g., `=HYPERLINK(...)`) and HTML payloads (e.g., `<img src=x onerror=alert(1)>`) render harmlessly as escaped text.

4. **Authenticated Binary Streaming**:
   - Original invoice PDFs and images (`GET /documents/{id}/file`) and export files (`GET /exports/{id}/download`) are fetched with typed `Authorization: Bearer <token>` headers via `authenticatedFetch`.
   - Temporary browser blob object URLs are cleanly revoked (`URL.revokeObjectURL`) on component unmount or modal teardown.

---

## 👥 Pages & Role-Based Access Control (RBAC)

| Route | Page | Accessible By | Key Capabilities |
| :--- | :--- | :--- | :--- |
| `/login` | Sign In | Public / Anonymous | Email & password login, session establishment |
| `/register` | Organization Registration | Public / Anonymous | Creates organization and initial admin account |
| `/` | Dashboard | Viewer, Reviewer, Admin | KPI stats cards, status breakdown, processing health |
| `/documents` | Documents List | Viewer, Reviewer, Admin | Paginated invoice table, filters, upload dropzone, exact-duplicate alerts, reprocess failed documents |
| `/review` | Review Queue | Reviewer, Admin | FIFO queue of invoices requiring human attention |
| `/documents/:id` | Review Workspace | Viewer, Reviewer, Admin | Desktop split-layout (PDF viewer + editable extraction), field navigation, optimistic 409 resolution, diff history, Approve/Reject/Reopen |
| `/exports` | Accounting Exports | Admin Only | List export batches, create export (CSV/JSON), authenticated downloads |

---

## 🛠️ Project Structure

```
frontend/
├── openapi.json             # Pinned OpenAPI 3.1 specification from backend
├── src/
│   ├── api/
│   │   ├── client.ts        # Typed openapi-fetch client, in-memory token, single-flight refresh
│   │   └── schema.d.ts      # Generated TypeScript API schemas (gen:api)
│   ├── auth/
│   │   └── AuthContext.tsx  # React context managing session restore, login, register, logout
│   ├── components/
│   │   ├── common/          # Reusable UI primitives (Button, Input, Modal, Toast, StatusBadge)
│   │   ├── layout/          # AppLayout, navigation header, role badges
│   │   └── review/          # DocumentViewer, IssuesPanel, HistoryDrawer, ConflictModal
│   ├── pages/
│   │   ├── Dashboard.tsx    # Operational metrics & status distributions
│   │   ├── Documents.tsx    # Paginated documents table & drag-and-drop upload
│   │   ├── ReviewQueue.tsx  # FIFO review queue
│   │   ├── ReviewScreen.tsx # Desktop split-screen review workspace & optimistic locking
│   │   ├── Exports.tsx      # Accounting export batch creation & downloads
│   │   ├── Login.tsx        # Sign-in form
│   │   └── Register.tsx     # Organization registration form
│   ├── test/
│   │   ├── setup.ts         # Vitest setup & MSW server lifecycle
│   │   ├── server.ts        # MSW node server definition
│   │   ├── components.test.tsx # Unit tests for UI components
│   │   ├── auth.test.tsx    # In-memory auth & session restore tests
│   │   ├── navigation.test.tsx # RBAC route protection tests
│   │   ├── batch1.test.tsx  # Documents, upload, queue & dashboard tests
│   │   └── batch2.test.tsx  # Review screen, 409 conflict, dirty guard & export tests
│   ├── App.tsx              # Application routes & provider composition
│   ├── main.tsx             # Application bootstrap
│   └── index.css            # Tailwind directives & styles
├── vitest.config.ts         # Vitest test runner configuration
├── tailwind.config.js       # Tailwind CSS design tokens
├── vite.config.ts           # Vite bundler configuration & local dev proxy
└── package.json             # Scripts & dependencies
```

---

## 💻 Setup & Development

### 1. Prerequisites
- **Node.js**: v18.0.0 or later (v20+ / v22+ recommended)
- **npm**: v9.0.0 or later

### 2. Install Dependencies
```bash
cd frontend
npm install
```

### 3. Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Default value:
```env
VITE_API_BASE_URL=http://localhost:8000
```

### 4. Regenerate API Types (if OpenAPI changes)
```bash
npm run gen:api
```

### 5. Start Development Server
```bash
npm run dev
```
The application will be accessible at `http://localhost:5173`.

---

## 🧪 Testing, Linting & Production Build

### Run All Tests
```bash
npm test -- --run
```
Expected output: **27 passed** across 5 test suites (`components`, `auth`, `navigation`, `batch1`, `batch2`).

### Run ESLint
```bash
npm run lint
```

### Run Production Build
```bash
npm run build
```
Executes TypeScript type check (`tsc -b`) followed by Vite production bundling into `dist/`.

---

## 📖 End-to-End Browser Walkthrough Script

Once the backend is running (`docker compose up` or local FastAPI at port 8000):

1. **Register / Login**:
   - Navigate to `http://localhost:5173/register` and create an organization with an admin user.
   - Verify immediate sign-in and redirect to the **Dashboard** (`/`).
   - Refresh the page (**F5**): observe that the session is seamlessly restored via the HttpOnly cookie without re-prompting for credentials.

2. **Upload Invoice**:
   - Navigate to **Documents** (`/documents`).
   - Drag and drop a valid invoice PDF (or test sample invoice).
   - Observe the progress indicator and upload completion notice.
   - If the file is still processing, the page polls every ~2 seconds until status changes to `needs_review` or `auto_approved`.

3. **Human Review & Field Editing**:
   - Click **Review Queue** (`/review`) or click the document from the documents table.
   - On `/documents/:id`:
     - **Left Pane**: View the invoice in the authenticated PDF viewer.
     - **Right Pane**: Inspect validation issues (grouped with errors first).
     - Click an issue to automatically scroll and focus the offending input.
     - Modify an input (e.g. `Vendor Name` or `Total Amount`). Notice the **Unsaved edits** badge appears and **Approve** is disabled.
     - Press **Ctrl+S** (or **Cmd+S**) to save changes. Version increments from `v1` to `v2`.
     - Click **History** in the top bar to inspect the field-level audit trail.

4. **Approve / Reject**:
   - If error issues remain, clicking **Approve** prompts for a mandatory override reason.
   - If no error issues remain, the invoice is approved immediately.

5. **Accounting Export (Admin Only)**:
   - Navigate to **Exports** (`/exports`).
   - Click **Create Export Batch**, choose format (`CSV` or `JSON`), and confirm.
   - Click **Summary CSV**, **Line Items CSV**, or **JSON** to download the generated export files with authenticated bearer tokens.
