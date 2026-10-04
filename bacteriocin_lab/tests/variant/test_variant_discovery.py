from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bacteriocin_lab.agents.candidate import CandidateGenerationAgent
from bacteriocin_lab.agents.candidate.schema import CandidateProposal
from bacteriocin_lab.agents.variant import (
    AlignmentError,
    AlignmentExecutionError,
    AlignmentTimeoutError,
    AlignmentUnavailableError,
    ClustalOmegaBackend,
    FixtureAlignmentBackend,
    MafftBackend,
    VariantBudgetExceededError,
    VariantDiscoveryAgent,
    VariantDiscoveryResult,
    VariantRecord,
    annotate_region,
    discover_variants,
    extract_variants_from_alignment,
    parse_fasta_alignment,
    verify_cds_translation,
)
from tools.launchers.candidates import build_server


# ---------------------------------------------------------------------------
# Test 1: Alignment output parser parses FASTA alignment and preserves gaps
# ---------------------------------------------------------------------------
def test_1_alignment_parser_preserves_gaps() -> None:
    fasta_text = """\
>ref
MK-TF-Y
>hom1
MKATFGY
>hom2
MK-TF--
"""
    parsed = parse_fasta_alignment(fasta_text)
    assert len(parsed) == 3
    assert parsed["ref"] == "MK-TF-Y"
    assert parsed["hom1"] == "MKATFGY"
    assert parsed["hom2"] == "MK-TF--"
    assert len(parsed["ref"]) == len(parsed["hom1"]) == len(parsed["hom2"]) == 7


# ---------------------------------------------------------------------------
# Test 2: Alignment parser rejects mismatched sequence lengths
# ---------------------------------------------------------------------------
def test_2_alignment_parser_rejects_mismatched_lengths() -> None:
    fasta_text = """\
>ref
MKTFY
>hom1
MKATFGY
"""
    with pytest.raises(AlignmentError, match="inconsistent lengths"):
        parse_fasta_alignment(fasta_text)


# ---------------------------------------------------------------------------
# Test 3: Substitution variant extraction
# ---------------------------------------------------------------------------
def test_3_substitution_variant_extraction() -> None:
    aligned = {
        "ref": "MKTVFLG",
        "hom1": "MKTVYLG",
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
    )
    assert len(variants) == 1
    v = variants[0]
    assert v.protein_position == 5
    assert v.reference_aa == "F"
    assert v.alternate_aa == "Y"
    assert v.protein_change == "F5Y"
    assert v.variant_type == "missense"
    assert v.observed_count == 1
    assert v.homolog_count == 1
    assert v.frequency == 1.0


# ---------------------------------------------------------------------------
# Test 4: Multiple substitutions in single homolog separated cleanly
# ---------------------------------------------------------------------------
def test_4_multiple_substitutions_in_single_homolog() -> None:
    aligned = {
        "ref": "MKTVFLGY",
        "hom1": "AKTVFLGF",
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
    )
    assert len(variants) == 2
    changes = {v.protein_change for v in variants}
    assert changes == {"M1A", "Y8F"}
    positions = {v.protein_position for v in variants}
    assert positions == {1, 8}


# ---------------------------------------------------------------------------
# Test 5: Insertion extraction and ungapped reference coordinate anchoring
# ---------------------------------------------------------------------------
def test_5_insertion_extraction_and_coordinates() -> None:
    # Reference has ungapped length 7: M=1, K=2, T=3, V=4, F=5, L=6, G=7
    # Homolog has insertions QQ after position 5 (F)
    aligned = {
        "ref": "MKTVF--LG",
        "hom1": "MKTVFQQLG",
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
    )
    assert len(variants) == 1
    v = variants[0]
    assert v.variant_type == "insertion"
    assert v.protein_position == 5
    assert v.alternate_aa == "QQ"
    assert v.protein_change == "ins5QQ"


# ---------------------------------------------------------------------------
# Test 6: Deletion extraction and ungapped reference coordinate anchoring
# ---------------------------------------------------------------------------
def test_6_deletion_extraction_and_coordinates() -> None:
    # Ref: M=1, K=2, T=3, V=4, F=5, L=6, G=7, K=8, L=9
    # Homolog deletes L6 and G7
    aligned = {
        "ref": "MKTVFLGKL",
        "hom1": "MKTVF--KL",
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
    )
    assert len(variants) == 1
    v = variants[0]
    assert v.variant_type == "deletion"
    assert v.protein_position == 6
    assert v.reference_aa == "LG"
    assert v.alternate_aa == "-"
    assert v.protein_change == "del6_7"


