from __future__ import annotations

from ..models import SourceDocument, SourceReference
from .client import NcbiClient
from .pubmed import fetch_pubmed_records, search_pubmed


class NcbiSource:
    """Read-only NCBI PubMed adapter returning SourceDocument objects."""

    name = "ncbi"

    def __init__(self, client: NcbiClient | None = None) -> None:
        self.client = client or NcbiClient()

    def search(self, query: str, limit: int, timeout_seconds: float) -> list[SourceDocument]:
        # Use timeout_seconds from caller if specified
        old_timeout = self.client.config.timeout_seconds
        try:
            if timeout_seconds and timeout_seconds > 0:
                self.client.config.timeout_seconds = timeout_seconds
            search_res = search_pubmed(query, limit=limit, client=self.client)
            pmids = search_res.get("pmids", [])
            if not pmids:
                return []

            records = fetch_pubmed_records(pmids, client=self.client)
            documents: list[SourceDocument] = []
            for r in records:
                abstract = r.get("abstract")
                title = r.get("title")
                if not isinstance(abstract, str) or not abstract.strip():
                    continue
                if not isinstance(title, str) or not title.strip():
                    continue

                pmid = r.get("pmid")
                doi = r.get("doi")
                source_id = f"pmid:{pmid}" if pmid else (f"doi:{doi}" if doi else f"ncbi:{title.strip()}")
                doi_or_url = (
                    f"https://doi.org/{doi}"
                    if doi
                    else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None)
                )

                documents.append(
                    SourceDocument(
                        source=SourceReference(
                            source_id=source_id,
                            title=title.strip(),
                            doi_or_url=doi_or_url,
                            year=r.get("year"),
                            authors=r.get("authors", []),
                            journal=r.get("journal"),
                            source_type="journal-article",
                        ),
                        text=abstract.strip(),
                        locator="abstract",
                    )
                )
            return documents
        finally:
            self.client.config.timeout_seconds = old_timeout
