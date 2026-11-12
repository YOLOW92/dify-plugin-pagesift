"""Structured error contracts for PageSift Dify Plugin."""

from __future__ import annotations


class PageSiftError(Exception):
    """Base exception for all PageSift operations."""
    def __init__(self, message: str, code: str = "PAGESIFT_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class PageSiftSSRFError(PageSiftError):
    """Raised when a requested URL resolves to an untrusted or private network address."""
    def __init__(self, message: str):
        super().__init__(message, code="SSRF_BLOCKED", status_code=403)


class PageSiftAuthError(PageSiftError):
    """Raised when authentication against PageSift fails (invalid API key)."""
    def __init__(self, message: str = "Invalid PageSift API Key or unauthorized access"):
        super().__init__(message, code="AUTH_FAILED", status_code=401)


class PageSiftRateLimitError(PageSiftError):
    """Raised when PageSift or target origin returns 429 Too Many Requests."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message, code="RATE_LIMITED", status_code=429)
        self.retry_after = retry_after


class PageSiftTimeoutError(PageSiftError):
    """Raised when extraction or network request times out."""
    def __init__(self, message: str = "Operation timed out"):
        super().__init__(message, code="TIMEOUT", status_code=408)


class PageSiftDocumentError(PageSiftError):
    """Raised when document parsing fails (corrupted file, unsupported format, etc.)."""
    def __init__(self, message: str):
        super().__init__(message, code="DOC_PARSE_FAILED", status_code=422)


class PageSiftServiceError(PageSiftError):
    """Raised when PageSift server is unreachable or returns 5xx."""
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message, code="SERVICE_ERROR", status_code=status_code)
