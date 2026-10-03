from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import SourceDocument, SourceReference


class LiteratureSource(Protocol):
    name: str

    def search(self, query: str, limit: int, timeout_seconds: float) -> list[SourceDocument]: ...


JsonTransport = Callable[[str, float], dict[str, Any]]


def _default_json_transport(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "B4-Literature-Agent/0.1"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed HTTPS endpoint
        return json.load(response)


class EuropePmcSource:
    """Read-only Europe PMC REST adapter returning metadata and abstracts."""

    name = "europe_pmc"
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, transport: JsonTransport | None = None) -> None:
        self._transport = transport or _default_json_transport

    def search(self, query: str, limit: int, timeout_seconds: float) -> list[SourceDocument]:
        params = urlencode({"query": query, "format": "json", "resultType": "core", "pageSize": limit})
        payload = self._transport(f"{self.endpoint}?{params}", timeout_seconds)
        results = payload.get("resultList", {}).get("result", [])
        documents: list[SourceDocument] = []
        for item in results:
            abstract = item.get("abstractText")
            title = item.get("title")
            if not isinstance(abstract, str) or not abstract.strip() or not isinstance(title, str) or not title.strip():
                continue
            doi = item.get("doi")
            pmid = item.get("pmid")
            source_id = f"doi:{doi.lower()}" if doi else f"pmid:{pmid}" if pmid else f"epmc:{item.get('id', title)}"
            url = f"https://europepmc.org/article/MED/{pmid}" if pmid else None
            authors = [part.strip() for part in str(item.get("authorString", "")).split(",") if part.strip()]
            year_raw = item.get("pubYear")
            year = int(year_raw) if str(year_raw).isdigit() else None
            documents.append(
                SourceDocument(
                    source=SourceReference(
                        source_id=source_id,
                        title=title.strip(),
                        doi_or_url=f"https://doi.org/{doi}" if doi else url,
                        year=year,
                        authors=authors,
                        journal=item.get("journalTitle"),
                    ),
                    text=abstract.strip(),
                    locator="abstract",
                )
            )
        return documents
