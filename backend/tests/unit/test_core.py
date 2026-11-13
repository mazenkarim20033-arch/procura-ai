import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import CurrentUser, require_role
from app.config import Settings
from app.db import enums as E
from app.db.models import Base, Finding
from app.errors import install_error_handlers
from app.main import create_app
from app.services import audit


def test_database_url_is_normalised_to_psycopg3():
    s = Settings(database_url="postgresql://u:p@h:5432/db", _env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"
    s = Settings(database_url="postgres://u:p@h/db", _env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")


def test_default_provider_is_mock():
    assert Settings(_env_file=None).is_mock_ai


def test_health_live_and_ready_degrades_without_database():
    client = TestClient(create_app())
    assert client.get("/health/live").json() == {"status": "ok"}
    r = client.get("/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["ok"] is False
    assert body["checks"]["llm"]["mock"] is True
    assert "x-request-id" in r.headers


def test_unhandled_errors_become_problem_json_without_leaking_details():
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise ValueError("secret internals")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "secret" not in r.text


def test_role_enforcement():
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/decide")
    def decide(user: CurrentUser = Depends(require_role(E.Role.reviewer))):
        return {"by": user.role}

    c = TestClient(app)
    assert c.post("/decide", headers={"x-demo-role": "requester"}).status_code == 403
    assert c.post("/decide", headers={"x-demo-role": "reviewer"}).status_code == 200
    assert c.post("/decide", headers={"x-demo-role": "admin"}).status_code == 200
    assert c.post("/decide", headers={"x-demo-role": "hacker"}).status_code == 403


def test_ai_status_vocabulary_has_no_approval():
    values = {m.value for m in E.ComplianceStatus}
    assert not any("approv" in v for v in values)


def test_only_rules_can_confirm_violations_constraint_exists():
    names = {c.name for c in Finding.__table__.constraints if c.name}
    assert any("confirmed_needs_rule" in n for n in names)


def test_schema_covers_planned_tables():
    expected = {
        "users", "app_settings", "documents", "document_pages", "extractions", "policies",
        "chunks", "policy_rules", "vendors", "vendor_aliases", "purchase_requests",
        "request_items", "request_documents", "quotations", "quotation_items", "assessments",
        "findings", "finding_evidence", "retrieval_logs", "llm_calls", "decisions",
        "finding_reviews", "info_requests", "audit_log", "jobs", "eval_runs", "eval_case_results",
    }
    assert expected == set(Base.metadata.tables)


def test_generated_ddl_is_in_sync_with_models():
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("gen_ddl", root / "scripts" / "gen_ddl.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    on_disk = (root / "migrations" / "sql" / "0001_initial.sql").read_text(encoding="utf-8")
    assert on_disk == mod.build(), "run scripts/gen_ddl.py"
    assert "%" not in on_disk
    for table in Base.metadata.tables:
        assert f"alter table public.{table} enable row level security" in on_disk


@dataclass
class Row:
    id: int
    ts: datetime
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    payload_json: dict
    prev_hash: str
    hash: str


def _chain(n: int) -> list[Row]:
    rows, prev = [], audit.GENESIS_HASH
    for i in range(1, n + 1):
        ts = datetime(2026, 1, 1, 12, 0, i, tzinfo=UTC)
        h = audit.compute_hash(prev, ts, "user", "u1", f"act{i}", "request", "r1", {"i": i})
        rows.append(Row(i, ts, "user", "u1", f"act{i}", "request", "r1", {"i": i}, prev, h))
        prev = h
    return rows


def test_audit_chain_verifies_and_detects_tampering():
    rows = _chain(5)
    assert audit.verify_chain(rows) == (True, None)
    rows[2].payload_json = {"i": 999}
    assert audit.verify_chain(rows) == (False, 3)


def test_audit_chain_detects_deleted_entry():
    rows = _chain(5)
    del rows[1]
    ok, bad = audit.verify_chain(rows)
    assert not ok and bad == 3


def test_audit_hash_is_deterministic_and_hex():
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    a = audit.compute_hash("0" * 64, ts, "system", None, "x", "t", None, {"k": 1})
    b = audit.compute_hash("0" * 64, ts, "system", None, "x", "t", None, {"k": 1})
    assert a == b and re.fullmatch(r"[0-9a-f]{64}", a)
