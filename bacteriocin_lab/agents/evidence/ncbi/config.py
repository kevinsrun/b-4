from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass


@dataclass
class NCBIConfig:
    """Configuration for NCBI E-utilities and BLAST client."""

    api_key: str | None = None
    email: str | None = None
    tool: str | None = None
    timeout_seconds: float = 15.0
    max_retries: int = 3
    rate_limit_per_second: float | None = None
    base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    # BLAST-specific configuration
    blast_url: str = "https://blast.ncbi.nlm.nih.gov/Blast.cgi"
    blast_timeout_seconds: float = 60.0
    blast_poll_interval_seconds: float = 5.0
    blast_max_poll_attempts: int = 30
    blast_max_concurrent_requests: int = 2
    blast_cache_enabled: bool = True
    max_blast_queries_per_run: int = 5

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.getenv("NCBI_API_KEY") or None
        if self.email is None:
            self.email = os.getenv("NCBI_EMAIL") or None
        if self.tool is None:
            self.tool = os.getenv("NCBI_TOOL", "b4-literature-evidence")
        if self.rate_limit_per_second is None:
            # Conservative rate limiting for E-utilities: <= 10 req/s with API key, <= 3 req/s without
            self.rate_limit_per_second = 10.0 if self.api_key else 3.0
        # Normalize base_url
        if not self.base_url.endswith("/"):
            self.base_url += "/"

        # Environment variable overrides for BLAST
        if os.getenv("BLAST_URL"):
            self.blast_url = os.getenv("BLAST_URL", self.blast_url)
        if os.getenv("BLAST_TIMEOUT_SECONDS"):
            with contextlib.suppress(ValueError):
                self.blast_timeout_seconds = float(os.getenv("BLAST_TIMEOUT_SECONDS", "60.0"))
        if os.getenv("BLAST_POLL_INTERVAL_SECONDS"):
            with contextlib.suppress(ValueError):
                self.blast_poll_interval_seconds = float(os.getenv("BLAST_POLL_INTERVAL_SECONDS", "5.0"))
        if os.getenv("BLAST_MAX_POLL_ATTEMPTS"):
            with contextlib.suppress(ValueError):
                self.blast_max_poll_attempts = int(os.getenv("BLAST_MAX_POLL_ATTEMPTS", "30"))
        if os.getenv("BLAST_MAX_CONCURRENT_REQUESTS"):
            with contextlib.suppress(ValueError):
                self.blast_max_concurrent_requests = int(os.getenv("BLAST_MAX_CONCURRENT_REQUESTS", "2"))
        if os.getenv("BLAST_CACHE_ENABLED") is not None:
            self.blast_cache_enabled = os.getenv("BLAST_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
        if os.getenv("MAX_BLAST_QUERIES_PER_RUN"):
            with contextlib.suppress(ValueError):
                self.max_blast_queries_per_run = int(os.getenv("MAX_BLAST_QUERIES_PER_RUN", "5"))
        elif os.getenv("BLAST_MAX_QUERIES_PER_RUN"):
            with contextlib.suppress(ValueError):
                self.max_blast_queries_per_run = int(os.getenv("BLAST_MAX_QUERIES_PER_RUN", "5"))

    def __repr__(self) -> str:
        masked_key = "'***REDACTED***'" if self.api_key else "None"
        return (
            f"NCBIConfig(api_key={masked_key}, email={self.email!r}, tool={self.tool!r}, "
            f"timeout_seconds={self.timeout_seconds}, max_retries={self.max_retries}, "
            f"rate_limit_per_second={self.rate_limit_per_second}, base_url={self.base_url!r}, "
            f"blast_url={self.blast_url!r}, blast_timeout_seconds={self.blast_timeout_seconds}, "
            f"blast_poll_interval_seconds={self.blast_poll_interval_seconds}, "
            f"blast_max_poll_attempts={self.blast_max_poll_attempts}, "
            f"blast_max_concurrent_requests={self.blast_max_concurrent_requests}, "
            f"blast_cache_enabled={self.blast_cache_enabled}, "
            f"max_blast_queries_per_run={self.max_blast_queries_per_run})"
        )

    @classmethod
    def from_env(cls) -> NCBIConfig:
        return cls(
            api_key=os.getenv("NCBI_API_KEY") or None,
            email=os.getenv("NCBI_EMAIL") or None,
            tool=os.getenv("NCBI_TOOL", "b4-literature-evidence"),
            timeout_seconds=float(os.getenv("NCBI_TIMEOUT_SECONDS", "15.0")),
            max_retries=int(os.getenv("NCBI_MAX_RETRIES", "3")),
            blast_url=os.getenv("BLAST_URL", "https://blast.ncbi.nlm.nih.gov/Blast.cgi"),
            blast_timeout_seconds=float(os.getenv("BLAST_TIMEOUT_SECONDS", "60.0")),
            blast_poll_interval_seconds=float(os.getenv("BLAST_POLL_INTERVAL_SECONDS", "5.0")),
            blast_max_poll_attempts=int(os.getenv("BLAST_MAX_POLL_ATTEMPTS", "30")),
            blast_max_concurrent_requests=int(os.getenv("BLAST_MAX_CONCURRENT_REQUESTS", "2")),
            blast_cache_enabled=os.getenv("BLAST_CACHE_ENABLED", "true").lower() in ("true", "1", "yes"),
            max_blast_queries_per_run=int(
                os.getenv("MAX_BLAST_QUERIES_PER_RUN", os.getenv("BLAST_MAX_QUERIES_PER_RUN", "5"))
            ),
        )
