"""Web dependencies, Jinja2 template setup, and authentication helpers."""

import logging
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.csrf import CSRF_COOKIE_NAME, generate_csrf_token, set_csrf_cookie
from app.core.security import decode_token
from app.models.user import User, UserRole
from app.repositories.hostel_repository import WardenAssignmentRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/templates")


# Template custom filters
def format_currency(value: Any) -> str:
    """Format decimal or float as standard currency."""
    if value is None:
        return "$0.00"
    try:
        dec = Decimal(str(value))
        return f"${dec:,.2f}"
    except Exception:
        return f"${value}"


def format_date(value: Any) -> str:
    """Format date as YYYY-MM-DD."""
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return str(value.strftime("%Y-%m-%d"))
    return str(value)[:10]


def format_datetime(value: Any) -> str:
    """Format datetime as YYYY-MM-DD HH:MM."""
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return str(value.strftime("%Y-%m-%d %H:%M"))
    return str(value)


def user_initials(name: str | None) -> str:
    """Extract up to 2 initials from a person's name."""
    if not name:
        return "U"
    parts = name.strip().split()
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def status_badge_class(status_str: str | None) -> str:
    """Return Tailwind color classes for domain status strings."""
    s = str(status_str).lower() if status_str else ""
    if s in ("active", "paid", "resolved", "approved"):
        return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20"
    if s in ("pending", "in_progress", "partial", "scheduled"):
        return "bg-amber-50 text-amber-700 ring-1 ring-amber-600/20"
    if s in ("unpaid", "overdue", "rejected", "urgent"):
        return "bg-rose-50 text-rose-700 ring-1 ring-rose-600/20"
    if s in ("vacated", "cancelled", "closed", "void", "expired", "inactive"):
        return "bg-zinc-100 text-zinc-600 ring-1 ring-zinc-500/20"
    return "bg-blue-50 text-blue-700 ring-1 ring-blue-600/20"


templates.env.filters["currency"] = format_currency
templates.env.filters["date_format"] = format_date
templates.env.filters["datetime_format"] = format_datetime
templates.env.filters["initials"] = user_initials
templates.env.filters["status_color"] = status_badge_class


def render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    """Render a Jinja2 template with common context (csrf, user, settings)."""
    ctx = context or {}
    ctx["request"] = request
    ctx["app_name"] = settings.APP_NAME
    ctx["app_version"] = settings.APP_VERSION
    if "current_user" not in ctx:
        ctx["current_user"] = getattr(request.state, "user", None)

    # Ensure CSRF token is present in context and cookie
    csrf_token = request.cookies.get(CSRF_COOKIE_NAME)
    must_set_cookie = False
    if not csrf_token:
        csrf_token = generate_csrf_token()
        must_set_cookie = True
    ctx["csrf_token"] = csrf_token

    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context=ctx,
        status_code=status_code,
        headers=headers,
    )
    if must_set_cookie:
        set_csrf_cookie(response, csrf_token)
    return response


async def get_current_web_user_optional(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """Retrieve authenticated user from cookie or Authorization header without raising."""
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        return None

    try:
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            return None
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        user_id = UUID(user_id_str)
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            return None
        request.state.user = user
        return user
    except Exception:
        return None


async def get_current_web_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Retrieve authenticated user or redirect to /login."""
    user = await get_current_web_user_optional(request, db)
    if not user:
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_401_UNAUTHORIZED)
            response.headers["HX-Redirect"] = f"/login?next={request.url.path}"
            return user  # type: ignore[return-value]
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={request.url.path}"},
        )
    return user


async def require_staff_web(
    request: Request,
    user: Annotated[User, Depends(get_current_web_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tuple[User, list[UUID]]:
    """Require Admin or Warden role; returns user and assigned hostel IDs."""
    if user.role not in (UserRole.ADMIN, UserRole.WARDEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")

    assigned_hostels: list[UUID] = []
    if user.role == UserRole.WARDEN:
        warden_repo = WardenAssignmentRepository(db)
        assigned_hostels = await warden_repo.list_hostel_ids_for_warden(user.id)

    return user, assigned_hostels


async def require_admin_web(
    user: Annotated[User, Depends(get_current_web_user)],
) -> User:
    """Require Admin role."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
