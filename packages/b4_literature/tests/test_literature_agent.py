from __future__ import annotations

from b4_literature.agent import LiteratureEvidenceAgent
from b4_literature.models import LiteratureQuery


def document(source_id: str, text: str) -> dict:
    return {
        "source": {
            "source_id": source_id,
            "title": f"Study {source_id}",
            "doi_or_url": f"https://doi.org/10.1000/{source_id}",
            "year": 2025,
        },
        "text": text,
        "locator": "Results, paragraph 2",
    }


def base_request(documents: list[dict]) -> dict:
    return {
        "question": "What is the activity of nisin against Listeria monocytogenes?",
        "bacteriocin": "nisin",
        "target_organism": "Listeria monocytogenes",
        "target_strain": "ATCC 19115",
        "source_documents": documents,
    }


def test_extracts_conditions_quantitative_measurement_and_provenance() -> None:
    response = LiteratureEvidenceAgent().run(
        base_request(
            [
                document(
                    "paper-1",
                    "In a broth microdilution assay, 10^6 CFU/mL Listeria monocytogenes ATCC 19115 in BHI broth "
                    "was exposed to nisin at 2.5 mg/L for 90 minutes at pH 6.5 and 37 °C. "
                    "The MIC of nisin was 2.5 mg/L.",
                )
            ]
        )
    )
    assert response.decision["candidate_decision"] == "not-performed"
    assert len(response.evidence) == 1
    record = response.evidence[0]
    assert record.evidence_type == "literature-derived"
    assert record.measurement.type == "minimum_inhibitory_concentration"
    assert record.measurement.value == 2.5
    assert record.conditions.bacteriocin_concentration.normalized_unit == "µg/mL"
    assert record.conditions.target_cell_density.value == 1_000_000
    assert record.conditions.ph.value == 6.5
    assert record.conditions.temperature_c.normalized_value == 37
    assert record.conditions.incubation_time.normalized_value == 1.5
    assert record.conditions.medium == "BHI broth"
    assert record.conditions.assay_type == "broth_microdilution"
    assert record.provenance.locator == "Results, paragraph 2"
    assert "producer_cell_density" in record.missing_variables


def test_deterministic_ids_and_duplicate_source_suppression() -> None:
    payload = base_request(
        [document("same", "Nisin showed antimicrobial activity."), document("same", "Nisin showed no activity.")]
    )
    first = LiteratureEvidenceAgent().run(payload)
    second = LiteratureEvidenceAgent().run(payload)
    assert first.query_id == second.query_id
    assert [item.evidence_id for item in first.evidence] == [item.evidence_id for item in second.evidence]
    assert first.decision["documents_considered"] == 1


def test_contradictions_are_preserved() -> None:
    response = LiteratureEvidenceAgent().run(
        base_request(
            [
                document("positive", "Nisin inhibited Listeria monocytogenes in vitro."),
                document("negative", "Nisin showed no activity against Listeria monocytogenes."),
            ]
        )
    )
    assert len(response.evidence) == 2
    assert len(response.contradictions) == 1
    assert response.contradictions[0].unresolved is True
    assert len(response.contradictions[0].evidence_ids) == 2


def test_retrieval_failure_is_explicit_and_supplied_documents_still_work() -> None:
    class BrokenSource:
        name = "europe_pmc"

        def search(self, query: str, limit: int, timeout_seconds: float):
            raise TimeoutError("source timed out")

    payload = base_request([document("local", "Nisin inhibited Listeria monocytogenes.")])
    payload["retrieval"] = {"enabled": True, "sources": ["europe_pmc"], "max_results": 3}
    response = LiteratureEvidenceAgent({"europe_pmc": BrokenSource()}).run(payload)
    assert len(response.evidence) == 1
    assert response.warnings == ["europe_pmc retrieval failed: TimeoutError: source timed out"]
    assert response.confidence < response.evidence[0].confidence


def test_no_claim_is_invented_when_no_measurement_or_activity_language_exists() -> None:
    response = LiteratureEvidenceAgent().run(
        base_request([document("metadata", "Nisin is a lantibiotic discovered in 1928.")])
    )
    assert response.evidence == []
    assert response.confidence == 0
    assert response.decision["status"] == "insufficient-evidence"
    assert "no supported" in response.warnings[0]


def test_unrelated_resistance_language_is_not_bound_to_requested_target() -> None:
    response = LiteratureEvidenceAgent().run(
        base_request(
            [
                document(
                    "unrelated-resistance",
                    "Antimicrobial activity was assessed against methicillin-resistant Staphylococcus aureus "
                    "and vancomycin-resistant Enterococcus faecium.",
                )
            ]
        )
    )
    assert response.evidence == []
    assert response.decision["status"] == "insufficient-evidence"


def test_measurement_for_comparator_peptide_is_not_attributed_to_requested_bacteriocin() -> None:
    response = LiteratureEvidenceAgent().run(
        base_request(
            [
                document(
                    "comparator",
                    "The peptides were tested against Listeria monocytogenes. Their MICs were compared with nisin Z, "
                    "and the most potent peptide, Pep-1, exhibited an MIC of 7.5 µM.",
                )
            ]
        )
    )
    assert response.evidence == []


def test_malformed_input_fails_validation() -> None:
    try:
        LiteratureQuery.model_validate({"question": "x", "unexpected": True})
    except Exception as exc:
        assert "unexpected" in str(exc)
    else:
        raise AssertionError("malformed input should fail")
