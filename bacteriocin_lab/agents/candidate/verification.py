"""Offline sequence verification for candidate records.

Nothing here is called from :meth:`CandidateGenerationAgent.run`, and that is
deliberate. ``run`` advertises that identical arguments produce identical
output, and the research state is an append-only hash-chained log that is
replayed by ``get_state_at_iteration``. A live query against a database that
changes between runs would make both claims false. Verification is therefore an
explicit, separate pass whose results are recorded as provenance, never folded
into a score.

Two different questions are asked of two different services, because they are
not interchangeable:

* **Is this sequence the one the accession names?** Answered by fetching the
  primary record and comparing strings. This is exact. A single substituted
  residue silently changes mass, net charge, GRAVY and every score derived from
  them, and that is the failure this pass exists to catch.

* **Is this sequence already a known protein?** Answered by BLAST, which is a
  heuristic local-alignment search. It is the right tool for a generated
  variant that has no accession, and the wrong tool for the question above: one
  wrong residue in a 34-mer still returns ~97% identity at an e-value around
  1e-14, which does not look like an error.

Seed records store the **mature** peptide while UniProt entries usually cover
the full precursor including the leader peptide that is cleaved during export.
A mature sequence that is a suffix of the reference is therefore the expected
result, not a conflict, and is reported as its own verdict.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

UNIPROT_FASTA_URL = "https://rest.uniprot.org/uniprotkb/{accession}.fasta"

#: Verdicts, in decreasing order of confidence that the stored sequence is right.
MATCH_EXACT = "exact"
MATCH_MATURE_SUFFIX = "mature_suffix"
MATCH_CONTAINED = "contained"
MATCH_MISMATCH = "mismatch"
MATCH_WRONG_RECORD = "wrong_record"
MATCH_UNAVAILABLE = "unavailable"

#: Only these verdicts justify flipping ``sequence_verified`` to true.
VERIFYING_MATCHES = frozenset({MATCH_EXACT, MATCH_MATURE_SUFFIX})


def fetch_uniprot_sequence(
    accession: str, client: Any | None = None, timeout: float = 30.0
) -> dict[str, str] | None:
    """Fetch one record from UniProt as ``{"sequence", "description"}``, or ``None``.

    A network failure is not a mismatch, and the caller is expected to keep the
    two apart.
    """
    try:
        import httpx
    except ModuleNotFoundError:  # pragma: no cover - optional 'verify' extra
        return None

    owns_client = client is None
    http = client or httpx.Client()
    try:
        response = http.get(UNIPROT_FASTA_URL.format(accession=accession), timeout=timeout)
        response.raise_for_status()
        body = response.text
    except Exception:  # network boundary; failure is reported, not raised
        return None
    finally:
        if owns_client:
            with _suppress():
                http.close()

    description = ""
    residues: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            description = description or line[1:]
            continue
        residues.append(line)
    sequence = "".join(residues).upper()
    if not sequence:
        return None
    return {"sequence": sequence, "description": description}


class _suppress:
    """Tiny context manager; closing a client must never fail a verification."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True


def compare_sequences(query: str | None, reference: str | None) -> str:
    """Classify a stored sequence against its primary-database reference."""
    if not query or not reference:
        return MATCH_UNAVAILABLE
    query = query.strip().upper()
    reference = reference.strip().upper()
    if query == reference:
        return MATCH_EXACT
    if reference.endswith(query):
        return MATCH_MATURE_SUFFIX
    if query in reference:
        return MATCH_CONTAINED
    return MATCH_MISMATCH


def _notes_for(match: str, query: str | None, reference: str | None) -> list[str]:
    if match == MATCH_EXACT:
        return ["Stored sequence equals the primary record exactly."]
    if match == MATCH_MATURE_SUFFIX:
        return [
            "Stored sequence is a suffix of the primary record, which is the expected "
            "relationship between a mature peptide and its precursor; the leader peptide "
            f"accounts for the leading {len(reference or '') - len(query or '')} residue(s).",
        ]
    if match == MATCH_CONTAINED:
        return [
            "Stored sequence occurs inside the primary record but not at its C-terminus. "
            "That is not the ordinary precursor relationship and needs a human check.",
        ]
    if match == MATCH_MISMATCH:
        return [
            "Stored sequence is not a substring of the primary record. Every feature "
            "derived from it -- mass, net charge, GRAVY -- is suspect until resolved.",
        ]
    if match == MATCH_WRONG_RECORD:
        return [
            "The accession resolves to an unrelated protein, so this is an accession "
            "error rather than evidence against the sequence. The sequence itself stays "
            "unverified: find the right accession before trusting it.",
        ]
    return ["No reference sequence was retrieved, so nothing was verified. This is not a mismatch."]


