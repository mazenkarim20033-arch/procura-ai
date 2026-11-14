"""Integration tests run against the real hosted database inside a transaction that is always rolled back.
To be independent of whatever data is already there (for example the seeded demo dataset), each test first
empties every table INSIDE that transaction. Nothing is committed, so the real data is never touched."""
from sqlalchemy import text

from app.db.models import Base

# Tables with immutability triggers (append-only audit log, immutable assessments/decisions). Disabling user
# triggers needs only table ownership; the change is transactional and is undone by the rollback.
_GUARDED = ("audit_log", "assessments", "findings", "finding_evidence", "decisions", "purchase_requests")


def wipe_all(connection) -> None:
    for table in _GUARDED:
        connection.execute(text(f"alter table public.{table} disable trigger user"))
    names = ", ".join(f"public.{t.name}" for t in Base.metadata.sorted_tables)
    connection.execute(text(f"truncate table {names} restart identity cascade"))
    for table in _GUARDED:
        connection.execute(text(f"alter table public.{table} enable trigger user"))
