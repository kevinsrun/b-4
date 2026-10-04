from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bacteriocin_lab.agents.variant.extractor import extract_variants_from_alignment

BENCHMARK_DIR = Path(__file__).resolve().parent.parent
PROT_FASTA = BENCHMARK_DIR / "fixtures" / "synthetic_protein_alignment.fasta"
CDS_FASTA = BENCHMARK_DIR / "fixtures" / "synthetic_cds_alignment.fasta"
EXPECTED_VARIANTS_FILE = BENCHMARK_DIR / "expected" / "synthetic_variants.json"


def load_fasta_dict(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    res: dict[str, str] = {}
    curr_id: str | None = None
    curr_lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if curr_id is not None:
                res[curr_id] = "".join(curr_lines).upper()
                curr_lines = []
            curr_id = line[1:].split()[0]
        else:
            curr_lines.append(line)
    if curr_id is not None:
        res[curr_id] = "".join(curr_lines).upper()
    return res


def load_fasta_sequences(path: Path) -> dict[str, str]:
    return load_fasta_dict(path)


def load_expected_variants(path: Path = EXPECTED_VARIANTS_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(mode="r", encoding="utf-8") as f:
        return json.load(f)


def run_variant_benchmark() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute synthetic gold-standard variant correctness benchmark.

    Measures:
    - substitution precision / recall
    - indel precision / recall
    - coordinate accuracy (catches off-by-one alignment gap errors)
    - frequency accuracy
    - CDS->protein mapping accuracy
    - variant-type accuracy

    Returns:
        tuple (summary_metrics_dict, detailed_csv_rows)
    """
    aligned_prot = load_fasta_sequences(PROT_FASTA)
    cds_dict = load_fasta_sequences(CDS_FASTA)
    expected_list = load_expected_variants()

    ref_cds = cds_dict.get("ref")
    homolog_cds = {k: v for k, v in cds_dict.items() if k != "ref"}

    extracted = extract_variants_from_alignment(
        parent_candidate_id="synthetic_candidate",
        aligned_sequences=aligned_prot,
        reference_id="ref",
        ref_cds=ref_cds,
        homolog_cds=homolog_cds,
    )

    extracted_by_change = {v.protein_change: v for v in extracted}
    expected_by_change = {exp["protein_change"]: exp for exp in expected_list}

    # Evaluate TP, FP, FN for substitutions and indels separately
    sub_tp = 0
    sub_fp = 0
    sub_fn = 0

    indel_tp = 0
    indel_fp = 0
    indel_fn = 0

    coord_correct = 0
    freq_correct = 0
    cds_correct = 0
    type_correct = 0
    total_tp = 0

    per_case_diagnostics: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []

    # Check each expected variant
    for change, exp in expected_by_change.items():
        vtype = exp["variant_type"]
        is_sub = vtype in ("missense", "synonymous", "stop_gain")
        is_indel = vtype in ("insertion", "deletion")

        if change in extracted_by_change:
            obs = extracted_by_change[change]
            total_tp += 1
            if is_sub:
                sub_tp += 1
            elif is_indel:
                indel_tp += 1

            # Check coordinate accuracy
            coord_match = obs.protein_position == exp["protein_position"]
            if coord_match:
                coord_correct += 1

            # Check frequency accuracy (within 0.01 tolerance)
            freq_match = abs(obs.frequency - exp["frequency"]) < 0.01
            if freq_match:
                freq_correct += 1

            # Check variant type
            type_match = obs.variant_type == exp["variant_type"]
            if type_match:
                type_correct += 1

            # Check CDS mapping
            exp_nt = exp.get("nucleotide_change")
            obs_nt = obs.nucleotide_change
            exp_cod = exp.get("codon_position")
            obs_cod = obs.codon_position
            cds_match = (obs_nt == exp_nt) and (obs_cod == exp_cod)
            if cds_match:
                cds_correct += 1

            diag = {
                "protein_change": change,
                "variant_type": vtype,
                "expected_position": exp["protein_position"],
                "observed_position": obs.protein_position,
                "coordinate_match": coord_match,
                "expected_frequency": exp["frequency"],
                "observed_frequency": obs.frequency,
                "frequency_match": freq_match,
                "expected_nt": exp_nt,
                "observed_nt": obs_nt,
                "expected_codon": exp_cod,
                "observed_codon": obs_cod,
                "cds_match": cds_match,
                "type_match": type_match,
                "status": "PASS",
            }
            per_case_diagnostics.append(diag)
            csv_rows.append(
                {
                    "benchmark": "variant_correctness",
                    "item_id": change,
                    "variant_type": vtype,
                    "status": "PASS",
                    "coord_match": coord_match,
                    "freq_match": freq_match,
                    "cds_match": cds_match,
                    "type_match": type_match,
                }
            )
        else:
            # FN
            if is_sub:
                sub_fn += 1
            elif is_indel:
                indel_fn += 1

            diag = {
                "protein_change": change,
                "variant_type": vtype,
                "status": "FALSE_NEGATIVE",
            }
            per_case_diagnostics.append(diag)
            csv_rows.append(
                {
                    "benchmark": "variant_correctness",
                    "item_id": change,
                    "variant_type": vtype,
                    "status": "FALSE_NEGATIVE",
                    "coord_match": False,
                    "freq_match": False,
                    "cds_match": False,
                    "type_match": False,
                }
            )

    # Check for FP (in extracted but not in expected)
    for change, obs in extracted_by_change.items():
        if change not in expected_by_change:
            is_sub = obs.variant_type in ("missense", "synonymous", "stop_gain")
            is_indel = obs.variant_type in ("insertion", "deletion")
            if is_sub:
                sub_fp += 1
            elif is_indel:
                indel_fp += 1

            diag = {
                "protein_change": change,
                "variant_type": obs.variant_type,
                "status": "FALSE_POSITIVE",
            }
            per_case_diagnostics.append(diag)
            csv_rows.append(
                {
                    "benchmark": "variant_correctness",
                    "item_id": change,
                    "variant_type": obs.variant_type,
                    "status": "FALSE_POSITIVE",
                    "coord_match": False,
                    "freq_match": False,
                    "cds_match": False,
                    "type_match": False,
                }
            )

    sub_precision = sub_tp / max(sub_tp + sub_fp, 1)
    sub_recall = sub_tp / max(sub_tp + sub_fn, 1)

    indel_precision = indel_tp / max(indel_tp + indel_fp, 1)
    indel_recall = indel_tp / max(indel_tp + indel_fn, 1)

    total_expected = len(expected_by_change)
    coord_acc = coord_correct / max(total_tp, 1)
    freq_acc = freq_correct / max(total_tp, 1)
    cds_acc = cds_correct / max(total_tp, 1)
    type_acc = type_correct / max(total_tp, 1)

    summary = {
        "total_expected_variants": total_expected,
        "total_extracted_variants": len(extracted),
        "true_positives": total_tp,
        "substitution_precision": round(sub_precision, 4),
        "substitution_recall": round(sub_recall, 4),
        "indel_precision": round(indel_precision, 4),
        "indel_recall": round(indel_recall, 4),
        "coordinate_accuracy": round(coord_acc, 4),
        "frequency_accuracy": round(freq_acc, 4),
        "cds_mapping_accuracy": round(cds_acc, 4),
        "variant_type_accuracy": round(type_acc, 4),
        "provenance": "synthetic-test-data",
        "diagnostics": per_case_diagnostics,
    }

    return summary, csv_rows
