from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import NCBIConfig
from .errors import NCBIParseError, NCBIRateLimitError, NCBIRequestError

logger = logging.getLogger("b4_literature.ncbi")

# Status codes that indicate a transient failure suitable for retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Signature: (url, headers, timeout_seconds) -> (status_code, headers_dict, body_text)
TransportFunc = Callable[[str, dict[str, str], float], tuple[int, dict[str, str], str]]


class RateLimiter:
    """Thread-safe rate limiter ensuring a minimum interval between requests."""

    def __init__(self, rate_per_second: float) -> None:
        self.min_interval = 1.0 / rate_per_second if rate_per_second > 0 else 0.0
        self._last_request_time: float = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                time.sleep(sleep_time)
            self._last_request_time = time.monotonic()


def _default_transport(url: str, headers: dict[str, str], timeout_seconds: float) -> tuple[int, dict[str, str], str]:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout_seconds) as resp:
        status = resp.status if hasattr(resp, "status") else 200
        resp_headers = {k.lower(): v for k, v in resp.headers.items()}
        body = resp.read().decode("utf-8", errors="replace")
        return status, resp_headers, body


def redact_params(params: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive parameters like api_key for safe logging."""
    redacted: dict[str, Any] = {}
    for k, v in params.items():
        if k.lower() == "api_key":
            redacted[k] = "***REDACTED***"
        else:
            redacted[k] = v
    return redacted


def redact_url(url: str) -> str:
    """Redact api_key from query string for safe logging."""
    return re.sub(r"(api_key=)[^&]+", r"\1***REDACTED***", url, flags=re.IGNORECASE)


class NcbiClient:
    """NCBI E-utilities HTTP client with rate limiting, retry policy, and configuration."""

    def __init__(
        self,
        config: NCBIConfig | None = None,
        transport: TransportFunc | None = None,
        backoff_factor: float = 0.5,
    ) -> None:
        self.config = config or NCBIConfig.from_env()
        self._transport = transport or _default_transport
        self._backoff_factor = backoff_factor
        rate = self.config.rate_limit_per_second or (10.0 if self.config.api_key else 3.0)
        self.rate_limiter = RateLimiter(rate)

    def _build_url_and_params(self, endpoint: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        full_params = dict(params)
        absolute_endpoint = endpoint.startswith("http://") or endpoint.startswith("https://")
        # NCBI_API_KEY is an E-utilities credential, not a BLAST queue credential.  Absolute
        # endpoints (currently the BLAST URL API) receive only parameters explicitly supplied by
        # their caller so the key cannot cross that service boundary accidentally.
        if not absolute_endpoint:
            if self.config.tool and "tool" not in full_params:
                full_params["tool"] = self.config.tool
            if self.config.email and "email" not in full_params:
                full_params["email"] = self.config.email
            if self.config.api_key and "api_key" not in full_params:
                full_params["api_key"] = self.config.api_key

        if absolute_endpoint:
            base = endpoint
            encoded_query = urlencode(full_params)
            sep = "&" if "?" in base else "?"
            url = f"{base}{sep}{encoded_query}" if encoded_query else base
            return url, full_params

        base = self.config.base_url.rstrip("/")
        ep = endpoint.lstrip("/")
        encoded_query = urlencode(full_params)
        url = f"{base}/{ep}?{encoded_query}" if encoded_query else f"{base}/{ep}"
        return url, full_params

    def get(self, endpoint: str, params: dict[str, Any]) -> str:
        """Issue a GET request to an NCBI E-utilities endpoint with retries and rate limiting."""
        url, full_params = self._build_url_and_params(endpoint, params)
        headers = {
            "Accept": "*/*",
            "User-Agent": f"{self.config.tool or 'b4-literature-evidence'}/0.1",
        }

        attempts = self.config.max_retries + 1
        last_error: Exception | None = None
        last_status: int | None = None

        for attempt in range(attempts):
            self.rate_limiter.acquire()
            try:
                logger.debug(
                    "NCBI GET %s (attempt %d/%d, params: %s)",
                    redact_url(url),
                    attempt + 1,
                    attempts,
                    redact_params(full_params),
                )
                status, resp_headers, body = self._transport(url, headers, self.config.timeout_seconds)

                if status == 200:
                    return body

                last_status = status
                if status not in RETRYABLE_STATUS_CODES:
                    # Non-retryable client error (400, 401, 403, 404, etc.)
                    raise NCBIRequestError(
                        f"NCBI HTTP error {status} for {redact_url(url)}",
                        status_code=status,
                        url=redact_url(url),
                    )

                # Transient HTTP error (429, 500, 502, 503, 504)
                if status == 429:
                    last_error = NCBIRateLimitError(
                        f"NCBI rate limit exceeded (HTTP 429) for {redact_url(url)}",
                        url=redact_url(url),
                    )
                else:
                    last_error = NCBIRequestError(
                        f"NCBI transient HTTP error {status} for {redact_url(url)}",
                        status_code=status,
                        url=redact_url(url),
                    )

                # Check Retry-After header
                retry_after = resp_headers.get("retry-after")
                sleep_seconds = self._backoff_factor * (2**attempt)
                if retry_after and retry_after.isdigit():
                    sleep_seconds = max(sleep_seconds, float(retry_after))

                if attempt < attempts - 1:
                    time.sleep(sleep_seconds)
                    continue

            except HTTPError as exc:
                last_status = exc.code
                if exc.code not in RETRYABLE_STATUS_CODES:
                    raise NCBIRequestError(
                        f"NCBI HTTP error {exc.code} for {redact_url(url)}: {exc.reason}",
                        status_code=exc.code,
                        url=redact_url(url),
                    ) from exc

                if exc.code == 429:
                    last_error = NCBIRateLimitError(
                        f"NCBI rate limit exceeded (HTTP 429) for {redact_url(url)}",
                        url=redact_url(url),
                    )
                else:
                    last_error = NCBIRequestError(
                        f"NCBI HTTP error {exc.code} for {redact_url(url)}: {exc.reason}",
                        status_code=exc.code,
                        url=redact_url(url),
                    )

                if attempt < attempts - 1:
                    sleep_seconds = self._backoff_factor * (2**attempt)
                    time.sleep(sleep_seconds)
                    continue

            except (URLError, TimeoutError, ConnectionError) as exc:
                last_error = NCBIRequestError(
                    f"NCBI connection error for {redact_url(url)}: {exc}",
                    url=redact_url(url),
                )
                if attempt < attempts - 1:
                    sleep_seconds = self._backoff_factor * (2**attempt)
                    time.sleep(sleep_seconds)
                    continue

        # Retries exhausted
        if last_status == 429 or isinstance(last_error, NCBIRateLimitError):
            raise NCBIRateLimitError(
                f"NCBI rate limit exceeded after {attempts} attempts for {redact_url(url)}",
                url=redact_url(url),
            )
        if last_error:
            raise last_error
        raise NCBIRequestError(f"NCBI request failed after {attempts} attempts for {redact_url(url)}")

    def esearch(self, db: str, term: str, retmax: int = 10, retmode: str = "json") -> dict[str, Any]:
        """Perform an ESearch query against NCBI."""
        params = {"db": db, "term": term, "retmax": retmax, "retmode": retmode}
        raw = self.get("esearch.fcgi", params)
        if retmode == "json":
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise NCBIParseError(f"Failed to parse ESearch JSON response: {exc}", raw_snippet=raw) from exc
        return {"raw": raw}

    def efetch(
        self,
        db: str,
        id: str | list[str],
        rettype: str | None = None,
        retmode: str = "text",
    ) -> str:
        """Fetch records from NCBI via EFetch."""
        id_str = ",".join(id) if isinstance(id, (list, tuple)) else str(id)
        params: dict[str, Any] = {"db": db, "id": id_str, "retmode": retmode}
        if rettype:
            params["rettype"] = rettype
        return self.get("efetch.fcgi", params)

    def esummary(self, db: str, id: str | list[str], retmode: str = "json") -> dict[str, Any]:
        """Fetch summaries from NCBI via ESummary."""
        id_str = ",".join(id) if isinstance(id, (list, tuple)) else str(id)
        params = {"db": db, "id": id_str, "retmode": retmode}
        raw = self.get("esummary.fcgi", params)
        if retmode == "json":
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise NCBIParseError(f"Failed to parse ESummary JSON response: {exc}", raw_snippet=raw) from exc
        return {"raw": raw}
