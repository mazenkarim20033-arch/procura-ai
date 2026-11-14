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

Milestone 6 (purchase request intelligence) — implemented and tested:

- `POST /requests` (all fields optional: incomplete requests are accepted and reported), `POST /requests/from-document/{id}` (from an extracted purchase-request PDF), `GET /requests`, `GET /requests/{id}`, `POST /requests/{id}/documents`, `GET /requests/{id}/intake`.
- `app/rules/intake.py`: deterministic checks for missing information, arithmetic/currency/date inconsistencies, and request-vs-quotation comparison (competing quotes are normal; it only warns if none matches the requested supplier).
- `app/services/duplicates.py`: exact duplicates (fingerprint), similar requests (item-embedding similarity), same-items-other-supplier, informational repeat purchases, split-purchase and near-threshold detection (USD only: no exchange-rate source, so other currencies are reported as a limitation).
- The intake report is computed live and not stored; milestone 7 folds it into the persisted assessment. Requests are never approved here; status stays `submitted`.
- Migration `0002` (applied with `alembic upgrade head`); migration SQL is now frozen/hand-written and `schema_snapshot.sql` is a drift-checked snapshot.

Limitations: no vendor identity resolution yet (names are compared after simple normalisation); category is not extracted from documents so split detection matches on supplier and period only (and says so); request-vs-quote total variance threshold (15%) and the near-threshold band (15%) are heuristics, not policy values.

Milestone 7 (compliance engine) — implemented and tested:

- `app/rules/policy_rules.py`: deterministic rules tied to specific policy clauses (quotation count and validity, quotation content/arithmetic, approved supplier, justification, split/duplicate signals, payment terms, injection guard). Each finding cites the clause it was looked up from; if a clause is not loaded the finding degrades to `inconclusive`. Only rules can emit `confirmed_violation` (also a database CHECK constraint). "Missing information" is never reported as a violation.
- `app/ai/`: provider interface with a **mock** provider (keyword heuristics, labelled `[MOCK]` and `is_mock` end to end) and an OpenAI-compatible provider for Groq (temperature 0, JSON output validated against a Pydantic schema, validation-error feedback retries, backoff on 429/5xx, token/latency tracking; tested with a mocked transport and benchmarked against the real Groq API (see docs/BENCHMARKS.md)); versioned prompts with SHA-256 recorded per call; injection scan; evidence verifier (clause must have been shown, quote must be verbatim, no unsupported numbers); LLM stage only sees clauses the rules do not own, retrieved first.
- Pipeline: rules -> retrieval + LLM -> verification -> aggregation (risk score, status, heuristic confidence, financial risks, next steps) -> persist immutable assessment + findings + evidence + retrieval/LLM logs + AI-actor audit entry. The request status moves to `assessed`, never to approved/rejected.
- API: `POST /requests/{id}/assess` (reviewer/admin), `GET /requests/{id}/assessments`, `GET /assessments/{id}`, `GET|PUT /settings/approved-suppliers` (admin to write).
- Benchmark: `evals/runners/compliance.py`; results in `docs/BENCHMARKS.md`.

