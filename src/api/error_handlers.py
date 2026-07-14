"""Global exception handlers for consistent HTTP error responses.

Maps domain exceptions to HTTP status codes so that individual endpoints
do not need to wrap every call in try/except blocks.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    """Raised when a requested resource does not exist."""

    def __init__(self, detail: str = "Resource not found"):
        self.detail = detail
        super().__init__(detail)


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError):
        return JSONResponse(status_code=403, content={"detail": str(exc) or "Forbidden"})

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
