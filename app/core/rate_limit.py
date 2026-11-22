"""Rate limiting configuration and utilities using slowapi."""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)


def get_login_rate_limit_key(request: Request) -> str:
    """Generate composite rate limiting key combining client IP and target login email."""
    client_ip = get_remote_address(request) or "127.0.0.1"
    email = getattr(request.state, "login_email", None)
    if not email:
        email = request.query_params.get("email") or "anonymous"
    return f"{client_ip}:{str(email).strip().lower()}"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    headers_enabled=False,
)


class LoginEmailExtractorMiddleware(BaseHTTPMiddleware):
    """Middleware extracting the login email into request.state for IP+email rate limiting."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.endswith("/auth/login") and request.method == "POST":
            try:
                body_bytes = await request.body()
                content_type = request.headers.get("content-type", "")
                if "application/json" in content_type:
                    data = json.loads(body_bytes)
                    if isinstance(data, dict):
                        email = data.get("email") or data.get("username")
                        if email and isinstance(email, str):
                            request.state.login_email = email
                elif "form" in content_type:
                    parsed = parse_qs(body_bytes.decode("utf-8", errors="ignore"))
                    emails = parsed.get("username") or parsed.get("email")
                    if emails and len(emails) > 0:
                        request.state.login_email = emails[0]
            except Exception as exc:
                logger.debug("Failed to extract login email: %s", exc)
        return await call_next(request)
