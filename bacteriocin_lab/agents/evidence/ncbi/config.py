from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class NCBIConfig:
    """Configuration for NCBI E-utilities client."""

    api_key: str | None = None
    email: str | None = None
    tool: str | None = None
    timeout_seconds: float = 15.0
    max_retries: int = 3
    rate_limit_per_second: float | None = None
    base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.getenv("NCBI_API_KEY") or None
        if self.email is None:
            self.email = os.getenv("NCBI_EMAIL") or None
        if self.tool is None:
            self.tool = os.getenv("NCBI_TOOL", "b4-literature-evidence")
        if self.rate_limit_per_second is None:
            # Conservative rate limiting: <= 10 req/s with API key, <= 3 req/s without
            self.rate_limit_per_second = 10.0 if self.api_key else 3.0
        # Normalize base_url
        if not self.base_url.endswith("/"):
            self.base_url += "/"

    @classmethod
    def from_env(cls) -> NCBIConfig:
        return cls(
            api_key=os.getenv("NCBI_API_KEY") or None,
            email=os.getenv("NCBI_EMAIL") or None,
            tool=os.getenv("NCBI_TOOL", "b4-literature-evidence"),
            timeout_seconds=float(os.getenv("NCBI_TIMEOUT_SECONDS", "15.0")),
            max_retries=int(os.getenv("NCBI_MAX_RETRIES", "3")),
        )