# ---------------------------------------------------------------------------
# Test 7: Gap-in-reference handling ensuring ungapped coordinates remain accurate
# ---------------------------------------------------------------------------
def test_7_gap_in_reference_preserves_ungapped_coordinates() -> None:
    # Ref has gap at column 3.
    # Ref ungapped: M=1, K=2, T=3, F=4, L=5, Y=6.
    # Homolog has insertion at col 3 (A) and substitution at col 6 (Y -> W).
    aligned = {
        "ref": "MKT-FLY",
        "hom1": "MKTAFLW",
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
    )
    assert len(variants) == 2
    sub_var = next(v for v in variants if v.variant_type == "missense")
    # Y is at ungapped reference position 6!
    assert sub_var.protein_position == 6
    assert sub_var.protein_change == "Y6W"


# ---------------------------------------------------------------------------
# Test 8: Protein-only records (no CDS) handled gracefully without fabricating CDS
# ---------------------------------------------------------------------------
def test_8_protein_only_records_no_cds_fabrication() -> None:
    aligned = {
        "ref": "MKTVFLG",
        "hom1": "MKTVYLG",
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
        ref_cds=None,
        homolog_cds=None,
    )
    assert len(variants) == 1
    v = variants[0]
    assert v.protein_change == "F5Y"
    assert v.nucleotide_change is None
    assert v.codon_position is None


# ---------------------------------------------------------------------------
# Test 9: CDS missense variant derivation (c.24T>A -> F8Y)
# ---------------------------------------------------------------------------
def test_9_cds_missense_variant_derivation() -> None:
    ref_prot = "MKTVLAGFQ"
    hom_prot = "MKTVLAGYQ"
    # Codon 8 (position 8, F) in ref: TTC (nt 22-24)
    # Codon 8 (position 8, Y) in hom: TAC (nt 22-24) -> c.24T>A
    ref_cds = "ATGAAGACTGTACTTGCAGGTTTCCAA"
    hom_cds = "ATGAAGACTGTACTTGCAGGTACCCAA"  # wait, TAC:
    hom_cds = "ATGAAGACTGTACTTGCAGGTTACCAA"

    aligned = {
        "ref": ref_prot,
        "hom1": hom_prot,
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
        ref_cds=ref_cds,
        homolog_cds={"hom1": hom_cds},
    )
    assert len(variants) == 1
    v = variants[0]
    assert v.protein_change == "F8Y"
    assert v.protein_position == 8
    assert v.nucleotide_change == "c.23T>A"
    assert v.codon_position == 22
    assert v.variant_type == "missense"


# ---------------------------------------------------------------------------
# Test 10: CDS synonymous variant derivation
# ---------------------------------------------------------------------------
def test_10_cds_synonymous_variant_derivation() -> None:
    ref_prot = "MKTVLAGFQ"
    hom_prot = "MKTVLAGFQ"  # Identical amino acid sequence!
    # Codon 8 in ref: TTC -> F
    # Codon 8 in hom: TTT -> F (nt 24 C>T)
    ref_cds = "ATGAAGACTGTACTTGCAGGTTTCCAA"
    hom_cds = "ATGAAGACTGTACTTGCAGGTTTTCAA"

    aligned = {
        "ref": ref_prot,
        "hom1": hom_prot,
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
        ref_cds=ref_cds,
        homolog_cds={"hom1": hom_cds},
    )
    assert len(variants) == 1
    v = variants[0]
    assert v.variant_type == "synonymous"
    assert v.protein_position == 8
    assert v.reference_aa == "F"
    assert v.alternate_aa == "F"
    assert v.nucleotide_change == "c.24C>T"
    assert v.codon_position == 22


# ---------------------------------------------------------------------------
# Test 11: CDS translation mismatch rejection or warning
# ---------------------------------------------------------------------------
def test_11_cds_translation_mismatch_warning() -> None:
    protein = "MKTVL"
    tampered_cds = "ATGGGGGGG"  # Translates to MGG, not MKTVL

    is_valid, reason = verify_cds_translation(tampered_cds, protein)
    assert not is_valid
    assert "mismatch" in reason.lower()

    # When passed to extractor, the tampered CDS is rejected with a warning
    # and no false nucleotide changes are assigned
    aligned = {"ref": protein, "hom1": "MKTVY"}
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
        ref_cds=tampered_cds,
    )
    assert len(variants) == 1
    assert variants[0].nucleotide_change is None


# ---------------------------------------------------------------------------
# Test 12: Region annotation (mature peptide vs leader peptide vs unknown)
# ---------------------------------------------------------------------------
def test_12_region_annotation() -> None:
    annotations = {
        "leader_peptide": (1, 15),
        "mature_peptide": (16, 45),
    }
    assert annotate_region(5, annotations) == "leader_peptide"
    assert annotate_region(25, annotations) == "mature_peptide"
    assert annotate_region(50, annotations) == "unknown"


