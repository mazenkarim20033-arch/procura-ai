# Deployment

**Status: a recorded-snapshot demo is deployed on GitHub Pages (https://mazenkarim20033-arch.github.io/procura-ai/). No live backend is deployed.** This file records what is deployed, what was prepared but not run, what was measured, and what a live deployment would need from the project owner. Every figure below was measured on 2026-11-18 on the developer's laptop (Windows) unless stated otherwise.

## The deployed demo: a recorded snapshot

The public demo is the real frontend built in snapshot mode (`npm run build:demo`, `VITE_STATIC_DEMO=1`). It has **no backend and no database**. Every read is answered from JSON files recorded from the running API over the synthetic demo data (`frontend/public/demo-data/`, 320 files, 0.75 MB, scanned for secrets before publishing). Every write is refused with an explanation, and the interface says "Snapshot" in the header and "Recorded snapshot" in the sidebar.

What that means in practice:
- You can browse the review queue, every request with its intake checks, quotations, documents, history and stored AI assessment, vendors, policies, analytics and the audit log.
- You cannot create requests, upload documents, run an assessment, record a decision, save settings or ask the policy search a question. Date-range analytics are not available either, because they are computed live.
- "Verify the chain" replays the verification result recorded when the snapshot was taken (157 entries, intact); it does not recompute anything, and the page says so.
- The assessments were produced by the keyword-based mock AI, except one request assessed with a real model (gpt-oss-120b); both are labelled.

How it is published: `.github/workflows/pages.yml` builds the demo on every push that changes `frontend/` and deploys it to GitHub Pages at the `/procura-ai/` sub-path (the repository is public). The build fails if the output is not in snapshot mode.

To refresh the snapshot: start the backend, run `python scripts/export_snapshot.py` from `backend/`, commit `frontend/public/demo-data/` and push.

Things that went wrong while deploying, so they are not repeated: a blanket `.env.*` ignore rule kept `frontend/.env.demo` out of git, so the first deploy ran in normal mode and asked for a backend at localhost (the workflow now guards against this); GitHub Pages caches pages for about 10 minutes, so a browser that visited the broken version kept showing it for a while; and `vite preview` ignores the sub-path unless given `--base`, which made a local test look like a bug in the app.

## What a live public instance must be

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

- `render.yaml`: Render blueprint for the live API (free web service), the way to get live policy search and assessments on a public demo. Written from the documentation; **never run**.
- `frontend/vercel.json`: single-page-app rewrite for Vercel or a similar static host with a live API. **Never run.** The frontend then needs `VITE_API_URL` set to the API's public URL at build time.
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
