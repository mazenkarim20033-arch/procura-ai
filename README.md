# Procura AI — Enterprise Procurement Intelligence Platform

> **Status: milestones 1-11 done (backend, evaluation harness and web UI), 12 partly done (see docs/BENCHMARKS.md); 13-14 (deployment, case study) are pending.** See [docs/ROADMAP.md](docs/ROADMAP.md).
> All data in this project is **synthetic**. Nothing here is connected to a real company or supplier. Sign-in is a demo persona picker, not real authentication.

Procura AI helps procurement teams process purchase requests against company policy. It extracts structured data from documents, retrieves the relevant policy clauses, evaluates the request with deterministic rules plus an LLM, and produces an explainable, evidence-backed assessment. **A human procurement officer always makes the final decision. The AI never approves a purchase.**

## Run it locally

Needs Python 3.12, Node 20+ and a Postgres database with pgvector (the project uses a free Supabase project; no Docker).

```bash
# 1. Backend (see backend/README.md for details): set DATABASE_URL in backend/.env first
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"      # use .venv/bin/python on macOS/Linux
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python scripts/seed_demo.py              # base demo data (policies, 12 requests, decisions)
.venv/Scripts/python scripts/seed_demo.py --scenarios  # optional: extra requests so every risk level appears
.venv/Scripts/python -m uvicorn app.main:app --port 8000

# 2. Frontend (another terminal)
cd frontend
npm install
npm run dev                                            # http://localhost:5173
```

The AI runs in **mock** mode unless `LLM_PROVIDER=groq` and `LLM_API_KEY` are set in `backend/.env`. Mock output is labelled as mock everywhere in the UI. The seed scripts refuse to run twice, and the audit log is append-only by design, so use a fresh database if you need a clean slate.

### Demo tour

1. Pick a persona in the sidebar (default: a finance director). Requesters get a simpler overview and cannot run assessments or decide; reviewers see the queue and AI columns.
2. **Overview** shows the review queue, highest AI risk first.
3. Open a request. **AI assessment** lists findings by category with the policy clause quoted next to each one. Only deterministic rules can mark a *confirmed* violation; the model can at most raise a *potential* issue.
4. The **Human decision** panel is separate. Approving needs written reasoning, enough authority for the amount (PRC-001 2.1-2.4), a different person than the requester, and an explicit override for any confirmed violation.
5. **Analytics** and **Audit log** (with hash-chain verification) are computed live from the database.

## Known limitations of the UI

- No browser end-to-end suite. The frontend has unit and component tests (18, including the decision panel's blocking rules); the whole decision flow is tested against the live database in the backend suite, and pages were exercised by hand in a browser. The final "Approve" click was not driven in the browser.
- Personas are demo headers (`X-Demo-Role`, `X-Demo-User`, `X-Demo-Authority`). Anyone can switch persona; this is not security.
- English only (the layout and strings are structured so Arabic could be added later).

## Planning documents

| Doc | Contents |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Product requirements, personas, user stories, scope |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, diagram, DB schema, directory layout, AI pipeline, RAG design, key decisions |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Evaluation dataset and benchmarking strategy |
| [docs/COST_AND_RISKS.md](docs/COST_AND_RISKS.md) | Cost analysis (what runs free) and risk register |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Milestones with exit criteria |

## Principles

1. Deterministic rules first, LLM only where judgment or language understanding is needed.
2. Every finding cites retrievable evidence; unsupported claims are rejected by a verifier.
3. Human decisions are stored separately from AI recommendations.
4. Metrics are only reported if produced by a real run of the evaluation harness.
5. Mock/demo mode is always labelled as mock in the UI and API.
