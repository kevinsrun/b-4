from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from .errors import NCBIParseError


def _elem_text(elem: ET.Element | None) -> str:
    """Extract all text inside an XML element including nested tags."""
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def parse_pubmed_article_set(xml_text: str) -> list[dict[str, Any]]:
    """Parse a PubMed XML PubmedArticleSet into structured records.

    Does not fabricate missing fields; missing values remain None or empty list.
    """
    if not xml_text or not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NCBIParseError(f"Malformed PubMed XML: {exc}", raw_snippet=xml_text) from exc

    articles: list[dict[str, Any]] = []

    # Handle both <PubmedArticleSet> and standalone <PubmedArticle>
    article_elements = root.findall(".//PubmedArticle")
    if not article_elements and root.tag == "PubmedArticle":
        article_elements = [root]

    for article_elem in article_elements:
        citation = article_elem.find("MedlineCitation")
        pubmed_data = article_elem.find("PubmedData")

        # PMID
        pmid: str | None = None
        if citation is not None:
            pmid_elem = citation.find("PMID")
            if pmid_elem is not None and pmid_elem.text:
                pmid = pmid_elem.text.strip()
        if not pmid and pubmed_data is not None:
            for aid in pubmed_data.findall(".//ArticleId"):
                if aid.get("IdType") == "pubmed" and aid.text:
                    pmid = aid.text.strip()
                    break

        # Article details
        article_sub = citation.find("Article") if citation is not None else None

        # Title
        title = ""
        if article_sub is not None:
            title_elem = article_sub.find("ArticleTitle")
            title = _elem_text(title_elem)
        if title.endswith("."):
            title = title[:-1].strip()

        # Abstract
        abstract_parts: list[str] = []
        if article_sub is not None:
            abstract_elem = article_sub.find("Abstract")
            if abstract_elem is not None:
                for text_elem in abstract_elem.findall("AbstractText"):
                    t = _elem_text(text_elem)
                    label = text_elem.get("Label")
                    if label and t:
                        abstract_parts.append(f"{label}: {t}")
                    elif t:
                        abstract_parts.append(t)
        abstract = " ".join(abstract_parts) if abstract_parts else None

        # Journal
        journal: str | None = None
        year: int | None = None
        if article_sub is not None:
            journal_elem = article_sub.find("Journal")
            if journal_elem is not None:
                title_elem = journal_elem.find("Title")
                if title_elem is None:
                    title_elem = journal_elem.find("ISOAbbreviation")
                if title_elem is not None and title_elem.text:
                    journal = title_elem.text.strip()

                # Publication Date / Year
                pub_date = journal_elem.find(".//PubDate")
                if pub_date is not None:
                    year_elem = pub_date.find("Year")
                    if year_elem is not None and year_elem.text and year_elem.text.strip().isdigit():
                        year = int(year_elem.text.strip())
                    elif pub_date.find("MedlineDate") is not None:
                        mdate = pub_date.find("MedlineDate")
                        if mdate is not None and mdate.text:
                            m = re.search(r"\b(18|19|20|21)\d{2}\b", mdate.text)
                            if m:
                                year = int(m.group(0))

        # Check ArticleDate if Year is still missing
        if year is None and article_sub is not None:
            adate = article_sub.find(".//ArticleDate/Year")
            if adate is not None and adate.text and adate.text.strip().isdigit():
                year = int(adate.text.strip())

        # Authors
        authors: list[str] = []
        if article_sub is not None:
            author_list = article_sub.find("AuthorList")
            if author_list is not None:
                for author in author_list.findall("Author"):
                    last = author.find("LastName")
                    fore = author.find("ForeName")
                    initials = author.find("Initials")
                    collab = author.find("CollectiveName")
                    if last is not None and last.text:
                        last_str = last.text.strip()
                        if fore is not None and fore.text:
                            authors.append(f"{last_str} {fore.text.strip()}")
                        elif initials is not None and initials.text:
                            authors.append(f"{last_str} {initials.text.strip()}")
                        else:
                            authors.append(last_str)
                    elif collab is not None and collab.text:
                        authors.append(collab.text.strip())

        # DOI & PMCID
        doi: str | None = None
        pmcid: str | None = None

        if article_sub is not None:
            for eloc in article_sub.findall("ELocationID"):
                if eloc.get("EIdType") == "doi" and eloc.text:
                    doi = eloc.text.strip()

        if pubmed_data is not None:
            for aid in pubmed_data.findall(".//ArticleId"):
                id_type = aid.get("IdType")
                if id_type == "doi" and not doi and aid.text:
                    doi = aid.text.strip()
                elif id_type == "pmc" and aid.text:
                    raw_pmc = aid.text.strip()
                    pmcid = raw_pmc if raw_pmc.upper().startswith("PMC") else f"PMC{raw_pmc}"

        articles.append(
            {
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "journal": journal,
                "year": year,
                "authors": authors,
                "doi": doi,
                "pmcid": pmcid,
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                "provenance": "literature-derived",
            }
        )

    return articles


