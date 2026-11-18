# Deployment

**Status: not deployed.** Nothing in this repository has been deployed to a public host. This file records what was prepared, what was measured, what has not been tested, and what a deployment needs from the project owner. Every figure below was measured on 2026-11-18 on the developer's laptop (Windows) unless stated otherwise.

## What a public instance must be

Sign-in in Procura is a persona picker that sends `X-Demo-Role` / `X-Demo-User` headers. It is not authentication: anyone can claim to be an administrator. An internet-facing instance would therefore let strangers upload documents, record "decisions" and fill an append-only audit log (database triggers make audit rows permanent).

So a public instance must run with **`READ_ONLY=true`**. In that mode every request that is not `GET`, `HEAD` or `OPTIONS` is refused with `403 read_only_demo`, before it reaches any handler. The one exception is `POST /policies/search`, which only reads the policies (and writes one retrieval-log row). `GET /health/ready` reports `read_only`, and the UI shows a "Read-only" badge.

Consequences to be aware of:
- Visitors can browse the seeded synthetic data, the AI assessments already stored, vendors, policies, analytics and the audit log, and can ask the policy search questions. They cannot create requests, run new assessments, upload documents or record decisions. The buttons for those actions are still shown and answer with the explanation above instead of being hidden.
- The seeded assessments were produced by the **mock** provider unless the seed was run with a real one, and the UI labels them as such.
- The decision workflow is demonstrated by the backend tests, the component tests and local use, not by the public demo.
- Do not point a public instance at a database that holds anything you care about: `READ_ONLY` is a guard in the application, not a database permission. Using a separate demo database with a read-only role would be stronger and was not done.

## Measured: does the API fit a free host?

Local run of the API in `READ_ONLY` mode with the real embedding model, one worker, against the hosted Supabase database:

| Measure | Result |
|---|---|
| Time until `/health/live` answers | 3 s |
| Memory (working set) right after start | 96 MB |
| Memory after the embedding model loaded and one policy question was answered | 235 MB |
| First policy question (model load included, model already cached on disk) | 4 s |

Not measured: memory under concurrent requests, a new assessment with a real model, behaviour on Linux, a cold first start on a host where the embedding model (about 90 MB, downloaded on first use) is not cached, and the free tier's own cold-start delay. A 512 MB free instance looks plausible from these numbers, but it is a prediction, not a result.

## Dependencies were trimmed

The newest `pymupdf` (2.x) depends on nine packages including `onnxruntime`, `networkx` and `pymupdf4llm`; plain text extraction needs none of them. `pyproject.toml` now pins `pymupdf>=1.24,<1.27` (1.26.7 has no dependencies). With that version the document unit tests pass and the extraction benchmark is identical to the documented one (`evals/reports/extraction_2026-11-18_f63ed8f.json`).

## Files prepared (untested)

- `render.yaml`: Render blueprint for the API (free web service). Written from the documentation; **never run**.
- `frontend/vercel.json`: single-page-app rewrite for Vercel or a similar static host. **Never run.** The frontend needs `VITE_API_URL` set to the API's public URL at build time.
- `.github/workflows/ci.yml`: lint, unit tests and the frontend typecheck/test/build on every push. It has not run on GitHub yet, so its first run may need small fixes. Integration tests are skipped in CI (no database secret) and are run by hand.

## What deploying needs from you

1. A free Render account (or similar) for the API and a free Vercel/Netlify account for the frontend. Accounts are created by the project owner.
2. The Supabase session-pooler `DATABASE_URL` entered in the host's dashboard as a secret, never in the repository. Prefer a database dedicated to the demo.
3. `CORS_ORIGINS` set to a JSON list holding the frontend's URL, for example `["https://your-app.vercel.app"]`.
4. `READ_ONLY=true` (already set in `render.yaml`). Keep `LLM_PROVIDER=mock` unless you want a public instance to spend a Groq key; with `READ_ONLY` no new assessments can be requested anyway.
5. The demo data seeded once from a trusted machine: `python scripts/seed_demo.py` (see the README).

## Known blockers and risks

- Free tiers sleep when idle, so the first visit after a pause can take tens of seconds.
- Supabase's free plan pauses an inactive project; it must be resumed before the demo works.
- The free Supabase plan allows two active projects; a third needs one paused.
- Nothing here has been load-tested, and the dashboard endpoints run a dozen sequential queries (about 10 s on the first load from the developer's laptop to the hosted database).
