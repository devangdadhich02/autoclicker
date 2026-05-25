from __future__ import annotations

from fastapi import HTTPException, status


class VeloraException(Exception):
    """Base exception for all application-level errors."""

    def __init__(self, message: str, code: str = "VELORA_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(VeloraException):
    def __init__(self, resource: str, identifier: str | int) -> None:
        super().__init__(f"{resource} '{identifier}' not found.", code="NOT_FOUND")


class ConflictError(VeloraException):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFLICT")


class AuthenticationError(VeloraException):
    def __init__(self, message: str = "Invalid credentials.") -> None:
        super().__init__(message, code="AUTH_ERROR")


class AuthorizationError(VeloraException):
    def __init__(self, message: str = "Insufficient permissions.") -> None:
        super().__init__(message, code="FORBIDDEN")


class AutomationError(VeloraException):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="AUTOMATION_ERROR")


class BrowserError(VeloraException):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="BROWSER_ERROR")


# ── HTTP exception helpers ─────────────────────────────────────────────────

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)

forbidden_exception = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Insufficient permissions.",
)
