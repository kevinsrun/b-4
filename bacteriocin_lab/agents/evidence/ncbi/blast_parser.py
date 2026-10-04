from __future__ import annotations

import contextlib
import re
import xml.etree.ElementTree as ET
from typing import Any

from .errors import BlastParseError, BlastSubmissionError


def parse_blast_submission(response_text: str) -> dict[str, Any]:
    """Parse RID and RTOE from official NCBI BLAST submission output.

    NCBI returns a comment block formatted like:
    <!-- QBlastInfoBegin
        RID = Z12345ABC014
        RTOE = 30
    QBlastInfoEnd -->

    Raises:
        BlastSubmissionError: If RID cannot be found or extracted.
    """
    rid_match = re.search(r"\bRID\s*=\s*([A-Za-z0-9_-]+)", response_text)
    rtoe_match = re.search(r"\bRTOE\s*=\s*(\d+)", response_text)

    if not rid_match:
        error_match = re.search(
            r"(?:Message ID#\d+|ERROR|Error:?)\s*(.*?)(?:\n|<|$)",
            response_text,
            re.IGNORECASE,
        )
        detail = error_match.group(0).strip() if error_match else response_text[:200].strip()
        raise BlastSubmissionError(
            f"Failed to obtain RID from BLAST submission response: {detail}",
        )

    rid = rid_match.group(1).strip()
    rtoe = int(rtoe_match.group(1)) if rtoe_match else 5
    return {"rid": rid, "rtoe": rtoe}


def parse_blast_status(response_text: str) -> dict[str, Any]:
    """Parse status and hit presence from NCBI SearchInfo response.

    Returns dict containing:
        - status: "WAITING" | "READY" | "FAILED" | "UNKNOWN"
        - has_hits: bool | None
    """
    status_match = re.search(r"\bStatus\s*=\s*([A-Za-z]+)", response_text, re.IGNORECASE)
    status = status_match.group(1).upper() if status_match else "UNKNOWN"

    hits_match = re.search(r"\bThereAreHits\s*=\s*(yes|no)", response_text, re.IGNORECASE)
    has_hits: bool | None = None
    if hits_match:
        has_hits = hits_match.group(1).lower() == "yes"

    return {"status": status, "has_hits": has_hits}


def parse_blast_xml(
    xml_text: str,
    candidate_id: str | None = None,
    rid: str | None = None,
) -> dict[str, Any]:
    """Parse standard NCBI BLAST XML output (<BlastOutput>) into a structured result.

    Returns structured record with hits containing rank, accession, title,
    organism, identity_percent, positive_percent, alignment_length, e_value,
    bit_score, query_start, query_end, subject_start, subject_end.
    Provenance is strictly 'database-derived'.
    """
    if not xml_text or not xml_text.strip():
        raise BlastParseError("Empty XML response received from BLAST")

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise BlastParseError(f"Failed to parse BLAST XML output: {exc}", raw_snippet=xml_text) from exc

    if not root.tag.endswith("BlastOutput"):
        raise BlastParseError(
            f"Expected root element BlastOutput, found {root.tag}",
            raw_snippet=xml_text,
        )

    program = root.findtext("BlastOutput_program", "blastp")
    database = root.findtext("BlastOutput_db", "nr")
    query_id = root.findtext("BlastOutput_query-ID", "")
    query_def = root.findtext("BlastOutput_query-def", "")
    query_len_raw = root.findtext("BlastOutput_query-len", "0")
    try:
        query_length = int(query_len_raw)
    except ValueError:
        query_length = 0

    hits: list[dict[str, Any]] = []

    iterations = root.findall(".//Iteration")
    for iteration in iterations:
        iter_query_len = iteration.findtext("Iteration_query-len")
        if iter_query_len and query_length == 0:
            with contextlib.suppress(ValueError):
                query_length = int(iter_query_len)

        iteration_hits = iteration.findall(".//Hit")
        for rank, hit_elem in enumerate(iteration_hits, start=1):
            hit_id = hit_elem.findtext("Hit_id", "")
            hit_def = hit_elem.findtext("Hit_def", "")
            hit_acc = hit_elem.findtext("Hit_accession", "")
            if not hit_acc and hit_id:
                parts = hit_id.split("|")
                hit_acc = parts[-2] if len(parts) >= 2 else hit_id

            org_match = re.search(r"\[(.*?)\]", hit_def)
            organism = org_match.group(1).strip() if org_match else None

            hsp = hit_elem.find(".//Hsp")
            if hsp is not None:
                bit_score_str = hsp.findtext("Hsp_bit-score", "0.0")
                evalue_str = hsp.findtext("Hsp_evalue", "1.0")
                identity_str = hsp.findtext("Hsp_identity", "0")
                positive_str = hsp.findtext("Hsp_positive", "0")
                align_len_str = hsp.findtext("Hsp_align-len", "0")
                q_from_str = hsp.findtext("Hsp_query-from", "0")
                q_to_str = hsp.findtext("Hsp_query-to", "0")
                h_from_str = hsp.findtext("Hsp_hit-from", "0")
                h_to_str = hsp.findtext("Hsp_hit-to", "0")

                try:
                    bit_score = round(float(bit_score_str), 2)
                    e_value = float(evalue_str)
                    identity = int(identity_str)
                    positive = int(positive_str)
                    align_len = int(align_len_str)
                    query_start = int(q_from_str)
                    query_end = int(q_to_str)
                    subject_start = int(h_from_str)
                    subject_end = int(h_to_str)
                except ValueError:
                    bit_score = 0.0
                    e_value = 1.0
                    identity = 0
                    positive = 0
                    align_len = 0
                    query_start = 0
                    query_end = 0
                    subject_start = 0
                    subject_end = 0

                ident_pct = round((identity / align_len * 100.0), 2) if align_len > 0 else 0.0
                pos_pct = round((positive / align_len * 100.0), 2) if align_len > 0 else 0.0
            else:
                bit_score = 0.0
                e_value = 1.0
                ident_pct = 0.0
                pos_pct = 0.0
                align_len = 0
                query_start = 0
                query_end = 0
                subject_start = 0
                subject_end = 0

            hits.append(
                {
                    "rank": rank,
                    "accession": hit_acc,
                    "title": hit_def or hit_id,
                    "organism": organism,
                    "identity_percent": ident_pct,
                    "positive_percent": pos_pct,
                    "alignment_length": align_len,
                    "e_value": e_value,
                    "bit_score": bit_score,
                    "query_start": query_start,
                    "query_end": query_end,
                    "subject_start": subject_start,
                    "subject_end": subject_end,
                }
            )

    return {
        "query_id": query_id or query_def or "query",
        "candidate_id": candidate_id,
        "program": program,
        "database": database,
        "rid": rid or "",
        "status": "complete",
        "query_length": query_length,
        "hits": hits,
        "provenance": "database-derived",
        "source": "ncbi_blast",
    }
