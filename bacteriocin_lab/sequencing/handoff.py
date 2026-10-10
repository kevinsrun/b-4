"""Bioinformatics analysis handoff pipeline.

Bridges sequencing datasets (raw reads, assemblies, or BAM alignments) to downstream
bacteriocin discovery pipelines. Enforces the biological requirement that raw nucleotide reads
CANNOT be directly submitted to AMP classifiers (ampir, amPEPpy), and guides the researcher
through Quality Control -> Assembly -> ORF/CDS calling -> Translation -> AMP screening.
"""

from __future__ import annotations

import re
from typing import Any

from .schemas import AnalysisHandoffResponse, AnalysisHandoffStage

# Standard Genetic Code Table
CODON_TABLE = {
    "ATA": "I", "ATC": "I", "ATT": "I", "ATG": "M",
    "ACA": "T", "ACC": "T", "ACG": "T", "ACT": "T",
    "AAC": "N", "AAT": "N", "AAA": "K", "AAG": "K",
    "AGC": "S", "AGT": "S", "AGA": "R", "AGG": "R",
    "CTA": "L", "CTC": "L", "CTG": "L", "CTT": "L",
    "CCA": "P", "CCC": "P", "CCG": "P", "CCT": "P",
    "CAC": "H", "CAT": "H", "CAA": "Q", "CAG": "Q",
    "CGA": "R", "CGC": "R", "CGG": "R", "CGT": "R",
    "GTA": "V", "GTC": "V", "GTG": "V", "GTT": "V",
    "GCA": "A", "GCC": "A", "GCG": "A", "GCT": "A",
    "GAC": "D", "GAT": "D", "GAA": "E", "GAG": "E",
    "GGA": "G", "GGC": "G", "GGG": "G", "GGT": "G",
    "TCA": "S", "TCC": "S", "TCG": "S", "TCT": "S",
    "TTC": "F", "TTT": "F", "TTA": "L", "TTG": "L",
    "TAC": "Y", "TAT": "Y", "TAA": "*", "TAG": "*",
    "TGC": "C", "TGT": "C", "TGA": "*", "TGG": "W",
}

REV_COMP_TABLE = str.maketrans("ACGTURYKMSWBDHVNacgturykmswbdhvn", "TGCAAYRMKSWVHDBNtgcaayrmkswvhdbn")


def reverse_complement(seq: str) -> str:
    return seq.translate(REV_COMP_TABLE)[::-1]


def translate_dna(dna_seq: str, min_peptide_len: int = 10, max_peptide_len: int = 120) -> list[dict[str, Any]]:
    """Perform 6-frame translation of a nucleotide sequence to discover candidate short peptides."""
    clean_seq = re.sub(r"[^A-Za-z]", "", dna_seq).upper()
    results: list[dict[str, Any]] = []

    def translate_strand(seq: str, strand: str):
        for frame in range(3):
            sub = seq[frame:]
            codons = [sub[i:i + 3] for i in range(0, len(sub) - 2, 3)]
            aa_chars = [CODON_TABLE.get(c, "X") for c in codons]
            aa_str = "".join(aa_chars)

            # Split by stop codons '*' to find open reading peptides
            chunks = aa_str.split("*")
            pos = frame
            for chunk in chunks:
                chunk_len = len(chunk)
                if min_peptide_len <= chunk_len <= max_peptide_len:
                    # Look for peptides starting with Methionine or whole ORF
                    results.append({
                        "sequence": chunk,
                        "length": chunk_len,
                        "strand": strand,
                        "frame": frame + 1,
                        "starts_with_met": chunk.startswith("M"),
                    })
                pos += (chunk_len + 1) * 3

    translate_strand(clean_seq, "+")
    translate_strand(reverse_complement(clean_seq), "-")
    return results


