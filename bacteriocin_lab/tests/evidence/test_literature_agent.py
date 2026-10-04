from __future__ import annotations

from bacteriocin_lab.agents.evidence.agent import LiteratureEvidenceAgent
from bacteriocin_lab.agents.evidence.models import LiteratureQuery


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


def test_length_units_are_not_read_as_molar_concentrations() -> None:
    """A nanoparticle diameter in nm must never become a bacteriocin concentration in nM."""
    response = LiteratureEvidenceAgent().run(
        base_request(
            [
                document(
                    "paper-nm",
                    "Nisin-loaded silver nanoparticles with an average size of 87 nm were synthesized. "
                    "The MIC of nisin against Listeria monocytogenes ATCC 19115 was 2.5 mg/L, "
                    "measured in BHI broth with inhibition zones of 12 mm.",
                )
            ]
        )
    )
    assert len(response.evidence) == 1
    concentration = response.evidence[0].conditions.bacteriocin_concentration
    assert concentration is not None
    # 87 nm is a particle diameter and 12 mm a zone width; neither is a dose.
    assert concentration.original_unit not in {"nm", "mm", "um"}
    assert concentration.original_value == "2.5"


def test_measurement_without_an_identifiable_bacteriocin_is_not_emitted() -> None:
    """An antimicrobial measurement for a non-bacteriocin agent is not bacteriocin evidence."""
    request = base_request(
        [
            document(
                "paper-agnp",
                "The biosynthesized AgNPs exhibited potent broad-spectrum antimicrobial activity, "
                "notably with inhibition zones of 25.8 mm for Listeria monocytogenes.",
            )
        ]
    )
    request.pop("bacteriocin")
    response = LiteratureEvidenceAgent().run(request)
    assert response.evidence == []
    assert response.decision["status"] == "insufficient-evidence"


def test_variant_query_still_matches_the_base_name_in_the_source() -> None:
    """Querying 'nisin A' must not silently discard every abstract that says 'nisin'."""
    request = base_request(
        [
            document(
                "paper-base",
                "Nisin inhibited Listeria monocytogenes ATCC 19115 with a MIC of 2.5 mg/L "
                "in BHI broth at pH 6.5.",
            )
        ]
    )
    request["bacteriocin"] = "nisin A"
    response = LiteratureEvidenceAgent().run(request)
    assert len(response.evidence) == 1
    record = response.evidence[0]
    assert record.measurement.value == 2.5
    # The record states what the source says, and keeps the requested term as an alias
    # rather than asserting the variant.
    assert record.bacteriocin.name == "nisin"
    assert "nisin A" in record.bacteriocin.aliases


def test_unattributable_mic_range_is_flagged_not_guessed() -> None:
    """An MIC given as a range for two agents is flagged, never split between them."""
    response = LiteratureEvidenceAgent().run(
        base_request(
            [
                document(
                    "paper-range",
                    "Nisin and oxacillin were tested against Listeria monocytogenes ATCC 19115. "
                    "MIC values for oxacillin and nisin ranged 4-8 ug/mL and 64-128 ug/mL, respectively.",
                )
            ]
        )
    )
    assert response.evidence == []
    assert any("could not attribute" in warning for warning in response.warnings)
    assert any("paper-range" in warning for warning in response.warnings)
