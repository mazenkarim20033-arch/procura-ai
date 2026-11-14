"""Hash-chained audit log. Tamper-evident (verify_chain detects edits), not tamper-proof:
the database trigger blocks UPDATE/DELETE, but a superuser could still bypass it."""
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import AuditLog

GENESIS_HASH = "0" * 64
_LOCK_KEY = 727_001  # arbitrary constant for pg_advisory_xact_lock


def compute_hash(
    prev_hash: str, ts: datetime, actor_type: str, actor_id: str | None, action: str,
    entity_type: str, entity_id: str | None, payload: dict,
) -> str:
    record = {
        "prev": prev_hash,
        "ts": ts.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
    }
    blob = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def append(
    session: Session, *, actor_type: str, actor_id: str | None, action: str,
    entity_type: str, entity_id: str | None = None, payload: dict | None = None,
) -> AuditLog:
    """Append one entry. Serialised with an advisory lock so the chain never forks."""
    session.execute(text("select pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    prev = session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
    prev_hash = prev or GENESIS_HASH
    clean = json.loads(json.dumps(payload or {}, default=str))  # normalise to JSON-native types
    ts = datetime.now(UTC)
    entry = AuditLog(
        ts=ts, actor_type=actor_type, actor_id=actor_id, action=action,
        entity_type=entity_type, entity_id=entity_id, payload_json=clean,
        prev_hash=prev_hash,
        hash=compute_hash(prev_hash, ts, actor_type, actor_id, action, entity_type, entity_id, clean),
    )
    session.add(entry)
    session.flush()
    return entry


def verify_chain(entries: Iterable[AuditLog], prev_hash: str = GENESIS_HASH) -> tuple[bool, int | None]:
    """Return (ok, first_bad_id). Entries must be ordered by id ascending; `prev_hash` is the hash the first
    entry must chain from (the genesis hash for a full chain, or the last verified hash when streaming)."""
    ok, bad, _ = _verify(entries, prev_hash)
    return ok, bad


def _verify(entries: Iterable[AuditLog], prev: str) -> tuple[bool, int | None, str]:
    for e in entries:
        expected = compute_hash(
            prev, e.ts, e.actor_type, e.actor_id, e.action, e.entity_type, e.entity_id, e.payload_json
        )
        if e.prev_hash != prev or e.hash != expected:
            return False, e.id, prev
        prev = e.hash
    return True, None, prev


def verify_all(session: Session, batch: int = 1000) -> dict:
    """Verify the whole stored chain in id order, streaming in batches. Detects edited or reordered entries
    and, because each hash covers its predecessor, deletions anywhere before the newest entry (deleting the
    newest entries is only detectable against a head hash recorded elsewhere)."""
    prev, count, last_id = GENESIS_HASH, 0, 0
    while True:
        rows = session.execute(
            select(AuditLog).where(AuditLog.id > last_id).order_by(AuditLog.id).limit(batch),
            execution_options={"populate_existing": True},  # never trust identity-mapped (possibly stale) copies
        ).scalars().all()
        if not rows:
            break
        ok, bad, prev = _verify(rows, prev)
        if not ok:
            return {"ok": False, "entries_checked": count, "first_bad_id": bad, "head_hash": None,
                    "verified_at": datetime.now(UTC).isoformat()}
        count += len(rows)
        last_id = rows[-1].id
    return {"ok": True, "entries_checked": count, "first_bad_id": None, "head_hash": None if count == 0 else prev,
            "verified_at": datetime.now(UTC).isoformat(),
            "scope": "tamper-evident, not tamper-proof: record head_hash elsewhere to also detect truncation"}


def list_entries(session: Session, *, entity_type: str | None = None, entity_id: str | None = None,
                 action: str | None = None, actor_type: str | None = None, before_id: int | None = None,
                 limit: int = 50) -> dict:
    """Newest first, keyset-paginated: pass the returned `next_before_id` to get the following page."""
    limit = max(1, min(limit, 200))
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    for col, val in ((AuditLog.entity_type, entity_type), (AuditLog.entity_id, entity_id),
                     (AuditLog.action, action), (AuditLog.actor_type, actor_type)):
        if val:
            q = q.where(col == val)
    if before_id:
        q = q.where(AuditLog.id < before_id)
    rows = session.execute(q).scalars().all()
    page = rows[:limit]
    return {
        "entries": [{"id": e.id, "ts": e.ts.isoformat(), "actor_type": e.actor_type, "actor": e.actor_id, "action": e.action,
                     "entity_type": e.entity_type, "entity_id": e.entity_id, "payload": e.payload_json,
                     "hash": e.hash[:16], "prev_hash": e.prev_hash[:16]} for e in page],
        "next_before_id": page[-1].id if len(rows) > limit else None,
    }
