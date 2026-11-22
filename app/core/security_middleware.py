"""Security middleware for HTTP response headers and request body limits."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforce defensive HTTP security headers on all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if settings.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies exceeding the maximum configured payload size (5MB)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        max_size = settings.MAX_REQUEST_BODY_SIZE
        max_mb = max_size // (1024 * 1024)
        err_msg = f"Request payload exceeds maximum allowed size of {max_mb}MB"

        if content_length:
            try:
                length = int(content_length)
                if length > max_size:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": err_msg,
                                "details": {"max_bytes": max_size, "received_bytes": length},
                            }
                        },
                    )
            except ValueError:
                logger.debug("Invalid Content-Length header: %s", content_length)

        # For requests without content-length or chunked transfer, guard body consumption
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                body = await request.body()
                if len(body) > max_size:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": err_msg,
                                "details": {"max_bytes": max_size, "received_bytes": len(body)},
                            }
                        },
                    )
            except Exception as exc:
                logger.debug("Failed reading request body in size limiter: %s", exc)

        return await call_next(request)