def _looks_like_a_different_protein(name: str | None, description: str | None) -> bool:
    """True when a reference description does not mention the record's name.

    A wrong accession and a wrong residue need different fixes, and the length
    of the reference is often the giveaway -- a 47-residue bacteriocin whose
    accession returns 1450 residues is not a transcription slip. Comparing the
    name against the record's own description separates them without guessing.
    """
    if not name or not description:
        return False
    head = name.split()[0].casefold()
    if len(head) < 4:
        return False
    return head not in description.casefold()


def verify_candidate(
    record: Any,
    fetch_reference: Callable[[str], str | None] | None = None,
    blast: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify one record's sequence and, optionally, annotate its novelty.

    ``record`` may be any object or mapping exposing ``name``, ``sequence`` and
    ``accession``. ``fetch_reference`` and ``blast`` are injected so this is
    testable without a network, and so the caller decides which services are
    contacted.
    """
    if isinstance(record, dict):
        get = record.get
    else:

        def get(key: str, default: Any = None) -> Any:
            return getattr(record, key, default)

    name = get("name")
    sequence = get("sequence")
    accession = get("accession")

    reference = None
    description = None
    if accession and sequence:
        fetcher = fetch_reference or fetch_uniprot_sequence
        fetched = fetcher(accession)
        if isinstance(fetched, dict):
            reference = fetched.get("sequence")
            description = fetched.get("description")
        else:
            reference = fetched

    match = compare_sequences(sequence, reference) if accession else MATCH_UNAVAILABLE
    if match == MATCH_MISMATCH and _looks_like_a_different_protein(name, description):
        match = MATCH_WRONG_RECORD
    notes = _notes_for(match, sequence, reference) if accession else [
        "Record carries no accession, so no primary record could be compared. "
        "BLAST can say whether the sequence resembles a known protein, but not "
        "whether it is the sequence this record claims."
    ]

    verification: dict[str, Any] = {
        "name": name,
        "accession": accession,
        "query_length": len(sequence) if sequence else None,
        "reference_length": len(reference) if reference else None,
        "reference_description": description,
        "match": match,
        "sequence_verified": match in VERIFYING_MATCHES,
        "notes": notes,
        "novelty_annotation": None,
        "provenance": "database-derived",
        "evidence_of_activity": False,
    }

    if blast is not None and sequence:
        try:
            verification["novelty_annotation"] = blast(sequence)
        except Exception as exc:  # a failed search is reported, not raised
            verification["novelty_annotation"] = {
                "novelty": "unknown",
                "reason": f"BLAST search failed: {type(exc).__name__}: {exc}",
                "provenance": "database-derived",
            }
    return verification


def verify_candidates(
    records: list[Any],
    fetch_reference: Callable[[str], str | None] | None = None,
    blast: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify many records and summarise what the pass established.

    The returned ``warnings`` restate the limits of what was checked, so a
    caller cannot read a verified sequence as a verified candidate.
    """
    verifications = [verify_candidate(record, fetch_reference, blast) for record in records]

    counts: dict[str, int] = {}
    for item in verifications:
        counts[item["match"]] = counts.get(item["match"], 0) + 1

    warnings: list[str] = [
        "SEQUENCE PROVENANCE ONLY. A verified sequence means the stored residues match a "
        "primary database record. It is not evidence that the peptide is active against "
        "any target, and it does not change any candidate's rank.",
    ]
    unresolved = counts.get(MATCH_MISMATCH, 0) + counts.get(MATCH_CONTAINED, 0)
    if unresolved:
        warnings.append(
            f"{unresolved} record(s) disagree with their primary record. Features computed "
            "from those sequences are unreliable; resolve before using their scores."
        )
    if counts.get(MATCH_WRONG_RECORD):
        wrong = [
            f"{item['name']} -> {item['accession']}"
            for item in verifications
            if item["match"] == MATCH_WRONG_RECORD
        ]
        warnings.append(
            f"{counts[MATCH_WRONG_RECORD]} record(s) cite an accession that resolves to an "
            f"unrelated protein ({'; '.join(wrong)}). That is a citation error, not a verdict "
            "on the sequence, and those sequences remain unverified either way."
        )
    if counts.get(MATCH_UNAVAILABLE):
        warnings.append(
            f"{counts[MATCH_UNAVAILABLE]} record(s) could not be checked (no accession, or the "
            "reference could not be retrieved). Unchecked is not the same as mismatched."
        )
    if blast is None:
        warnings.append(
            "No BLAST annotation was requested, so novelty against known protein space is "
            "unassessed; the agent's novelty score remains pool-relative."
        )

    return {
        "verifications": verifications,
        "match_counts": counts,
        "n_verified": sum(1 for item in verifications if item["sequence_verified"]),
        "n_records": len(verifications),
        "warnings": warnings,
        "provenance": "database-derived",
    }
