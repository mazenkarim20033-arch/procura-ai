from datetime import UTC, datetime
from types import SimpleNamespace

from app.services import audit


def chain(n: int):
    rows, prev = [], audit.GENESIS_HASH
    for i in range(1, n + 1):
        ts = datetime(2026, 1, 1, 12, 0, i, tzinfo=UTC)
        h = audit.compute_hash(prev, ts, "user", "u", f"a{i}", "request", "r", {"i": i})
        rows.append(SimpleNamespace(id=i, ts=ts, actor_type="user", actor_id="u", action=f"a{i}", entity_type="request",
                                    entity_id="r", payload_json={"i": i}, prev_hash=prev, hash=h))
        prev = h
    return rows


def test_streaming_verification_in_batches_equals_full_verification():
    rows = chain(7)
    assert audit.verify_chain(rows) == (True, None)
    ok, bad, head = audit._verify(rows[:3], audit.GENESIS_HASH)
    assert ok and head == rows[2].hash
    assert audit.verify_chain(rows[3:], prev_hash=head) == (True, None)  # second batch continues from the first
    assert audit.verify_chain(rows[3:]) == (False, 4)  # without the carried hash the link is (correctly) broken


def test_forged_and_reordered_entries_are_detected():
    rows = chain(5)
    rows[3].payload_json = {"i": 99}
    assert audit.verify_chain(rows) == (False, 4)
    rows = chain(5)
    rows[1], rows[2] = rows[2], rows[1]
    assert audit.verify_chain(rows)[0] is False
