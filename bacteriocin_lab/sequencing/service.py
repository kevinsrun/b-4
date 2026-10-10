"""Sequencing Service Coordinator.

Unifies platform connectors, thread-safe SQLite persistence, background synchronization,
dataset import orchestration, and downstream bioinformatics handoff.
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connector_base import SequencingConnector
from .handoff import evaluate_analysis_handoff
from .illumina_connector import IlluminaBaseSpaceConnector
from .local_connector import LocalFolderConnector
from .nanopore_connector import OxfordNanoporeConnector
from .pacbio_connector import PacBioConnector
from .schemas import (
    AnalysisHandoffResponse,
    ConnectionCreateRequest,
    ConnectionUpdateRequest,
    ConnectorInfo,
    ImportJob,
    ImportRequest,
    SequencingConnection,
    SequencingDataset,
    SequencingRun,
    SyncResult,
)
from .store import SequencingStore, utc_now

DEFAULT_DB_PATH = Path("artifacts/sequencing/sequencing.sqlite3")
DEFAULT_IMPORTS_DIR = Path("artifacts/sequencing/imported")


class SequencingService:
    """Central service managing sequencing connections, runs, datasets, and imports."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH, imports_dir: Path | str = DEFAULT_IMPORTS_DIR):
        self.db_path = Path(db_path)
        self.imports_dir = Path(imports_dir)
        self.imports_dir.mkdir(parents=True, exist_ok=True)
        self.store = SequencingStore(self.db_path)

        # Register connectors
        self._connectors: dict[str, SequencingConnector] = {}
        self.register_connector(LocalFolderConnector())
        self.register_connector(IlluminaBaseSpaceConnector())
        self.register_connector(OxfordNanoporeConnector())
        self.register_connector(PacBioConnector())

        # Ensure seed demo connections exist if fresh
        self._ensure_seed_connections()

    def register_connector(self, connector: SequencingConnector):
        self._connectors[connector.connector_id] = connector

    def get_connector(self, connector_id: str) -> SequencingConnector | None:
        return self._connectors.get(connector_id)

    def list_connectors(self) -> list[ConnectorInfo]:
        """Return metadata for all registered connectors."""
        res = []
        for c in self._connectors.values():
            res.append(
                ConnectorInfo(
                    connector_id=c.connector_id,
                    name=c.name,
                    vendor=c.vendor,  # type: ignore
                    auth_type=c.auth_type,  # type: ignore
                    description=c.description,
                    capabilities=c.capabilities(),
                    supported_file_types=c.supported_file_types(),
                )
            )
        return res

    def _ensure_seed_connections(self):
        """Seed demo connections if store is empty so the user can immediately test all 4 platforms."""
        existing = self.store.list_connections()
        if existing:
            return

        # 1. Illumina BaseSpace (Simulated / Contract-tested)
        self.create_connection(
            ConnectionCreateRequest(
                connector_id="illumina_basespace",
                name="BaseSpace Sequence Hub (BactroGen Facility)",
                config={"use_fixtures": True, "api_server": "https://api.basespace.illumina.com"},
                auto_sync=False,
            )
        )

        # 2. Oxford Nanopore MinKNOW (Simulated / Contract-tested)
        self.create_connection(
            ConnectionCreateRequest(
                connector_id="oxford_nanopore",
                name="PromethION 2 Solo (Lab P2S-01)",
                config={"use_fixtures": True, "instrument": "PromethION"},
                auto_sync=False,
            )
        )

        # 3. PacBio SMRT Link (Simulated / Contract-tested)
        self.create_connection(
            ConnectionCreateRequest(
                connector_id="pacbio_smrtlink",
                name="PacBio Revio SMRT Link (Cluster Alpha)",
                config={"use_fixtures": True, "server_url": "https://smrtlink.bactrogen.internal:8243"},
                auto_sync=False,
            )
        )

        # 4. Local Sequencing Folder
        local_incoming = Path("artifacts/sequencing/incoming").resolve()
        local_incoming.mkdir(parents=True, exist_ok=True)
        self.create_connection(
            ConnectionCreateRequest(
                connector_id="local_folder",
                name="Primary Instrument Drop Folder",
                config={"directory_path": str(local_incoming), "require_stability": True},
                auto_sync=False,
            )
        )

        # Trigger sync for seed fixture connections so runs and datasets are immediately populated
        for conn in self.store.list_connections():
            if conn["connector_id"] in ("illumina_basespace", "oxford_nanopore", "pacbio_smrtlink"):
                try:
                    self.sync_connection(conn["connection_id"])
                except Exception:
                    pass

    def create_connection(self, request: ConnectionCreateRequest) -> SequencingConnection:
        connector = self.get_connector(request.connector_id)
        if not connector:
            raise ValueError(f"Unknown connector_id: '{request.connector_id}'")

        # Validate connection credentials or directory
        validation = connector.validate_connection(request.config)
        status = "connected" if validation.get("valid") else "error"
        error_message = None if validation.get("valid") else validation.get("message")

        connection_id = f"conn_{hashlib.md5(f'{request.connector_id}:{request.name}:{time.time()}'.encode()).hexdigest()[:10]}"

        # Redact config for public transport
        safe_config = dict(request.config)
        for key in ("api_token", "api_key", "secret", "password"):
            if key in safe_config:
                safe_config[key] = "********"

        self.store.save_connection(
            connection_id=connection_id,
            connector_id=request.connector_id,
            name=request.name,
            vendor=connector.vendor,
            status=status,
            config=request.config,
            auto_sync=request.auto_sync,
            sync_interval_seconds=request.sync_interval_seconds,
            error_message=error_message,
        )
        saved = self.store.get_connection(connection_id)
        return SequencingConnection(**saved)  # type: ignore

    def get_connection(self, connection_id: str) -> SequencingConnection | None:
        raw = self.store.get_connection(connection_id)
        return SequencingConnection(**raw) if raw else None

    def list_connections(self) -> list[SequencingConnection]:
        raws = self.store.list_connections()
        return [SequencingConnection(**r) for r in raws]

    def delete_connection(self, connection_id: str) -> bool:
        return self.store.delete_connection(connection_id)

    def sync_connection(self, connection_id: str) -> SyncResult:
        """Discover runs and datasets for a connection and persist them."""
        raw_conn = self.store.get_connection(connection_id)
        if not raw_conn:
            raise KeyError(f"Connection not found: {connection_id}")

        connector = self.get_connector(raw_conn["connector_id"])
        if not connector:
            raise ValueError(f"Connector '{raw_conn['connector_id']}' is not registered")

        config = raw_conn.get("config", {})
        start_time = time.time()
        errors: list[str] = []
        runs_discovered = 0
        datasets_discovered = 0

        try:
            discovered_runs = connector.discover_runs(config)
            runs_discovered = len(discovered_runs)

            for r_data in discovered_runs:
                ext_run_id = r_data["external_run_id"]
                run_id = f"{connection_id}_{hashlib.md5(ext_run_id.encode()).hexdigest()[:10]}"

                run_record = {
                    "run_id": run_id,
                    "connection_id": connection_id,
                    "vendor": connector.vendor,
                    "external_run_id": ext_run_id,
                    "run_name": r_data.get("run_name", ext_run_id),
                    "instrument_model": r_data.get("instrument_model"),
                    "sequencing_method": r_data.get("sequencing_method", "unknown"),
                    "project_name": r_data.get("project_name"),
                    "sample_count": r_data.get("sample_count", 0),
                    "status": r_data.get("status", "completed"),
                    "started_at": r_data.get("started_at"),
                    "completed_at": r_data.get("completed_at"),
                    "total_size_bytes": r_data.get("total_size_bytes", 0),
                    "source_metadata": r_data.get("source_metadata", {}),
                    "last_synced_at": utc_now(),
                    "provenance": r_data.get("provenance", {}),
                }

                # Discover datasets for this run
                try:
                    datasets = connector.list_datasets(config, ext_run_id)
                    run_record["dataset_count"] = len(datasets)
                    run_record["total_size_bytes"] = sum(d.get("file_size_bytes", 0) for d in datasets)

                    self.store.upsert_run(run_record)

                    for ds in datasets:
                        ds_id = f"{run_id}_{hashlib.md5(ds['file_name'].encode()).hexdigest()[:10]}"
                        ds_record = {
                            "dataset_id": ds_id,
                            "run_id": run_id,
                            "connection_id": connection_id,
                            "sample_id": ds.get("sample_id"),
                            "sample_name": ds.get("sample_name"),
                            "file_name": ds["file_name"],
                            "file_path": ds["file_path"],
                            "file_format": ds["file_format"],
                            "file_size_bytes": ds["file_size_bytes"],
                            "checksum": ds.get("checksum"),
                            "checksum_algorithm": ds.get("checksum_algorithm", "sha256"),
                            "read_type": ds.get("read_type", "unknown"),
                            "is_complete": ds.get("is_complete", True),
                            "stability_verified": ds.get("stability_verified", True),
                            "import_status": "available",
                            "analysis_eligibility": ds.get("analysis_eligibility", {}),
                            "discovered_at": utc_now(),
                        }
                        self.store.upsert_dataset(ds_record)
                        datasets_discovered += 1
                except Exception as ex:
                    errors.append(f"Failed listing datasets for run {ext_run_id}: {ex}")
                    self.store.upsert_run(run_record)

            self.store.update_connection_sync(connection_id, status="connected")
            sync_status = "succeeded" if not errors else "partial"
        except Exception as e:
            errors.append(str(e))
            self.store.update_connection_sync(connection_id, status="error", error_message=str(e))
            sync_status = "failed"

        duration = time.time() - start_time
        return SyncResult(
            connection_id=connection_id,
            status=sync_status,  # type: ignore
            runs_discovered=runs_discovered,
            runs_updated=runs_discovered,
            datasets_discovered=datasets_discovered,
            sync_duration_seconds=round(duration, 3),
            timestamp=utc_now(),
            errors=errors,
        )

    def list_runs(
        self, connection_id: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[SequencingRun]:
        raws = self.store.list_runs(connection_id=connection_id, status=status, limit=limit)
        return [SequencingRun(**r) for r in raws]

    def get_run(self, run_id: str) -> SequencingRun | None:
        raw = self.store.get_run(run_id)
        return SequencingRun(**raw) if raw else None

    def list_datasets(
        self, run_id: str | None = None, connection_id: str | None = None, limit: int = 200
    ) -> list[SequencingDataset]:
        raws = self.store.list_datasets(run_id=run_id, connection_id=connection_id, limit=limit)
        return [SequencingDataset(**r) for r in raws]

    def get_dataset(self, dataset_id: str) -> SequencingDataset | None:
        raw = self.store.get_dataset(dataset_id)
        return SequencingDataset(**raw) if raw else None

    def initiate_import(self, dataset_id: str, request: ImportRequest) -> ImportJob:
        """Trigger dataset import transfer and verification."""
        dataset = self.store.get_dataset(dataset_id)
        if not dataset:
            raise KeyError(f"Dataset not found: {dataset_id}")

        connection = self.store.get_connection(dataset["connection_id"])
        if not connection:
            raise KeyError(f"Connection not found: {dataset['connection_id']}")

        connector = self.get_connector(connection["connector_id"])
        if not connector:
            raise ValueError(f"Connector '{connection['connector_id']}' is not registered")

        import_id = f"imp_{hashlib.md5(f'{dataset_id}:{time.time()}'.encode()).hexdigest()[:10]}"
        dest_folder = self.imports_dir
        if request.destination_subfolder:
            dest_folder = dest_folder / request.destination_subfolder

        self.store.create_import(
            import_id=import_id,
            dataset_id=dataset_id,
            run_id=dataset["run_id"],
            connection_id=dataset["connection_id"],
            total_bytes=dataset.get("file_size_bytes", 0),
        )

        def progress_cb(transferred: int, total: int):
            self.store.update_import_progress(
                import_id,
                bytes_transferred=transferred,
                total_bytes=total,
                status="transferring",
            )

        # Execute import
        try:
            result = connector.import_dataset(
                config=connection.get("config", {}),
                dataset=dataset,
                destination_dir=dest_folder,
                progress_callback=progress_cb,
            )

            if result.get("success"):
                checksum_verified = True
                if request.verify_checksum and dataset.get("checksum"):
                    checksum_verified = result.get("checksum") == dataset.get("checksum")

                self.store.update_import_progress(
                    import_id,
                    bytes_transferred=dataset.get("file_size_bytes", 0),
                    total_bytes=dataset.get("file_size_bytes", 0),
                    status="completed",
                    destination_path=result.get("local_path"),
                    checksum_verified=checksum_verified,
                )
            else:
                self.store.update_import_progress(
                    import_id,
                    status="failed",
                    error_message=result.get("error", "Transfer failed"),
                )
        except Exception as e:
            self.store.update_import_progress(
                import_id,
                status="failed",
                error_message=str(e),
            )

        updated_import = self.store.get_import(import_id)
        return ImportJob(**updated_import)  # type: ignore

    def get_import(self, import_id: str) -> ImportJob | None:
        raw = self.store.get_import(import_id)
        return ImportJob(**raw) if raw else None

    def get_analysis_handoff(self, dataset_id: str) -> AnalysisHandoffResponse:
        """Evaluate dataset for downstream bioinformatics pipeline handoff."""
        dataset = self.store.get_dataset(dataset_id)
        if not dataset:
            raise KeyError(f"Dataset not found: {dataset_id}")
        return evaluate_analysis_handoff(dataset)


# Global singleton instance for FastAPI application
_service_instance: SequencingService | None = None


def get_sequencing_service() -> SequencingService:
    global _service_instance
    if _service_instance is None:
        _service_instance = SequencingService()
    return _service_instance