To use Groq: set `LLM_PROVIDER=groq`, `LLM_API_KEY` and `LLM_MODEL` (default recommendation `openai/gpt-oss-120b`; list models with GET https://api.groq.com/openai/v1/models) in `.env` (optionally `LLM_PRICE_IN_PER_M` / `LLM_PRICE_OUT_PER_M` to get a cost estimate; none is assumed).

Limitations: confidence is an uncalibrated heuristic; the approved-supplier list must be configured by an admin (no data source otherwise); amount rules are USD-only (no FX source); category-specific rules (for example "IT hardware needs IT review") are left to the LLM stage and the human; the injection scan is a heuristic.

Milestone 8 (vendor intelligence) — implemented and tested:

- Vendor records are created from quotations, invoices and contracts at ingest (`app/services/vendors.py`): tax ID first, then normalised name/alias, then fuzzy name similarity (always `needs_review`; never merges vendors with different tax IDs). Profile gaps (missing tax ID, email, phone, address, country) and conflicts (same name, different tax ID) are reported per vendor. Quotations and their line items are stored in `quotations` / `quotation_items` and linked to a request when attached.
- Quote comparison (`GET /requests/{id}/quote-comparison`, `app/vendors/compare.py`): ranking (never across currencies; subtotals when tax treatment differs), item alignment by embedding similarity, price outliers / suspiciously low prices against the median, quantity and coverage differences, payment terms, validity, arithmetic errors, and the same vendor's earlier prices.
- API: `GET /vendors`, `GET /vendors/{id}`, `POST /vendors/{id}/merge` (admin). A request's supplier is linked to a vendor record when its name matches exactly or by a known alias.
- Every response states that it is based only on uploaded documents: **no external supplier verification, market data or exchange rates exist**, and nothing may be presented as if they did.

Limitations: names and profile fields come from rule-based extraction of simple layouts; item alignment and price thresholds are heuristics (see docs/BENCHMARKS.md for what was and was not measured); vendor insights are not yet folded into the persisted assessment.

Milestone 9 (human approval workflow) — implemented and tested:

- `POST /requests/{id}/decisions` (reviewer/admin): approve, reject or request information, always with written reasoning (PRC-001:3.2). Decisions live in their own tables and are the **only** way a request becomes approved or rejected: a unit test scans the code base so that nothing outside `services/decisions.py` can assign those statuses, and a database trigger refuses them without a matching decision row (verified in a live test).
- Rules (`app/rules/decisions.py`, unit-tested as a matrix): the requester cannot decide on their own request (PRC-001:3.1); approve/reject must name the latest assessment the reviewer actually looked at (stale or missing assessment is refused); approval level follows the USD amount (PRC-001:2.1-2.4: department manager, procurement officer, finance director, chief financial officer, set with the demo header `X-Demo-Authority`, defaults reviewer = procurement officer, admin = CFO); amounts that are missing or not in USD can only be approved by the CFO level; approving over a confirmed violation requires a per-finding override (`disagree` plus a note). Decisions are final once approved or rejected.
- `GET /requests/{id}/decisions`, `GET /requests/{id}/history` (audit-backed timeline plus separate lists of AI assessments and human decisions, each decision showing the AI's status at that moment and whether it went against the AI signal), `POST /requests/{id}/info-response` (answers an open information request and returns the request to the queue), `GET /review/queue` (reviewer-only; highest AI risk first as an ordering signal, then oldest; shows the approval level the amount needs).
- Migration `0003`: `decisions.created_at` uses `clock_timestamp()` so decisions inside one transaction order correctly for the database gate. `tests/unit/test_layering.py` now enforces the layer rules from docs/ARCHITECTURE.md.

Limitations: identities are demo headers, not real authentication; there are no email notifications; the approval-level mapping is read from the synthetic policy and is not configurable; a request cannot be reopened after a final decision.

Milestone 10 (analytics and audit) — implemented and tested:

- `GET /analytics/overview` (reviewer/admin; filters `since`, `until`, `exclude_mock`): everything is SQL over the real tables, nothing stored or hand-written. Request counts by status and per week; assessments by provider/model with latency (avg, p50, p95), tokens and (only when prices are configured) estimated cost; latest-assessment status mix and risk distribution; findings by category/source and the most frequent rules; LLM call outcomes; decisions by action; hours from request creation to first assessment and to first decision (p50/p90); AI-versus-human agreement (agreed, approved despite AI issues, rejected despite a clean AI result, no clear signal) and the reviewers' agree/disagree rate on individual findings; review queue sizes; vendor statistics (vendors without a tax ID, with conflicts or alias reviews) and quotation comparison insights (spread between lowest and highest quote, lowest-bidder wins, whether the chosen supplier was the lowest and its premium when not). The response carries a `definitions` block so no figure can be read more broadly than it is defined. Mock-provider assessments are listed separately and can be excluded.
- `GET /audit` (filters, newest first, keyset pagination) and `GET /audit/verify` (recomputes the whole hash chain in batches, reading rows fresh from the database). Tamper-evident, not tamper-proof: truncation of the newest entries is only detectable against a head hash recorded elsewhere, and the response says so.
- Tests check analytics as deltas around data the test creates (so they stay valid on a non-empty database), compare vendor insights with an independent computation from the synthetic documents, and prove tamper detection against the live database by switching the immutability trigger off inside a rolled-back transaction and forging a row.

Limitations: no caching (each call runs a dozen queries, fine at demo scale); "AI agreement" treats the AI's "no issues found" as the only approve-like signal because the AI never recommends approval; processing times use the audit log creation time, so documents carrying older business dates do not distort them; the demo database has to be seeded for the dashboards to show anything (planned with the frontend/demo milestone).

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
