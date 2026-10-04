"""Post-Translational Modification (PTM) analysis and uncertainty estimation.

Addresses P3:
- Detects Class I lantibiotic and lasso peptide PTM dependence.
- Identifies putative modification sites (dehydrated Ser/Thr, thioether bridges, macrolactams).
- Quantifies structural uncertainty from unmodeled 3D ring topologies in linear sequence.
- Distinguishes unmodified ribosomal peptides from complex RiPPs requiring enzymes.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

PTMClass = Literal[
    "class_i_lantibiotic",
    "lasso_peptide",
    "class_iia_disulfide",
    "unmodified_ribosomal",
]


class ModificationSite(BaseModel):
    """An inferred post-translational modification site in a bacteriocin sequence."""

    model_config = ConfigDict(frozen=True)

    position: int = Field(..., description="1-indexed residue position")
    residue: str = Field(..., min_length=1, max_length=1)
    modification_type: str = Field(
        ...,
        description=(
            "Type of modification: 'dehydration_candidate', 'thioether_bridge_donor', "
            "'macrolactam_isopeptide', 'disulfide_bridge'"
        ),
    )
    description: str


class PTMProfile(BaseModel):
    """PTM characteristics and associated structural uncertainty for a bacteriocin."""

    model_config = ConfigDict(extra="ignore")

    is_ptm_dependent: bool = Field(
        ...,
        description="True if antimicrobial activity strictly requires PTM maturation",
    )
    ptm_class: PTMClass = Field(..., description="Classified RiPP / PTM family")
    structural_uncertainty_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Epistemic uncertainty penalty (0.0=linear, 0.50=lantibiotic, 0.60=lasso)",
    )
    requires_enzymatic_machinery: bool = Field(
        ...,
        description="Whether biosynthetic gene cluster (BGC) enzymes are required for active form",
    )
    mature_topology_confirmed: bool = Field(
        default=False,
        description="False for in silico sequence hypotheses where ring topology is not solved",
    )
    modification_sites: list[ModificationSite] = Field(default_factory=list)
    modification_summary: dict[str, int] = Field(
        default_factory=dict, description="Counts of putative modification sites"
    )
    notes: list[str] = Field(default_factory=list)


def analyze_ptm_profile(
    sequence: str,
    bacteriocin_class: str | None = None,
    candidate_name: str | None = None,
) -> PTMProfile:
    """Analyze sequence and annotation to infer PTM requirements and structural uncertainty.

    Bacteriocin classification:
    - Class I (Lantibiotics): contain lanthionine/methyllanthionine rings formed from
      dehydrated Ser (Dha) or Thr (Dhb) coupled to Cys.
    - Lasso peptides (Class V): macrolactam ring threaded by a C-terminal tail.
    - Class IIa: unmodified backbone, but stabilized by conserved disulfide bridge(s).
    - Unmodified linear peptides: unmodified ribosomal synthesis.
    """
    seq = sequence.upper().strip()
    cls_lower = (bacteriocin_class or "").lower().strip()
    name_lower = (candidate_name or "").lower().strip()

    is_lantibiotic = (
        cls_lower == "class_i"
        or "lantibiotic" in cls_lower
        or "nisin" in name_lower
        or "subtilin" in name_lower
        or "epidermin" in name_lower
    )
    is_lasso = (
        "lasso" in cls_lower
        or "class_v" in cls_lower
        or "microcin j" in name_lower
        or "microcin_j" in name_lower
    )
    is_class_iia = (
        cls_lower == "class_iia"
        or "pediocin" in name_lower
        or "sakacin" in name_lower
        or "leucocin" in name_lower
        or "enterocin" in name_lower
        or seq.startswith("KYYGNGV")
    )

    sites: list[ModificationSite] = []

    if is_lantibiotic:
        # Scan for Ser/Thr (potential dehydration to Dha/Dhb) and Cys (thioether bridge donor)
        cys_count = 0
        ser_count = 0
        thr_count = 0

        for idx, aa in enumerate(seq, start=1):
            if aa == "C":
                cys_count += 1
                sites.append(
                    ModificationSite(
                        position=idx,
                        residue=aa,
                        modification_type="thioether_bridge_donor",
                        description=f"Cys{idx} putative thioether bridge partner (lanthionine)",
                    )
                )
            elif aa == "S":
                ser_count += 1
                sites.append(
                    ModificationSite(
                        position=idx,
                        residue=aa,
                        modification_type="dehydration_candidate",
                        description=f"Ser{idx} putative dehydration target -> dehydroalanine (Dha)",
                    )
                )
            elif aa == "T":
                thr_count += 1
                sites.append(
                    ModificationSite(
                        position=idx,
                        residue=aa,
                        modification_type="dehydration_candidate",
                        description=f"Thr{idx} putative dehydration target -> Dhb",
                    )
                )

        notes = [
            "Class I lantibiotic: activity requires LanB/LanC/LanM maturation.",
            "Lanthionine ring topology is motif-inferred, not mechanistically folded.",
            "Linear sequences lack steric constraints of mature rings in simulation.",
        ]
        return PTMProfile(
            is_ptm_dependent=True,
            ptm_class="class_i_lantibiotic",
            structural_uncertainty_score=0.50,
            requires_enzymatic_machinery=True,
            mature_topology_confirmed=False,
            modification_sites=sites,
            modification_summary={
                "cysteine_bridge_donors": cys_count,
                "serine_dehydration_candidates": ser_count,
                "threonine_dehydration_candidates": thr_count,
            },
            notes=notes,
        )

    if is_lasso:
        # Lasso peptide: macrolactam ring between N-terminal Gly/Cys/Ala and Asp/Glu at pos 8-9
        n_term = seq[0] if seq else "G"
        sites.append(
            ModificationSite(
                position=1,
                residue=n_term,
                modification_type="macrolactam_isopeptide",
                description=f"{n_term}1 N-terminal isopeptide ring anchor",
            )
        )
        for idx in range(1, min(len(seq), 12)):
            aa = seq[idx]
            if aa in ("D", "E"):
                sites.append(
                    ModificationSite(
                        position=idx + 1,
                        residue=aa,
                        modification_type="macrolactam_isopeptide",
                        description=f"{aa}{idx + 1} putative macrolactam ring acceptor",
                    )
                )

        notes = [
            "Lasso peptide: requires leader peptidase and cyclase for macrolactam ring.",
            "Steric knot confers protease resistance; unconfirmed from sequence alone.",
        ]
        return PTMProfile(
            is_ptm_dependent=True,
            ptm_class="lasso_peptide",
            structural_uncertainty_score=0.60,
            requires_enzymatic_machinery=True,
            mature_topology_confirmed=False,
            modification_sites=sites,
            modification_summary={"lasso_ring_residues": len(sites)},
            notes=notes,
        )

    if is_class_iia:
        # Class IIa: conserved N-terminal disulfide bridge
        cys_positions = [i + 1 for i, aa in enumerate(seq) if aa == "C"]
        for pos in cys_positions:
            sites.append(
                ModificationSite(
                    position=pos,
                    residue="C",
                    modification_type="disulfide_bridge",
                    description=f"Cys{pos} participates in conserved structural disulfide bridge",
                )
            )

        notes = [
            "Class IIa pediocin-like bacteriocin: ribosomally synthesized without enzyme complex.",
            "Conserved disulfide bridge required for receptor-binding conformation.",
        ]
        return PTMProfile(
            is_ptm_dependent=False,  # Ribosomally synthesized without modification machinery
            ptm_class="class_iia_disulfide",
            structural_uncertainty_score=0.15,
            requires_enzymatic_machinery=False,
            mature_topology_confirmed=False,
            modification_sites=sites,
            modification_summary={"disulfide_cysteines": len(cys_positions)},
            notes=notes,
        )

    # Default: Unmodified ribosomal peptide
    cys_count = seq.count("C")
    if cys_count >= 2:
        for idx, aa in enumerate(seq, start=1):
            if aa == "C":
                sites.append(
                    ModificationSite(
                        position=idx,
                        residue=aa,
                        modification_type="disulfide_bridge",
                        description=f"Cys{idx} potential disulfide bridge partner",
                    )
                )

    notes = [
        "Unmodified or linear ribosomal bacteriocin: synthesized as standard prepeptide.",
        "Minimal PTM-induced structural uncertainty.",
    ]
    return PTMProfile(
        is_ptm_dependent=False,
        ptm_class="unmodified_ribosomal",
        structural_uncertainty_score=0.05 if cys_count < 2 else 0.10,
        requires_enzymatic_machinery=False,
        mature_topology_confirmed=False,
        modification_sites=sites,
        modification_summary={"cysteines": cys_count},
        notes=notes,
    )
