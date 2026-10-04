from __future__ import annotations

import logging

logger = logging.getLogger("b4_variant.cds")

CODON_TABLE: dict[str, str] = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}


def clean_sequence(seq: str) -> str:
    """Normalize nucleotide sequence: uppercase, strip whitespace, replace U with T."""
    return "".join(seq.split()).upper().replace("U", "T")


def translate_cds(cds: str, strip_stop: bool = True) -> str:
    """Translate a coding sequence (CDS) using the standard genetic code.

    Args:
        cds: Nucleotide sequence string.
        strip_stop: If True, trailing stop codon ('*') is omitted.

    Returns:
        Amino acid string.
    """
    clean_cds = clean_sequence(cds)
    aa_list: list[str] = []
    limit = len(clean_cds) - (len(clean_cds) % 3)
    for i in range(0, limit, 3):
        codon = clean_cds[i : i + 3]
        aa = CODON_TABLE.get(codon, "X")
        aa_list.append(aa)

    protein = "".join(aa_list)
    if strip_stop and protein.endswith("*"):
        protein = protein[:-1]
    return protein


def verify_cds_translation(cds: str, protein: str) -> tuple[bool, str]:
    """Verify that a given CDS translates exactly to the provided protein sequence.

    Args:
        cds: Nucleotide sequence string.
        protein: Target amino acid sequence string.

    Returns:
        tuple (is_valid, reason_string)
    """
    if not cds or not cds.strip():
        return False, "CDS is empty"
    if not protein or not protein.strip():
        return False, "Protein sequence is empty"

    clean_prot = "".join(protein.split()).upper().rstrip("*")
    translated = translate_cds(cds, strip_stop=True)

    if translated == clean_prot:
        return True, "Translation matches protein sequence perfectly"

    if translated.startswith(clean_prot) and len(translated) == len(clean_prot) + 1:
        # Accept if extra terminal stop codon was present
        return True, "Translation matches protein sequence (including stop codon)"

    return (
        False,
        (
            f"CDS translation mismatch: translated length {len(translated)} vs protein "
            f"{len(clean_prot)}. '{translated[:12]}...' != '{clean_prot[:12]}...'"
        ),
    )


def derive_codon_change(
    ref_cds: str | None,
    hom_cds: str | None,
    ref_protein_pos: int,
    hom_protein_pos: int | None,
    ref_aa: str,
    alt_aa: str,
) -> tuple[str | None, int | None, str]:
    """Derive nucleotide change string, codon position, and variant type from CDS information.

    Args:
        ref_cds: Reference nucleotide coding sequence.
        hom_cds: Homolog nucleotide coding sequence.
        ref_protein_pos: 1-indexed ungapped coordinate in reference protein.
        hom_protein_pos: 1-indexed ungapped coordinate in homolog protein (if mapped).
        ref_aa: Reference amino acid or gap character.
        alt_aa: Homolog amino acid or gap character.

    Returns:
        tuple of (nucleotide_change, codon_position_1indexed, variant_type)
    """
    if ref_aa == "-":
        return None, None, "insertion"
    if alt_aa == "-":
        codon_pos = (ref_protein_pos - 1) * 3 + 1 if ref_cds else None
        return None, codon_pos, "deletion"

    default_type = (
        "stop_gain" if alt_aa == "*" else ("synonymous" if ref_aa == alt_aa else "missense")
    )

    if not ref_cds or not ref_cds.strip():
        return None, None, default_type

    clean_ref = clean_sequence(ref_cds)
    ref_start = (ref_protein_pos - 1) * 3
    if ref_start + 3 > len(clean_ref):
        return None, None, default_type

    ref_codon = clean_ref[ref_start : ref_start + 3]
    codon_pos_1indexed = ref_start + 1

    if not hom_cds or not hom_cds.strip() or hom_protein_pos is None:
        return None, codon_pos_1indexed, default_type

    clean_hom = clean_sequence(hom_cds)
    hom_start = (hom_protein_pos - 1) * 3
    if hom_start + 3 > len(clean_hom):
        return None, codon_pos_1indexed, default_type

    hom_codon = clean_hom[hom_start : hom_start + 3]

    if ref_codon == hom_codon:
        if ref_aa == alt_aa:
            return None, codon_pos_1indexed, "synonymous"
        return None, codon_pos_1indexed, default_type

    # Pinpoint nucleotide difference
    diff_indices = [i for i in range(3) if ref_codon[i] != hom_codon[i]]
    if len(diff_indices) == 1:
        idx = diff_indices[0]
        nt_coord = codon_pos_1indexed + idx
        nt_change = f"c.{nt_coord}{ref_codon[idx]}>{hom_codon[idx]}"
    else:
        nt_change = f"c.{codon_pos_1indexed}_{codon_pos_1indexed + 2}{ref_codon}>{hom_codon}"

    variant_type = (
        "synonymous" if ref_aa == alt_aa else ("stop_gain" if alt_aa == "*" else "missense")
    )
    return nt_change, codon_pos_1indexed, variant_type
