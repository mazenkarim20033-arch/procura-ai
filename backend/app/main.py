import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analytics,
    assessments,
    decisions,
    documents,
    health,
    policies,
    requests,
    vendors,
)
from app.config import get_settings
from app.errors import _problem, install_error_handlers
from app.logging import configure_logging, request_id_var

log = logging.getLogger("procura")

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
READ_ONLY_ALLOWED_POSTS = {"/policies/search"}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Procura AI", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins,
        allow_methods=["*"], allow_headers=["*"],
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def read_only_guard(request: Request, call_next):
        if settings.read_only and request.method not in READ_METHODS and request.url.path not in READ_ONLY_ALLOWED_POSTS:
            return _problem(403, "read_only_demo", "This public demo is read-only. Run Procura locally to create requests, "
                            "upload documents or record decisions.")
        return await call_next(request)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        log.info(
            "request",
            extra={"extra_fields": {
                "method": request.method, "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - start) * 1000, 1),
            }},
        )
        return response

    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(policies.router)
    app.include_router(requests.router)
    app.include_router(assessments.router)
    app.include_router(vendors.router)
    app.include_router(decisions.router)
    app.include_router(analytics.router)
    return app


app = create_app()
