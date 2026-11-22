"""Application logging configuration, formatters, and request tracking middleware."""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Retrieve the current request ID from the context variable."""
    return request_id_ctx_var.get()


class RequestIdFilter(logging.Filter):
    """Logging filter to inject request ID into all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production environments."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "request_id",
            "asctime",
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in standard_attrs and not key.startswith("_")
        }
        if extras:
            log_payload["extra"] = extras

        return json.dumps(log_payload, default=str)


class DevFormatter(logging.Formatter):
    """Human-readable formatter for local development environments."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = getattr(record, "request_id", None) or get_request_id() or "-"
        timestamp = self.formatTime(record, self.datefmt or "%Y-%m-%d %H:%M:%S")
        message = record.getMessage()
        formatted = f"{timestamp} [{record.levelname}] [{record.name}] [{req_id}] {message}"
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        return formatted


def setup_logging() -> None:
    """Configure root logger with appropriate formatter and level."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in list(root_logger.handlers):
        if "LogCapture" in type(handler).__name__:
            continue
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(log_level)

    if settings.APP_ENV != "development":
        stream_handler.setFormatter(JSONFormatter())
    else:
        stream_handler.setFormatter(DevFormatter())

    stream_handler.addFilter(RequestIdFilter())
    root_logger.addHandler(stream_handler)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """ASGI middleware for extracting/generating Request ID and logging request timing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        header_request_id = request.headers.get("X-Request-ID")
        request_id = (
            header_request_id.strip()
            if header_request_id and header_request_id.strip()
            else uuid.uuid4().hex
        )
        token = request_id_ctx_var.set(request_id)
        request.state.request_id = request_id
        start_time = time.perf_counter()

        logger = logging.getLogger("app.middleware.request")

        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.exception("Unhandled server error: %s", exc)
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "An internal server error occurred",
                        "details": {},
                    }
                },
            )
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "%s %s %d %.2fms [request_id=%s]",
                request.method,
                request.url.path,
                500,
                elapsed_ms,
                request_id,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": round(elapsed_ms, 2),
                    "request_id": request_id,
                },
            )
            return response
        else:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "%s %s %d %.2fms [request_id=%s]",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                request_id,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(elapsed_ms, 2),
                    "request_id": request_id,
                },
            )
            return response
        finally:
            request_id_ctx_var.reset(token)
