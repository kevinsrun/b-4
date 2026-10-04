from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from typing import Any

from bacteriocin_lab.agents.candidate.features import compute_features
from bacteriocin_lab.agents.candidate.schema import CandidateFeatures, CandidateProposal
from bacteriocin_lab.agents.evidence.ncbi import AutoBlastBackend, BlastBackend, NcbiClient
from bacteriocin_lab.agents.evidence.ncbi.fasta import fetch_fasta

from .alignment import AlignmentBackend, AutoAlignmentBackend
from .errors import VariantBudgetExceededError, VariantDiscoveryError
from .extractor import extract_variants_from_alignment
from .models import VariantDiscoveryResult, VariantRecord

logger = logging.getLogger("b4_variant.agent")

DEFAULT_MAX_VARIANT_HOMOLOGS = int(os.getenv("MAX_VARIANT_HOMOLOGS", "50"))
DEFAULT_MAX_VARIANTS_PER_CANDIDATE = int(os.getenv("MAX_VARIANTS_PER_CANDIDATE", "10"))
DEFAULT_MAX_VARIANT_CANDIDATES_PER_RUN = int(os.getenv("MAX_VARIANT_CANDIDATES_PER_RUN", "5"))


def mutate_sequence(sequence: str, variant: VariantRecord) -> str:
    """Apply a VariantRecord mutation to a reference amino acid sequence.

    Args:
        sequence: Reference protein sequence (ungapped).
        variant: VariantRecord describing the change.

    Returns:
        Mutated protein amino acid sequence string.
    """
    clean_seq = sequence.strip().upper()
    pos = variant.protein_position

    if variant.variant_type == "synonymous":
        return clean_seq

    if variant.variant_type in ("missense", "stop_gain"):
        idx = pos - 1
        if idx < 0 or idx >= len(clean_seq):
            raise VariantDiscoveryError(
                f"Variant position {pos} out of range for sequence of length {len(clean_seq)}"
            )
        return clean_seq[:idx] + variant.alternate_aa + clean_seq[idx + 1 :]

    if variant.variant_type == "insertion":
        # Insertion occurs after position pos
        anchor = min(pos, len(clean_seq))
        return clean_seq[:anchor] + variant.alternate_aa + clean_seq[anchor:]

    if variant.variant_type == "deletion":
        # Check deletion range e.g. del6_7 or del6
        m = re.match(r"^del(\d+)(?:_(\d+))?", variant.protein_change)
        if m:
            start_del = int(m.group(1))
            end_del = int(m.group(2)) if m.group(2) else start_del
            start_idx = start_del - 1
            end_idx = end_del
            return clean_seq[:start_idx] + clean_seq[end_idx:]
        # Fallback to reference_aa length
        del_len = max(len(variant.reference_aa), 1)
        idx = pos - 1
        return clean_seq[:idx] + clean_seq[idx + del_len :]

    return clean_seq


def variant_to_proposal(
    variant: VariantRecord,
    reference_sequence: str,
    parent_features: CandidateFeatures | None = None,
) -> CandidateProposal:
    """Convert an extracted VariantRecord into a CandidateProposal for downstream simulation.

    Args:
        variant: Structured VariantRecord.
        reference_sequence: Parent candidate sequence.
        parent_features: Optional parent CandidateFeatures to inherit context.

    Returns:
        Valid CandidateProposal marked as origin='modified' and validation_status='unvalidated'.
    """
    mutated_seq = mutate_sequence(reference_sequence, variant)
    computed_features = compute_features(mutated_seq)

    features = (
        parent_features.model_copy(deep=True)
        if parent_features is not None
        else CandidateFeatures()
    )
    features.computed = computed_features

    cid = f"{variant.parent_candidate_id}_{variant.protein_change}".replace(">", "_")

    return CandidateProposal(
        candidate_id=cid,
        origin="modified",
        name=cid,
        sequence=mutated_seq,
        derived_from_candidate_id=variant.parent_candidate_id,
        modifications=[variant.protein_change],
        validation_status="unvalidated",
        hypothesis=variant.functional_effect.hypothesis,
        confidence=variant.functional_effect.confidence,
        features=features,
        expected_strengths=variant.functional_effect.possible_effects,
        expected_failure_modes=["natural_variant_loss_of_function", "stability_decrease"],
        evidence_ids=[],
    )