# ---------------------------------------------------------------------------
# Test 13: Deduplication of identical variants across multiple homologs
# ---------------------------------------------------------------------------
def test_13_deduplication_and_accession_aggregation() -> None:
    aligned = {
        "ref": "MKTVFLG",
        "hom1": "MKTVYLG",
        "hom2": "MKTVYLG",
        "hom3": "MKTVYLG",
        "hom4": "MKTVFLG",  # match
    }
    metadata = {
        "hom1": {"accession": "ACC_001"},
        "hom2": {"accession": "ACC_002"},
        "hom3": {"accession": "ACC_003"},
        "hom4": {"accession": "ACC_004"},
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
        homolog_metadata=metadata,
    )
    assert len(variants) == 1
    v = variants[0]
    assert v.protein_change == "F5Y"
    assert v.observed_count == 3
    assert v.homolog_count == 4
    assert v.source_accessions == ["ACC_001", "ACC_002", "ACC_003"]


# ---------------------------------------------------------------------------
# Test 14: Frequency and conservation calculations
# ---------------------------------------------------------------------------
def test_14_frequency_and_conservation_calculations() -> None:
    aligned = {
        "ref": "MKTVFLG",
        "hom1": "MKTVYLG",
        "hom2": "MKTVYLG",
        "hom3": "MKTVYLG",
        "hom4": "MKTVFLG",
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
    )
    v = variants[0]
    # 3 out of 4 homologs carry Y -> frequency = 0.75
    assert v.frequency == 0.75
    # 1 out of 4 homologs retains F -> conservation = 0.25
    assert v.conservation_score == 0.25


# ---------------------------------------------------------------------------
# Test 15: Alignment tool missing/unavailable raises clean error
# ---------------------------------------------------------------------------
def test_15_alignment_tool_missing_error() -> None:
    backend = MafftBackend(executable="/nonexistent/mafft_bin")
    assert not backend.is_available()
    with pytest.raises(AlignmentUnavailableError, match="not found"):
        backend.align({"seq1": "MKT", "seq2": "MKT"})


# ---------------------------------------------------------------------------
# Test 16: Alignment execution failure handling (non-zero exit)
# ---------------------------------------------------------------------------
def test_16_alignment_execution_failure() -> None:
    backend = MafftBackend()
    mock_proc = MagicMock()
    mock_proc.returncode = 2
    mock_proc.stderr = "MAFFT syntax error"
    with (
        patch("shutil.which", return_value="/usr/bin/mafft"),
        patch("subprocess.run", return_value=mock_proc),
        pytest.raises(AlignmentExecutionError, match="exited with code 2"),
    ):
        backend.align({"s1": "MKT", "s2": "MKV"})


# ---------------------------------------------------------------------------
# Test 17: Alignment timeout handling
# ---------------------------------------------------------------------------
def test_17_alignment_timeout_handling() -> None:
    backend = ClustalOmegaBackend()
    timeout_exc = subprocess.TimeoutExpired(cmd="clustalo", timeout=5.0)
    with (
        patch("shutil.which", return_value="/usr/bin/clustalo"),
        patch("subprocess.run", side_effect=timeout_exc),
        pytest.raises(AlignmentTimeoutError, match="timed out"),
    ):
        backend.align({"s1": "MKT", "s2": "MKV"}, timeout_seconds=5.0)


# ---------------------------------------------------------------------------
# Test 18: Temporary files created during alignment are cleaned up
# ---------------------------------------------------------------------------
def test_18_tempfile_cleanup() -> None:
    import tempfile

    backend = MafftBackend()
    created_files: list[str] = []

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ">s1\nMKT\n>s2\nMKV\n"

    with tempfile.NamedTemporaryFile(delete=False) as real_file:
        created_files.append(real_file.name)

    with (
        patch("shutil.which", return_value="/usr/bin/mafft"),
        patch("subprocess.run", return_value=mock_proc),
        patch("tempfile.NamedTemporaryFile") as mock_tf,
    ):
        mock_tf.return_value.__enter__.return_value.name = created_files[0]
        backend.align({"s1": "MKT", "s2": "MKV"})

        # Verify file was cleaned up
        assert not Path(created_files[0]).exists()


# ---------------------------------------------------------------------------
# Test 19: Provenance checks (database-derived, hypotheses, never validated)
# ---------------------------------------------------------------------------
def test_19_provenance_and_hypothesis_calibration() -> None:
    aligned = {
        "ref": "MKTVFLG",
        "hom1": "MKTVYLG",
    }
    variants = extract_variants_from_alignment(
        parent_candidate_id="cand_test",
        aligned_sequences=aligned,
        reference_id="ref",
    )
    v = variants[0]
    assert v.provenance == "database-derived"
    assert v.functional_effect.status == "hypothesis"
    assert v.functional_effect.confidence <= 0.4
    assert "validated" not in v.functional_effect.hypothesis.lower()
    assert "confirmed" not in v.functional_effect.hypothesis.lower()


