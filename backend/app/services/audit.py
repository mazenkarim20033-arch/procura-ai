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


def verify_chain(entries: Iterable[AuditLog]) -> tuple[bool, int | None]:
    """Return (ok, first_bad_id). Entries must be ordered by id ascending."""
    prev = GENESIS_HASH
    for e in entries:
        expected = compute_hash(
            prev, e.ts, e.actor_type, e.actor_id, e.action, e.entity_type, e.entity_id, e.payload_json
        )
        if e.prev_hash != prev or e.hash != expected:
            return False, e.id
        prev = e.hash
    return True, None