class VariantDiscoveryAgent:
    """Specialist agent for discovering natural sequence variants in bacteriocin homologs.

    Combines sequence similarity search (BLAST), multiple sequence alignment (MAFFT / Clustal),
    ungapped reference coordinate mapping, CDS verification, and conservative hypotheses.
    """

    def __init__(
        self,
        blast_backend: BlastBackend | None = None,
        alignment_backend: AlignmentBackend | None = None,
        ncbi_client: NcbiClient | None = None,
    ) -> None:
        self.blast_backend = blast_backend or AutoBlastBackend()
        self.alignment_backend = alignment_backend or AutoAlignmentBackend()
        self.ncbi_client = ncbi_client or NcbiClient()

    def discover(
        self,
        candidate_id: str,
        sequence: str,
        homologs: list[dict[str, Any]] | None = None,
        ref_cds: str | None = None,
        homolog_cds: Mapping[str, str] | None = None,
        region_annotations: Mapping[str, tuple[int, int]] | None = None,
        database: str = "swissprot",
        max_homologs: int = DEFAULT_MAX_VARIANT_HOMOLOGS,
        max_variants: int = DEFAULT_MAX_VARIANTS_PER_CANDIDATE,
        strict_budget: bool = False,
        blast_options: dict[str, Any] | None = None,
    ) -> VariantDiscoveryResult:
        """Run variant discovery pipeline for a bacteriocin candidate.

        Args:
            candidate_id: Identifier of the query bacteriocin candidate.
            sequence: Query amino acid sequence.
            homologs: Optional pre-retrieved homolog records. If omitted, BLAST is performed.
            ref_cds: Optional reference nucleotide coding sequence.
            homolog_cds: Optional mapping of homolog_id -> coding sequence.
            region_annotations: Optional mapping of region name -> (start, end) 1-indexed.
            database: BLAST database to query if homologs not provided.
            max_homologs: Maximum number of homologs to retrieve/align.
            max_variants: Maximum number of ranked variants to return.
            strict_budget: If True, raise VariantBudgetExceededError when limits exceeded.
            blast_options: Additional options forwarded to BLAST backend.

        Returns:
            VariantDiscoveryResult envelope containing ranked VariantRecord items.
        """
        clean_seq = sequence.strip().upper()
        if not clean_seq:
            return VariantDiscoveryResult(
                candidate_id=candidate_id,
                reference_sequence="",
                homolog_count=0,
                aligned_homolog_count=0,
                variants=[],
                warnings=["Empty candidate sequence provided."],
            )

        # Budget checks
        if max_homologs > DEFAULT_MAX_VARIANT_HOMOLOGS:
            if strict_budget:
                raise VariantBudgetExceededError(
                    f"Requested max_homologs ({max_homologs}) exceeds limit "
                    f"({DEFAULT_MAX_VARIANT_HOMOLOGS})"
                )
            max_homologs = DEFAULT_MAX_VARIANT_HOMOLOGS

        if max_variants > DEFAULT_MAX_VARIANTS_PER_CANDIDATE:
            if strict_budget:
                raise VariantBudgetExceededError(
                    f"Requested max_variants ({max_variants}) exceeds limit "
                    f"({DEFAULT_MAX_VARIANTS_PER_CANDIDATE})"
                )
            max_variants = DEFAULT_MAX_VARIANTS_PER_CANDIDATE

        warnings: list[str] = []
        sources: list[str] = []
        homolog_records: list[dict[str, Any]] = []

        # 1. Retrieve or prepare homologs
        if homologs is not None:
            homolog_records = list(homologs[:max_homologs])
            sources.append("user_supplied_homologs")
        else:
            opts = dict(blast_options or {})
            opts["hitlist_size"] = max_homologs
            try:
                blast_res = self.blast_backend.blastp(
                    sequence=clean_seq,
                    database=database,
                    candidate_id=candidate_id,
                    **opts,
                )
                hits = blast_res.get("hits", [])
                sources.append(f"blastp:{database}:{blast_res.get('backend_used', 'auto')}")

                # Retrieve missing sequences if needed
                hits_needing_seq: list[dict[str, Any]] = []
                for h in hits:
                    acc = h.get("accession") or h.get("id")
                    h_seq = h.get("sequence") or h.get("hit_sequence")
                    if not h_seq and acc:
                        hits_needing_seq.append(h)
                    elif h_seq:
                        homolog_records.append(
                            {
                                "id": acc or f"hit_{len(homolog_records)}",
                                "accession": acc,
                                "sequence": h_seq,
                                "organism": h.get("organism") or h.get("title"),
                            }
                        )

                if hits_needing_seq:
                    acc_list = [h.get("accession") or h.get("id") for h in hits_needing_seq]
                    try:
                        fasta_res = fetch_fasta(db="protein", ids=acc_list, client=self.ncbi_client)
                        fetched_records = {
                            rec.get("accession") or rec.get("id"): rec.get("sequence")
                            for rec in fasta_res.get("records", [])
                        }
                        for h in hits_needing_seq:
                            acc = h.get("accession") or h.get("id")
                            seq = fetched_records.get(acc)
                            if seq:
                                homolog_records.append(
                                    {
                                        "id": acc,
                                        "accession": acc,
                                        "sequence": seq,
                                        "organism": h.get("organism") or h.get("title"),
                                    }
                                )
                    except Exception as exc:
                        warnings.append(
                            f"Failed to fetch FASTA for {len(acc_list)} BLAST hits: {exc}"
                        )

            except Exception as exc:
                logger.warning("BLAST search failed during variant discovery: %s", exc)
                warnings.append(f"Homolog search failed: {exc}")
                return VariantDiscoveryResult(
                    candidate_id=candidate_id,
                    reference_sequence=clean_seq,
                    homolog_count=0,
                    aligned_homolog_count=0,
                    variants=[],
                    warnings=warnings,
                )

        if not homolog_records:
            warnings.append("No homologs found for candidate sequence.")
            return VariantDiscoveryResult(
                candidate_id=candidate_id,
                reference_sequence=clean_seq,
                homolog_count=0,
                aligned_homolog_count=0,
                variants=[],
                sources=sources,
                warnings=warnings,
            )

        # 2. Build sequence mapping for alignment
        sequences_to_align: dict[str, str] = {candidate_id: clean_seq}
        homolog_metadata: dict[str, dict[str, Any]] = {}

        for idx, h in enumerate(homolog_records):
            h_id = str(h.get("id") or h.get("accession") or f"homolog_{idx}")
            h_seq = str(h.get("sequence", "")).strip().upper()
            if h_seq:
                sequences_to_align[h_id] = h_seq
                homolog_metadata[h_id] = h

        if len(sequences_to_align) <= 1:
            warnings.append("No valid homolog sequences available for multiple sequence alignment.")
            return VariantDiscoveryResult(
                candidate_id=candidate_id,
                reference_sequence=clean_seq,
                homolog_count=len(homolog_records),
                aligned_homolog_count=0,
                variants=[],
                sources=sources,
                warnings=warnings,
            )

        # 3. Align sequences
        try:
            aligned = self.alignment_backend.align(sequences_to_align)
        except Exception as exc:
            logger.error("Multiple sequence alignment failed: %s", exc)
            warnings.append(f"Multiple sequence alignment failed: {exc}")
            return VariantDiscoveryResult(
                candidate_id=candidate_id,
                reference_sequence=clean_seq,
                homolog_count=len(homolog_records),
                aligned_homolog_count=0,
                variants=[],
                sources=sources,
                warnings=warnings,
            )

        # 4. Extract variants
        variants = extract_variants_from_alignment(
            parent_candidate_id=candidate_id,
            aligned_sequences=aligned,
            reference_id=candidate_id,
            homolog_metadata=homolog_metadata,
            ref_cds=ref_cds,
            homolog_cds=homolog_cds,
            region_annotations=region_annotations,
        )

        ranked_variants = variants[:max_variants]

        return VariantDiscoveryResult(
            candidate_id=candidate_id,
            reference_sequence=clean_seq,
            homolog_count=len(homolog_records),
            aligned_homolog_count=len(aligned) - 1,
            variants=ranked_variants,
            provenance="database-derived",
            sources=sources,
            warnings=warnings,
        )


