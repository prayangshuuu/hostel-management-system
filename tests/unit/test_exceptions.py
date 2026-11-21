"""Unit tests for custom exception classes."""

from app.core.exceptions import (
    AppException,
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationAppError,
)


def test_base_app_exception() -> None:
    """Verify base AppException initialization and default values."""
    exc = AppException("Custom base error")
    assert str(exc) == "Custom base error"
    assert exc.message == "Custom base error"
    assert exc.code == "APP_ERROR"
    assert exc.status_code == 400
    assert exc.details == {}


def test_not_found_error() -> None:
    """Verify NotFoundError status code and default code."""
    exc = NotFoundError("Hostel not found", details={"hostel_id": 1})
    assert exc.message == "Hostel not found"
    assert exc.code == "NOT_FOUND"
    assert exc.status_code == 404
    assert exc.details == {"hostel_id": 1}


def test_conflict_error() -> None:
    """Verify ConflictError status code and default code."""
    exc = ConflictError("Email already in use")
    assert exc.message == "Email already in use"
    assert exc.code == "CONFLICT"
    assert exc.status_code == 409
    assert exc.details == {}


def test_forbidden_error() -> None:
    """Verify ForbiddenError status code and default code."""
    exc = ForbiddenError("Forbidden resource")
    assert exc.message == "Forbidden resource"
    assert exc.code == "FORBIDDEN"
    assert exc.status_code == 403
    assert exc.details == {}


def test_unauthorized_error() -> None:
    """Verify UnauthorizedError status code and default code."""
    exc = UnauthorizedError("Invalid credentials")
    assert exc.message == "Invalid credentials"
    assert exc.code == "UNAUTHORIZED"
    assert exc.status_code == 401
    assert exc.details == {}


def test_validation_app_error() -> None:
    """Verify ValidationAppError status code and default code."""
    exc = ValidationAppError("Field mismatch", details={"field": "password"})
    assert exc.message == "Field mismatch"
    assert exc.code == "VALIDATION_ERROR"
    assert exc.status_code == 422
    assert exc.details == {"field": "password"}


def test_business_rule_error() -> None:
    """Verify BusinessRuleError status code and default code."""
    exc = BusinessRuleError("Maximum occupancy reached")
    assert exc.message == "Maximum occupancy reached"
    assert exc.code == "BUSINESS_RULE_VIOLATION"
    assert exc.status_code == 400
    assert exc.details == {}
