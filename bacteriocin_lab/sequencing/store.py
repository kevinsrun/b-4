"""SQLite storage for universal sequencing integrations, runs, datasets, and import jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SequencingStore:
    """Thread-safe SQLite store for sequencing connections, runs, datasets, and imports."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS sequencing_connections (
        connection_id TEXT PRIMARY KEY,
        connector_id TEXT NOT NULL,
        name TEXT NOT NULL,
        vendor TEXT NOT NULL,
        status TEXT NOT NULL,
        config_json TEXT NOT NULL,
        auto_sync INTEGER NOT NULL DEFAULT 0,
        sync_interval_seconds INTEGER NOT NULL DEFAULT 300,
        last_sync_at TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sequencing_runs (
        run_id TEXT PRIMARY KEY,
        connection_id TEXT NOT NULL,
        vendor TEXT NOT NULL,
        external_run_id TEXT NOT NULL,
        run_name TEXT NOT NULL,
        instrument_model TEXT,
        sequencing_method TEXT NOT NULL,
        project_name TEXT,
        sample_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        dataset_count INTEGER NOT NULL DEFAULT 0,
        total_size_bytes INTEGER NOT NULL DEFAULT 0,
        source_metadata_json TEXT NOT NULL,
        last_synced_at TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        FOREIGN KEY (connection_id) REFERENCES sequencing_connections(connection_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS sequencing_datasets (
        dataset_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        connection_id TEXT NOT NULL,
        sample_id TEXT,
        sample_name TEXT,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_format TEXT NOT NULL,
        file_size_bytes INTEGER NOT NULL,
        checksum TEXT,
        checksum_algorithm TEXT,
        read_type TEXT NOT NULL,
        is_complete INTEGER NOT NULL DEFAULT 1,
        stability_verified INTEGER NOT NULL DEFAULT 1,
        import_status TEXT NOT NULL DEFAULT 'available',
        local_storage_path TEXT,
        analysis_eligibility_json TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES sequencing_runs(run_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS sequencing_imports (
        import_id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        connection_id TEXT NOT NULL,
        status TEXT NOT NULL,
        bytes_transferred INTEGER NOT NULL DEFAULT 0,
        total_bytes INTEGER NOT NULL DEFAULT 0,
        transfer_rate_bps REAL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        destination_path TEXT,
        checksum_verified INTEGER,
        error_message TEXT,
        FOREIGN KEY (dataset_id) REFERENCES sequencing_datasets(dataset_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_runs_conn ON sequencing_runs(connection_id);
    CREATE INDEX IF NOT EXISTS idx_datasets_run ON sequencing_datasets(run_id);
    CREATE INDEX IF NOT EXISTS idx_datasets_conn ON sequencing_datasets(connection_id);
    CREATE INDEX IF NOT EXISTS idx_imports_dataset ON sequencing_imports(dataset_id);
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self.connection() as conn:
            conn.executescript(self.SCHEMA)

    def connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # -------------------------------------------------------------
    # Connections
    # -------------------------------------------------------------

    def save_connection(
        self,
        connection_id: str,
        connector_id: str,
        name: str,
        vendor: str,
        status: str,
        config: dict[str, Any],
        auto_sync: bool = False,
        sync_interval_seconds: int = 300,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        with self._lock, self.connection() as conn:
            now = utc_now()
            conn.execute(
                """
                INSERT INTO sequencing_connections (
                    connection_id, connector_id, name, vendor, status, config_json,
                    auto_sync, sync_interval_seconds, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    config_json=excluded.config_json,
                    auto_sync=excluded.auto_sync,
                    sync_interval_seconds=excluded.sync_interval_seconds,
                    error_message=excluded.error_message
                """,
                (
                    connection_id,
                    connector_id,
                    name,
                    vendor,
                    status,
                    json.dumps(config),
                    1 if auto_sync else 0,
                    sync_interval_seconds,
                    error_message,
                    now,
                ),
            )
        return self.get_connection(connection_id)  # type: ignore

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT c.*,
                       (SELECT COUNT(*) FROM sequencing_runs r WHERE r.connection_id = c.connection_id) as discovered_runs_count,
                       (SELECT COUNT(*) FROM sequencing_datasets d WHERE d.connection_id = c.connection_id) as discovered_datasets_count
                FROM sequencing_connections c
                WHERE c.connection_id = ?
                """,
                (connection_id,),
            ).fetchone()
            if not row:
                return None
            return self._format_connection(row)

    def list_connections(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.*,
                       (SELECT COUNT(*) FROM sequencing_runs r WHERE r.connection_id = c.connection_id) as discovered_runs_count,
                       (SELECT COUNT(*) FROM sequencing_datasets d WHERE d.connection_id = c.connection_id) as discovered_datasets_count
                FROM sequencing_connections c
                ORDER BY c.created_at DESC
                """
            ).fetchall()
            return [self._format_connection(r) for r in rows]

    def delete_connection(self, connection_id: str) -> bool:
        with self._lock, self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM sequencing_connections WHERE connection_id = ?",
                (connection_id,),
            )
            return cursor.rowcount > 0

    def update_connection_sync(
        self, connection_id: str, status: str, error_message: str | None = None
    ):
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                UPDATE sequencing_connections
                SET status = ?, last_sync_at = ?, error_message = ?
                WHERE connection_id = ?
                """,
                (status, utc_now(), error_message, connection_id),
            )

    def _format_connection(self, row: sqlite3.Row) -> dict[str, Any]:
        cfg = json.loads(row["config_json"])
        # Redact secrets in config summary
        redacted = {
            k: ("***" if "token" in k.lower() or "secret" in k.lower() or "key" in k.lower() else v)
            for k, v in cfg.items()
        }
        return {
            "connection_id": row["connection_id"],
            "connector_id": row["connector_id"],
            "name": row["name"],
            "vendor": row["vendor"],
            "status": row["status"],
            "config_summary": redacted,
            "auto_sync": bool(row["auto_sync"]),
            "sync_interval_seconds": row["sync_interval_seconds"],
            "last_sync_at": row["last_sync_at"],
            "discovered_runs_count": row["discovered_runs_count"],
            "discovered_datasets_count": row["discovered_datasets_count"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
        }

    # -------------------------------------------------------------
    # Runs
    # -------------------------------------------------------------

    def upsert_run(self, run: dict[str, Any]):
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO sequencing_runs (
                    run_id, connection_id, vendor, external_run_id, run_name,
                    instrument_model, sequencing_method, project_name, sample_count,
                    status, started_at, completed_at, dataset_count, total_size_bytes,
                    source_metadata_json, last_synced_at, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    run_name=excluded.run_name,
                    status=excluded.status,
                    sample_count=excluded.sample_count,
                    dataset_count=excluded.dataset_count,
                    total_size_bytes=excluded.total_size_bytes,
                    completed_at=excluded.completed_at,
                    source_metadata_json=excluded.source_metadata_json,
                    last_synced_at=excluded.last_synced_at,
                    provenance_json=excluded.provenance_json
                """,
                (
                    run["run_id"],
                    run["connection_id"],
                    run["vendor"],
                    run["external_run_id"],
                    run["run_name"],
                    run.get("instrument_model"),
                    run.get("sequencing_method", "unknown"),
                    run.get("project_name"),
                    run.get("sample_count", 0),
                    run.get("status", "unknown"),
                    run.get("started_at"),
                    run.get("completed_at"),
                    run.get("dataset_count", 0),
                    run.get("total_size_bytes", 0),
                    json.dumps(run.get("source_metadata", {})),
                    run.get("last_synced_at", utc_now()),
                    json.dumps(run.get("provenance", {})),
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM sequencing_runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            return self._format_run(row)

    def list_runs(
        self,
        connection_id: str | None = None,
        vendor: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions, params = [], []
        if connection_id:
            conditions.append("connection_id = ?")
            params.append(connection_id)
        if vendor:
            conditions.append("vendor = ?")
            params.append(vendor)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM sequencing_runs {where} ORDER BY started_at DESC, run_id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [self._format_run(r) for r in rows]

    def _format_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "connection_id": row["connection_id"],
            "vendor": row["vendor"],
            "external_run_id": row["external_run_id"],
            "run_name": row["run_name"],
            "instrument_model": row["instrument_model"],
            "sequencing_method": row["sequencing_method"],
            "project_name": row["project_name"],
            "sample_count": row["sample_count"],
            "status": row["status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "dataset_count": row["dataset_count"],
            "total_size_bytes": row["total_size_bytes"],
            "source_metadata": json.loads(row["source_metadata_json"]),
            "last_synced_at": row["last_synced_at"],
            "provenance": json.loads(row["provenance_json"]),
        }

    # -------------------------------------------------------------
    # Datasets
    # -------------------------------------------------------------

    def upsert_dataset(self, dataset: dict[str, Any]):
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO sequencing_datasets (
                    dataset_id, run_id, connection_id, sample_id, sample_name,
                    file_name, file_path, file_format, file_size_bytes,
                    checksum, checksum_algorithm, read_type, is_complete,
                    stability_verified, import_status, local_storage_path,
                    analysis_eligibility_json, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    file_size_bytes=excluded.file_size_bytes,
                    checksum=excluded.checksum,
                    is_complete=excluded.is_complete,
                    stability_verified=excluded.stability_verified,
                    import_status=excluded.import_status,
                    local_storage_path=excluded.local_storage_path,
                    analysis_eligibility_json=excluded.analysis_eligibility_json
                """,
                (
                    dataset["dataset_id"],
                    dataset["run_id"],
                    dataset["connection_id"],
                    dataset.get("sample_id"),
                    dataset.get("sample_name"),
                    dataset["file_name"],
                    dataset["file_path"],
                    dataset["file_format"],
                    dataset["file_size_bytes"],
                    dataset.get("checksum"),
                    dataset.get("checksum_algorithm"),
                    dataset.get("read_type", "unknown"),
                    1 if dataset.get("is_complete", True) else 0,
                    1 if dataset.get("stability_verified", True) else 0,
                    dataset.get("import_status", "available"),
                    dataset.get("local_storage_path"),
                    json.dumps(dataset.get("analysis_eligibility", {})),
                    dataset.get("discovered_at", utc_now()),
                ),
            )

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM sequencing_datasets WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
            if not row:
                return None
            return self._format_dataset(row)

    def list_datasets(
        self, run_id: str | None = None, connection_id: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        conditions, params = [], []
        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)
        if connection_id:
            conditions.append("connection_id = ?")
            params.append(connection_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM sequencing_datasets {where} ORDER BY file_name ASC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [self._format_dataset(r) for r in rows]

    def _format_dataset(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "dataset_id": row["dataset_id"],
            "run_id": row["run_id"],
            "connection_id": row["connection_id"],
            "sample_id": row["sample_id"],
            "sample_name": row["sample_name"],
            "file_name": row["file_name"],
            "file_path": row["file_path"],
            "file_format": row["file_format"],
            "file_size_bytes": row["file_size_bytes"],
            "checksum": row["checksum"],
            "checksum_algorithm": row["checksum_algorithm"],
            "read_type": row["read_type"],
            "is_complete": bool(row["is_complete"]),
            "stability_verified": bool(row["stability_verified"]),
            "import_status": row["import_status"],
            "local_storage_path": row["local_storage_path"],
            "analysis_eligibility": json.loads(row["analysis_eligibility_json"]),
            "discovered_at": row["discovered_at"],
        }

    # -------------------------------------------------------------
    # Imports
    # -------------------------------------------------------------

    def create_import(
        self,
        import_id: str,
        dataset_id: str,
        run_id: str,
        connection_id: str,
        total_bytes: int,
    ) -> dict[str, Any]:
        with self._lock, self.connection() as conn:
            now = utc_now()
            conn.execute(
                """
                INSERT INTO sequencing_imports (
                    import_id, dataset_id, run_id, connection_id, status,
                    bytes_transferred, total_bytes, started_at
                ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)
                """,
                (import_id, dataset_id, run_id, connection_id, total_bytes, now),
            )
            conn.execute(
                "UPDATE sequencing_datasets SET import_status = 'importing' WHERE dataset_id = ?",
                (dataset_id,),
            )
        return self.get_import(import_id)  # type: ignore

    def update_import_progress(
        self,
        import_id: str,
        status: str = "transferring",
        bytes_transferred: int = 0,
        total_bytes: int | None = None,
        transfer_rate_bps: float | None = None,
        destination_path: str | None = None,
        checksum_verified: bool | None = None,
        error_message: str | None = None,
    ):
        with self._lock, self.connection() as conn:
            completed_at = utc_now() if status in ("completed", "failed", "cancelled") else None
            conn.execute(
                """
                UPDATE sequencing_imports SET
                    status = ?,
                    bytes_transferred = ?,
                    transfer_rate_bps = ?,
                    destination_path = COALESCE(?, destination_path),
                    checksum_verified = COALESCE(?, checksum_verified),
                    completed_at = ?,
                    error_message = ?
                WHERE import_id = ?
                """,
                (
                    status,
                    bytes_transferred,
                    transfer_rate_bps,
                    destination_path,
                    1 if checksum_verified else (0 if checksum_verified is False else None),
                    completed_at,
                    error_message,
                    import_id,
                ),
            )
            # Update dataset import status
            ds_status = (
                "imported" if status == "completed" else "failed" if status == "failed" else "importing"
            )
            row = conn.execute("SELECT dataset_id FROM sequencing_imports WHERE import_id = ?", (import_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE sequencing_datasets SET import_status = ?, local_storage_path = COALESCE(?, local_storage_path) WHERE dataset_id = ?",
                    (ds_status, destination_path, row["dataset_id"]),
                )

    def get_import(self, import_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM sequencing_imports WHERE import_id = ?", (import_id,)).fetchone()
            if not row:
                return None
            return {
                "import_id": row["import_id"],
                "dataset_id": row["dataset_id"],
                "run_id": row["run_id"],
                "connection_id": row["connection_id"],
                "status": row["status"],
                "bytes_transferred": row["bytes_transferred"],
                "total_bytes": row["total_bytes"],
                "transfer_rate_bps": row["transfer_rate_bps"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "destination_path": row["destination_path"],
                "checksum_verified": bool(row["checksum_verified"]) if row["checksum_verified"] is not None else None,
                "error_message": row["error_message"],
            }
