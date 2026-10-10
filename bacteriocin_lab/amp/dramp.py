"""Reproducible official DRAMP TSV import; preserve annotations without inferring activity."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

from .adapters import digest, file_hash, timestamp
from .store import Store

DRAMP_GENERAL_URL = (
    "https://dramp.cpu-bioinfor.org/downloads/download.php?"
    "filename=download_data%2FDRAMP3.0_new%2Fgeneral_amps.txt"
)


def ingest(
    store: Store,
    path: Path,
    *,
    source_url: str,
    source_version: str,
    expected_sha256: str,
    license_id: str = "CC-BY-4.0",
    source_provenance: dict | None = None,
) -> dict:
    if path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("DRAMP import exceeds 30 MiB")
    actual = file_hash(path)
    if actual != expected_sha256:
        raise ValueError("source checksum mismatch")
    identity = {
        "source": "DRAMP",
        "source_url": source_url,
        "source_version": source_version,
        "source_sha256": actual,
        "license": license_id,
        "ingestion_revision": "1",
        "attribution": "DRAMP database, Zheng group, https://dramp.cpu-bioinfor.org/",
    }
    if source_provenance is not None:
        if source_provenance.get("normalized_tsv_sha256") != actual:
            raise ValueError("normalized TSV provenance checksum mismatch")
        raw_hash = source_provenance.get("source_artifact_sha256", "")
        if len(raw_hash) != 64 or any(c not in "0123456789abcdef" for c in raw_hash):
            raise ValueError("original distribution SHA256 required")
        if source_provenance.get("release_version_status") not in {
            "verified_publication_snapshot",
            "unresolved",
        }:
            raise ValueError("explicit publication snapshot/release assessment required")
        identity.update(ingestion_revision="2", source_provenance=source_provenance)
    dataset_id = digest(identity)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            "SELECT manifest_json FROM dramp_datasets WHERE dataset_id=?", (dataset_id,)
        ).fetchone()
        if previous:
            return json.loads(previous[0])
        text = path.read_bytes().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        if not reader.fieldnames or not {"DRAMP_ID", "Sequence"}.issubset(reader.fieldnames):
            raise ValueError("expected official DRAMP TSV columns DRAMP_ID and Sequence")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("duplicate TSV column names")
        manifest = {**identity, "dataset_id": dataset_id, "ingested_at": timestamp()}
        db.execute("INSERT INTO dramp_datasets VALUES (?,?)", (dataset_id, json.dumps(manifest)))
        accepted, rejected, duplicates, seen = 0, 0, 0, set()
        for row_number, row in enumerate(reader, start=2):
            record_id = (row.get("DRAMP_ID") or "").strip()
            sequence = "".join((row.get("Sequence") or "").split())
            reason = None
            if None in row or any(value is None for value in row.values()):
                reason = "malformed TSV row"
            elif not record_id:
                reason = "missing source identifier"
            elif not sequence or any(c not in "ACDEFGHIKLMNPQRSTVWY" for c in sequence):
                reason = "empty, modified or noncanonical sequence; original metadata retained"
            elif len(sequence) > 10000:
                reason = "sequence exceeds import length limit"
            if reason:
                db.execute(
                    "INSERT INTO dramp_rejected VALUES (?,?,?,?)",
                    (dataset_id, row_number, reason, json.dumps(row)),
                )
                rejected += 1
                continue
            checksum = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            duplicates += checksum in seen
            seen.add(checksum)
            # Duplicate identifiers are an ambiguous snapshot, and roll back the entire import.
            db.execute(
                "INSERT INTO dramp_records VALUES (?,?,?,?,?)",
                (dataset_id, record_id, sequence, checksum, json.dumps(row)),
            )
            accepted += 1
        manifest.update(
            accepted_records=accepted,
            rejected_records=rejected,
            duplicate_sequence_records=duplicates,
            unique_sequences=len(seen),
        )
        db.execute(
            "UPDATE dramp_datasets SET manifest_json=? WHERE dataset_id=?",
            (json.dumps(manifest), dataset_id),
        )
        return manifest


def display_provenance(manifest: dict) -> dict:
    """Add a conservative assessment without changing the preserved snapshot identity."""
    source = manifest.get("source_provenance", {})
    return {
        **manifest,
        "release_version_status": source.get("release_version_status", "unresolved"),
        "release_version_assessment": source.get(
            "release_version_assessment",
            "download path/snapshot date do not establish a numbered database release",
        ),
    }
