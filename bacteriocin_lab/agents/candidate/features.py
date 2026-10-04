"""Deterministic physicochemical features computed from a peptide sequence.

Everything here is a closed-form calculation over the primary sequence, so it is
fully reproducible (contract rule 13) and carries the provenance type
``model-predicted`` rather than ``database-derived``.

IMPORTANT SCIENTIFIC CAVEAT
---------------------------
These formulas assume an unmodified linear peptide. Class I bacteriocins
(lantibiotics such as nisin) carry extensive post-translational modifications --
dehydration of Ser/Thr and lanthionine/methyllanthionine thioether bridges --
and lasso peptides are topologically knotted. For those, molecular weight and
charge computed from the primary sequence are *wrong*, typically by ~18 Da per
dehydration. ``compute_features`` flags this in ``caveats`` instead of silently
reporting a confident-looking number.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

#: Average residue masses in Da (free amino acid minus water).
_RESIDUE_MASS: dict[str, float] = {
    "A": 71.0788, "R": 156.1875, "N": 114.1038, "D": 115.0886, "C": 103.1388,
    "E": 129.1155, "Q": 128.1307, "G": 57.0519, "H": 137.1411, "I": 113.1594,
    "L": 113.1594, "K": 128.1741, "M": 131.1926, "F": 147.1766, "P": 97.1167,
    "S": 87.0782, "T": 101.1051, "W": 186.2132, "Y": 163.1760, "V": 99.1326,
}

_WATER_MASS = 18.01528

#: Kyte & Doolittle (1982) hydropathy index. Mean over the sequence is GRAVY.
_KYTE_DOOLITTLE: dict[str, float] = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

#: Side-chain pKa values (EMBOSS set) plus terminal pKas.
_PKA_POSITIVE: dict[str, float] = {"K": 10.8, "R": 12.5, "H": 6.5}
_PKA_NEGATIVE: dict[str, float] = {"D": 3.9, "E": 4.1, "C": 8.5, "Y": 10.1}
_PKA_N_TERM = 8.6
_PKA_C_TERM = 3.6

STANDARD_RESIDUES = frozenset(_RESIDUE_MASS)

#: Residues usually counted as hydrophobic when describing membrane-active peptides.
_HYDROPHOBIC = frozenset("AVLIMFWC")
_AROMATIC = frozenset("FWY")

#: Bacteriocin classes whose mature form is post-translationally modified enough
#: that primary-sequence mass and charge are unreliable.
MODIFIED_CLASSES = frozenset(
    {"class_i", "lantibiotic", "lasso_peptide", "sactipeptide", "glycocin", "circular"}
)


class SequenceValidationError(ValueError):
    """Raised when a sequence cannot be interpreted as a peptide."""


class PeptideFeatures(BaseModel):
    """Computed features for one peptide. All fields are ``model-predicted``."""

    model_config = ConfigDict(extra="forbid")

    sequence_length: int
    molecular_weight: float = Field(description="Average mass in Da, unmodified linear peptide.")
    net_charge: float = Field(description="Net charge at ``charge_ph``, Henderson-Hasselbalch.")
    charge_ph: float
    charge_density: float = Field(description="net_charge / sequence_length.")
    gravy: float = Field(description="Kyte-Doolittle grand average of hydropathy.")
    hydrophobic_fraction: float
    aromatic_fraction: float
    cysteine_count: int
    max_disulfide_bonds: int = Field(description="cysteine_count // 2; an upper bound only.")
    residue_composition: dict[str, float] = Field(
        default_factory=dict, description="Fraction of each residue present."
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Reasons these numbers may not describe the mature peptide.",
    )


def normalise_sequence(sequence: str) -> str:
    """Upper-case and strip whitespace; reject anything non-standard.

    Raises:
        SequenceValidationError: On an empty sequence or a non-standard residue.
            Ambiguity codes (B, J, O, U, X, Z) are rejected rather than guessed,
            because silently substituting a residue would corrupt the mass and
            charge of every downstream calculation.
    """
    cleaned = "".join(sequence.split()).upper()
    if not cleaned:
        raise SequenceValidationError("Sequence is empty")

    unknown = sorted(set(cleaned) - STANDARD_RESIDUES)
    if unknown:
        raise SequenceValidationError(
            f"Sequence contains non-standard residue(s) {unknown}; "
            "only the 20 standard amino acids are supported"
        )
    return cleaned


def molecular_weight(sequence: str) -> float:
    """Average molecular weight in Da of the unmodified linear peptide."""
    seq = normalise_sequence(sequence)
    return round(sum(_RESIDUE_MASS[r] for r in seq) + _WATER_MASS, 4)


def net_charge(sequence: str, ph: float = 7.0) -> float:
    """Net charge at ``ph`` via Henderson-Hasselbalch over ionisable groups.

    Both termini are included. Protonation fraction of a basic group is
    ``1 / (1 + 10**(pH - pKa))``; deprotonation of an acidic group is
    ``1 / (1 + 10**(pKa - pH))``.
    """
    seq = normalise_sequence(sequence)
    if not 0.0 <= ph <= 14.0:
        raise ValueError(f"pH must be within 0-14, got {ph}")

    charge = 1.0 / (1.0 + 10 ** (ph - _PKA_N_TERM))
    charge -= 1.0 / (1.0 + 10 ** (_PKA_C_TERM - ph))

    for residue, pka in _PKA_POSITIVE.items():
        charge += seq.count(residue) / (1.0 + 10 ** (ph - pka))
    for residue, pka in _PKA_NEGATIVE.items():
        charge -= seq.count(residue) / (1.0 + 10 ** (pka - ph))

    return round(charge, 4)


def gravy(sequence: str) -> float:
    """Grand average of hydropathy (mean Kyte-Doolittle index)."""
    seq = normalise_sequence(sequence)
    return round(sum(_KYTE_DOOLITTLE[r] for r in seq) / len(seq), 4)


def compute_features(
    sequence: str,
    *,
    ph: float = 7.0,
    bacteriocin_class: str | None = None,
) -> PeptideFeatures:
    """Compute the full feature set for one peptide.

    Args:
        sequence: Primary sequence, standard one-letter codes.
        ph: pH at which to evaluate net charge. Pass the pH the experiment will
            actually run at -- charge is the main driver of the initial
            electrostatic association with an anionic bacterial membrane, and it
            shifts meaningfully across the pH range bacteriocin assays use.
        bacteriocin_class: Used only to attach caveats for modified classes.

    Raises:
        SequenceValidationError: If the sequence is unusable.
    """
    seq = normalise_sequence(sequence)
    length = len(seq)

    composition = {r: round(seq.count(r) / length, 4) for r in sorted(set(seq))}
    cys = seq.count("C")

    caveats: list[str] = []
    cls = (bacteriocin_class or "").strip().lower()
    if cls in MODIFIED_CLASSES:
        caveats.append(
            f"Class '{bacteriocin_class}' is post-translationally modified; molecular_weight "
            "and net_charge are computed from the primary sequence and do not describe the "
            "mature peptide (each dehydration removes ~18 Da and thioether bridges alter "
            "both mass and topology)."
        )
    if cys >= 2:
        caveats.append(
            f"{cys} cysteines present; max_disulfide_bonds is a combinatorial upper bound, "
            "not a predicted bonding pattern. Actual pairing requires structure prediction."
        )

    return PeptideFeatures(
        sequence_length=length,
        molecular_weight=molecular_weight(seq),
        net_charge=net_charge(seq, ph),
        charge_ph=ph,
        charge_density=round(net_charge(seq, ph) / length, 5),
        gravy=gravy(seq),
        hydrophobic_fraction=round(sum(seq.count(r) for r in _HYDROPHOBIC) / length, 4),
        aromatic_fraction=round(sum(seq.count(r) for r in _AROMATIC) / length, 4),
        cysteine_count=cys,
        max_disulfide_bonds=cys // 2,
        residue_composition=composition,
        caveats=caveats,
    )


def kmer_profile(sequence: str, k: int = 3) -> set[str]:
    """Set of k-mers in the sequence, used for the similarity measure."""
    seq = normalise_sequence(sequence)
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    if len(seq) < k:
        return {seq}
    return {seq[i : i + k] for i in range(len(seq) - k + 1)}


def sequence_similarity(a: str, b: str, k: int = 3) -> float:
    """Jaccard similarity over k-mers, in ``[0, 1]``.

    Chosen over alignment because it is symmetric, deterministic, needs no
    substitution matrix or gap-penalty choices to justify, and is cheap enough
    to run over every pair during diversity selection. It is a coarse proxy:
    it detects shared motifs (the conserved YGNGV motif of class IIa
    bacteriocins, for instance) but says nothing about structural homology.
    """
    pa, pb = kmer_profile(a, k), kmer_profile(b, k)
    union = pa | pb
    if not union:
        return 1.0
    return round(len(pa & pb) / len(union), 6)


__all__ = [
    "MODIFIED_CLASSES",
    "STANDARD_RESIDUES",
    "PeptideFeatures",
    "SequenceValidationError",
    "compute_features",
    "gravy",
    "kmer_profile",
    "molecular_weight",
    "net_charge",
    "normalise_sequence",
    "sequence_similarity",
]
