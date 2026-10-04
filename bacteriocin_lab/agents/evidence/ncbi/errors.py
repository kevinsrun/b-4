from __future__ import annotations


class NCBIError(Exception):
    """Base exception for all NCBI-related errors."""


class NCBIRequestError(NCBIError):
    """Raised when an HTTP or network request to NCBI fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class NCBIRateLimitError(NCBIRequestError):
    """Raised when NCBI rate limits requests (HTTP 429) after retry attempts."""

    def __init__(
        self,
        message: str = "NCBI rate limit exceeded (HTTP 429)",
        url: str | None = None,
    ) -> None:
        super().__init__(message, status_code=429, url=url)


class NCBIParseError(NCBIError):
    """Raised when an NCBI response cannot be parsed (e.g. malformed XML or JSON)."""

    def __init__(
        self,
        message: str,
        raw_snippet: str | None = None,
    ) -> None:
        snippet = (raw_snippet[:200] + "...") if raw_snippet and len(raw_snippet) > 200 else raw_snippet
        full_msg = f"{message} (snippet: {snippet!r})" if snippet else message
        super().__init__(full_msg)
        self.raw_snippet = snippet
