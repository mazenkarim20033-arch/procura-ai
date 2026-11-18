# Procura AI — Enterprise Procurement Intelligence Platform

> **Status: milestones 1-11 done (backend, evaluation harness and web UI), 12 done except latency/cost (see docs/BENCHMARKS.md), 13 done except a live backend (a recorded demo is deployed, see docs/DEPLOYMENT.md); 14 (case study) written: [docs/CASE_STUDY.md](docs/CASE_STUDY.md).**
>
> **Live demo:** https://mazenkarim20033-arch.github.io/procura-ai/ is a recorded, read-only snapshot of the app over synthetic data, with the keyword-based mock AI. It has no backend, so creating requests, assessing, deciding and live policy search are off there; run the project locally for those. See [docs/ROADMAP.md](docs/ROADMAP.md).
> All data in this project is **synthetic**. Nothing here is connected to a real company or supplier. Sign-in is a demo persona picker, not real authentication.

Procura AI helps procurement teams process purchase requests against company policy. It extracts structured data from documents, retrieves the relevant policy clauses, evaluates the request with deterministic rules plus an LLM, and produces an explainable, evidence-backed assessment. **A human procurement officer always makes the final decision. The AI never approves a purchase.**

## Run it locally

Needs Python 3.12, Node 20+ and a Postgres database with pgvector (the project uses a free Supabase project; no Docker).

One manual step first: copy `backend/.env.example` to `backend/.env` and put your database connection string in `DATABASE_URL`. Then, from the repository root, four command lines in two terminals:

```bash
# terminal 1 (macOS/Linux: use .venv/bin/python)
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m alembic upgrade head && .venv/Scripts/python scripts/seed_demo.py --yes && .venv/Scripts/python scripts/seed_demo.py --scenarios --yes
.venv/Scripts/python -m uvicorn app.main:app --port 8000

# terminal 2
cd frontend && npm install && npm run dev              # http://localhost:5173
```

On Windows, keep the project in a short path (for example `C:\Users\you\procura-ai`): a deeply nested folder can exceed the 260-character path limit and `pip install` then fails with "No such file or directory".

The seed step is optional (without it the UI is empty) and `--scenarios` adds extra requests so every risk level appears. A public instance must set `READ_ONLY=true` (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), which also records what is deployed: the snapshot demo only, no live backend).

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
| [docs/CASE_STUDY.md](docs/CASE_STUDY.md) | Portfolio write-up: decisions, measured results with sources, what went wrong, limitations, demo script |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Deployment status, read-only public mode, measured memory, blockers |

## Principles

1. Deterministic rules first, LLM only where judgment or language understanding is needed.
2. Every finding cites retrievable evidence; unsupported claims are rejected by a verifier.
3. Human decisions are stored separately from AI recommendations.
4. Metrics are only reported if produced by a real run of the evaluation harness.
5. Mock/demo mode is always labelled as mock in the UI and API.