# ---------------------------------------------------------------------------
# Test 20: Candidate Agent integration produces valid CandidateProposals
# ---------------------------------------------------------------------------
def test_20_candidate_agent_integration_proposals() -> None:
    ref_seq = "MKTVFLG"
    homologs = [
        {"id": "hom1", "sequence": "MKTVYLG"},
    ]
    agent = CandidateGenerationAgent()
    discovery_res, proposals = agent.discover_candidate_variants(
        candidate_id="cand_001",
        sequence=ref_seq,
        homologs=homologs,
        alignment_backend=FixtureAlignmentBackend(),
    )
    assert isinstance(discovery_res, VariantDiscoveryResult)
    assert len(proposals) == 1
    prop = proposals[0]
    assert isinstance(prop, CandidateProposal)
    assert prop.origin == "modified"
    assert prop.derived_from_candidate_id == "cand_001"
    assert prop.parent_candidate_id == "cand_001"
    assert prop.validation_status == "unvalidated"
    # Mutated sequence has F5Y
    assert prop.sequence == "MKTVYLG"
    assert prop.modifications == ["F5Y"]


# ---------------------------------------------------------------------------
# Test 21: No-homolog case returns valid empty discovery result without crashing
# ---------------------------------------------------------------------------
def test_21_no_homolog_case_empty_result() -> None:
    agent = VariantDiscoveryAgent(alignment_backend=FixtureAlignmentBackend())
    res = agent.discover(
        candidate_id="cand_empty",
        sequence="MKTVFLG",
        homologs=[],
    )
    assert res.homolog_count == 0
    assert res.aligned_homolog_count == 0
    assert len(res.variants) == 0
    assert len(res.warnings) > 0


# ---------------------------------------------------------------------------
# Test 22: Omnigent MCP tool discover_candidate_variants exposure and budget
# ---------------------------------------------------------------------------
def test_22_omnigent_mcp_tool_exposure_and_budget() -> None:
    import asyncio

    server = build_server()
    tools = asyncio.run(server.list_tools())
    tool_names = [t.name for t in tools]
    assert "discover_candidate_variants" in tool_names

    # Budget enforcement check: exceeding max_homologs raises VariantBudgetExceededError
    with pytest.raises(VariantBudgetExceededError, match="exceeds limit"):
        discover_variants(
            candidate_id="test",
            sequence="MKT",
            homologs=[],
            max_homologs=100,
            strict_budget=True,
        )

    # Execute tool call through FastMCP server
    with patch(
        "bacteriocin_lab.agents.variant.agent.VariantDiscoveryAgent.discover",
        return_value=VariantDiscoveryResult(
            candidate_id="nisin_a",
            reference_sequence="MKTVFLG",
            homolog_count=1,
            aligned_homolog_count=1,
            variants=[
                VariantRecord(
                    variant_id="nisin_a_F5Y",
                    parent_candidate_id="nisin_a",
                    protein_position=5,
                    reference_aa="F",
                    alternate_aa="Y",
                    protein_change="F5Y",
                    observed_count=1,
                    homolog_count=1,
                    frequency=1.0,
                    conservation_score=0.0,
                )
            ],
        ),
    ):
        tool_res = asyncio.run(
            server.call_tool(
                "discover_candidate_variants",
                {
                    "candidate_id": "nisin_a",
                    "sequence": "MKTVFLG",
                    "max_homologs": 5,
                    "max_variants": 2,
                },
            )
        )
        if hasattr(tool_res, "content"):
            res_text = tool_res.content[0].text
        elif isinstance(tool_res, (list, tuple)):
            item = tool_res[0]
            res_text = item[0].text if isinstance(item, (list, tuple)) else item.text
        else:
            res_text = str(tool_res)
        payload = json.loads(res_text)
        assert payload["candidate_id"] == "nisin_a"
        assert len(payload["variants"]) == 1
        assert len(payload["proposals"]) == 1
        assert payload["proposals"][0]["origin"] == "modified"



# ---------------------------------------------------------------------------
# Test 23: Opt-in live smoke test
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_VARIANT_DISCOVERY_TESTS") != "1",
    reason="Opt-in live variant discovery smoke test; set RUN_LIVE_VARIANT_DISCOVERY_TESTS=1",
)
def test_23_live_variant_discovery_smoke() -> None:
    # Live discovery against swissprot or remote NCBI
    nisin_a = "MSTKDFNLDLVSVSKKDSGASPRITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    res = discover_variants(
        candidate_id="nisin_a",
        sequence=nisin_a,
        max_homologs=10,
        max_variants=5,
    )
    assert isinstance(res, VariantDiscoveryResult)
    assert res.candidate_id == "nisin_a"
