"""Deterministic sequence-derived physicochemical descriptors.

Everything in this module is a pure function of the amino-acid sequence, so
descriptors are exactly reproducible and carry
``ParameterSource.SEQUENCE_DERIVED`` provenance. These are *model-predicted*
descriptors computed from published amino-acid scales -- they are not measured
values, and the backend labels them accordingly.

Scales used:
* hydropathy: Kyte & Doolittle (1982)
* hydrophobicity for the hydrophobic moment: Eisenberg consensus (1984)
* side-chain pKa: EMBOSS/Expasy-style set, used in a Henderson-Hasselbalch
  charge model
* average residue masses: standard average isotopic masses
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..schemas import BacteriocinClass

KYTE_DOOLITTLE: dict[str, float] = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

EISENBERG_CONSENSUS: dict[str, float] = {
    "A": 0.62, "R": -2.53, "N": -0.78, "D": -0.90, "C": 0.29,
    "Q": -0.85, "E": -0.74, "G": 0.48, "H": -0.40, "I": 1.38,
    "L": 1.06, "K": -1.50, "M": 0.64, "F": 1.19, "P": 0.12,
    "S": -0.18, "T": -0.05, "W": 0.81, "Y": 0.26, "V": 1.08,
}

RESIDUE_MASS_DA: dict[str, float] = {
    "G": 57.0519, "A": 71.0788, "S": 87.0782, "P": 97.1167, "V": 99.1326,
    "T": 101.1051, "C": 103.1388, "L": 113.1594, "I": 113.1594, "N": 114.1038,
    "D": 115.0886, "Q": 128.1307, "K": 128.1741, "E": 129.1155, "M": 131.1926,
    "H": 137.1411, "F": 147.1766, "R": 156.1875, "Y": 163.1760, "W": 186.2132,
}
WATER_MASS_DA = 18.0153

# positive and negative ionisable groups
PKA_N_TERMINUS = 8.6
PKA_C_TERMINUS = 3.6
PKA_POSITIVE: dict[str, float] = {"K": 10.8, "R": 12.5, "H": 6.5}
PKA_NEGATIVE: dict[str, float] = {"D": 3.9, "E": 4.1, "C": 8.5, "Y": 10.1}

#: ambiguous one-letter codes are replaced by a neutral, average-ish residue
_AMBIGUOUS_SUBSTITUTE = {"X": None, "B": "N", "Z": "Q", "J": "L", "U": "C", "O": "K"}

#: the pediocin box, the canonical class-IIa N-terminal motif
PEDIOCIN_BOX = "YGNGV"

#: reference descriptor values (nisin-A-like) that the potency model centres on
REFERENCE_NET_CHARGE = 3.0
REFERENCE_HYDROPHOBIC_MOMENT = 0.35
REFERENCE_LENGTH = 34


@dataclass(frozen=True)
class PeptideDescriptors:
    """Physicochemical summary of a candidate peptide."""

    sequence: str | None
    length: int
    molecular_weight_da: float | None
    net_charge: float
    net_charge_ph: float
    isoelectric_point: float | None
    gravy: float
    hydrophobic_moment: float
    aliphatic_index: float
    cationic_residue_fraction: float
    cysteine_count: int
    inferred_class: BacteriocinClass
    class_inference_confidence: float
    is_generic_fallback: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


def clean_sequence(sequence: str | None) -> str | None:
    """Uppercase, strip whitespace/gaps, resolve ambiguous codes."""
    if not sequence:
        return None
    seq = "".join(ch for ch in sequence.upper() if ch.isalpha())
    if not seq:
        return None
    out: list[str] = []
    for ch in seq:
        if ch in KYTE_DOOLITTLE:
            out.append(ch)
        elif ch in _AMBIGUOUS_SUBSTITUTE:
            sub = _AMBIGUOUS_SUBSTITUTE[ch]
            if sub is not None:
                out.append(sub)
        # anything else is dropped; schema validation rejects truly invalid chars
    return "".join(out) or None


def net_charge_at_ph(sequence: str, ph: float) -> float:
    """Net charge from the Henderson-Hasselbalch model.

    Each basic group contributes ``1/(1+10**(pH-pKa))`` and each acidic group
    ``-1/(1+10**(pKa-pH))``. Termini are included once each.
    """
    charge = 1.0 / (1.0 + 10 ** (ph - PKA_N_TERMINUS))
    charge -= 1.0 / (1.0 + 10 ** (PKA_C_TERMINUS - ph))
    for residue, pka in PKA_POSITIVE.items():
        n = sequence.count(residue)
        if n:
            charge += n / (1.0 + 10 ** (ph - pka))
    for residue, pka in PKA_NEGATIVE.items():
        n = sequence.count(residue)
        if n:
            charge -= n / (1.0 + 10 ** (pka - ph))
    return charge


def isoelectric_point(sequence: str) -> float:
    """pI by bisection on :func:`net_charge_at_ph` (deterministic, 1e-3 pH)."""
    low, high = 0.0, 14.0
    for _ in range(60):
        mid = 0.5 * (low + high)
        if net_charge_at_ph(sequence, mid) > 0.0:
            low = mid
        else:
            high = mid
        if high - low < 1e-3:
            break
    return round(0.5 * (low + high), 3)


def gravy(sequence: str) -> float:
    """Grand average of hydropathy (Kyte-Doolittle)."""
    return sum(KYTE_DOOLITTLE[a] for a in sequence) / len(sequence)


def hydrophobic_moment(sequence: str, window: int = 11, angle_deg: float = 100.0) -> float:
    """Maximum per-residue hydrophobic moment (Eisenberg) over all windows.

    An alpha-helical periodicity of 100 degrees per residue is assumed; the
    returned value is the largest window-mean moment, which is the standard
    proxy for amphipathicity of a membrane-active peptide.
    """
    n = len(sequence)
    w = min(window, n)
    angle = math.radians(angle_deg)
    best = 0.0
    for start in range(0, n - w + 1):
        sin_sum = 0.0
        cos_sum = 0.0
        for i in range(w):
            h = EISENBERG_CONSENSUS[sequence[start + i]]
            theta = angle * (start + i)
            sin_sum += h * math.sin(theta)
            cos_sum += h * math.cos(theta)
        moment = math.hypot(sin_sum, cos_sum) / w
        best = max(best, moment)
    return best


def aliphatic_index(sequence: str) -> float:
    """Ikai aliphatic index: relative volume of aliphatic side chains."""
    n = len(sequence)
    pct = lambda r: 100.0 * sequence.count(r) / n  # noqa: E731
    return pct("A") + 2.9 * pct("V") + 3.9 * (pct("I") + pct("L"))


def molecular_weight(sequence: str) -> float:
    """Average molecular weight of the unmodified linear peptide.

    Post-translational modifications (lanthionine rings, head-to-tail
    cyclisation) reduce the true mass by ~18 Da per dehydration; this is a
    linear-backbone estimate and the backend flags it as such.
    """
    return sum(RESIDUE_MASS_DA[a] for a in sequence) + WATER_MASS_DA


def infer_class(sequence: str) -> tuple[BacteriocinClass, float, list[str]]:
    """Heuristic structural-class inference from primary sequence.

    Returns ``(class, confidence, notes)``. Confidence is deliberately low for
    everything except the pediocin box, which is a strong, specific motif.
    Post-translational modifications are invisible in primary sequence, so
    lantibiotic calls can only ever be suggestive.
    """
    notes: list[str] = []
    cys = sequence.count("C")
    ser_thr = sequence.count("S") + sequence.count("T")
    n = len(sequence)

    if PEDIOCIN_BOX in sequence[: min(n, 24)] and cys >= 2:
        notes.append("pediocin box YGNGV with >=2 Cys in N-terminal region")
        return BacteriocinClass.CLASS_IIA_PEDIOCIN_LIKE, 0.80, notes
    if PEDIOCIN_BOX in sequence:
        notes.append("pediocin box YGNGV present but not N-terminal")
        return BacteriocinClass.CLASS_IIA_PEDIOCIN_LIKE, 0.55, notes
    if n <= 40 and cys >= 2 and ser_thr / n >= 0.14:
        notes.append(
            "short peptide, Cys>=2 and Ser/Thr-rich: compatible with a lanthionine-"
            "containing class I peptide, but post-translational modification cannot "
            "be confirmed from sequence"
        )
        return BacteriocinClass.CLASS_I_LANTIBIOTIC, 0.35, notes
    if n > 120:
        notes.append("large peptide (>120 aa): bacteriolysin/colicin-like size range")
        return BacteriocinClass.CLASS_III_BACTERIOLYSIN, 0.40, notes
    if n <= 60:
        notes.append("small unmodified-peptide size range")
        return BacteriocinClass.CLASS_IID_UNMODIFIED, 0.25, notes
    notes.append("no diagnostic motif found")
    return BacteriocinClass.UNKNOWN, 0.10, notes


def generic_fallback_descriptors(ph: float = 6.5) -> PeptideDescriptors:
    """Prior for an unknown candidate (no sequence available anywhere).

    Values are the central tendency of characterised small bacteriocins. A
    result built on this must carry a large uncertainty term and a warning --
    it is a placeholder, not a prediction about a specific molecule.
    """
    return PeptideDescriptors(
        sequence=None,
        length=REFERENCE_LENGTH,
        molecular_weight_da=None,
        net_charge=REFERENCE_NET_CHARGE,
        net_charge_ph=ph,
        isoelectric_point=None,
        gravy=0.0,
        hydrophobic_moment=REFERENCE_HYDROPHOBIC_MOMENT,
        aliphatic_index=80.0,
        cationic_residue_fraction=0.10,
        cysteine_count=0,
        inferred_class=BacteriocinClass.UNKNOWN,
        class_inference_confidence=0.0,
        is_generic_fallback=True,
        notes=("no sequence available; generic small-bacteriocin prior used",),
    )


def describe_peptide(sequence: str | None, ph: float = 6.5) -> PeptideDescriptors:
    """Compute the full descriptor set at a given pH."""
    seq = clean_sequence(sequence)
    if seq is None:
        return generic_fallback_descriptors(ph)

    notes: list[str] = []
    inferred, conf, class_notes = infer_class(seq)
    notes.extend(class_notes)
    if seq.count("C") >= 2:
        notes.append(
            "molecular weight is a linear-backbone estimate; any lanthionine or "
            "disulfide modification lowers the true mass"
        )

    cationic = sum(seq.count(r) for r in ("K", "R"))
    return PeptideDescriptors(
        sequence=seq,
        length=len(seq),
        molecular_weight_da=round(molecular_weight(seq), 3),
        net_charge=round(net_charge_at_ph(seq, ph), 4),
        net_charge_ph=ph,
        isoelectric_point=isoelectric_point(seq),
        gravy=round(gravy(seq), 4),
        hydrophobic_moment=round(hydrophobic_moment(seq), 4),
        aliphatic_index=round(aliphatic_index(seq), 2),
        cationic_residue_fraction=round(cationic / len(seq), 4),
        cysteine_count=seq.count("C"),
        inferred_class=inferred,
        class_inference_confidence=conf,
        is_generic_fallback=False,
        notes=tuple(notes),
    )
