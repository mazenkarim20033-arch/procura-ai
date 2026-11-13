# Procura AI — Enterprise Procurement Intelligence Platform

> **Status: planning phase. No application code exists yet.** Everything below describes the intended product; see [docs/ROADMAP.md](docs/ROADMAP.md) for progress.
> All data in this project is **synthetic**. Nothing here is connected to a real company or supplier.

Procura AI helps procurement teams process purchase requests against company policy. It extracts structured data from documents, retrieves the relevant policy clauses, evaluates the request with deterministic rules plus an LLM, and produces an explainable, evidence-backed assessment. **A human procurement officer always makes the final decision. The AI never approves a purchase.**

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
