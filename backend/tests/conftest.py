import os

import pytest

# Unit tests must never touch a real database, whatever the developer's .env says.
os.environ.pop("DATABASE_URL", None)


@pytest.fixture(autouse=True)
def _no_database(monkeypatch, request):
    if "integration" in request.keywords:
        yield
        # Each integration fixture builds its own engine. Dispose it afterwards: the hosted session pooler allows
        # only ~15 client connections, and leaked idle pools exhausted it as the suite grew.
        from app.db import session as db_session

        if db_session.get_engine.cache_info().currsize:
            db_session.get_engine().dispose()
        db_session.get_engine.cache_clear()
        return
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    from app.db import session

    session.get_engine.cache_clear()
    # Settings reads .env too; force "no database" for unit tests.
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", None)
    # Likewise never call a real LLM or depend on the developer's provider/model choice.
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "llm_api_key", None)
    yield
    get_settings.cache_clear()
