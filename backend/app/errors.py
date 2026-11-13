"""Typed domain errors rendered as RFC 7807 problem+json responses."""
import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "permission_denied"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


def _problem(status: int, code: str, detail: str, **extra) -> JSONResponse:
    body = {"type": f"urn:procura:{code}", "title": code, "status": status, "detail": detail}
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        return _problem(exc.status_code, exc.code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # jsonable_encoder: error contexts can hold Decimals/exceptions that plain JSON cannot serialise.
        errors = [{k: v for k, v in e.items() if k != "ctx"} for e in jsonable_encoder(exc.errors())]
        return _problem(422, "validation_error", "Request validation failed", errors=errors)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return _problem(500, "internal_error", "Internal server error")
