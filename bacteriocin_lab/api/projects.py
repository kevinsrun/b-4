"""FastAPI endpoints for projects, samples, sequence records, and CRISPR investigations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from bacteriocin_lab.projects.schemas import (
    AnnotatedSequence,
    BiologicalSample,
    CrisprObjective,
    CrisprObjectiveCreateRequest,
    ProjectCreateRequest,
    ResearchProject,
    SampleCreateRequest,
    SequenceComparisonRequest,
    SequenceComparisonResult,
)
from bacteriocin_lab.projects.service import get_project_service

router = APIRouter(prefix="/api/v1", tags=["projects", "crispr"])


# -------------------------------------------------------------
# Projects
# -------------------------------------------------------------

@router.get("/projects", response_model=list[ResearchProject])
def list_projects() -> list[ResearchProject]:
    """List all research projects."""
    service = get_project_service()
    return service.list_projects()


@router.post("/projects", response_model=ResearchProject, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreateRequest) -> ResearchProject:
    """Create a new research project."""
    service = get_project_service()
    try:
        return service.create_project(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/projects/{project_id}", response_model=ResearchProject)
def get_project(project_id: str) -> ResearchProject:
    """Retrieve metadata, samples, and linked analyses for a research project."""
    service = get_project_service()
    proj = service.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return proj


@router.get("/projects/{project_id}/samples", response_model=list[BiologicalSample])
def list_project_samples(project_id: str) -> list[BiologicalSample]:
    """List biological samples associated with a project."""
    service = get_project_service()
    return service.list_samples(project_id=project_id)


@router.post("/projects/{project_id}/samples", response_model=BiologicalSample, status_code=status.HTTP_201_CREATED)
def create_sample(project_id: str, body: SampleCreateRequest) -> BiologicalSample:
    """Register a new biological sample inside a project."""
    service = get_project_service()
    try:
        return service.create_sample(project_id, body)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/projects/{project_id}/sequences", response_model=list[AnnotatedSequence])
def list_project_sequences(project_id: str) -> list[AnnotatedSequence]:
    """List annotated sequence records for a project."""
    service = get_project_service()
    return service.list_sequences(project_id=project_id)


@router.get("/projects/{project_id}/crispr-studies", response_model=list[CrisprObjective])
def list_project_crispr_studies(project_id: str) -> list[CrisprObjective]:
    """List CRISPR investigations associated with a project."""
    service = get_project_service()
    return service.list_crispr_studies(project_id=project_id)


@router.post("/projects/{project_id}/crispr-studies", response_model=CrisprObjective, status_code=status.HTTP_201_CREATED)
def create_project_crispr_study(project_id: str, body: CrisprObjectiveCreateRequest) -> CrisprObjective:
    """Record a CRISPR sequence annotation and variant study objective."""
    service = get_project_service()
    try:
        return service.create_crispr_study(project_id, body)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# -------------------------------------------------------------
# Samples & Sequences
# -------------------------------------------------------------

@router.get("/samples/{sample_id}", response_model=BiologicalSample)
def get_sample(sample_id: str) -> BiologicalSample:
    """Retrieve details for a biological sample."""
    service = get_project_service()
    sample = service.get_sample(sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail=f"Sample '{sample_id}' not found")
    return sample


@router.get("/sequences/{sequence_id}", response_model=AnnotatedSequence)
def get_sequence(sequence_id: str) -> AnnotatedSequence:
    """Retrieve full sequence, genomic coordinates, and annotations."""
    service = get_project_service()
    seq = service.get_sequence(sequence_id)
    if not seq:
        raise HTTPException(status_code=404, detail=f"Sequence '{sequence_id}' not found")
    return seq


@router.post("/sequences/{sequence_id}/compare", response_model=SequenceComparisonResult)
def compare_sequence(sequence_id: str, body: SequenceComparisonRequest) -> SequenceComparisonResult:
    """Perform coordinate-aware comparison between a reference sequence and query sequence."""
    service = get_project_service()
    try:
        return service.compare_sequences(
            reference_sequence_id=sequence_id,
            query_sequence=body.query_sequence,
            query_name=body.query_name or "Query Sequence",
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Comparison failed: {e}") from e


# -------------------------------------------------------------
# CRISPR Studies Standalone
# -------------------------------------------------------------

@router.get("/crispr/studies", response_model=list[CrisprObjective])
def list_crispr_studies(project_id: str | None = Query(default=None)) -> list[CrisprObjective]:
    """List CRISPR investigations across projects."""
    service = get_project_service()
    return service.list_crispr_studies(project_id=project_id)


@router.get("/crispr/studies/{study_id}", response_model=CrisprObjective)
def get_crispr_study(study_id: str) -> CrisprObjective:
    """Retrieve CRISPR investigation details, target regions, and variants."""
    service = get_project_service()
    study = service.get_crispr_study(study_id)
    if not study:
        raise HTTPException(status_code=404, detail=f"CRISPR study '{study_id}' not found")
    return study
