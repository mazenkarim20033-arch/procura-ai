# Backend

Milestone 3 (foundation) — implemented and tested:

- FastAPI app with request-id logging (JSON), problem+json errors, CORS, `/health/live`, `/health/ready` (DB + pgvector + LLM provider mode).
- SQLAlchemy models for the full planned schema (27 tables); DDL generated to `migrations/sql/0001_initial.sql`.
- DB-level integrity: append-only `audit_log`, immutable assessments/findings/decisions, "only rules can confirm violations", "a request is approved/rejected only after a matching human decision", RLS on every table.
- Hash-chained audit log service (`app/services/audit.py`), demo-grade role enforcement (`app/api/auth.py`).

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

## Not verified yet

- `alembic upgrade head` against a real connection string has not been run (the schema was applied to Supabase through the SQL API and stamped as revision `0001`).
- `/health/ready` has only been tested in its "no database" path.
- The audit-log `append()` function has not been run against a live database (hash/verify logic is unit-tested).
