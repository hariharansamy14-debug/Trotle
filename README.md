# Trotle AI — Evidence-First Enterprise RAG Platform

Trotle AI is a dark-themed, evidence-first enterprise retrieval-augmented generation (RAG) application with a React + Vite frontend and a FastAPI backend. It helps authorized users search uploaded company documents, inspect answer evidence, review possible conflicts, and track document history.

## Stack

- Frontend: React, TypeScript, Vite, Tailwind, Lucide icons
- Backend: FastAPI, SQLAlchemy, Pydantic, Alembic
- Database: Supabase PostgreSQL or local PostgreSQL, with SQLite for local testing
- Vector search: Qdrant support in Docker Compose and optional configuration

## Prerequisites

- Node.js 20+
- Python 3.11+
- Docker Desktop for local PostgreSQL (optional when using Supabase)

## Windows setup

1. Open PowerShell in the project folder.
2. Create a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r backend\requirements.txt
   ```
3. Install frontend dependencies:
   ```powershell
   cd frontend
   npm install
   cd ..
   ```
4. Copy environment template:
   ```powershell
   Copy-Item .env.example .env
   ```
   Set `GOOGLE_API_KEY` to a Google AI Studio key for Gemini `models/gemini-embedding-001` embeddings and, if desired, Gemini answer generation; `GEMINI_API_KEY` is accepted as a backward-compatible key name. Set `LLM_PROVIDER=gemini` for Gemini answers, or configure Grok explicitly with `LLM_PROVIDER=grok` and `GROK_API_KEY`. Embedding setup fails explicitly when the key or provider is missing/unsupported; there is no mock-embedding fallback. Keys are backend-only. Retrieved source text is sent to Google for embedding after permission checks and sensitive-text masking. Keep keys private and restart the backend after changing them. Provider authentication, model, quota, and network errors are returned as actionable messages instead of being presented as answers. Backend settings load `.env` from the project root when Uvicorn starts, including when launched from `backend`.
5. Choose a database:

   **Local PostgreSQL:** start the local services:
   ```powershell
   docker compose up -d postgres qdrant
   ```

   **Supabase PostgreSQL:** in the Supabase dashboard, open **Project Settings → Database** and copy a connection string. Put it in `.env` as `SUPABASE_DB_URL`; use a Session Pooler string if your deployment network cannot reach the direct database host. Set `BOOTSTRAP_ADMIN_PASSWORD` to a strong one-time password. The backend selects `SUPABASE_DB_URL` when it is non-empty, normalizes it for psycopg 3, and enforces TLS (`sslmode=require`). Leave `DATABASE_URL` as the local fallback.

   Keep `.env` private and out of source control. Never put the database connection string in frontend configuration or share it in chat. This project connects to Supabase Postgres only; it does not use Supabase Auth or Supabase Storage. Existing FastAPI authentication and local file uploads remain in use.

6. Apply database migrations:
   ```powershell
   cd backend
   ..\.venv\Scripts\python -m alembic upgrade head
   cd ..
   ```
7. Start backend:
   ```powershell
   .\.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
8. Start frontend:
   ```powershell
   cd frontend
   npm run dev -- --host 0.0.0.0
   ```

## Default login

- Local SQLite development: `admin@company.com` / `admin123`
- Supabase: the initial `admin@company.com` account is created with `BOOTSTRAP_ADMIN_PASSWORD` only if it does not already exist. Remove that variable after the first successful initialization.

## Main routes

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Health check: http://localhost:8000/health

## One-command local startup

From the project root in PowerShell, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

The launcher reuses an already healthy backend/frontend, otherwise opens a PowerShell window for each service and waits for both to respond before opening the frontend. For local startup it selects the backend's SQLite database, so a Supabase project HTTPS URL in `SUPABASE_DB_URL` cannot prevent the API from starting. AI provider settings remain loaded from `.env`; configure a valid xAI key there to use Grok. Keep both service windows open while using the app.

## API highlights

- POST /api/auth/login
- POST /api/auth/register
- GET /api/auth/me
- GET /api/sources
- POST /api/sources/{source_id}/access (admin)
- DELETE /api/sources/{source_id}/access/{access_id} (admin)
- POST /api/sources/files
- POST /api/chat
- GET /api/answers/{answer_id}/evidence
- GET /api/conflicts
- GET /api/change-alerts
- GET /api/documents/{document_id}/compare
- GET /api/documents/relationships/map (authorized evidence activity records used by the table)
- GET /api/reports/evidence
- GET /api/reports/export?format=json|csv
- GET /api/reports/summary
- GET /api/settings/runtime (authenticated, secret-free provider and connector status)
- GET /api/conversations
- DELETE /api/conversations/{conversation_id}

## Evidence and document history

