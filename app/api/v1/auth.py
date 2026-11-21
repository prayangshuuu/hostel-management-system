"""Authentication and session endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db
from app.core.exceptions import ValidationAppError
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.user import UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and issue token pair",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": LoginRequest.model_json_schema(),
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string"},
                            "password": {"type": "string"},
                        },
                        "required": ["username", "password"],
                    }
                },
            }
        }
    },
)
async def login(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate via JSON credentials or OAuth2 form-urlencoded parameters."""
    content_type = request.headers.get("content-type", "")
    email: str | None = None
    password: str | None = None

    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        form_username = form.get("username")
        form_email = form.get("email")
        raw_email = form_username if form_username is not None else form_email
        raw_password = form.get("password")
        if raw_email is not None and isinstance(raw_email, str):
            email = raw_email
        if raw_password is not None and isinstance(raw_password, str):
            password = raw_password
    else:
        try:
            body = await request.json()
        except Exception as err:
            raise ValidationAppError("Invalid JSON body", code="VALIDATION_ERROR") from err

        if not isinstance(body, dict):
            raise ValidationAppError("Request body must be a JSON object", code="VALIDATION_ERROR")
        raw_email = body.get("email") or body.get("username")
        raw_password = body.get("password")
        if raw_email is not None and isinstance(raw_email, str):
            email = raw_email
        if raw_password is not None and isinstance(raw_password, str):
            password = raw_password

    if not email or not password:
        raise ValidationAppError(
            "Email and password are required",
            code="VALIDATION_ERROR",
        )

    try:
        validated = LoginRequest(email=email, password=password)
    except ValidationError as err:
        raise RequestValidationError(err.errors()) from err

    auth_service = AuthService(UserRepository(session))
    return await auth_service.authenticate(email=str(validated.email), password=validated.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh token pair",
)
async def refresh_token(
    body: RefreshTokenRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Exchange a valid refresh token for a fresh access + refresh token pair."""
    auth_service = AuthService(UserRepository(session))
    return await auth_service.refresh_token(refresh_token=body.refresh_token)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user details",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Retrieve authenticated user details."""
    return UserRead.model_validate(current_user)


@router.post(
    "/change-password",
    summary="Change user password",
)
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Rotate password after verifying current credentials."""
    auth_service = AuthService(UserRepository(session))
    await auth_service.change_password(
        user=current_user,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return {"message": "Password changed successfully"}
