"""Project-centered scientific research service coordinating samples, sequencing, sequences, and CRISPR studies."""

from __future__ import annotations

import difflib
import hashlib
import time
from pathlib import Path
from typing import Any

from .schemas import (
    AnnotatedSequence,
    BiologicalSample,
    CrisprObjective,
    CrisprTargetRegion,
    ProjectCreateRequest,
    ResearchProject,
    SampleCreateRequest,
    SequenceAnnotation,
    SequenceComparisonResult,
    SequenceVariant,
)
from .store import ProjectStore, utc_now

DEFAULT_PROJECTS_DB = Path("artifacts/projects/projects.sqlite3")


class ProjectService:
    """Manages project traceability across biological samples, sequencing, and analyses."""

    def __init__(self, db_path: Path | str = DEFAULT_PROJECTS_DB):
        self.store = ProjectStore(db_path)
        self._ensure_seed_projects()

    def _ensure_seed_projects(self):
        """Populate realistic scientific bacteriocin projects and CRISPR reference sequences if empty."""
        existing = self.store.list_projects()
        if existing:
            return

        now = utc_now()

        # -------------------------------------------------------------
        # PROJECT 1: Lactococcus lactis Nisin BGC & Immunity
        # -------------------------------------------------------------
        p1_id = "proj_lactis_nisin"
        s1_id = "samp_llactis_atcc11454"
        seq1_dna_id = "seq_nisin_cluster_ref"
        seq1_pep_id = "seq_nisi_immunity_pep"
        study1_id = "crispr_nisi_immunity_01"

        # Annotated DNA sequence: NisA precursor and NisI immunity region (480 bp)
        # Nisin A coding sequence: ATGAATAAA... (57 aa precursor)
        nisin_dna = (
            "ATGAATAAAACAAACTTATTATTACATGAAGTAACAGGATCATCATATACTTTTACTAGT"
            "ACTACAAATGTAAACTCTTTAAGTGCTGGATGTTTAACTGGTTGTTCTACTGGTTGTACA"
            "ACTGGTTGTTGTGCTACATGTTCTTGTTCTATTCATGTTTCTAAATAAGTTTTAATTTTT"
            "TAAGGAGGTGTTTTTATGAAGAAACTCTTAACTCTTACTTTAATTGTAGCACTAATTGTT"
            "TCTGGATGTGGAGATAATAGTGAGAAAAGTAGTAAAGATAAAAATTCAAGTGATAAACAA"
            "AAAAATAAAGACGATAAATCAAATAAAAATGAAAAAAATGATAAACAAAAAAAGCAAGAG"
            "AAGAAGGATAGTGACAAAAATAGTGACAAAGAGAAAGATAGTGACAAAGAAAAAGAGAAA"
            "GATAGTGACAAAGAAAAAGAGAAAGATAGTGACAAAGAAAAAGAGAAAGATAGTGACAAA"
        )

        p1_seq_dna = AnnotatedSequence(
            sequence_id=seq1_dna_id,
            project_id=p1_id,
            sample_id=s1_id,
            source_dataset_id="ds_bs_miseq_r1",
            name="Lactococcus lactis nisin A (nisA) and NisI immunity locus",
            molecule_type="dna",
            sequence=nisin_dna,
            length=len(nisin_dna),
            description="Reference locus encoding lantibiotic Nisin A precursor and NisI lipoprotein immunity factor",
            genomic_coordinates="NC_007799.1:1820410-1820890",
            reference_version="v2.1",
            orientation="5to3",
            annotations=[
                SequenceAnnotation(
                    annotation_id="ann_nisA_cds",
                    feature_type="cds",
                    name="nisA",
                    start=1,
                    end=174,
                    strand="+",
                    qualifiers={"gene": "nisA", "product": "nisin A precursor peptide"},
                    evidence_ids=["PMID:2839491", "DRAMP:DRAMP00001"],
                ),
                SequenceAnnotation(
                    annotation_id="ann_nisA_core",
                    feature_type="core_peptide",
                    name="Nisin A Core Peptide",
                    start=70,
                    end=171,
                    strand="+",
                    qualifiers={"cleavage_site": "Arg23-Ile24"},
                    evidence_ids=["PMID:2839491"],
                ),
                SequenceAnnotation(
                    annotation_id="ann_nisI_cds",
                    feature_type="immunity_protein",
                    name="nisI",
                    start=195,
                    end=480,
                    strand="+",
                    qualifiers={"gene": "nisI", "product": "nisin immunity lipoprotein NisI"},
                    evidence_ids=["PMID:8474195"],
                ),
                SequenceAnnotation(
                    annotation_id="ann_crispr_target_1",
                    feature_type="crispr_spacer",
                    name="NisI Regulatory Target Region",
                    start=180,
                    end=202,
                    strand="+",
                    qualifiers={"pam": "NGG", "protospacer": "AAGGAGGTGTTTTTATGAAGAAAC"},
                    evidence_ids=["PMID:29109281"],
                ),
            ],
            provenance={"source": "NCBI RefSeq & BaseSpace FASTQ Assembly", "verified": True},
            created_at=now,
        )

        study1 = CrisprObjective(
            study_id=study1_id,
            project_id=p1_id,
            sample_id=s1_id,
            title="NisI Immunity Gene Promoter & Ribosome Binding Site Characterization",
            investigation_purpose=(
                "Evaluate natural nucleotide polymorphisms upstream of the nisI immunity lipoprotein gene "
                "to understand variations in bacteriocin self-protection thresholds across industrial starter strains. "
                "Note: Intended strictly for sequence annotation and variant interpretation; experimental editing instructions excluded."
            ),
            target_gene="nisI",
            target_sequence_id=seq1_dna_id,
            reference_version="v2.1",
            target_regions=[
                CrisprTargetRegion(
                    target_id="target_nisI_rbs",
                    study_id=study1_id,
                    target_name="nisI Ribosome Binding Site Region",
                    locus_tag="nisI_5UTR",
                    sequence_id=seq1_dna_id,
                    start_pos=175,
                    end_pos=205,
                    strand="+",
                    target_sequence="AAGGAGGTGTTTTTATGAAGAAACTCTTAAC",
                    pam_motif="TGG",
                    orientation="5to3",
                    annotations=["RBS Shine-Dalgarno", "Start Codon Met1"],
                    published_evidence=[
                        {"pmid": "8474195", "title": "NisI immunity protein protects against external nisin."},
                        {"pmid": "29109281", "title": "Bacteriocin self-resistance gene regulation in lactic acid bacteria."},
                    ],
                    validation_status="literature_confirmed",
                )
            ],
            variants=[
                SequenceVariant(
                    variant_id="var_nisI_c185T",
                    reference_sequence_id=seq1_dna_id,
                    position=185,
                    reference_allele="G",
                    alternate_allele="A",
                    variant_type="snv",
                    predicted_effect="Alters Shine-Dalgarno pairing stability (ΔΔG = +1.2 kcal/mol)",
                    evidence_citations=["PMID:29109281"],
                    uncertainty_level="low",
                    confidence_score=0.94,
                ),
                SequenceVariant(
                    variant_id="var_nisA_hinge",
                    reference_sequence_id=seq1_dna_id,
                    position=148,
                    reference_allele="A",
                    alternate_allele="C",
                    variant_type="snv",
                    predicted_effect="Nisin Z variant substitution: p.His31Asn",
                    evidence_citations=["PMID:1418703"],
                    uncertainty_level="low",
                    confidence_score=0.98,
                ),
            ],
            specificity_considerations="High homology to nisF and nisE ABC transporter promoters; off-target cross-matching requires stringency.",
            experimental_findings_summary="Literature confirms that the Asn31 variant maintains equal antimicrobial activity with improved diffusion.",
            review_status="approved",
            created_at=now,
            updated_at=now,
        )

        sample1 = BiologicalSample(
            sample_id=s1_id,
            project_id=p1_id,
            sample_name="Lactococcus lactis subsp. lactis ATCC 11454",
            organism="Lactococcus lactis",
            strain="ATCC 11454",
            gram_stain="positive",
            isolation_source="Dairy Starter Culture",
            collection_date="2026-09-15",
            sequencing_run_ids=["run_bs_miseq_01"],
            dataset_ids=["ds_bs_miseq_r1", "ds_bs_miseq_r2"],
            metadata={"growth_temp_c": 30, "medium": "M17 broth + 0.5% glucose"},
            created_at=now,
        )

        project1 = ResearchProject(
            project_id=p1_id,
            name="Lactococcus lactis Nisin Biosynthetic Cluster & Immunity",
            description="Characterizing natural variants of Nisin lantibiotic operon and NisI lipoprotein immunity in cheese starter isolates.",
            lead_investigator="Dr. E. Hansen",
            target_organism="Lactococcus lactis",
            status="active",
            sample_ids=[s1_id],
            sequencing_run_ids=["run_bs_miseq_01"],
            dataset_ids=["ds_bs_miseq_r1", "ds_bs_miseq_r2"],
            sequence_ids=[seq1_dna_id],
            amp_job_ids=["batch-sample-demo-1"],
            crispr_study_ids=[study1_id],
            created_at=now,
            updated_at=now,
        )

        self.store.upsert_project(project1)
        self.store.upsert_sample(sample1)
        self.store.upsert_sequence(p1_seq_dna)
        self.store.upsert_crispr_study(study1)

        # -------------------------------------------------------------
        # PROJECT 2: Enterococcus faecium Circular Bacteriocin Mining
        # -------------------------------------------------------------
        p2_id = "proj_enterococcus_as48"
        s2_id = "samp_efaecium_e980"
        seq2_dna_id = "seq_as48_cluster_ref"
        study2_id = "crispr_as48_transporter_01"

        as48_dna = (
            "ATGAAAAAATTAGCGATTTTGTTGCTTAGTGTTACAGTTTTTGCTGAAGGAAAACCTGAA"
            "AAAGTTGTTAGAGGTGCTTGTGCTGGAGTTTGTGCTACTCATTTAACTGTTGTTGCTGGA"
            "TGTGTTGCTGGTGCTGCTGTTTGTGTTGGTGGTTTTGCTACTTGTGGATGTGCTGTTGGA"
            "GGTTTTGCTGCTGGAATTGCAGCTGGTGCTGCTGTTTGTGTTGGAGCTACTGCTGTTGGA"
            "GCTGGAGCTGTTGCAGCTGGTGGATTTGCTACTGCTTGTTGTGCTTAA"
        )

        p2_seq_dna = AnnotatedSequence(
            sequence_id=seq2_dna_id,
            project_id=p2_id,
            sample_id=s2_id,
            source_dataset_id="ds_ont_fastq_01",
            name="Enterococcus faecium Enterocin AS-48 precursor cluster",
            molecule_type="dna",
            sequence=as48_dna,
            length=len(as48_dna),
            description="Reference operon for circular Class IIc bacteriocin Enterocin AS-48",
            genomic_coordinates="pWVO2:1240-1530",
            reference_version="v1.4",
            orientation="5to3",
            annotations=[
                SequenceAnnotation(
                    annotation_id="ann_as48A_cds",
                    feature_type="cds",
                    name="as-48A",
                    start=1,
                    end=288,
                    strand="+",
                    qualifiers={"product": "Enterocin AS-48 prepeptide"},
                    evidence_ids=["PMID:9765582", "DRAMP:DRAMP00023"],
                ),
                SequenceAnnotation(
                    annotation_id="ann_as48_leader",
                    feature_type="leader_peptide",
                    name="AS-48 Leader",
                    start=1,
                    end=105,
                    strand="+",
                    qualifiers={"cleavage": "Ala35-Met36"},
                    evidence_ids=["PMID:9765582"],
                ),
            ],
            provenance={"source": "Oxford Nanopore Long-Read MinKNOW & Assembly", "verified": True},
            created_at=now,
        )

        study2 = CrisprObjective(
            study_id=study2_id,
            project_id=p2_id,
            sample_id=s2_id,
            title="Enterocin AS-48 Circularization Domain Variation Analysis",
            investigation_purpose=(
                "Document natural sequence diversity across the head-to-tail circularization ligation domain "
                "in Enterococcus hospital isolates to assess resistance evolution against membrane pore formation."
            ),
            target_gene="as-48A",
            target_sequence_id=seq2_dna_id,
            reference_version="v1.4",
            target_regions=[
                CrisprTargetRegion(
                    target_id="target_as48_junction",
                    study_id=study2_id,
                    target_name="Head-to-tail circularization cleavage site",
                    locus_tag="as-48A_junction",
                    sequence_id=seq2_dna_id,
                    start_pos=90,
                    end_pos=125,
                    strand="+",
                    target_sequence="GTGCTTGTGCTGGAGTTTGTGCTACTCATTTAACTG",
                    pam_motif="CGG",
                    orientation="5to3",
                    annotations=["Ligation boundary", "Met1-Trp70 circular peptide"],
                    published_evidence=[
                        {"pmid": "9765582", "title": "Structure and genetics of circular bacteriocin enterocin AS-48."}
                    ],
                    validation_status="literature_confirmed",
                )
            ],
            variants=[
                SequenceVariant(
                    variant_id="var_as48_v112C",
                    reference_sequence_id=seq2_dna_id,
                    position=112,
                    reference_allele="A",
                    alternate_allele="G",
                    variant_type="snv",
                    predicted_effect="Conservative substitution: p.Thr38Ala",
                    evidence_citations=["PMID:9765582"],
                    uncertainty_level="low",
                    confidence_score=0.91,
                )
            ],
            specificity_considerations="High GC-islands around ABC transporter genes; specificity filtering required.",
            experimental_findings_summary="Observed in 14 clinical isolates with intact bactericidal potency.",
            review_status="approved",
            created_at=now,
            updated_at=now,
        )

        sample2 = BiologicalSample(
            sample_id=s2_id,
            project_id=p2_id,
            sample_name="Enterococcus faecium E980",
            organism="Enterococcus faecium",
            strain="E980",
            gram_stain="positive",
            isolation_source="Human Clinical Isolate",
            collection_date="2026-08-10",
            sequencing_run_ids=["run_ont_prome_01"],
            dataset_ids=["ds_ont_fastq_01", "ds_ont_pod5_01"],
            metadata={"vancomycin_resistant": True, "linezolid_susceptible": True},
            created_at=now,
        )

        project2 = ResearchProject(
            project_id=p2_id,
            name="Enterococcus faecium Enterocin AS-48 Circular Bacteriocin Mining",
            description="Investigating circular bacteriocin AS-48 operon structures in multi-drug resistant clinical Enterococci.",
            lead_investigator="Dr. M. Alvarez",
            target_organism="Enterococcus faecium",
            status="active",
            sample_ids=[s2_id],
            sequencing_run_ids=["run_ont_prome_01"],
            dataset_ids=["ds_ont_fastq_01", "ds_ont_pod5_01"],
            sequence_ids=[seq2_dna_id],
            amp_job_ids=[],
            crispr_study_ids=[study2_id],
            created_at=now,
            updated_at=now,
        )

        self.store.upsert_project(project2)
        self.store.upsert_sample(sample2)
        self.store.upsert_sequence(p2_seq_dna)
        self.store.upsert_crispr_study(study2)

        # -------------------------------------------------------------
        # PROJECT 3: Bacillus thuringiensis Thuricin CD Locus
        # -------------------------------------------------------------
        p3_id = "proj_bacillus_thuricin"
        s3_id = "samp_bthuringiensis_hd1"
        seq3_dna_id = "seq_thuricin_cd_ref"
        study3_id = "crispr_thuricin_sam_01"

        thuricin_dna = (
            "ATGAATAAAACAAACTTATTATTACATGAAGTAACAGGATCATCATATACTTTTACTAGT"
            "ACTACAAATGTAAACTCTTTAAGTGCTGGATGTTTAACTGGTTGTTCTACTGGTTGTACA"
            "ACTGGTTGTTGTGCTACATGTTCTTGTTCTATTCATGTTTCTAAATAAGTTTTAATTTTT"
        )

        p3_seq_dna = AnnotatedSequence(
            sequence_id=seq3_dna_id,
            project_id=p3_id,
            sample_id=s3_id,
            source_dataset_id="ds_pb_hifi_01",
            name="Bacillus thuringiensis Thuricin CD Trn-alpha/beta locus",
            molecule_type="dna",
            sequence=thuricin_dna,
            length=len(thuricin_dna),
            description="PacBio HiFi consensus locus encoding two-component sactipeptide Thuricin CD",
            genomic_coordinates="BtHD1_pBMB:41200-41380",
            reference_version="v1.0",
            orientation="5to3",
            annotations=[
                SequenceAnnotation(
                    annotation_id="ann_trn_alpha",
                    feature_type="core_peptide",
                    name="Trn-alpha core peptide",
                    start=1,
                    end=90,
                    strand="+",
                    qualifiers={"product": "Thuricin CD alpha sactipeptide"},
                    evidence_ids=["PMID:19762534"],
                )
            ],
            provenance={"source": "PacBio Revio SMRT Link HiFi CCS", "verified": True},
            created_at=now,
        )

        sample3 = BiologicalSample(
            sample_id=s3_id,
            project_id=p3_id,
            sample_name="Bacillus thuringiensis HD1",
            organism="Bacillus thuringiensis",
            strain="HD1",
            gram_stain="positive",
            isolation_source="Agricultural Soil Isolate",
            collection_date="2026-07-22",
            sequencing_run_ids=["run_pb_revio_01"],
            dataset_ids=["ds_pb_hifi_01"],
            metadata={"crystal_protein": "Cry1Ac"},
            created_at=now,
        )

        project3 = ResearchProject(
            project_id=p3_id,
            name="Bacillus thuringiensis Thuricin CD Sactipeptide System",
            description="Characterizing narrow-spectrum anti-Clostridioides difficile sactipeptide Thuricin CD using PacBio HiFi assemblies.",
            lead_investigator="Dr. S. O'Connor",
            target_organism="Bacillus thuringiensis",
            status="active",
            sample_ids=[s3_id],
            sequencing_run_ids=["run_pb_revio_01"],
            dataset_ids=["ds_pb_hifi_01"],
            sequence_ids=[seq3_dna_id],
            amp_job_ids=[],
            crispr_study_ids=[],
            created_at=now,
            updated_at=now,
        )

        self.store.upsert_project(project3)
        self.store.upsert_sample(sample3)
        self.store.upsert_sequence(p3_seq_dna)

    # -------------------------------------------------------------
    # API Methods
    # -------------------------------------------------------------

    def list_projects(self) -> list[ResearchProject]:
        return self.store.list_projects()

    def get_project(self, project_id: str) -> ResearchProject | None:
        return self.store.get_project(project_id)

    def create_project(self, req: ProjectCreateRequest) -> ResearchProject:
        project_id = f"proj_{hashlib.md5(f'{req.name}:{time.time()}'.encode()).hexdigest()[:10]}"
        now = utc_now()
        proj = ResearchProject(
            project_id=project_id,
            name=req.name,
            description=req.description,
            lead_investigator=req.lead_investigator,
            target_organism=req.target_organism,
            status="active",
            sample_ids=[],
            sequencing_run_ids=[],
            dataset_ids=[],
            sequence_ids=[],
            amp_job_ids=[],
            crispr_study_ids=[],
            created_at=now,
            updated_at=now,
        )
        self.store.upsert_project(proj)
        return proj

    def list_samples(self, project_id: str | None = None) -> list[BiologicalSample]:
        return self.store.list_samples(project_id)

    def get_sample(self, sample_id: str) -> BiologicalSample | None:
        return self.store.get_sample(sample_id)

    def create_sample(self, project_id: str, req: SampleCreateRequest) -> BiologicalSample:
        proj = self.store.get_project(project_id)
        if not proj:
            raise KeyError(f"Project '{project_id}' not found")

        sample_id = f"samp_{hashlib.md5(f'{project_id}:{req.sample_name}:{time.time()}'.encode()).hexdigest()[:10]}"
        now = utc_now()
        sample = BiologicalSample(
            sample_id=sample_id,
            project_id=project_id,
            sample_name=req.sample_name,
            organism=req.organism,
            strain=req.strain,
            gram_stain=req.gram_stain,
            isolation_source=req.isolation_source,
            collection_date=now[:10],
            sequencing_run_ids=[],
            dataset_ids=[],
            metadata={},
            created_at=now,
        )
        self.store.upsert_sample(sample)

        # Update project samples list
        if sample_id not in proj.sample_ids:
            proj.sample_ids.append(sample_id)
            proj.updated_at = now
            self.store.upsert_project(proj)

        return sample

    def list_sequences(self, project_id: str | None = None, sample_id: str | None = None) -> list[AnnotatedSequence]:
        return self.store.list_sequences(project_id=project_id, sample_id=sample_id)

    def get_sequence(self, sequence_id: str) -> AnnotatedSequence | None:
        return self.store.get_sequence(sequence_id)

    def list_crispr_studies(self, project_id: str | None = None) -> list[CrisprObjective]:
        return self.store.list_crispr_studies(project_id)

    def get_crispr_study(self, study_id: str) -> CrisprObjective | None:
        return self.store.get_crispr_study(study_id)

    def create_crispr_study(self, project_id: str, req: CrisprObjectiveCreateRequest) -> CrisprObjective:
        proj = self.store.get_project(project_id)
        if not proj:
            raise KeyError(f"Project '{project_id}' not found")

        study_id = f"crispr_{hashlib.md5(f'{project_id}:{req.title}:{time.time()}'.encode()).hexdigest()[:10]}"
        now = utc_now()

        study = CrisprObjective(
            study_id=study_id,
            project_id=project_id,
            sample_id=req.sample_id,
            title=req.title,
            investigation_purpose=req.investigation_purpose,
            target_gene=req.target_gene,
            target_sequence_id=req.target_sequence_id,
            reference_version=req.reference_version,
            target_regions=[],
            variants=[],
            specificity_considerations=req.specificity_considerations,
            experimental_findings_summary=None,
            review_status="draft",
            created_at=now,
            updated_at=now,
        )
        self.store.upsert_crispr_study(study)

        if study_id not in proj.crispr_study_ids:
            proj.crispr_study_ids.append(study_id)
            proj.updated_at = now
            self.store.upsert_project(proj)

        return study

    def compare_sequences(
        self, reference_sequence_id: str, query_sequence: str, query_name: str = "Query Sequence"
    ) -> SequenceComparisonResult:
        """Perform exact coordinate-aware comparison between reference and query sequence."""
        ref_record = self.store.get_sequence(reference_sequence_id)
        if not ref_record:
            raise KeyError(f"Reference sequence '{reference_sequence_id}' not found")

        ref_str = ref_record.sequence.strip().upper()
        query_str = query_sequence.strip().upper()

        variants: list[SequenceVariant] = []
        alignment_chunks: list[dict[str, Any]] = []
        mismatches = 0
        gaps = 0

        # Equal length fast-path for exact point-mutation scanning
        if len(ref_str) == len(query_str):
            chunk_type = "match"
            chunk_start = 0
            for idx in range(len(ref_str)):
                rc = ref_str[idx]
                qc = query_str[idx]
                if rc != qc:
                    mismatches += 1
                    pos = idx + 1
                    variants.append(
                        SequenceVariant(
                            variant_id=f"var_{pos}_{rc}_{qc}",
                            reference_sequence_id=reference_sequence_id,
                            position=pos,
                            reference_allele=rc,
                            alternate_allele=qc,
                            variant_type="snv",
                            coordinate_system="1_based",
                            predicted_effect=f"Substitution at position {pos}: {rc}>{qc}",
                            evidence_citations=[],
                            uncertainty_level="low",
                            confidence_score=1.0,
                        )
                    )
            identity = ((len(ref_str) - mismatches) / len(ref_str)) * 100.0 if len(ref_str) > 0 else 100.0
            return SequenceComparisonResult(
                reference_id=reference_sequence_id,
                reference_name=ref_record.name,
                query_name=query_name,
                length_reference=len(ref_str),
                length_query=len(query_str),
                identity_percentage=round(identity, 2),
                mismatches_count=mismatches,
                gaps_count=0,
                variants=variants,
                alignment_chunks=[
                    {
                        "type": "match" if mismatches == 0 else "variant_bearing",
                        "ref_start": 1,
                        "ref_end": len(ref_str),
                        "query_start": 1,
                        "query_end": len(query_str),
                        "ref_text": ref_str,
                        "query_text": query_str,
                    }
                ],
            )

        matcher = difflib.SequenceMatcher(None, ref_str, query_str, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            sub_ref = ref_str[i1:i2]
            sub_query = query_str[j1:j2]

            if tag == "equal":
                alignment_chunks.append({
                    "type": "match",
                    "ref_start": i1 + 1,
                    "ref_end": i2,
                    "query_start": j1 + 1,
                    "query_end": j2,
                    "ref_text": sub_ref,
                    "query_text": sub_query,
                })
            elif tag == "replace":
                mismatches += max(len(sub_ref), len(sub_query))
                for offset in range(min(len(sub_ref), len(sub_query))):
                    ref_char = sub_ref[offset]
                    alt_char = sub_query[offset]
                    pos = i1 + 1 + offset
                    if ref_char != alt_char:
                        variants.append(
                            SequenceVariant(
                                variant_id=f"var_{pos}_{ref_char}_{alt_char}",
                                reference_sequence_id=reference_sequence_id,
                                position=pos,
                                reference_allele=ref_char,
                                alternate_allele=alt_char,
                                variant_type="snv",
                                coordinate_system="1_based",
                                predicted_effect=f"Substitution at position {pos}: {ref_char}>{alt_char}",
                                evidence_citations=[],
                                uncertainty_level="low",
                                confidence_score=1.0,
                            )
                        )
                alignment_chunks.append({
                    "type": "mismatch",
                    "ref_start": i1 + 1,
                    "ref_end": i2,
                    "query_start": j1 + 1,
                    "query_end": j2,
                    "ref_text": sub_ref,
                    "query_text": sub_query,
                })
            elif tag == "delete":
                gaps += len(sub_ref)
                variants.append(
                    SequenceVariant(
                        variant_id=f"var_del_{i1+1}_{len(sub_ref)}",
                        reference_sequence_id=reference_sequence_id,
                        position=i1 + 1,
                        reference_allele=sub_ref,
                        alternate_allele="-",
                        variant_type="deletion",
                        coordinate_system="1_based",
                        predicted_effect=f"Deletion of {len(sub_ref)} bp at position {i1+1}",
                        evidence_citations=[],
                        uncertainty_level="low",
                        confidence_score=1.0,
                    )
                )
                alignment_chunks.append({
                    "type": "deletion",
                    "ref_start": i1 + 1,
                    "ref_end": i2,
                    "query_start": j1,
                    "query_end": j1,
                    "ref_text": sub_ref,
                    "query_text": "-" * len(sub_ref),
                })
            elif tag == "insert":
                gaps += len(sub_query)
                variants.append(
                    SequenceVariant(
                        variant_id=f"var_ins_{i1}_{len(sub_query)}",
                        reference_sequence_id=reference_sequence_id,
                        position=i1,
                        reference_allele="-",
                        alternate_allele=sub_query,
                        variant_type="insertion",
                        coordinate_system="1_based",
                        predicted_effect=f"Insertion of {len(sub_query)} bp after position {i1}",
                        evidence_citations=[],
                        uncertainty_level="low",
                        confidence_score=1.0,
                    )
                )
                alignment_chunks.append({
                    "type": "insertion",
                    "ref_start": i1,
                    "ref_end": i1,
                    "query_start": j1 + 1,
                    "query_end": j2,
                    "ref_text": "-" * len(sub_query),
                    "query_text": sub_query,
                })

        identity = matcher.ratio() * 100.0

        return SequenceComparisonResult(
            reference_id=reference_sequence_id,
            reference_name=ref_record.name,
            query_name=query_name,
            length_reference=len(ref_str),
            length_query=len(query_str),
            identity_percentage=round(identity, 2),
            mismatches_count=mismatches,
            gaps_count=gaps,
            variants=variants,
            alignment_chunks=alignment_chunks,
        )


# Global singleton
_project_service: ProjectService | None = None


def get_project_service() -> ProjectService:
    global _project_service
    if _project_service is None:
        _project_service = ProjectService()
    return _project_service
