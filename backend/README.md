# Backend

Milestone 3 (foundation) — implemented and tested:

- FastAPI app with request-id logging (JSON), problem+json errors, CORS, `/health/live`, `/health/ready` (DB + pgvector + LLM provider mode).
- SQLAlchemy models for the full planned schema (27 tables); DDL generated to `migrations/sql/0001_initial.sql`.
- DB-level integrity: append-only `audit_log`, immutable assessments/findings/decisions, "only rules can confirm violations", "a request is approved/rejected only after a matching human decision", RLS on every table.
- Hash-chained audit log service (`app/services/audit.py`), demo-grade role enforcement (`app/api/auth.py`).

Milestone 4 (document ingestion) — implemented and tested:

- `app/documents/`: PDF/TXT parsing (PyMuPDF), rule-based classification, rule-based field extraction with per-field source tracking (page, offsets, text), strict Pydantic models, arithmetic/date validation, clause-level policy chunking.
- `app/services/ingest.py`: parse → classify → extract → validate → chunk → persist (dedupe by SHA-256). Chunks are stored without embeddings; embedding arrives in milestone 5.
- API: `POST /documents` (multipart; only admins may upload policies), `GET /documents`, `GET /documents/{id}`. Uploads are audit-logged.
- Benchmark: `evals/runners/extraction.py` → `evals/reports/`. See `data/synthetic/README.md`.

Limitations: extraction is rule-based and only handles "Label: value" headers plus one-line item rows; no field-level confidence; **OCR code exists but is unverified** (Tesseract is not installed here, so scanned pages produce a warning instead of text); no DOCX/image upload; no LLM fallback yet; the `pymupdf` package currently pulls in heavy optional dependencies (onnxruntime etc.) that should be trimmed before deployment.

Milestone 5 (retrieval) — implemented and tested:

- `app/retrieval/`: `Embedder`/`Reranker` interfaces; fastembed (ONNX, no torch) embedder, a test-only hashing embedder, optional cross-encoder reranker; `index_chunks` (embeds the context-prefixed text, keeps `Chunk.text` verbatim for citations); hybrid search = pgvector cosine + Postgres FTS fused with RRF, filtered by policy status / effective date / category / code; relevance gate; retrieval logging.
- API: `GET /policies`, `GET /policies/{id}`, `POST /policies/search` (debug view of what the pipeline would retrieve), `POST /policies/reindex` (admin).
- Benchmark: `evals/runners/retrieval.py` (ablations over search mode, embedding model, query prefix, reranker). Results live in `evals/reports/`; the embedding model downloads to the fastembed cache on first use (about 130 MB for bge-small).
- Test-suite embedder is a hashing stub, so the unit/integration tests verify SQL, filters and wiring, not retrieval quality.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows; use .venv/bin/python on macOS/Linux
cp .env.example .env                               # then set DATABASE_URL (Supabase session pooler string)
.venv/Scripts/python -m uvicorn app.main:app --reload
.venv/Scripts/python -m pytest
```

If you change `app/db/models.py`, regenerate the SQL with `python scripts/gen_ddl.py` (a unit test fails if it is stale).

## Verified against the live Supabase database

`alembic upgrade head` (no-op at revision `0001`), `/health/ready`, the audit-log chain, and document ingestion/upload (integration tests run inside a transaction that is rolled back; the database is left empty).