def parse_pmc_article(xml_text: str) -> dict[str, Any]:
    """Parse a PMC JATS XML document into structured metadata and sections."""
    if not xml_text or not xml_text.strip():
        raise NCBIParseError("Empty PMC XML response", raw_snippet=xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NCBIParseError(f"Malformed PMC XML: {exc}", raw_snippet=xml_text) from exc

    article_elem = root if root.tag == "article" else root.find(".//article")
    if article_elem is None:
        article_elem = root

    front = article_elem.find("front")
    body = article_elem.find("body")

    pmcid: str | None = None
    pmid: str | None = None
    doi: str | None = None
    title = ""
    abstract: str | None = None

    if front is not None:
        meta = front.find("article-meta")
        if meta is not None:
            for aid in meta.findall("article-id"):
                pub_id_type = aid.get("pub-id-type")
                if pub_id_type == "pmc" and aid.text:
                    raw_c = aid.text.strip()
                    pmcid = raw_c if raw_c.upper().startswith("PMC") else f"PMC{raw_c}"
                elif pub_id_type == "pmid" and aid.text:
                    pmid = aid.text.strip()
                elif pub_id_type == "doi" and aid.text:
                    doi = aid.text.strip()

            title_elem = meta.find(".//article-title")
            title = _elem_text(title_elem)
            if title.endswith("."):
                title = title[:-1].strip()

            abstract_elem = meta.find("abstract")
            if abstract_elem is not None:
                abstract = _elem_text(abstract_elem)

    # Extract sections from body
    sections: list[dict[str, str]] = []
    if body is not None:
        for sec in body.findall(".//sec"):
            sec_title_elem = sec.find("title")
            sec_title = _elem_text(sec_title_elem) or "Section"
            paragraphs = [_elem_text(p) for p in sec.findall("p") if _elem_text(p)]
            sec_text = "\n\n".join(paragraphs) if paragraphs else _elem_text(sec)
            if sec_text:
                sections.append({"title": sec_title, "text": sec_text})

    # Combined full text
    full_text_parts: list[str] = []
    if abstract:
        full_text_parts.append(f"Abstract\n{abstract}")
    for sec in sections:
        full_text_parts.append(f"{sec['title']}\n{sec['text']}")
    full_text = "\n\n".join(full_text_parts) if full_text_parts else _elem_text(body)

    return {
        "pmcid": pmcid,
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "sections": sections,
        "full_text": full_text,
        "raw_xml": xml_text,
        "provenance": "literature-derived",
        "source_url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/" if pmcid else None,
    }


def parse_fasta_text(fasta_text: str, db: str = "protein") -> list[dict[str, Any]]:
    """Parse FASTA text into structured sequence records."""
    records: list[dict[str, Any]] = []
    current_header: str | None = None
    current_lines: list[str] = []

    for line in fasta_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_header is not None:
                seq = "".join(current_lines).upper()
                acc = current_header.split()[0] if current_header else "unknown"
                records.append(
                    {
                        "accession": acc,
                        "header": current_header,
                        "sequence": seq,
                        "source_database": db,
                    }
                )
                current_lines = []
            current_header = line[1:].strip()
        else:
            current_lines.append(line)

    if current_header is not None:
        seq = "".join(current_lines).upper()
        acc = current_header.split()[0] if current_header else "unknown"
        records.append(
            {
                "accession": acc,
                "header": current_header,
                "sequence": seq,
                "source_database": db,
            }
        )

    return records
