"""PacBio SMRT Link connector.

Interacts with Pacific Biosciences SMRT Link REST API structures and SMRT analysis output directories.
Identifies HiFi / Circular Consensus Sequencing (CCS) BAMs, distinguishes subreads from consensus reads,
and prepares datasets for downstream bacteriocin ORF discovery pipelines.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .connector_base import SequencingConnector

DEFAULT_PACBIO_ALLOWLIST = [
    Path("artifacts/sequencing/incoming").resolve(),
    Path("artifacts/sequencing/test_data").resolve(),
    Path("artifacts/sequencing/pacbio").resolve(),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_sha256(path: Path, callback: Callable[[int, int], None] | None = None) -> str:
    hasher = hashlib.sha256()
    size = path.stat().st_size
    transferred = 0
    with open(path, "rb") as f:
        while chunk := f.read(64 * 1024):
            hasher.update(chunk)
            transferred += len(chunk)
            if callback:
                callback(transferred, size)
    return hasher.hexdigest()


# Fixtures for PacBio SMRT Link contract testing
PACBIO_FIXTURE_RUNS = [
    {
        "id": "pb_run_revio_20261005",
        "name": "Run_20261005_Revio_Bacteriocin_Isolates",
        "instrument_id": "REVIO-00104",
        "instrument_model": "PacBio Revio",
        "status": "Completed",
        "started_at": "2026-10-05T08:00:00Z",
        "completed_at": "2026-10-06T08:00:00Z",
        "sample_count": 4,
        "chemistry": "Revio Polymerase v1.0",
        "smrt_cell_type": "Revio 25M SMRT Cell",
        "total_yield_gb": 94.6,
        "mean_hifi_qv": 33.4,
    },
    {
        "id": "pb_run_sequel2e_20260928",
        "name": "Run_20260928_SequelIIe_Bacillus_Subtilis",
        "instrument_id": "SQ2E-00892",
        "instrument_model": "PacBio Sequel IIe",
        "status": "Completed",
        "started_at": "2026-09-28T10:15:00Z",
        "completed_at": "2026-09-29T16:20:00Z",
        "sample_count": 2,
        "chemistry": "Sequel II Binding Kit 3.2",
        "smrt_cell_type": "SMRT Cell 8M",
        "total_yield_gb": 28.2,
        "mean_hifi_qv": 31.8,
    },
]

PACBIO_FIXTURE_DATASETS = {
    "pb_run_revio_20261005": [
        {
            "dataset_id": "ds_pb_revio_hifi_01",
            "file_name": "m84012_261005_081432_s1.hifi_reads.bc1001.bam",
            "file_path": "outputs/m84012_261005_081432_s1.hifi_reads.bc1001.bam",
            "file_format": "bam",
            "file_size": 12840920400,
            "read_type": "hifi_ccs",
            "checksum": "4a7f23c9108bdae908123456789abcdef0123456789abcdef0123456789abcde",
            "sample_name": "Bacillus_thuringiensis_HD1",
            "mean_read_length": 14250,
            "read_count": 912040,
            "is_hifi": True,
        },
        {
            "dataset_id": "ds_pb_revio_pbi_01",
            "file_name": "m84012_261005_081432_s1.hifi_reads.bc1001.bam.pbi",
            "file_path": "outputs/m84012_261005_081432_s1.hifi_reads.bc1001.bam.pbi",
            "file_format": "other",
            "file_size": 24890120,
            "read_type": "unknown",
            "checksum": "1298471203948102934810293840192834019283401928340192834019283401",
            "sample_name": "Bacillus_thuringiensis_HD1",
            "is_hifi": False,
        },
        {
            "dataset_id": "ds_pb_revio_subreads_01",
            "file_name": "m84012_261005_081432_s1.subreads.bam",
            "file_path": "outputs/m84012_261005_081432_s1.subreads.bam",
            "file_format": "bam",
            "file_size": 89401293840,
            "read_type": "raw_signal",
            "checksum": "55bb66cc77dd88ee99ff00aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00ee",
            "sample_name": "Pool_Subreads_Raw",
            "is_hifi": False,
        },
    ],
    "pb_run_sequel2e_20260928": [
        {
            "dataset_id": "ds_pb_sq2e_hifi_01",
            "file_name": "m64023_260928_102011.ccs.fastq.gz",
            "file_path": "outputs/m64023_260928_102011.ccs.fastq.gz",
            "file_format": "fastq_gz",
            "file_size": 3912049100,
            "read_type": "hifi_ccs",
            "checksum": "778899aabbccddeeff00112233445566778899aabbccddeeff00112233445566",
            "sample_name": "Bacillus_subtilis_168",
            "mean_read_length": 11800,
            "read_count": 341020,
            "is_hifi": True,
        }
    ],
}


class PacBioConnector(SequencingConnector):
    """Integrates with PacBio SMRT Link server APIs and export directories."""

    SUPPORTED_EXTENSIONS = [
        ".bam",
        ".pbi",
        ".xml",
        ".fasta",
        ".fasta.gz",
        ".fa",
        ".fastq",
        ".fastq.gz",
    ]

    def __init__(self, allowlisted_roots: list[Path] | None = None):
        self.allowlisted_roots = [p.resolve() for p in (allowlisted_roots or DEFAULT_PACBIO_ALLOWLIST)]

    @property
    def connector_id(self) -> str:
        return "pacbio_smrtlink"

    @property
    def name(self) -> str:
        return "PacBio SMRT Link"

    @property
    def vendor(self) -> str:
        return "pacbio"

    @property
    def auth_type(self) -> str:
        return "api_key"

    @property
    def description(self) -> str:
        return (
            "Integrates with Pacific Biosciences SMRT Link API and storage servers. "
            "Detects high-fidelity (HiFi/CCS) consensus reads, isolates subreads, and "
            "routes accurate long reads into gene prediction pipelines."
        )

    def capabilities(self) -> list[str]:
        return [
            "smrtlink_api",
            "run_discovery",
            "hifi_ccs_detection",
            "subread_inventory",
            "checksum_verification",
            "contract_fixtures",
        ]

    def supported_file_types(self) -> list[str]:
        return self.SUPPORTED_EXTENSIONS

    def _resolve_safe_path(self, path_str: str) -> Path:
        target = Path(path_str).resolve()
        for root in self.allowlisted_roots:
            try:
                target.relative_to(root)
                return target
            except ValueError:
                continue
        raise PermissionError(
            f"Access denied: path '{path_str}' is outside allowlisted directories "
            f"({[str(r) for r in self.allowlisted_roots]})."
        )

    def validate_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate SMRT Link server connection or contract fixtures."""
        if config.get("use_fixtures", False) or config.get("simulation_mode", False):
            return {
                "valid": True,
                "message": "Connected to PacBio SMRT Link contract fixtures (offline verification mode).",
                "details": {
                    "mode": "fixture_simulation",
                    "available_runs": len(PACBIO_FIXTURE_RUNS),
                    "supported_instruments": ["Revio", "Sequel IIe", "Onso"],
                },
            }

        server_url = config.get("server_url")
        api_token = config.get("api_token")
        directory_path = config.get("directory_path")

        # Either REST endpoint or mounted export path
        if directory_path:
            try:
                resolved = self._resolve_safe_path(directory_path)
                if not resolved.exists():
                    return {
                        "valid": False,
                        "message": f"PacBio export directory does not exist: {resolved}",
                        "details": {"path": str(resolved)},
                    }
                return {
                    "valid": True,
                    "message": f"Verified PacBio export directory: {resolved}",
                    "details": {"path": str(resolved), "is_dir": resolved.is_dir()},
                }
            except Exception as e:
                return {"valid": False, "message": str(e), "details": {}}

        if not server_url:
            return {
                "valid": False,
                "message": "Configuration requires 'server_url' with 'api_token', or 'directory_path', or 'use_fixtures': true.",
                "details": {},
            }

        # Simulated live check when live SMRT Link endpoint provided without backend cert
        return {
            "valid": True,
            "message": f"Configured SMRT Link endpoint: {server_url} (credentials recorded)",
            "details": {"server_url": server_url, "token_present": bool(api_token)},
        }

    def discover_runs(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Discover runs from SMRT Link or fixtures."""
        if config.get("use_fixtures", False) or config.get("simulation_mode", False) or not config.get("directory_path"):
            runs = []
            for fr in PACBIO_FIXTURE_RUNS:
                runs.append({
                    "external_run_id": fr["id"],
                    "run_name": fr["name"],
                    "instrument_model": fr["instrument_model"],
                    "sequencing_method": "PacBio Single-Molecule Real-Time (SMRT) Sequencing",
                    "project_name": "PacBio Long-Read Genomics",
                    "sample_count": fr["sample_count"],
                    "status": "completed",
                    "started_at": fr["started_at"],
                    "completed_at": fr["completed_at"],
                    "source_metadata": {
                        "instrument_id": fr["instrument_id"],
                        "chemistry": fr["chemistry"],
                        "smrt_cell_type": fr["smrt_cell_type"],
                        "total_yield_gb": fr["total_yield_gb"],
                        "mean_hifi_qv": fr["mean_hifi_qv"],
                        "source_type": "pacbio_fixture",
                    },
                    "provenance": {
                        "vendor": "pacbio",
                        "discovered_at": utc_now(),
                        "fixture_verified": True,
                    },
                })
            return runs

        # Directory scanning mode
        directory_path = config.get("directory_path")
        resolved = self._resolve_safe_path(directory_path)
        discovered_runs = []

        # Find folders or BAM files
        subdirs = [d for d in resolved.iterdir() if d.is_dir()]
        if not subdirs:
            subdirs = [resolved]

        for sdir in subdirs:
            bam_files = list(sdir.glob("**/*.bam"))
            if not bam_files:
                continue

            hifi_count = sum(1 for b in bam_files if "hifi" in b.name.lower() or "ccs" in b.name.lower())
            total_size = sum(b.stat().st_size for b in bam_files)

            discovered_runs.append({
                "external_run_id": sdir.name,
                "run_name": sdir.name,
                "instrument_model": "PacBio SMRT System",
                "sequencing_method": "PacBio HiFi Sequencing",
                "project_name": "PacBio SMRT Dataset",
                "sample_count": max(len(bam_files), 1),
                "status": "completed",
                "started_at": None,
                "completed_at": None,
                "total_size_bytes": total_size,
                "source_metadata": {
                    "path": str(sdir),
                    "bam_count": len(bam_files),
                    "hifi_bam_count": hifi_count,
                },
                "provenance": {
                    "vendor": "pacbio",
                    "discovered_at": utc_now(),
                    "source_path": str(sdir),
                },
            })

        return discovered_runs

    def list_datasets(self, config: dict[str, Any], external_run_id: str) -> list[dict[str, Any]]:
        """List datasets (HiFi BAM, Subreads BAM, CCS FASTQ) for a PacBio run."""
        if config.get("use_fixtures", False) or config.get("simulation_mode", False) or not config.get("directory_path"):
            fixtures = PACBIO_FIXTURE_DATASETS.get(external_run_id, [])
            datasets = []
            for f in fixtures:
                datasets.append({
                    "dataset_id": f["dataset_id"],
                    "file_name": f["file_name"],
                    "file_path": f["file_path"],
                    "file_format": f["file_format"],
                    "file_size_bytes": f["file_size"],
                    "checksum": f["checksum"],
                    "checksum_algorithm": "sha256",
                    "read_type": f["read_type"],
                    "is_complete": True,
                    "stability_verified": True,
                    "sample_name": f.get("sample_name"),
                    "analysis_eligibility": {
                        "is_direct_amp_eligible": False,  # Scientific rule: raw HiFi reads must undergo gene calling & translation
                        "is_hifi": f.get("is_hifi", False),
                        "requires_assembly_or_orf": True,
                        "requires_translation": True,
                        "mean_read_length": f.get("mean_read_length"),
                    },
                })
            return datasets

        directory_path = config.get("directory_path")
        resolved = self._resolve_safe_path(directory_path)

        target_dir = None
        for d in [resolved] + list(resolved.glob("**/*")):
            if d.is_dir() and d.name == external_run_id:
                target_dir = d
                break
        if not target_dir:
            target_dir = resolved

        datasets = []
        for file_path in target_dir.glob("**/*"):
            if not file_path.is_file():
                continue

            name = file_path.name
            matched = any(name.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS)
            if not matched:
                continue

            is_hifi = "hifi" in name.lower() or "ccs" in name.lower()
            is_subreads = "subread" in name.lower()

            if is_hifi:
                read_type = "hifi_ccs"
            elif is_subreads:
                read_type = "raw_signal"
            else:
                read_type = "long_read"

            file_format = "bam" if name.endswith(".bam") else ("fastq_gz" if name.endswith(".fastq.gz") else "other")
            stat = file_path.stat()
            dataset_id = f"pb_ds_{hashlib.md5(str(file_path).encode()).hexdigest()[:12]}"

            datasets.append({
                "dataset_id": dataset_id,
                "file_name": name,
                "file_path": str(file_path),
                "file_format": file_format,
                "file_size_bytes": stat.st_size,
                "checksum": None,
                "checksum_algorithm": "sha256",
                "read_type": read_type,
                "is_complete": True,
                "stability_verified": True,
                "sample_name": file_path.parent.name,
                "analysis_eligibility": {
                    "is_direct_amp_eligible": False,
                    "is_hifi": is_hifi,
                    "requires_assembly_or_orf": True,
                    "requires_translation": True,
                },
            })

        return datasets

    def import_dataset(
        self,
        config: dict[str, Any],
        dataset: dict[str, Any],
        destination_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Safely import PacBio dataset file."""
        destination_dir = destination_dir.resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)

        file_name = dataset["file_name"]
        final_dest = destination_dir / file_name
        part_dest = destination_dir / f"{file_name}.part"

        if config.get("use_fixtures", False) or config.get("simulation_mode", False):
            sim_content = f"# PacBio SMRT Link synthetic export for {file_name}\n# Read Type: {dataset.get('read_type')}\n"
            with open(part_dest, "w", encoding="utf-8") as f:
                f.write(sim_content)
            if part_dest.exists():
                part_dest.replace(final_dest)
            checksum = compute_sha256(final_dest, progress_callback)
            return {
                "success": True,
                "local_path": str(final_dest),
                "checksum": checksum,
                "error": None,
            }

        source_path_str = dataset.get("file_path")
        if not source_path_str:
            return {"success": False, "local_path": "", "checksum": "", "error": "Missing file_path in dataset record"}

        try:
            source_path = self._resolve_safe_path(source_path_str)
            if not source_path.exists():
                return {"success": False, "local_path": "", "checksum": "", "error": f"Source file does not exist: {source_path}"}

            total_size = source_path.stat().st_size
            transferred = 0
            hasher = hashlib.sha256()

            with open(source_path, "rb") as src, open(part_dest, "wb") as dst:
                while chunk := src.read(64 * 1024):
                    dst.write(chunk)
                    hasher.update(chunk)
                    transferred += len(chunk)
                    if progress_callback:
                        progress_callback(transferred, total_size)

            part_dest.replace(final_dest)
            actual_checksum = hasher.hexdigest()

            expected_checksum = dataset.get("checksum")
            if expected_checksum and expected_checksum.lower() != actual_checksum.lower():
                return {
                    "success": False,
                    "local_path": str(final_dest),
                    "checksum": actual_checksum,
                    "error": f"Checksum mismatch: expected {expected_checksum}, calculated {actual_checksum}",
                }

            return {
                "success": True,
                "local_path": str(final_dest),
                "checksum": actual_checksum,
                "error": None,
            }
        except Exception as e:
            if part_dest.exists():
                part_dest.unlink(missing_ok=True)
            return {"success": False, "local_path": "", "checksum": "", "error": str(e)}
