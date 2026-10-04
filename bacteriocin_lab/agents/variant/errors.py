from __future__ import annotations


class VariantDiscoveryError(Exception):
    """Base exception for all variant and genomics discovery errors."""


class AlignmentError(VariantDiscoveryError):
    """Base exception for multiple sequence alignment errors."""


class AlignmentUnavailableError(AlignmentError):
    """Raised when an alignment executable (MAFFT or Clustal Omega) is missing or not executable."""


class AlignmentExecutionError(AlignmentError):
    """Raised when an alignment process exits with a non-zero return code."""

    def __init__(
        self,
        message: str,
        returncode: int | None = None,
        stderr: str | None = None,
        cmd: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.cmd = cmd


class AlignmentTimeoutError(AlignmentError):
    """Raised when an alignment process exceeds its execution timeout."""


class VariantBudgetExceededError(VariantDiscoveryError):
    """Raised when variant generation exceeds configured run budget."""
