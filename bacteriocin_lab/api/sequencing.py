"""FastAPI routing surface for universal sequencing platform integrations."""

from __future__ import annotations

from typing import Any, Literal
from fastapi import APIRouter, HTTPException, Query, status

from bacteriocin_lab.sequencing.schemas import (
    AnalysisHandoffResponse,
    ConnectionCreateRequest,
    ConnectorInfo,
    ImportJob,
    ImportRequest,
    SequencingConnection,
    SequencingDataset,
    SequencingRun,
    SyncResult,
)
from bacteriocin_lab.sequencing.service import get_sequencing_service

router = APIRouter(prefix="/api/v1/sequencing", tags=["sequencing"])


@router.get("/connectors", response_model=list[ConnectorInfo])
def list_connectors() -> list[ConnectorInfo]:
    """List all registered sequencing platform connectors and capabilities."""
    service = get_sequencing_service()
    return service.list_connectors()


@router.get("/connections", response_model=list[SequencingConnection])
def list_connections() -> list[SequencingConnection]:
    """List configured sequencing platform connections."""
    service = get_sequencing_service()
    return service.list_connections()


@router.post("/connections", response_model=SequencingConnection, status_code=status.HTTP_201_CREATED)
def create_connection(body: ConnectionCreateRequest) -> SequencingConnection:
    """Register and validate a new sequencing platform connection."""
    service = get_sequencing_service()
    try:
        return service.create_connection(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection setup failed: {e}") from e


@router.get("/connections/{connection_id}", response_model=SequencingConnection)
def get_connection(connection_id: str) -> SequencingConnection:
    """Retrieve details for a specific connection."""
    service = get_sequencing_service()
    conn = service.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{connection_id}' not found")
    return conn


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(connection_id: str):
    """Delete a sequencing connection and associated runs/datasets."""
    service = get_sequencing_service()
    deleted = service.delete_connection(connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Connection '{connection_id}' not found")
    return None


@router.post("/connections/{connection_id}/sync", response_model=SyncResult)
def sync_connection(connection_id: str) -> SyncResult:
    """Trigger automated synchronization for a connection to discover new runs and datasets."""
    service = get_sequencing_service()
    try:
        return service.sync_connection(connection_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}") from e


@router.get("/runs", response_model=list[SequencingRun])
def list_runs(
    connection_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SequencingRun]:
    """List sequencing runs discovered across connected platforms."""
    service = get_sequencing_service()
    return service.list_runs(connection_id=connection_id, status=status, limit=limit)


@router.get("/runs/{run_id}", response_model=SequencingRun)
def get_run(run_id: str) -> SequencingRun:
    """Retrieve metadata and status for a specific sequencing run."""
    service = get_sequencing_service()
    run = service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run


@router.get("/runs/{run_id}/datasets", response_model=list[SequencingDataset])
def list_run_datasets(run_id: str) -> list[SequencingDataset]:
    """List output datasets (FASTQ, FASTA, BAM, POD5) associated with a sequencing run."""
    service = get_sequencing_service()
    run = service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return service.list_datasets(run_id=run_id)


@router.get("/datasets", response_model=list[SequencingDataset])
def list_datasets(
    run_id: str | None = Query(default=None),
    connection_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[SequencingDataset]:
    """List sequencing datasets across all platforms."""
    service = get_sequencing_service()
    return service.list_datasets(run_id=run_id, connection_id=connection_id, limit=limit)


@router.get("/datasets/{dataset_id}", response_model=SequencingDataset)
def get_dataset(dataset_id: str) -> SequencingDataset:
    """Retrieve metadata for a specific dataset file."""
    service = get_sequencing_service()
    ds = service.get_dataset(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return ds


@router.post("/datasets/{dataset_id}/import", response_model=ImportJob)
def initiate_import(dataset_id: str, body: ImportRequest) -> ImportJob:
    """Trigger verified import transfer of a sequencing dataset into local platform storage."""
    service = get_sequencing_service()
    try:
        return service.initiate_import(dataset_id, body)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}") from e


@router.get("/imports/{import_id}", response_model=ImportJob)
def get_import_job(import_id: str) -> ImportJob:
    """Check the status and transfer progress of an import job."""
    service = get_sequencing_service()
    job = service.get_import(import_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Import job '{import_id}' not found")
    return job


@router.get("/datasets/{dataset_id}/handoff", response_model=AnalysisHandoffResponse)
def get_analysis_handoff(dataset_id: str) -> AnalysisHandoffResponse:
    """Evaluate scientific readiness of a dataset for downstream bacteriocin & AMP analysis."""
    service = get_sequencing_service()
    try:
        return service.get_analysis_handoff(dataset_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis evaluation failed: {e}") from e
