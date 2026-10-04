"""Scientific critic gate for prospective computational bacteriocin designs."""

from __future__ import annotations

import re
from typing import Literal

from .config import MAX_MUTATIONS_PER_DESIGN
from .models import DesignedCandidate

CriticVerdict = Literal[
    "approve_for_computational_testing",
    "approve_with_caveats",
    "needs_more_evidence",
    "reject",
]


class DesignCritic:
    """Scientific critic that enforces conservatism, calibration, and biological constraints."""

    PEDIOCIN_BOX = "YGNGV"

    def review_candidate(
        self,
        candidate: DesignedCandidate,
        parent_class: str | None = None,
        parent_sequence: str | None = None,
    ) -> tuple[CriticVerdict, list[str]]:
        """Review a designed candidate against conservative scientific standards.

        Returns:
            Tuple of (verdict, list_of_critique_notes).
        """
        notes: list[str] = []

        # 1. Experimental validation check
        if candidate.experimentally_validated:
            notes.append("REJECT: Computational design improperly asserts experimental validation.")
            return "reject", notes

        # 2. Provenance check
        if candidate.provenance != "model-predicted":
            notes.append(
                f"REJECT: Designed candidate provenance must be 'model-predicted', "
                f"got '{candidate.provenance}'."
            )
            return "reject", notes

        # 3. Mutation count check
        if len(candidate.mutations) > MAX_MUTATIONS_PER_DESIGN:
            notes.append(
                f"REJECT: Mutation count ({len(candidate.mutations)}) exceeds maximum allowed "
                f"conservative budget ({MAX_MUTATIONS_PER_DESIGN})."
            )
            return "reject", notes

        # 4. Biological motif constraints check
        # Check pediocin box motif for class IIa peptides
        if parent_class == "class_iia" or (
            parent_sequence and self.PEDIOCIN_BOX in parent_sequence
        ):
            # If parent has pediocin box and candidate lost it
            if (
                parent_sequence
                and self.PEDIOCIN_BOX in parent_sequence
                and self.PEDIOCIN_BOX not in candidate.sequence
            ):
                notes.append(
                    f"REJECT: Mutation disrupts essential Class IIa "
                    f"pediocin box motif ({self.PEDIOCIN_BOX})."
                )
                return "reject", notes

            if parent_sequence:
                motif = "KYYGNGV" if "KYYGNGV" in parent_sequence else self.PEDIOCIN_BOX
                box_idx = parent_sequence.find(motif)
                if box_idx != -1:
                    for mut in candidate.mutations:
                        if box_idx <= (mut.position - 1) < box_idx + len(motif):
                            notes.append(
                                f"REJECT: Mutation {mut.reference}{mut.position}{mut.alternate} "
                                f"disrupts essential Class IIa pediocin box motif ({motif})."
                            )
                            return "reject", notes

        # Check cysteine disruption (disulfide / lanthionine bridges)
        for mut in candidate.mutations:
            if mut.reference == "C":
                notes.append(
                    f"REJECT: Mutation {mut.reference}{mut.position}{mut.alternate} "
                    f"alters essential cysteine residue required for structural ring formation."
                )
                return "reject", notes

        # 5. False novelty claims check
        all_text = " ".join(
            candidate.rationale.expected_properties
            + candidate.rationale.natural_variant_support
            + [candidate.candidate_id]
        )
        if re.search(r"\bnovel bacteriocin\b", all_text, re.IGNORECASE) and not re.search(
            r"sequence-novelty|relative to searched databases", all_text, re.IGNORECASE
        ):
            notes.append(
                "REJECT: Standalone claim of 'novel bacteriocin' without database search "
                "provenance. Must be phrased as 'high sequence-novelty signal relative "
                "to searched databases'."
            )
            return "reject", notes

        # 6. Simulator uncertainty evaluation
        uncertainty = candidate.uncertainty
        confidence = uncertainty.get("confidence", 0.5)
        if confidence is not None and confidence < 0.35:
            notes.append(
                f"NEEDS MORE EVIDENCE: Simulator confidence ({confidence:.2f}) is below "
                f"confidence threshold (0.35). Additional computational dose-response or "
                f"time-kill simulation is required."
            )
            return "needs_more_evidence", notes

        # 7. Unsupported radical substitutions
        has_natural_support = any(
            mut.origin == "natural_homolog" or bool(mut.supporting_accessions)
            for mut in candidate.mutations
        )
        has_conservative = any(
            mut.origin == "conservative_substitution" for mut in candidate.mutations
        )

        if not has_natural_support and not has_conservative:
            notes.append(
                "CAVEAT: Mutations lack direct homologous support; treated as exploratory "
                "computational hypothesis."
            )
            return "approve_with_caveats", notes

        notes.append(
            "Approved for downstream computational testing and simulated experiment planning."
        )
        return "approve_for_computational_testing", notes
