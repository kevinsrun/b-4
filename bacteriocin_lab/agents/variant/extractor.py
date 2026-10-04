from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from .annotation import (
    annotate_region,
    build_functional_effect_hypothesis,
    compute_conservation_score,
    score_variant,
)
from .cds import derive_codon_change, verify_cds_translation
from .models import VariantRecord

logger = logging.getLogger("b4_variant.extractor")


def extract_variants_from_alignment(
    parent_candidate_id: str,
    aligned_sequences: dict[str, str],
    reference_id: str = "ref",
    homolog_metadata: Mapping[str, dict[str, Any]] | None = None,
    ref_cds: str | None = None,
    homolog_cds: Mapping[str, str] | None = None,
    region_annotations: Mapping[str, tuple[int, int]] | None = None,
) -> list[VariantRecord]:
    """Extract, aggregate, score, and rank natural sequence variants from an MSA.

    Uses ungapped reference coordinates. Correctly anchors substitutions, insertions,
    and deletions regardless of alignment gaps.

    Args:
        parent_candidate_id: ID of the parent candidate bacteriocin.
        aligned_sequences: Mapping of sequence_id -> aligned amino acid sequence (equal lengths).
        reference_id: Sequence ID of the reference in aligned_sequences.
        homolog_metadata: Optional mapping of homolog_id -> metadata dict.
        ref_cds: Optional reference coding sequence (nucleotide).
        homolog_cds: Optional mapping of homolog_id -> coding sequence (nucleotide).
        region_annotations: Optional mapping of region name -> (start, end) 1-indexed.

    Returns:
        Deterministic list of aggregated VariantRecord objects sorted by priority score descending.
    """
    if reference_id not in aligned_sequences:
        logger.warning("Reference ID '%s' not present in aligned sequences", reference_id)
        return []

    ref_aligned = aligned_sequences[reference_id].upper()
    homolog_ids = [k for k in aligned_sequences if k != reference_id]
    total_homologs = len(homolog_ids)

    if total_homologs == 0:
        return []

    align_len = len(ref_aligned)

    # Validate CDS translations upfront if provided
    valid_ref_cds = None
    if ref_cds:
        ref_prot_ungapped = ref_aligned.replace("-", "")
        valid, reason = verify_cds_translation(ref_cds, ref_prot_ungapped)
        if valid:
            valid_ref_cds = ref_cds
        else:
            logger.warning("Reference CDS failed translation verification: %s", reason)

    valid_hom_cds: dict[str, str] = {}
    if homolog_cds:
        for hid in homolog_ids:
            h_cds = homolog_cds.get(hid)
            if h_cds:
                h_prot_ungapped = aligned_sequences[hid].upper().replace("-", "")
                valid, reason = verify_cds_translation(h_cds, h_prot_ungapped)
                if valid:
                    valid_hom_cds[hid] = h_cds
                else:
                    logger.warning(
                        "Homolog %s CDS failed translation verification: %s", hid, reason
                    )

    # Map column index -> ungapped reference position (1-indexed) and character
    col_to_ref_pos: list[int | None] = []
    current_ref_pos = 0
    ref_pos_to_col: dict[int, int] = {}

    for col in range(align_len):
        char = ref_aligned[col]
        if char != "-":
            current_ref_pos += 1
            col_to_ref_pos.append(current_ref_pos)
            ref_pos_to_col[current_ref_pos] = col
        else:
            col_to_ref_pos.append(None)

    # Map column index -> ungapped homolog position for each homolog
    col_to_hom_pos: dict[str, list[int | None]] = {}
    for hid in homolog_ids:
        h_aligned = aligned_sequences[hid].upper()
        h_pos_list: list[int | None] = []
        cur_h_pos = 0
        for col in range(align_len):
            if h_aligned[col] != "-":
                cur_h_pos += 1
                h_pos_list.append(cur_h_pos)
            else:
                h_pos_list.append(None)
        col_to_hom_pos[hid] = h_pos_list

    # Raw variant observations: key -> list of homolog_ids
    # key: (protein_change, protein_pos, ref_aa, alt_aa, variant_type, nt_change, codon_pos)
    observations: dict[
        tuple[str, int, str, str, str, str | None, int | None],
        list[str],
    ] = {}

    for hid in homolog_ids:
        h_aligned = aligned_sequences[hid].upper()
        h_cds = valid_hom_cds.get(hid)
        last_ref_pos = 0

        col = 0
        while col < align_len:
            ref_char = ref_aligned[col]
            hom_char = h_aligned[col]
            ref_pos = col_to_ref_pos[col]
            hom_pos = col_to_hom_pos[hid][col]

            if ref_pos is not None:
                last_ref_pos = ref_pos

            # Case 1: Insertion (ref_char == '-', hom_char != '-')
            if ref_char == "-" and hom_char != "-":
                ins_chars: list[str] = []
                anchor_pos = max(1, last_ref_pos)
                while col < align_len and ref_aligned[col] == "-" and h_aligned[col] != "-":
                    ins_chars.append(h_aligned[col])
                    col += 1
                ins_str = "".join(ins_chars)
                prot_change = f"ins{anchor_pos}{ins_str}"
                key = (prot_change, anchor_pos, "-", ins_str, "insertion", None, None)
                observations.setdefault(key, []).append(hid)
                continue

            # Case 2: Deletion (ref_char != '-', hom_char == '-')
            if ref_char != "-" and hom_char == "-":
                del_ref_chars: list[str] = []
                start_del_pos = ref_pos
                end_del_pos = ref_pos
                while col < align_len and ref_aligned[col] != "-" and h_aligned[col] == "-":
                    del_ref_chars.append(ref_aligned[col])
                    end_del_pos = col_to_ref_pos[col]
                    last_ref_pos = end_del_pos
                    col += 1
                assert start_del_pos is not None and end_del_pos is not None
                if start_del_pos == end_del_pos:
                    prot_change = f"del{start_del_pos}"
                else:
                    prot_change = f"del{start_del_pos}_{end_del_pos}"
                ref_del_str = "".join(del_ref_chars)
                key = (prot_change, start_del_pos, ref_del_str, "-", "deletion", None, None)
                observations.setdefault(key, []).append(hid)
                continue

            # Case 3: Both non-gap
            if ref_char != "-" and hom_char != "-":
                assert ref_pos is not None
                if ref_char != hom_char:
                    # Missense or stop_gain
                    prot_change = f"{ref_char}{ref_pos}{hom_char}"
                    nt_change, codon_pos, vtype = derive_codon_change(
                        valid_ref_cds, h_cds, ref_pos, hom_pos, ref_char, hom_char
                    )
                    key = (prot_change, ref_pos, ref_char, hom_char, vtype, nt_change, codon_pos)
                    observations.setdefault(key, []).append(hid)
                elif valid_ref_cds and h_cds:
                    # Same AA, but check for synonymous nucleotide change
                    nt_change, codon_pos, vtype = derive_codon_change(
                        valid_ref_cds, h_cds, ref_pos, hom_pos, ref_char, hom_char
                    )
                    if nt_change and vtype == "synonymous":
                        prot_change = f"{ref_char}{ref_pos}="
                        key = (
                            prot_change,
                            ref_pos,
                            ref_char,
                            hom_char,
                            "synonymous",
                            nt_change,
                            codon_pos,
                        )
                        observations.setdefault(key, []).append(hid)

            col += 1

    # Now aggregate observations into VariantRecord instances
    variant_records: list[VariantRecord] = []

    for (
        prot_change,
        pos,
        ref_aa,
        alt_aa,
        vtype,
        nt_change,
        codon_pos,
    ), observed_hids in observations.items():
        unique_hids = sorted(set(observed_hids))
        obs_count = len(unique_hids)
        frequency = round(obs_count / total_homologs, 4)

        # Source accessions
        accessions: list[str] = []
        for hid in unique_hids:
            acc = None
            if homolog_metadata and hid in homolog_metadata:
                acc = homolog_metadata[hid].get("accession") or homolog_metadata[hid].get("id")
            accessions.append(acc or hid)
        sorted_accessions = sorted(set(accessions))

        # Conservation score
        if vtype in ("missense", "synonymous", "stop_gain"):
            col = ref_pos_to_col.get(pos)
            if col is not None:
                hom_aas = [aligned_sequences[h][col] for h in homolog_ids]
                conservation = compute_conservation_score(ref_aa, hom_aas)
            else:
                conservation = 1.0
        elif vtype == "deletion":
            # Fraction of homologs that retain the reference residue(s)
            col = ref_pos_to_col.get(pos)
            if col is not None:
                retained = sum(1 for h in homolog_ids if aligned_sequences[h][col] != "-")
                conservation = round(retained / total_homologs, 4)
            else:
                conservation = 1.0
        else:  # insertion
            # Fraction of homologs that do not have an insertion
            not_inserted = total_homologs - obs_count
            conservation = round(max(0, not_inserted) / total_homologs, 4)

        # Region
        region = annotate_region(pos, region_annotations)

        # Scoring
        priority_score, score_components = score_variant(
            frequency=frequency,
            conservation_score=conservation,
            region=region,
            homolog_count=total_homologs,
            source_count=len(sorted_accessions),
        )

        # Functional hypothesis
        hypothesis = build_functional_effect_hypothesis(
            variant_type=vtype,
            protein_change=prot_change,
            region=region,
            frequency=frequency,
            conservation_score=conservation,
        )

        # Stable variant ID
        suffix = f"_{nt_change}" if nt_change else ""
        variant_id = f"{parent_candidate_id}_{prot_change}{suffix}".replace(">", "_")

        record = VariantRecord(
            variant_id=variant_id,
            parent_candidate_id=parent_candidate_id,
            protein_position=pos,
            reference_aa=ref_aa,
            alternate_aa=alt_aa,
            protein_change=prot_change,
            nucleotide_change=nt_change,
            codon_position=codon_pos,
            variant_type=vtype,  # type: ignore[arg-type]
            observed_count=obs_count,
            homolog_count=total_homologs,
            frequency=frequency,
            conservation_score=conservation,
            region=region,
            source_accessions=sorted_accessions,
            provenance="database-derived",
            variant_priority_score=priority_score,
            score_components=score_components,
            functional_effect=hypothesis,
        )
        variant_records.append(record)

    # Sort deterministically: priority_score desc, protein_position asc, protein_change asc
    variant_records.sort(
        key=lambda v: (-v.variant_priority_score, v.protein_position, v.protein_change)
    )

    return variant_records
