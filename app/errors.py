"""One error format for the whole API.

Every error response looks like:
    {"error": {"code": "not_found", "message": "Artist 5 not found", "details": {...}}}

`code` is stable and meant for programs, `message` is meant for humans,
`details` is optional extra data (e.g. the list of invalid fields).
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors raised on purpose by our code (services and routers)."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnprocessableError(AppError):
    """Input is well-formed but breaks a business rule (e.g. `from` after `to`)."""

    status_code = 422
    code = "unprocessable"

    def __init__(self, message: str, details: Any | None = None, code: str | None = None) -> None:
        super().__init__(message, details)
        if code:
            self.code = code


def error_body(code: str, message: str, details: Any | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details)
    )


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default 422 body has a different shape; we wrap its list of problems
    # in our format. "input"/"ctx" may hold non-JSON values, so we keep only the basics.
    details = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=error_body("validation_error", "Request validation failed", details),
    )


async def _http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Raised by the framework itself, e.g. 404 for an unknown URL or 405 for a wrong method.
    codes = {404: "not_found", 405: "method_not_allowed"}
    code = codes.get(exc.status_code, "http_error")
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(error_body(code, str(exc.detail))),
        headers=getattr(exc, "headers", None),
    )


async def _unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # Never leak internals (stack traces, SQL) to the client; log them instead.
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500, content=error_body("internal_error", "Internal server error")
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
