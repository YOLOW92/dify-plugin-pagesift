"""Structured error contracts for PageSift 1.6.3 Dify Plugin."""

from __future__ import annotations

from typing import Any


class PageSiftError(Exception):
    """Base exception for all PageSift operations."""

    def __init__(
        self,
        message: str,
        code: str = "PAGESIFT_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | Any | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class PageSiftSSRFError(PageSiftError):
    """Raised when a requested URL resolves to an untrusted or private network address."""

    def __init__(self, message: str, status_code: int = 403, details: Any = None):
        super().__init__(message, code="SSRF_BLOCKED", status_code=status_code, details=details)


class PageSiftAuthError(PageSiftError):
    """Raised when authentication against PageSift fails (missing or invalid API key)."""

    def __init__(
        self,
        message: str = "Invalid PageSift API Key or unauthorized access",
        code: str = "UNAUTHORIZED",
        details: Any = None,
    ):
        super().__init__(message, code=code, status_code=401, details=details)


class PageSiftForbiddenError(PageSiftError):
    """Raised when access is denied by robots.txt, access barrier/CAPTCHA, or tenant ACL."""

    def __init__(
        self,
        message: str,
        code: str = "FORBIDDEN",
        status_code: int = 403,
        details: Any = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)


class PageSiftRateLimitError(PageSiftError):
    """Raised on HTTP 429: RPM limit, concurrency cap, daily page quota, or target rate limit."""

    def __init__(
        self,
        message: str,
        retry_after: float | None = None,
        code: str = "RATE_LIMITED",
        details: Any = None,
    ):
        super().__init__(message, code=code, status_code=429, details=details)
        self.retry_after = retry_after


class PageSiftTimeoutError(PageSiftError):
    """Raised when extraction or network request times out."""

    def __init__(self, message: str = "Operation timed out", details: Any = None):
        super().__init__(message, code="TIMEOUT", status_code=408, details=details)


class PageSiftDocumentError(PageSiftError):
    """Raised when document download or parsing fails (corrupted, empty, or too large)."""

    def __init__(
        self,
        message: str,
        code: str = "DOC_PARSE_FAILED",
        status_code: int = 422,
        details: Any = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)


class PageSiftUnsupportedError(PageSiftError):
    """Raised when a requested option or capability is unsupported or disabled on the server."""

    def __init__(self, message: str, details: Any = None):
        super().__init__(message, code="UNSUPPORTED_OPTION", status_code=400, details=details)


class PageSiftInvalidRequestError(PageSiftError):
    """Raised when PageSift rejects malformed or out-of-range request parameters."""

    def __init__(
        self,
        message: str,
        code: str = "INVALID_REQUEST",
        status_code: int = 400,
        details: Any = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)


class PageSiftNotFoundError(PageSiftError):
    """Raised when a job, source, attachment, or browser session does not exist or expired."""

    def __init__(
        self,
        message: str,
        code: str = "NOT_FOUND",
        status_code: int = 404,
        details: Any = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)


class PageSiftServiceError(PageSiftError):
    """Raised when PageSift server or upstream target fails (5xx, DNS/TLS/network, cooldown)."""

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        code: str = "SERVICE_ERROR",
        details: Any = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)
