"""CSRF protection utilities for web forms and HTMX requests."""

import hmac
import secrets

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str) -> None:
    """Set the CSRF cookie on a response."""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,  # Allow JS/HTMX to read if needed for hx-headers
        secure=settings.APP_ENV == "production",
        samesite="lax",
        path="/",
    )


def verify_csrf(request: Request, form_csrf: str | None = None) -> None:
    """Verify CSRF token from header or form data against cookie."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing from cookies",
        )

    # Check header first (HTMX), then form field
    header_token = request.headers.get(CSRF_HEADER_NAME)
    submitted_token = header_token or form_csrf

    if not submitted_token or not hmac.compare_digest(cookie_token, submitted_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token validation failed",
        )
