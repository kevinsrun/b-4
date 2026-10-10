"""Local SQLite persistence for jobs, successful inference cache and DRAMP snapshots."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .adapters import digest, timestamp


class JobConflict(Exception):
    pass


class CapacityExceeded(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE,
                    request_hash TEXT NOT NULL, request_json TEXT NOT NULL,
                    status TEXT NOT NULL, owner_pid INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    report_json TEXT, error_json TEXT
                );
                CREATE TABLE IF NOT EXISTS prediction_cache (
                    cache_key TEXT PRIMARY KEY, prediction_json TEXT NOT NULL,
                    stored_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dramp_datasets (
                    dataset_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dramp_records (
                    dataset_id TEXT NOT NULL, record_id TEXT NOT NULL,
                    sequence TEXT NOT NULL, checksum TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, record_id),
                    FOREIGN KEY (dataset_id) REFERENCES dramp_datasets(dataset_id)
                );
                CREATE INDEX IF NOT EXISTS dramp_checksum ON dramp_records(checksum);
                CREATE INDEX IF NOT EXISTS dramp_record_id ON dramp_records(record_id);
                CREATE TABLE IF NOT EXISTS dramp_rejected (
                    dataset_id TEXT NOT NULL, row_number INTEGER NOT NULL,
                    reason TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, row_number),
                    FOREIGN KEY (dataset_id) REFERENCES dramp_datasets(dataset_id)
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover_dead_jobs(self) -> int:
        """Single-host recovery. Never interrupt another live server's jobs."""
        recovered = 0
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(
                "SELECT job_id, owner_pid FROM jobs WHERE status IN ('queued','running')"
            ):
                try:
                    os.kill(row["owner_pid"], 0)
                except ProcessLookupError:
                    db.execute(
                        "UPDATE jobs SET status='interrupted', updated_at=?, error_json=? "
                        "WHERE job_id=?",
                        (
                            timestamp(),
                            json.dumps(
                                {
                                    "code": "WORKER_INTERRUPTED",
                                    "message": "server exited before job completion",
                                    "retryable": True,
                                }
                            ),
                            row["job_id"],
                        ),
                    )
                    recovered += 1
                except PermissionError:
                    pass
        return recovered

    def create_job(self, request: dict[str, Any], identity: dict[str, Any], key: str | None):
        request_hash = digest({"request": request, "model_identities": identity})
        key_hash = digest(key) if key else None
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if key_hash:
                existing = db.execute(
                    "SELECT * FROM jobs WHERE idempotency_key=?", (key_hash,)
                ).fetchone()
                if existing:
                    if existing["request_hash"] != request_hash:
                        raise JobConflict(
                            "idempotency key already used with a different request/runtime"
                        )
                    return self._job(existing), False
            active = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if active >= 4:
                raise CapacityExceeded("four AMP jobs are already queued or running")
            job_id, now = uuid.uuid4().hex, timestamp()
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    key_hash,
                    request_hash,
                    json.dumps(request),
                    "queued",
                    os.getpid(),
                    now,
                    now,
                    None,
                    None,
                ),
            )
            return self._job(
                db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            ), True

    @staticmethod
    def _job(row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "report": json.loads(row["report_json"]) if row["report_json"] else None,
            "error": json.loads(row["error_json"]) if row["error_json"] else None,
        }

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return self._job(row) if row else None

    def update_job(self, job_id: str, status: str, *, report=None, error=None):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status=?, updated_at=?, report_json=?, error_json=? "
                "WHERE job_id=?",
                (
                    status,
                    timestamp(),
                    json.dumps(report) if report else None,
                    json.dumps(error) if error else None,
                    job_id,
                ),
            )

    def cached(self, key: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT prediction_json FROM prediction_cache WHERE cache_key=?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def cache(self, key: str, prediction: dict[str, Any]):
        if prediction["status"] != "succeeded":
            raise ValueError("only successful predictions may be cached")
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO prediction_cache VALUES (?,?,?)",
                (key, json.dumps(prediction), timestamp()),
            )
            db.execute(
                "DELETE FROM prediction_cache WHERE cache_key IN "
                "(SELECT cache_key FROM prediction_cache ORDER BY stored_at DESC "
                "LIMIT -1 OFFSET 4096)"
            )

    def dramp_search(
        self,
        *,
        sequence: str | None = None,
        record_id: str | None = None,
        dataset_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        from .dramp import display_provenance

        conditions, params = [], []
        if sequence is not None:
            from hashlib import sha256

            conditions.append("r.checksum=? AND r.sequence=?")
            params.extend([sha256(sequence.encode("ascii")).hexdigest(), sequence])
        if record_id is not None:
            conditions.append("r.record_id=?")
            params.append(record_id)
        if dataset_id is not None:
            conditions.append("r.dataset_id=?")
            params.append(dataset_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.connection() as db:
            total = db.execute("SELECT COUNT(*) FROM dramp_records r" + where, params).fetchone()[0]
            rows = db.execute(
                "SELECT r.*, d.manifest_json FROM dramp_records r JOIN dramp_datasets d "
                "USING(dataset_id)"
                + where
                + " ORDER BY r.record_id, r.dataset_id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            datasets = db.execute(
                "SELECT manifest_json FROM dramp_datasets ORDER BY dataset_id"
            ).fetchall()
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "database_available": bool(datasets),
                "datasets": [display_provenance(json.loads(row[0])) for row in datasets],
                "records": [
                    {
                        "record_id": r["record_id"],
                        "sequence": r["sequence"],
                        "sequence_checksum": r["checksum"],
                        "metadata": json.loads(r["metadata_json"]),
                        "provenance": display_provenance(json.loads(r["manifest_json"])),
                        "annotation_origin": (
                            "publisher annotations; experimental/computational origin "
                            "not independently adjudicated"
                        ),
                        "evidence_type": "reference-database-annotation",
                        "experimental_verification": "not independently assessed",
                    }
                    for r in rows
                ],
            }