- Answers use permission-filtered retrieval that combines BM25, TF-IDF sparse-vector cosine ranking, and Gemini `models/gemini-embedding-001` dense vector similarity. Query and document vectors use the provider's retrieval-specific task types. Matching document titles, sections, and structured question headings receive extra weight. Embeddings are generated from masked evidence at query time; no mock fallback or persisted vector index is used. Claim checks also require meaningful overlap between the original question and the cited passage; passages with no such alignment are marked **Unsupported** and are not cited as support.
- Citations preserve the document, version, page where extraction provides it, source URL, and quoted chunk. PDF extraction tracks page numbers; other supported uploads do not currently provide page numbers.
- Evidence coverage counts supported, partly supported, conflicting, unsupported, and insufficiently supported claims. It is a source-match metric, not a correctness guarantee.
- Numeric disagreements in retrieved passages are surfaced as reviewable conflicts. Authorized admin/manager users must provide a non-empty resolution explanation; reviews are audited.
- Re-uploading a changed file creates a new document version and a deduplicated change alert. Deleting a document removes it from search by marking it deleted, preserving old citation snapshots and a deletion alert.
- Asking "What changed this month?" returns this month's permitted, recorded upload-change events. The result is explicitly an ingestion log, not a policy-content verification.
- Version comparison uses a line diff of stored chunk text. Evidence Activity presents authorized, bounded records of saved questions, answer claims, cited passages, accessible source documents, recorded conflicts, and upload-tracked document versions in a searchable, filterable table. Citation links represent stored provenance; claim verification remains deterministic term overlap, not semantic entailment. Shared-term document links are visibly marked as candidates and never mean support or contradiction. Version groups use the same source and exact original filename plus upload-assigned version history; identical content hashes are shown as duplicates without merging records.
- "Why These Results?" shows matched terms, source metadata, dates, and the actual local relevance score. It does not expose private model reasoning.
- Evidence exports are available in JSON and CSV to admins/managers and are audited. PDF export is not implemented.
- Evidence Reports includes a permission-filtered claim explorer with source quotations, available document metadata, query-level conflicts, evidence coverage, and evidence gaps. Browser Print / PDF uses the browser print dialog; authority and freshness are not scored because source approval/effective-date metadata is not stored.
- User/source access is enforced before retrieval and rechecked when saved evidence, alerts, and exports are returned. Admins can access all sources; other users can access owned sources or those explicitly assigned through source access.
- Search History filters saved conversations, opens the saved evidence report for the latest query, and supports owner-scoped deletion. Runtime Settings reports configured provider status without returning credentials; Grok remains unverified until a real provider call succeeds. Database, website/API, and cloud-storage ingestion connectors are not implemented.

## Database migration

After upgrading an existing installation, run:

```powershell
cd backend
..\.venv\Scripts\python -m alembic upgrade head
cd ..
```

The application applies additive compatibility columns for local SQLite development. It does not create tables automatically on Supabase/PostgreSQL: apply Alembic migrations successfully before starting the backend. The `/health` endpoint executes a database query and reports an error if the configured database is unreachable.

Before production, replace `SECRET_KEY` with a strong random value and use a dedicated, least-privilege database role where practical. The Supabase connection string is a server-side secret; do not expose it through Vite variables or the browser. Supabase Auth and database row-level policies are not integrated—the API uses its existing FastAPI authentication and source-access checks.

## Testing

```powershell
cd backend
..\.venv\Scripts\python -m pytest app/tests/test_api.py
```

## Known limitations

- Retrieval combines BM25, TF-IDF sparse-vector cosine similarity, and Google Gemini `models/gemini-embedding-001` dense embeddings. Dense embeddings are recomputed for permitted chunks per question; large corpora may require a persistent vector index for efficiency. Matching structured question headings and document metadata receive additional ranking weight. When configured, Grok/Gemini are instructed to reject evidence that shares keywords but does not answer the question's core intent. The final claim check is a conservative lexical alignment guard, not an independent NLI model. Output-limit responses are continued before returning.
- Numeric conflict detection is heuristic and may surface values that need human review. It does not decide which policy is authoritative.
- Upload version tracking and deletion/change alerts work for locally uploaded files. There is no scheduled sync engine; database, website/API, and cloud connectors remain setup-required and sync attempts explicitly report that no adapter is configured.
- Temporal ranking currently uses the indexed document update timestamp where present. Effective-date extraction, authoritative policy selection, and a complete "what changed this month" source synchronization workflow are not implemented.
- Evidence Activity displays bounded saved records (150 documents, 50 recent questions, 300 citations, and 40 documents for optional keyword candidates). It summarizes recorded relationships and does not infer source authority or semantic support. Shared-term links are marked as candidates and must not be treated as evidence of support or contradiction.
- No schema change is required for Evidence Activity; it uses existing query, citation, conflict, document hash, and version records, filtered using the existing account and source-access rules.
- Embeddings require a valid Google API key and internet access. The application does not silently substitute mock embeddings; dense vectors are generated per request and are not stored in Qdrant.
- Claim verification is conservative but lexical: citations point to stored passages and require overlap with the question and claim; no independent semantic-entailment verifier is configured.
- Conflict detection is heuristic and numeric, with an audited human-review route; it does not reliably distinguish every scope, date, or system difference.
- Source approval, effective/expiry dates, and authority categories are not implemented. The upload workflow tracks file versions and alerts but has no external synchronization engine.
- A PostgreSQL source connector, evaluation dataset/dashboard, and measured benchmark results are not implemented. Database connection attempts are not performed by the placeholder endpoint; external website/API and cloud-storage ingestion are unavailable.
- With Grok configured, retrieved evidence is sent to the xAI API; sensitive values matching the application's masking rules are redacted first. Review your organization's data-sharing requirements before enabling it. Other production secrets and connector credential storage/OAuth require deployment-specific setup.
- The upload workflow supports PDF, DOCX, TXT, Markdown, CSV, and XLSX. PDF page references are available; other formats currently have no page-level metadata.
