"""Conservative sequence modification -- the inverse-design stretch goal.

Scope is deliberately narrow. This module proposes *small, explainable, fully
reversible* variants of a parent bacteriocin and labels them as computational
proposals with ``origin="modified"`` and ``validation_status="unvalidated"``.

What it will not do:

* It does not do de novo generation. There is no trained generative model here,
  and emitting plausible-looking novel sequences without one would manufacture
  false confidence.
* It does not touch conserved motif positions, because the motif is usually what
  makes the class work -- the YGNGV box of class IIa bacteriocins sits in the
  receptor-binding region.
* It does not touch cysteines, because disulfide topology is load-bearing for
  the fold and a lost bridge is a confound, not a variable.
* It makes at most ``max_substitutions`` changes, so a result stays attributable
  to a specific substitution.

Every variant is a hypothesis-generating device: the point is to probe which
property drives activity, not to assert an improvement. Disabled unless
``constraints.allow_sequence_modification`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass

from .features import normalise_sequence

#: Motifs never altered. Conserved across the class and functionally implicated.
PROTECTED_MOTIFS: tuple[str, ...] = ("YGNGV", "YGNGL")

#: Residues never substituted: cysteines (disulfides), glycines in the motif
#: region (backbone flexibility), prolines (turn geometry).
PROTECTED_RESIDUES = frozenset("CP")

#: Conservative swaps that raise net positive charge while keeping size and
#: hydrophobicity class roughly intact. Used to probe the electrostatic
#: association hypothesis.
_CHARGE_INCREASING: dict[str, str] = {
    "Q": "K",  # isosteric, polar -> cationic
    "N": "K",  # polar -> cationic
    "T": "R",  # polar -> cationic
    "S": "K",  # polar -> cationic
    "A": "K",  # small -> cationic
}

#: Conservative swaps that lower net charge, for the negative control arm.
_CHARGE_DECREASING: dict[str, str] = {
    "K": "Q",
    "R": "T",
}


@dataclass(frozen=True)
class SequenceVariant:
    """One proposed variant plus the exact changes that produced it."""

    sequence: str
    modifications: list[str]
    design_intent: str

    def __post_init__(self) -> None:
        if not self.modifications:
            raise ValueError("A variant must record at least one modification")


def _protected_positions(sequence: str) -> set[int]:
    """Indices that must not be substituted."""
    protected: set[int] = set()
    for motif in PROTECTED_MOTIFS:
        start = sequence.find(motif)
        while start != -1:
            protected.update(range(start, start + len(motif)))
            start = sequence.find(motif, start + 1)
    for index, residue in enumerate(sequence):
        if residue in PROTECTED_RESIDUES:
            protected.add(index)
    # Termini are frequently involved in processing and receptor contact.
    protected.update({0, len(sequence) - 1})
    return protected


def _substitute(
    sequence: str,
    table: dict[str, str],
    max_substitutions: int,
    intent: str,
) -> SequenceVariant | None:
    """Apply up to ``max_substitutions`` swaps from ``table``, N-to-C order.

    Deterministic: the same parent and table always produce the same variant.
    """
    if max_substitutions <= 0:
        return None

    protected = _protected_positions(sequence)
    residues = list(sequence)
    modifications: list[str] = []

    for index, residue in enumerate(residues):
        if len(modifications) >= max_substitutions:
            break
        if index in protected:
            continue
        replacement = table.get(residue)
        if replacement is None:
            continue
        residues[index] = replacement
        # 1-based position, matching how substitutions are written in the literature.
        modifications.append(f"{residue}{index + 1}{replacement}")

    if not modifications:
        return None
    return SequenceVariant(
        sequence="".join(residues), modifications=modifications, design_intent=intent
    )


def propose_variants(
    parent_sequence: str,
    *,
    max_variants: int = 2,
    max_substitutions: int = 2,
) -> list[SequenceVariant]:
    """Propose conservative variants of ``parent_sequence``.

    Returns a charge-increased variant and, if room remains, a charge-decreased
    one. The pair is the useful unit: together they bracket the parent and let a
    simulation sweep test whether activity tracks net charge at all. A single
    variant in one direction cannot distinguish "charge matters" from "this
    particular substitution helped".

    Raises:
        SequenceValidationError: If the parent sequence is unusable.
    """
    sequence = normalise_sequence(parent_sequence)
    if max_variants <= 0:
        return []

    variants: list[SequenceVariant] = []

    increased = _substitute(
        sequence,
        _CHARGE_INCREASING,
        max_substitutions,
        "Raise net positive charge to probe whether electrostatic association with the "
        "anionic envelope is rate-limiting.",
    )
    if increased is not None:
        variants.append(increased)

    if len(variants) < max_variants:
        decreased = _substitute(
            sequence,
            _CHARGE_DECREASING,
            max_substitutions,
            "Lower net positive charge as the opposing arm of the charge-dependence test; "
            "serves as a negative control for the charge hypothesis.",
        )
        if decreased is not None and decreased.sequence != sequence:
            variants.append(decreased)

    return variants[:max_variants]


__all__ = ["PROTECTED_MOTIFS", "PROTECTED_RESIDUES", "SequenceVariant", "propose_variants"]
