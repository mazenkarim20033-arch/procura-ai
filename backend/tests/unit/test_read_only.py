"""READ_ONLY=true makes the API safe to expose publicly: nothing can be created, uploaded or decided."""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "read_only", True)
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.mark.parametrize("method,path", [
    ("POST", "/requests"), ("POST", "/documents"), ("PUT", "/settings/approved-suppliers"), ("POST", "/policies/reindex"),
    ("POST", "/requests/00000000-0000-0000-0000-000000000000/decisions"), ("POST", "/requests/x/assess"),
    ("POST", "/vendors/x/merge"), ("DELETE", "/requests/x"), ("PATCH", "/requests/x"),
])
def test_every_write_is_refused_before_it_reaches_a_handler(client, method, path):
    r = client.request(method, path, headers={"x-demo-role": "admin"})
    assert r.status_code == 403 and r.json()["title"] == "read_only_demo"
    assert r.headers["content-type"].startswith("application/problem+json")


def test_reads_and_policy_questions_are_not_blocked(client):
    assert client.get("/health/live").status_code == 200
    # The search handler may fail here (no database in unit tests), but the guard must not be what stops it.
    assert client.post("/policies/search", json={"query": "who approves large purchases"}).json().get("title") != "read_only_demo"


def test_default_is_writable(monkeypatch):
    monkeypatch.setattr(get_settings(), "read_only", False)
    r = TestClient(create_app(), raise_server_exceptions=False).post("/requests", json={"total_amount": "-5"})
    # Without a database the handler fails (500), but the point is that the read-only guard did not answer.
    assert r.json()["title"] != "read_only_demo"
