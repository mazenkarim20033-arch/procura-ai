# Product Requirements Document — Procura AI

## 1. Problem
Procurement teams review purchase requests manually against long policy documents (spend thresholds, quote requirements, approved-vendor lists, category rules). Reviews are slow, inconsistent, and poorly documented. Policy lookups are manual; missing information is found late; duplicate or split purchases are easy to miss.

## 2. Goal
Reduce reviewer effort and inconsistency by pre-processing each request: extract data, find the applicable policy clauses, flag issues with evidence, and hand a structured assessment to a human who decides.

**Non-goals:** autonomous approval, real supplier verification (no data source), payments/ERP integration, multi-tenant SaaS, production-grade auth (demo-grade role separation only).

## 3. Personas
- **Requester (employee):** submits a request with quotes/justification.
- **Procurement officer (reviewer):** reviews AI assessment, decides, records reasoning.
- **Procurement manager / auditor:** views analytics and the audit trail.
- **Admin:** uploads/maintains policies, configures providers.

## 4. Core workflow
Submit → extract & validate → duplicate check → retrieve policies → rules engine → LLM reasoning over retrieved evidence → evidence verification → assessment stored → human review (approve / reject / request info) → immutable audit log.

## 5. Functional requirements

### FR-A Document intelligence
- Upload PDF/DOCX/TXT/images (policies, quotations, contracts, invoices, request forms).
- Text extraction (PyMuPDF); OCR fallback for scanned pages (Tesseract, optional install; detected at runtime).
- Document-type classification (rules + keyword features first; LLM fallback when confidence is low).
- Structured extraction into strict Pydantic models per type (Quotation, Invoice, Contract, PurchaseRequest). Each extracted field carries `source_span` (page, char offsets) and `confidence`.
- Validation: arithmetic (line totals = qty × unit price, totals sum), currency/date formats, required fields.
- Language field on every document; English first, schema and chunker Unicode/RTL-safe for later Arabic support (multilingual embedding model option).

### FR-B RAG
- Policy ingestion: structure-aware chunking (by section/clause), metadata (policy id, section, effective date, category, version).
- Hybrid retrieval: dense (pgvector) + lexical (Postgres full-text) fused with RRF; metadata filters (category, effective date); optional cross-encoder rerank.
- Context relevance check before generation; if nothing relevant is retrieved the assessment is `inconclusive`, never fabricated.
- Every cited clause is a stored chunk ID; the UI links to the exact text.

### FR-C Purchase request intelligence
- Fields: request ID, requester/department, line items (qty, unit cost), currency, supplier, justification, attachments, submitted date.
- Missing-field detection, inconsistency detection (totals, currency mismatch between request and quote, quote date older than policy window).
- Duplicate / split-purchase detection: same supplier+category within a window, embedding similarity of item descriptions, amounts just under thresholds.

### FR-D Compliance assessment
Output (`Assessment`): overall risk (low/medium/high/critical), compliance status, applicable policies, findings, missing information, financial risks, next steps, confidence per finding and overall.
Finding classes (mutually exclusive): `CONFIRMED_VIOLATION`, `POTENTIAL_VIOLATION`, `MISSING_INFORMATION`, `COMPLIANT`, `INCONCLUSIVE`.
- Deterministic rules own anything computable (thresholds, number of quotes, approved vendor list, required fields, currency, dates). Only rules may emit `CONFIRMED_VIOLATION`; LLM findings are capped at `POTENTIAL_VIOLATION` unless they cite a clause *and* the rule engine corroborates.
- Each finding: evidence list (policy chunk id + quote, request field refs), explanation, rule id or prompt version.
- Overall status can never be "approved"; vocabulary is `no_issues_found`, `issues_found`, `needs_information`, `inconclusive`.

### FR-E Vendor intelligence
- Supplier extraction, name normalization (legal suffix stripping, casefold, fuzzy match + alias table), quote comparison (unit price, total, delivery, payment terms, validity), outlier price flags relative to other quotes and to the vendor's own history in the system.
- Explicitly **no** external verification; UI states "based on uploaded documents only".

### FR-F Human workflow
- Reviewer actions: approve, reject, request information, each with required reasoning; can agree/override each AI finding.
- Human decisions in their own table; AI recommendation never mutates it. Override of AI is recorded.
- Full decision history per request.

### FR-G Audit & analytics
- Append-only audit log (request created, document processed, assessment generated with prompt/model versions, human decision).
- Dashboards: compliance status mix, risk distribution, top violation categories, avg processing time (AI and end-to-end), vendor comparison, AI-vs-human agreement rate.

### FR-H Demo mode
- `LLM_PROVIDER=mock` runs the whole app with no credentials using recorded fixtures. UI shows a persistent "MOCK AI — recorded responses" badge. Retrieval, rules, extraction, and analytics are real in this mode; only LLM calls are replayed.

## 6. Non-functional requirements
- Local setup in ≤ 5 commands (Docker Compose runs Postgres+pgvector; no SQLite fallback, since pgvector is required).
- No secrets in repo; `.env` driven config; `.env.example` provided.
- Health endpoints `/health/live`, `/health/ready` (DB, embedding model loaded, LLM provider reachable).
- Structured JSON logging with request ids; per-LLM-call token, latency, cost recorded.
- Prompt-injection defense for uploaded documents (see ARCHITECTURE §6.5).
- Test coverage: unit (rules, validators, chunker), integration (API+DB), golden evaluation suite in CI.
- p95 assessment latency target (to be *measured*, not promised): reported in EVALUATION results.

## 7. Pages
Overview, Purchase Requests, Request Detail + AI Assessment, Document Intelligence, Vendor Intelligence, Policies, Compliance Analytics, Audit History, Settings. Every control must be wired to real functionality; nothing ships as a placeholder.

## 8. Success criteria (measured, not assumed)
- Extraction field-level accuracy, retrieval Recall@5, compliance precision/recall per class, **false approval rate** (violation labelled compliant) and unsupported-claim rate are reported from the eval harness on the synthetic gold set, with the caveat that the set is synthetic and small.
- Zero code paths that set a request to approved without a human decision (enforced by tests).

## 9. Decisions (resolved)
- **LLM:** Groq (free tier, OpenAI-compatible API) via the `openai_compat` provider; Mock provider for demo mode. Free-tier rate limits and model JSON reliability will be measured, not assumed.
- **Auth:** demo-grade. A user picker in the UI sets the role (requester / reviewer / admin); the API enforces role permissions server-side (e.g. only reviewers can record decisions). No passwords or SSO; documented as a limitation.
- **Arabic:** English-only v1. Architecture stays Arabic-ready (multilingual embedder option, Unicode-safe chunking). Arabic is added only if retrieval over a small Arabic policy proves cheap in M5; Arabic extraction and rules are out of scope.

## 10. Original open questions (kept for history)
1. Dev location: I used `Desktop\MY PROJECTS\procura-ai` (matches your other projects). OK?
2. LLM for real-AI mode: which do you have access to (Anthropic API, OpenAI, local Ollama)? Default plan: Anthropic via an adapter, Ollama as free option.
3. Should auth be a simple role switcher (demo-grade) or real login? Plan assumes role switcher + JWT stub.
4. Arabic: schema-ready only, or include a small Arabic policy sample in the eval set in v1?
