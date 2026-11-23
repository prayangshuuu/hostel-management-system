"""Web authentication routes (/login, /logout)."""

import logging

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.csrf import verify_csrf
from app.core.exceptions import AuthenticationError
from app.models.user import UserRole
from app.repositories.auth_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.web.deps import get_current_web_user_optional, render_template

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web-auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render login page or redirect if already authenticated."""
    current_user = await get_current_web_user_optional(request, db)
    if current_user:
        target = "/portal" if current_user.role == UserRole.STUDENT else "/admin/students"
        return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)

    return render_template(
        request,
        "auth/login.html",
        {"next": next or "", "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str | None = Form(None),
    csrf_token: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Process login form submission."""
    verify_csrf(request, form_csrf=csrf_token)

    auth_service = AuthService(UserRepository(db), RefreshTokenRepository(db))
    try:
        token_response = await auth_service.authenticate(email.strip(), password)
    except AuthenticationError as e:
        logger.warning("Web login failure for email %s: %s", email, e.message)
        return render_template(
            request,
            "auth/login.html",
            {
                "next": next or "",
                "email": email,
                "error": e.message,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Determine redirect destination
    target = next if (next and next.startswith("/") and not next.startswith("//")) else None
    if not target:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_email(email.strip())
        target = "/portal" if (user and user.role == UserRole.STUDENT) else "/admin/students"

    response = RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
    # Set cookies
    is_prod = settings.APP_ENV == "production"
    response.set_cookie(
        key="access_token",
        value=token_response.access_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=token_response.refresh_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/",
    )
    return response


@router.post("/logout")
async def logout_submit(
    request: Request,
    csrf_token: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Log out web user, invalidate refresh token family, and clear cookies."""
    verify_csrf(request, form_csrf=csrf_token)

    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        try:
            auth_service = AuthService(UserRepository(db), RefreshTokenRepository(db))
            await auth_service.logout(refresh_token)
        except Exception as e:
            logger.debug("Web logout token revocation error: %s", e)

    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return response
