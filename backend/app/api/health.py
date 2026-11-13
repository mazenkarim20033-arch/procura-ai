from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response) -> dict:
    settings = get_settings()
    checks: dict[str, dict] = {}

    try:
        from app.db.session import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
            has_vector = conn.execute(
                text("select 1 from pg_extension where extname = 'vector'")
            ).first()
        checks["database"] = {"ok": True}
        checks["pgvector"] = {"ok": bool(has_vector)}
    except Exception as exc:  # noqa: BLE001 - report any failure, never crash the probe
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        checks["pgvector"] = {"ok": False}

    # Honest status: the embedding model and real LLM are wired in later milestones.
    checks["llm"] = {"ok": True, "provider": settings.llm_provider, "mock": settings.is_mock_ai}

    healthy = all(c["ok"] for c in checks.values())
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}
