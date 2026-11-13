import os

import pytest

# Unit tests must never touch a real database, whatever the developer's .env says.
os.environ.pop("DATABASE_URL", None)


@pytest.fixture(autouse=True)
def _no_database(monkeypatch, request):
    if "integration" in request.keywords:
        yield
        return
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    from app.db import session

    session.get_engine.cache_clear()
    # Settings reads .env too; force "no database" for unit tests.
    monkeypatch.setattr(get_settings(), "database_url", None)
    yield
    get_settings.cache_clear()
