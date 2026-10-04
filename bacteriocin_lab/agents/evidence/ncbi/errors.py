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


class BlastError(NCBIError):
    """Base exception for all NCBI BLAST-related errors."""


class BlastValidationError(BlastError, ValueError):
    """Raised when sequence validation fails prior to network dispatch."""


class BlastSubmissionError(BlastError):
    """Raised when BLAST job submission fails or RID cannot be extracted."""


class BlastTimeoutError(BlastError):
    """Raised when BLAST polling exceeds configured timeout or max attempts."""


class BlastRemoteFailure(BlastError):
    """Raised when a remote BLAST search fails or RID is unknown/expired on NCBI."""


class BlastParseError(BlastError, NCBIParseError):
    """Raised when BLAST output or XML cannot be parsed."""


class BlastBudgetExceededError(BlastError):
    """Raised when the maximum allowed BLAST searches for a run is exceeded."""