def discover_variants(
    candidate_id: str,
    sequence: str,
    homologs: list[dict[str, Any]] | None = None,
    blast_backend: BlastBackend | None = None,
    alignment_backend: AlignmentBackend | None = None,
    ncbi_client: NcbiClient | None = None,
    ref_cds: str | None = None,
    homolog_cds: Mapping[str, str] | None = None,
    region_annotations: Mapping[str, tuple[int, int]] | None = None,
    database: str = "swissprot",
    max_homologs: int = DEFAULT_MAX_VARIANT_HOMOLOGS,
    max_variants: int = DEFAULT_MAX_VARIANTS_PER_CANDIDATE,
    strict_budget: bool = False,
    blast_options: dict[str, Any] | None = None,
) -> VariantDiscoveryResult:
    """Convenience function to discover natural bacteriocin variants."""
    agent = VariantDiscoveryAgent(
        blast_backend=blast_backend,
        alignment_backend=alignment_backend,
        ncbi_client=ncbi_client,
    )
    return agent.discover(
        candidate_id=candidate_id,
        sequence=sequence,
        homologs=homologs,
        ref_cds=ref_cds,
        homolog_cds=homolog_cds,
        region_annotations=region_annotations,
        database=database,
        max_homologs=max_homologs,
        max_variants=max_variants,
        strict_budget=strict_budget,
        blast_options=blast_options,
    )
