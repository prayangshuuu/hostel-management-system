"""Custom application exception hierarchy."""

from typing import Any


class AppException(Exception):  # noqa: N818
    """Base application exception for handled domain and operational errors."""

    def __init__(
        self,
        message: str,
        code: str = "APP_ERROR",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details if details is not None else {}


class NotFoundError(AppException):
    """Raised when an entity or resource is not found."""

    def __init__(
        self,
        message: str = "Resource not found",
        code: str = "NOT_FOUND",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=404,
            details=details,
        )


class ConflictError(AppException):
    """Raised when a resource conflict occurs (e.g., unique violation, duplicate state)."""

    def __init__(
        self,
        message: str = "Resource conflict",
        code: str = "CONFLICT",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=409,
            details=details,
        )


class ForbiddenError(AppException):
    """Raised when the authenticated user lacks permission for the requested action."""

    def __init__(
        self,
        message: str = "Access forbidden",
        code: str = "FORBIDDEN",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=403,
            details=details,
        )


class UnauthorizedError(AppException):
    """Raised when authentication credentials are missing or invalid."""

    def __init__(
        self,
        message: str = "Unauthorized",
        code: str = "UNAUTHORIZED",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=401,
            details=details,
        )


class ValidationAppError(AppException):
    """Raised when business validation fails outside request schema parsing."""

    def __init__(
        self,
        message: str = "Validation error",
        code: str = "VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=422,
            details=details,
        )


class BusinessRuleError(AppException):
    """Raised when a business rule or invariant is violated."""

    def __init__(
        self,
        message: str = "Business rule violation",
        code: str = "BUSINESS_RULE_VIOLATION",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=400,
            details=details,
        )
