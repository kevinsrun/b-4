from __future__ import annotations

from bacteriocin_lab.agents.candidate.agent import CandidateGenerationAgent
from bacteriocin_lab.agents.candidate.schema import CandidateRequest
from bacteriocin_lab.agents.candidate.verification import (
    MATCH_CONTAINED,
    MATCH_EXACT,
    MATCH_MATURE_SUFFIX,
    MATCH_MISMATCH,
    MATCH_UNAVAILABLE,
    MATCH_WRONG_RECORD,
    compare_sequences,
    verify_candidate,
    verify_candidates,
)

NISIN_MATURE = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
NISIN_LEADER = "MSTKDFNLDLVSVSKKDSGASPR"
NISIN_PRECURSOR = NISIN_LEADER + NISIN_MATURE


def record(name: str, sequence: str | None, accession: str | None) -> dict:
    return {"name": name, "sequence": sequence, "accession": accession}


def test_exact_match_verifies() -> None:
    result = verify_candidate(
        record("nisin A", NISIN_MATURE, "P13068"),
        fetch_reference=lambda _: NISIN_MATURE,
    )
    assert result["match"] == MATCH_EXACT
    assert result["sequence_verified"] is True
    assert result["provenance"] == "database-derived"
    # A verified sequence is never evidence that the peptide works.
    assert result["evidence_of_activity"] is False


def test_mature_peptide_is_a_suffix_of_its_precursor_and_still_verifies() -> None:
    """UniProt stores the precursor; the seed file stores the mature peptide."""
    result = verify_candidate(
        record("nisin A", NISIN_MATURE, "P13068"),
        fetch_reference=lambda _: NISIN_PRECURSOR,
    )
    assert result["match"] == MATCH_MATURE_SUFFIX
    assert result["sequence_verified"] is True
    assert "leader peptide" in " ".join(result["notes"])


def test_single_substituted_residue_is_a_mismatch() -> None:
    """The failure this pass exists to catch, and the one BLAST would smooth over."""
    corrupted = "A" + NISIN_MATURE[1:]
    result = verify_candidate(
        record("nisin A", corrupted, "P13068"),
        fetch_reference=lambda _: NISIN_PRECURSOR,
    )
    assert result["match"] == MATCH_MISMATCH
    assert result["sequence_verified"] is False


def test_fetch_failure_is_not_reported_as_a_mismatch() -> None:
    result = verify_candidate(
        record("nisin A", NISIN_MATURE, "P13068"),
        fetch_reference=lambda _: None,
    )
    assert result["match"] == MATCH_UNAVAILABLE
    assert result["sequence_verified"] is False
    assert "not a mismatch" in " ".join(result["notes"])


def test_internal_substring_is_flagged_rather_than_accepted() -> None:
    result = verify_candidate(
        record("fragment", NISIN_MATURE, "P13068"),
        fetch_reference=lambda _: NISIN_PRECURSOR + "GGGG",
    )
    assert result["match"] == MATCH_CONTAINED
    assert result["sequence_verified"] is False


def test_blast_annotation_is_attached_but_never_verifies_a_sequence() -> None:
    """A 100% BLAST hit does not substitute for the exact comparison."""
    result = verify_candidate(
        record("variant", NISIN_MATURE, None),
        blast=lambda _: {"novelty": "low", "max_identity_percent": 100.0},
    )
    assert result["novelty_annotation"]["novelty"] == "low"
    assert result["match"] == MATCH_UNAVAILABLE
    assert result["sequence_verified"] is False


def test_blast_failure_is_recorded_not_raised() -> None:
    def failing(_: str) -> dict:
        raise RuntimeError("remote failure")

    result = verify_candidate(record("variant", NISIN_MATURE, None), blast=failing)
    assert result["novelty_annotation"]["novelty"] == "unknown"
    assert "remote failure" in result["novelty_annotation"]["reason"]


def test_batch_counts_and_warnings_separate_unchecked_from_mismatched() -> None:
    result = verify_candidates(
        [
            record("ok", NISIN_MATURE, "P13068"),
            record("bad", "AAAAAAAAAA", "P29430"),
            record("unchecked", NISIN_MATURE, None),
        ],
        fetch_reference=lambda _: NISIN_PRECURSOR,
    )
    assert result["n_records"] == 3
    assert result["n_verified"] == 1
    assert result["match_counts"][MATCH_MATURE_SUFFIX] == 1
    assert result["match_counts"][MATCH_MISMATCH] == 1
    assert result["match_counts"][MATCH_UNAVAILABLE] == 1
    joined = " ".join(result["warnings"])
    assert "not evidence that the peptide is active" in joined
    assert "Unchecked is not the same as mismatched" in joined


def test_compare_sequences_is_case_and_whitespace_insensitive() -> None:
    assert compare_sequences(" itsislctpgck ", "ITSISLCTPGCK") == MATCH_EXACT


def test_verification_does_not_run_inside_generate_candidates() -> None:
    """The scoring path must stay deterministic and offline."""
    calls: list[str] = []

    def spy(accession: str) -> str | None:
        calls.append(accession)
        return NISIN_PRECURSOR

    agent = CandidateGenerationAgent()
    request = CandidateRequest.model_validate(
        {"target": {"organism": "Staphylococcus aureus", "gram": "positive"}, "max_candidates": 3}
    )
    first = agent.run(request)
    second = agent.run(request)
    assert calls == []
    assert [c.candidate_id for c in first.candidates] == [c.candidate_id for c in second.candidates]

    # The explicit pass does reach the reference service, and leaves ranking alone.
    verified = agent.verify_candidate_sequences(fetch_reference=spy)
    assert calls, "verify_candidate_sequences should consult the primary database"
    assert verified["n_records"] >= 6
    assert verified["knowledge_source"]


def test_accession_pointing_at_an_unrelated_protein_is_its_own_verdict() -> None:
    """A wrong accession and a wrong residue need different fixes, so they differ here."""
    result = verify_candidate(
        record("enterocin A", "TTHSGKYYGNGVYCTKNKCTVDWAKATTCIAGMSIGGFLGGAIPGKC", "P0C988"),
        fetch_reference=lambda _: {
            "sequence": "MQQ" + "A" * 1447,
            "description": "sp|P0C988|RPB1_ASFWA DNA-directed RNA polymerase RPB1 homolog "
            "OS=African swine fever virus",
        },
    )
    assert result["match"] == MATCH_WRONG_RECORD
    assert result["sequence_verified"] is False
    assert "accession error rather than evidence against the sequence" in " ".join(result["notes"])


def test_genuine_residue_conflict_stays_a_mismatch() -> None:
    """When the reference IS the right protein, a disagreement is about the sequence."""
    result = verify_candidate(
        record("nisin A", "A" + NISIN_MATURE[1:], "P13068"),
        fetch_reference=lambda _: {
            "sequence": NISIN_PRECURSOR,
            "description": "sp|P13068|NISA_LACLL Nisin A OS=Lactococcus lactis",
        },
    )
    assert result["match"] == MATCH_MISMATCH


def test_wrong_record_is_reported_separately_from_sequence_conflicts() -> None:
    result = verify_candidates(
        [record("enterocin A", NISIN_MATURE, "P0C988")],
        fetch_reference=lambda _: {
            "sequence": "A" * 1450,
            "description": "DNA-directed RNA polymerase RPB1 homolog OS=African swine fever virus",
        },
    )
    joined = " ".join(result["warnings"])
    assert "resolves to an unrelated protein" in joined
    assert "enterocin A -> P0C988" in joined
    assert result["n_verified"] == 0
