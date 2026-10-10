"""SQLite storage for research projects, biological samples, annotated sequences, and CRISPR studies."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import (
    AnnotatedSequence,
    BiologicalSample,
    CrisprObjective,
    CrisprTargetRegion,
    ResearchProject,
    SequenceVariant,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectStore:
    """Thread-safe SQLite store for project-centered research entities."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS research_projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        lead_investigator TEXT,
        target_organism TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        sample_ids_json TEXT NOT NULL DEFAULT '[]',
        sequencing_run_ids_json TEXT NOT NULL DEFAULT '[]',
        dataset_ids_json TEXT NOT NULL DEFAULT '[]',
        sequence_ids_json TEXT NOT NULL DEFAULT '[]',
        amp_job_ids_json TEXT NOT NULL DEFAULT '[]',
        crispr_study_ids_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS biological_samples (
        sample_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        sample_name TEXT NOT NULL,
        organism TEXT NOT NULL,
        strain TEXT,
        gram_stain TEXT NOT NULL DEFAULT 'unknown',
        isolation_source TEXT,
        collection_date TEXT,
        sequencing_run_ids_json TEXT NOT NULL DEFAULT '[]',
        dataset_ids_json TEXT NOT NULL DEFAULT '[]',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS annotated_sequences (
        sequence_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        sample_id TEXT,
        source_dataset_id TEXT,
        name TEXT NOT NULL,
        molecule_type TEXT NOT NULL,
        sequence TEXT NOT NULL,
        length INTEGER NOT NULL,
        description TEXT,
        genomic_coordinates TEXT,
        reference_version TEXT,
        orientation TEXT NOT NULL DEFAULT '5to3',
        annotations_json TEXT NOT NULL DEFAULT '[]',
        provenance_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS crispr_studies (
        study_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        sample_id TEXT,
        title TEXT NOT NULL,
        investigation_purpose TEXT NOT NULL,
        target_gene TEXT NOT NULL,
        target_sequence_id TEXT NOT NULL,
        reference_version TEXT NOT NULL,
        target_regions_json TEXT NOT NULL DEFAULT '[]',
        variants_json TEXT NOT NULL DEFAULT '[]',
        specificity_considerations TEXT,
        experimental_findings_summary TEXT,
        review_status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_samples_project ON biological_samples(project_id);
    CREATE INDEX IF NOT EXISTS idx_sequences_project ON annotated_sequences(project_id);
    CREATE INDEX IF NOT EXISTS idx_crispr_project ON crispr_studies(project_id);
    """

    def __init__(self, db_path: Path | str = "artifacts/projects/projects.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock, self.connection() as conn:
            conn.executescript(self.SCHEMA)

    # -------------------------------------------------------------
    # Research Projects
    # -------------------------------------------------------------

    def upsert_project(self, project: ResearchProject):
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO research_projects (
                    project_id, name, description, lead_investigator, target_organism, status,
                    sample_ids_json, sequencing_run_ids_json, dataset_ids_json, sequence_ids_json,
                    amp_job_ids_json, crispr_study_ids_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    lead_investigator=excluded.lead_investigator,
                    target_organism=excluded.target_organism,
                    status=excluded.status,
                    sample_ids_json=excluded.sample_ids_json,
                    sequencing_run_ids_json=excluded.sequencing_run_ids_json,
                    dataset_ids_json=excluded.dataset_ids_json,
                    sequence_ids_json=excluded.sequence_ids_json,
                    amp_job_ids_json=excluded.amp_job_ids_json,
                    crispr_study_ids_json=excluded.crispr_study_ids_json,
                    updated_at=excluded.updated_at
                """,
                (
                    project.project_id,
                    project.name,
                    project.description,
                    project.lead_investigator,
                    project.target_organism,
                    project.status,
                    json.dumps(project.sample_ids),
                    json.dumps(project.sequencing_run_ids),
                    json.dumps(project.dataset_ids),
                    json.dumps(project.sequence_ids),
                    json.dumps(project.amp_job_ids),
                    json.dumps(project.crispr_study_ids),
                    project.created_at,
                    project.updated_at,
                ),
            )

    def get_project(self, project_id: str) -> ResearchProject | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
            if not row:
                return None
            return self._format_project(row)

    def list_projects(self) -> list[ResearchProject]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM research_projects ORDER BY updated_at DESC").fetchall()
            return [self._format_project(r) for r in rows]

    def _format_project(self, row: sqlite3.Row) -> ResearchProject:
        return ResearchProject(
            project_id=row["project_id"],
            name=row["name"],
            description=row["description"],
            lead_investigator=row["lead_investigator"],
            target_organism=row["target_organism"],
            status=row["status"],
            sample_ids=json.loads(row["sample_ids_json"]),
            sequencing_run_ids=json.loads(row["sequencing_run_ids_json"]),
            dataset_ids=json.loads(row["dataset_ids_json"]),
            sequence_ids=json.loads(row["sequence_ids_json"]),
            amp_job_ids=json.loads(row["amp_job_ids_json"]),
            crispr_study_ids=json.loads(row["crispr_study_ids_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -------------------------------------------------------------
    # Biological Samples
    # -------------------------------------------------------------

    def upsert_sample(self, sample: BiologicalSample):
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO biological_samples (
                    sample_id, project_id, sample_name, organism, strain, gram_stain,
                    isolation_source, collection_date, sequencing_run_ids_json,
                    dataset_ids_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sample_id) DO UPDATE SET
                    sample_name=excluded.sample_name,
                    organism=excluded.organism,
                    strain=excluded.strain,
                    gram_stain=excluded.gram_stain,
                    isolation_source=excluded.isolation_source,
                    collection_date=excluded.collection_date,
                    sequencing_run_ids_json=excluded.sequencing_run_ids_json,
                    dataset_ids_json=excluded.dataset_ids_json,
                    metadata_json=excluded.metadata_json
                """,
                (
                    sample.sample_id,
                    sample.project_id,
                    sample.sample_name,
                    sample.organism,
                    sample.strain,
                    sample.gram_stain,
                    sample.isolation_source,
                    sample.collection_date,
                    json.dumps(sample.sequencing_run_ids),
                    json.dumps(sample.dataset_ids),
                    json.dumps(sample.metadata),
                    sample.created_at,
                ),
            )

    def get_sample(self, sample_id: str) -> BiologicalSample | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM biological_samples WHERE sample_id = ?", (sample_id,)).fetchone()
            if not row:
                return None
            return self._format_sample(row)

    def list_samples(self, project_id: str | None = None) -> list[BiologicalSample]:
        with self.connection() as conn:
            if project_id:
                rows = conn.execute("SELECT * FROM biological_samples WHERE project_id = ? ORDER BY sample_name ASC", (project_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM biological_samples ORDER BY created_at DESC").fetchall()
            return [self._format_sample(r) for r in rows]

    def _format_sample(self, row: sqlite3.Row) -> BiologicalSample:
        return BiologicalSample(
            sample_id=row["sample_id"],
            project_id=row["project_id"],
            sample_name=row["sample_name"],
            organism=row["organism"],
            strain=row["strain"],
            gram_stain=row["gram_stain"],
            isolation_source=row["isolation_source"],
            collection_date=row["collection_date"],
            sequencing_run_ids=json.loads(row["sequencing_run_ids_json"]),
            dataset_ids=json.loads(row["dataset_ids_json"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
        )

    # -------------------------------------------------------------
    # Annotated Sequences
    # -------------------------------------------------------------

    def upsert_sequence(self, seq: AnnotatedSequence):
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO annotated_sequences (
                    sequence_id, project_id, sample_id, source_dataset_id, name, molecule_type,
                    sequence, length, description, genomic_coordinates, reference_version,
                    orientation, annotations_json, provenance_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sequence_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    sequence=excluded.sequence,
                    length=excluded.length,
                    genomic_coordinates=excluded.genomic_coordinates,
                    reference_version=excluded.reference_version,
                    orientation=excluded.orientation,
                    annotations_json=excluded.annotations_json,
                    provenance_json=excluded.provenance_json
                """,
                (
                    seq.sequence_id,
                    seq.project_id,
                    seq.sample_id,
                    seq.source_dataset_id,
                    seq.name,
                    seq.molecule_type,
                    seq.sequence,
                    seq.length,
                    seq.description,
                    seq.genomic_coordinates,
                    seq.reference_version,
                    seq.orientation,
                    json.dumps([a.model_dump() for a in seq.annotations]),
                    json.dumps(seq.provenance),
                    seq.created_at,
                ),
            )

    def get_sequence(self, sequence_id: str) -> AnnotatedSequence | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM annotated_sequences WHERE sequence_id = ?", (sequence_id,)).fetchone()
            if not row:
                return None
            return self._format_sequence(row)

    def list_sequences(self, project_id: str | None = None, sample_id: str | None = None) -> list[AnnotatedSequence]:
        conditions, params = [], []
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if sample_id:
            conditions.append("sample_id = ?")
            params.append(sample_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self.connection() as conn:
            rows = conn.execute(f"SELECT * FROM annotated_sequences {where} ORDER BY created_at DESC", (*params,)).fetchall()
            return [self._format_sequence(r) for r in rows]

    def _format_sequence(self, row: sqlite3.Row) -> AnnotatedSequence:
        raw_annotations = json.loads(row["annotations_json"])
        return AnnotatedSequence(
            sequence_id=row["sequence_id"],
            project_id=row["project_id"],
            sample_id=row["sample_id"],
            source_dataset_id=row["source_dataset_id"],
            name=row["name"],
            molecule_type=row["molecule_type"],
            sequence=row["sequence"],
            length=row["length"],
            description=row["description"],
            genomic_coordinates=row["genomic_coordinates"],
            reference_version=row["reference_version"],
            orientation=row["orientation"],
            annotations=raw_annotations,
            provenance=json.loads(row["provenance_json"]),
            created_at=row["created_at"],
        )

    # -------------------------------------------------------------
    # CRISPR Studies
    # -------------------------------------------------------------

    def upsert_crispr_study(self, study: CrisprObjective):
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO crispr_studies (
                    study_id, project_id, sample_id, title, investigation_purpose,
                    target_gene, target_sequence_id, reference_version, target_regions_json,
                    variants_json, specificity_considerations, experimental_findings_summary,
                    review_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(study_id) DO UPDATE SET
                    title=excluded.title,
                    investigation_purpose=excluded.investigation_purpose,
                    target_gene=excluded.target_gene,
                    target_sequence_id=excluded.target_sequence_id,
                    reference_version=excluded.reference_version,
                    target_regions_json=excluded.target_regions_json,
                    variants_json=excluded.variants_json,
                    specificity_considerations=excluded.specificity_considerations,
                    experimental_findings_summary=excluded.experimental_findings_summary,
                    review_status=excluded.review_status,
                    updated_at=excluded.updated_at
                """,
                (
                    study.study_id,
                    study.project_id,
                    study.sample_id,
                    study.title,
                    study.investigation_purpose,
                    study.target_gene,
                    study.target_sequence_id,
                    study.reference_version,
                    json.dumps([t.model_dump() for t in study.target_regions]),
                    json.dumps([v.model_dump() for v in study.variants]),
                    study.specificity_considerations,
                    study.experimental_findings_summary,
                    study.review_status,
                    study.created_at,
                    study.updated_at,
                ),
            )

    def get_crispr_study(self, study_id: str) -> CrisprObjective | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM crispr_studies WHERE study_id = ?", (study_id,)).fetchone()
            if not row:
                return None
            return self._format_crispr_study(row)

    def list_crispr_studies(self, project_id: str | None = None) -> list[CrisprObjective]:
        with self.connection() as conn:
            if project_id:
                rows = conn.execute("SELECT * FROM crispr_studies WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM crispr_studies ORDER BY updated_at DESC").fetchall()
            return [self._format_crispr_study(r) for r in rows]

    def _format_crispr_study(self, row: sqlite3.Row) -> CrisprObjective:
        return CrisprObjective(
            study_id=row["study_id"],
            project_id=row["project_id"],
            sample_id=row["sample_id"],
            title=row["title"],
            investigation_purpose=row["investigation_purpose"],
            target_gene=row["target_gene"],
            target_sequence_id=row["target_sequence_id"],
            reference_version=row["reference_version"],
            target_regions=json.loads(row["target_regions_json"]),
            variants=json.loads(row["variants_json"]),
            specificity_considerations=row["specificity_considerations"],
            experimental_findings_summary=row["experimental_findings_summary"],
            review_status=row["review_status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