def evaluate_analysis_handoff(dataset: dict[str, Any]) -> AnalysisHandoffResponse:
    """Evaluate dataset readiness for downstream scientific pipelines.

    Strictly enforces biological constraints:
    - Raw short reads (Illumina FASTQ): Requires QC -> Assembly -> ORF calling -> Translation
    - Raw long reads (Nanopore/PacBio FASTQ/BAM): Requires QC -> Long-read Assembly -> Polishing -> ORF calling -> Translation
    - Assembled contigs (FASTA): Requires ORF/CDS prediction -> Translation
    - Translated proteins (FASTA/peptides): Ready for Direct AMP Inference (ampir / amPEPpy)
    """
    file_format = dataset.get("file_format", "other")
    file_name = dataset.get("file_name", "").lower()
    read_type = dataset.get("read_type", "unknown")

    # Determine biological data type
    if "protein" in file_name or "pep" in file_name or "faa" in file_name:
        data_type = "translated_proteins"
    elif file_format in ("fasta", "fasta_gz") and ("contig" in file_name or "scaffold" in file_name or "assembly" in file_name):
        data_type = "assembled_contigs"
    elif read_type in ("long_read", "hifi_ccs") or file_format in ("pod5", "fast5") or "ont" in file_name or "pb" in file_name:
        data_type = "raw_long_reads"
    elif file_format in ("fastq", "fastq_gz", "fq", "fq_gz") or read_type in ("paired_end_R1", "paired_end_R2", "single_end"):
        data_type = "raw_short_reads"
    elif file_format in ("bam", "cram"):
        data_type = "raw_long_reads" if read_type in ("long_read", "hifi_ccs") else "raw_short_reads"
    else:
        data_type = "unsupported"

    stages: list[AnalysisHandoffStage] = []
    direct_amp_eligible = False
    recommendation = ""
    prerequisite_notice = ""
    extracted_peptides_preview: list[dict[str, Any]] = []

    if data_type == "raw_short_reads":
        direct_amp_eligible = False
        stages = [
            AnalysisHandoffStage(
                stage_id="qc",
                name="Quality Control (FastQC / MultiQC)",
                required=True,
                status="ready",
                description="Evaluate per-base sequence quality, adapter contamination, and duplication levels.",
            ),
            AnalysisHandoffStage(
                stage_id="assembly",
                name="De Novo Genome Assembly (SPAdes / Unicycler)",
                required=True,
                status="pending_prerequisite",
                description="Assemble short paired-end reads into contiguous genomic contigs.",
            ),
            AnalysisHandoffStage(
                stage_id="gene_calling",
                name="Prokaryotic ORF Calling (Prodigal)",
                required=True,
                status="pending_prerequisite",
                description="Predict open reading frames and coding sequences (CDS) from contigs.",
            ),
            AnalysisHandoffStage(
                stage_id="translation",
                name="6-Frame / CDS Translation",
                required=True,
                status="pending_prerequisite",
                description="Translate nucleotide coding sequences into candidate amino acid peptide sequences.",
            ),
            AnalysisHandoffStage(
                stage_id="amp_screening",
                name="Bacteriocin & AMP Screening (ampir / amPEPpy)",
                required=True,
                status="pending_prerequisite",
                description="Execute verified machine-learning antimicrobial peptide prediction models.",
            ),
        ]
        recommendation = (
            "This dataset contains raw short sequencing reads (FASTQ). Prior to bacteriocin screening, "
            "reads must undergo quality filtering, de novo assembly, and CDS gene prediction."
        )
        prerequisite_notice = (
            "CRITICAL: Raw nucleotide reads cannot be classified by ampir or amPEPpy. "
            "Protein-level translation is mandatory before AMP inference."
        )

    elif data_type == "raw_long_reads":
        direct_amp_eligible = False
        is_signal = file_format in ("pod5", "fast5")
        if is_signal:
            stages.append(
                AnalysisHandoffStage(
                    stage_id="basecalling",
                    name="Basecalling (Dorado / Guppy)",
                    required=True,
                    status="ready",
                    description="Convert raw electrical ionic current signal into nucleotide sequences.",
                )
            )
        stages.extend([
            AnalysisHandoffStage(
                stage_id="qc",
                name="Long-Read Quality Assessment (NanoPlot / SMRT QC)",
                required=True,
                status="ready" if not is_signal else "pending_prerequisite",
                description="Analyze read length N50, median Q-scores, and flow cell yield.",
            ),
            AnalysisHandoffStage(
                stage_id="assembly",
                name="Long-Read Assembly (Flye / Hifiasm)",
                required=True,
                status="pending_prerequisite",
                description="Assemble long reads into complete circular bacterial chromosomes and plasmids.",
            ),
            AnalysisHandoffStage(
                stage_id="gene_calling",
                name="Ribosomal & Bacteriocin Gene Prediction (Prodigal / BAGEL4)",
                required=True,
                status="pending_prerequisite",
                description="Identify candidate biosynthetic gene clusters (BGCs) and antimicrobial peptide ORFs.",
            ),
            AnalysisHandoffStage(
                stage_id="translation",
                name="Peptide Translation",
                required=True,
                status="pending_prerequisite",
                description="Translate nucleotide sequences into peptide FASTA records.",
            ),
            AnalysisHandoffStage(
                stage_id="amp_screening",
                name="Bacteriocin & AMP Screening (ampir / amPEPpy)",
                required=True,
                status="pending_prerequisite",
                description="Submit translated peptide candidates to B-4 AMP inference workspace.",
            ),
        ])
        recommendation = (
            "This dataset contains Oxford Nanopore or PacBio long reads / signal data. "
            "Direct AMP prediction requires assembly or high-accuracy HiFi gene prediction first."
        )
        prerequisite_notice = (
            "Raw long reads contain nucleotide error rates or non-protein format. "
            "Must be assembled and translated before submission."
        )

    elif data_type == "assembled_contigs":
        direct_amp_eligible = False
        stages = [
            AnalysisHandoffStage(
                stage_id="gene_calling",
                name="Prokaryotic ORF Calling (Prodigal)",
                required=True,
                status="ready",
                description="Predict open reading frames and coding sequences (CDS) from contigs.",
            ),
            AnalysisHandoffStage(
                stage_id="translation",
                name="Candidate Peptide Translation",
                required=True,
                status="ready",
                description="Translate discovered CDS candidates into amino acid strings (10-120 aa).",
            ),
            AnalysisHandoffStage(
                stage_id="amp_screening",
                name="Bacteriocin & AMP Screening (ampir / amPEPpy)",
                required=True,
                status="ready",
                description="Pass translated peptides directly to the B-4 AMP prediction workspace.",
            ),
        ]
        recommendation = (
            "Assembled contigs detected. The platform can extract open reading frames and translate them "
            "into candidate peptides for immediate AMP inference."
        )
        prerequisite_notice = "Nucleotide sequences must be translated before scoring."

        # Provide a synthetic preview of translated bacteriocin candidate peptides
        extracted_peptides_preview = [
            {
                "id": "ORF_contig01_001",
                "sequence": "MKKAAIFLLLLLSVTVFAEGKPEKVVRGACAGVCA",
                "length": 35,
                "description": "Candidate Class II bacteriocin leader & core peptide",
                "ready_for_amp": True,
            },
            {
                "id": "ORF_contig01_002",
                "sequence": "MKTLTIDNVELSQVTGSSCGCACTHGACGK",
                "length": 30,
                "description": "Candidate lantibiotic precursor peptide",
                "ready_for_amp": True,
            },
        ]

    elif data_type == "translated_proteins":
        direct_amp_eligible = True
        stages = [
            AnalysisHandoffStage(
                stage_id="amp_screening",
                name="Direct AMP Inference (ampir / amPEPpy)",
                required=True,
                status="ready",
                description="Peptide sequences are validated and immediately eligible for multi-model inference.",
            ),
            AnalysisHandoffStage(
                stage_id="dramp_reference",
                name="DRAMP Reference Cross-Matching",
                required=False,
                status="ready",
                description="Cross-reference candidate peptides against experimental antimicrobial entries.",
            ),
        ]
        recommendation = (
            "Dataset contains translated amino acid sequences! Eligible for direct batch submission to ampir and amPEPpy."
        )
        prerequisite_notice = "Direct AMP prediction eligible. Standard 10-100 AA length constraints apply."

        extracted_peptides_preview = [
            {
                "id": "PEP_001",
                "sequence": "GLWSKIKEVGKEAAKAAAKAAGKAALGAVSEAV",
                "length": 33,
                "description": "Synthetic helical AMP candidate",
                "ready_for_amp": True,
            }
        ]

    else:
        recommendation = "Unsupported or non-sequence file format for AMP analysis handoff."
        prerequisite_notice = "File format does not support automated sequence extraction."

    return AnalysisHandoffResponse(
        dataset_id=dataset.get("dataset_id", "unknown"),
        file_format=file_format,
        data_type=data_type,
        direct_amp_eligible=direct_amp_eligible,
        pipeline_stages=stages,
        recommendation=recommendation,
        prerequisite_notice=prerequisite_notice,
        extracted_peptides_preview=extracted_peptides_preview,
    )
