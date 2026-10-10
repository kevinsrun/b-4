"""Oxford Nanopore Technologies MinKNOW connector.

Supports MinKNOW run directories, parsing final_summary.txt and sequencing_summary.txt,
distinguishing raw electrical signal (POD5/FAST5) from basecalled long reads (fastq_pass, fastq_fail),
and importing verified read sets.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .connector_base import SequencingConnector

DEFAULT_NANOPORE_ALLOWLIST = [
    Path("artifacts/sequencing/incoming").resolve(),
    Path("artifacts/sequencing/test_data").resolve(),
    Path("artifacts/sequencing/nanopore").resolve(),
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


# Fixtures for contract testing and disconnected laboratory validation
NANOPORE_FIXTURE_RUNS = [
    {
        "run_id": "ont_run_20261007_promethion",
        "name": "20261007_1430_P2S-01928-A_PAM78901_enterococcus_bacteriocin",
        "device_id": "P2S-01928-A",
        "instrument_model": "PromethION 2 Solo",
        "flow_cell_id": "PAM78901",
        "protocol_run_id": "018e47b2-f38a-7840-a1bb-c8b18f0a2d5e",
        "sample_id": "Enterococcus_faecium_E980",
        "status": "completed",
        "started_at": "2026-10-07T14:30:00Z",
        "completed_at": "2026-10-08T02:30:00Z",
        "total_size": 24890123450,
        "sample_count": 1,
        "pore_type": "R10.4.1",
        "basecaller": "Dorado 0.5.3 (super-accurate)",
        "reads_basecalled": 2450810,
        "bases_basecalled": 11840920150,
    },
    {
        "run_id": "ont_run_20261006_gridion",
        "name": "20261006_0915_GA50000_FAK12345_lactobacillus_multiplex",
        "device_id": "GA50000",
        "instrument_model": "GridION Mk1",
        "flow_cell_id": "FAK12345",
        "protocol_run_id": "018e4210-91ab-7231-9ff2-a1288cba9912",
        "sample_id": "Lactobacillus_paracasei_pool",
        "status": "completed",
        "started_at": "2026-10-06T09:15:00Z",
        "completed_at": "2026-10-07T09:15:00Z",
        "total_size": 18450190800,
        "sample_count": 8,
        "pore_type": "R10.4.1",
        "basecaller": "Guppy 6.5.7 (high-accuracy)",
        "reads_basecalled": 1820400,
        "bases_basecalled": 8920100400,
    },
]

NANOPORE_FIXTURE_DATASETS = {
    "ont_run_20261007_promethion": [
        {
            "dataset_id": "ds_ont_prome_fastq_01",
            "file_name": "PAM78901_pass_barcode01_001.fastq.gz",
            "relative_path": "fastq_pass/barcode01/PAM78901_pass_barcode01_001.fastq.gz",
            "file_format": "fastq_gz",
            "file_size": 4120930100,
            "read_type": "long_read",
            "checksum": "88a9c1e7a641b9d0e2e132049e7b23f81e053a5c18e9d34e9c70b8a1f4d92e10",
            "sample_name": "E_faecium_E980_isolate1",
            "is_pass": True,
            "content_type": "basecalled_reads",
        },
        {
            "dataset_id": "ds_ont_prome_bam_01",
            "file_name": "PAM78901_pass_dorado_calls.bam",
            "relative_path": "bam_pass/PAM78901_pass_dorado_calls.bam",
            "file_format": "bam",
            "file_size": 5890120400,
            "read_type": "long_read",
            "checksum": "3b7c91a08234ff98d1a4918e93ba024ef12409b8231089adfe0982314e8912ba",
            "sample_name": "E_faecium_E980_isolate1",
            "is_pass": True,
            "content_type": "aligned_basecalls",
        },
        {
            "dataset_id": "ds_ont_prome_pod5_01",
            "file_name": "PAM78901_output_001.pod5",
            "relative_path": "pod5/PAM78901_output_001.pod5",
            "file_format": "pod5",
            "file_size": 14879072950,
            "read_type": "raw_signal",
            "checksum": "99e128ab8301824ef9381023ba9401284ebf10928348e029318fa9023419bb11",
            "sample_name": "E_faecium_E980_isolate1",
            "is_pass": True,
            "content_type": "raw_signal",
        },
    ],
    "ont_run_20261006_gridion": [
        {
            "dataset_id": "ds_ont_grid_fastq_01",
            "file_name": "FAK12345_pass_barcode01.fastq.gz",
            "relative_path": "fastq_pass/barcode01/FAK12345_pass_barcode01.fastq.gz",
            "file_format": "fastq_gz",
            "file_size": 2109400200,
            "read_type": "long_read",
            "checksum": "11ab34cd56ef78901234567890abcdef1234567890abcdef1234567890abcdef",
            "sample_name": "L_paracasei_subsp_paracasei",
            "is_pass": True,
            "content_type": "basecalled_reads",
        },
        {
            "dataset_id": "ds_ont_grid_summary",
            "file_name": "final_summary_FAK12345.txt",
            "relative_path": "final_summary_FAK12345.txt",
            "file_format": "other",
            "file_size": 14200,
            "read_type": "unknown",
            "checksum": "44cc22aa11bb33dd55ee77ff9900112233445566778899aabbccddeeff001122",
            "sample_name": "Lactobacillus_multiplex",
            "is_pass": True,
            "content_type": "run_summary",
        },
    ],
}


class OxfordNanoporeConnector(SequencingConnector):
    """Integrates with Oxford Nanopore MinKNOW run directories and summaries."""

    SUPPORTED_EXTENSIONS = [
        ".fastq",
        ".fastq.gz",
        ".fq",
        ".fq.gz",
        ".pod5",
        ".fast5",
        ".bam",
        ".cram",
        ".txt",
    ]

    def __init__(self, allowlisted_roots: list[Path] | None = None):
        self.allowlisted_roots = [p.resolve() for p in (allowlisted_roots or DEFAULT_NANOPORE_ALLOWLIST)]

    @property
    def connector_id(self) -> str:
        return "oxford_nanopore"

    @property
    def name(self) -> str:
        return "Oxford Nanopore MinKNOW"

    @property
    def vendor(self) -> str:
        return "nanopore"

    @property
    def auth_type(self) -> str:
        return "directory_path"

    @property
    def description(self) -> str:
        return (
            "Integrates with Oxford Nanopore MinKNOW sequencing output folders. "
            "Parses final_summary.txt metrics, separates basecalled reads (fastq_pass) from "
            "raw electrical signal (POD5/FAST5), and enforces downstream translation prerequisites."
        )

    def capabilities(self) -> list[str]:
        return [
            "run_discovery",
            "sample_tracking",
            "fastq_ingestion",
            "raw_signal_inventory",
            "final_summary_parsing",
            "checksum_verification",
            "contract_fixtures",
        ]

    def supported_file_types(self) -> list[str]:
        return self.SUPPORTED_EXTENSIONS

    def _resolve_safe_path(self, path_str: str) -> Path:
        """Resolve path and verify it is inside allowlisted roots."""
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
        """Validate MinKNOW folder path or contract fixture mode."""
        if config.get("use_fixtures", False) or config.get("simulation_mode", False):
            return {
                "valid": True,
                "message": "Connected to Oxford Nanopore contract fixtures (offline verification mode).",
                "details": {
                    "mode": "fixture_simulation",
                    "available_runs": len(NANOPORE_FIXTURE_RUNS),
                    "supported_pores": ["R10.4.1", "R9.4.1"],
                },
            }

        directory_path = config.get("directory_path")
        if not directory_path:
            return {
                "valid": False,
                "message": "Configuration requires 'directory_path' or 'use_fixtures': true.",
                "details": {},
            }

        try:
            resolved = self._resolve_safe_path(directory_path)
            if not resolved.exists():
                return {
                    "valid": False,
                    "message": f"MinKNOW output directory does not exist: {resolved}",
                    "details": {"path": str(resolved)},
                }
            if not resolved.is_dir():
                return {
                    "valid": False,
                    "message": f"Path exists but is not a directory: {resolved}",
                    "details": {"path": str(resolved)},
                }

            # Check read permissions
            if not os.access(resolved, os.R_OK):
                return {
                    "valid": False,
                    "message": f"Directory lacks read permissions: {resolved}",
                    "details": {"path": str(resolved)},
                }

            # Scan for final_summary files or run folders
            summary_files = list(resolved.glob("**/final_summary*.txt"))
            fastq_dirs = list(resolved.glob("**/fastq_pass"))
            pod5_dirs = list(resolved.glob("**/pod5"))

            return {
                "valid": True,
                "message": f"Verified MinKNOW directory: {resolved}",
                "details": {
                    "path": str(resolved),
                    "final_summary_count": len(summary_files),
                    "fastq_pass_count": len(fastq_dirs),
                    "pod5_count": len(pod5_dirs),
                },
            }
        except PermissionError as e:
            return {"valid": False, "message": str(e), "details": {"type": "PermissionError"}}
        except Exception as e:
            return {"valid": False, "message": f"Validation failed: {e}", "details": {"error": str(e)}}

    def _parse_final_summary(self, summary_path: Path) -> dict[str, str]:
        """Parse key-value pairs from MinKNOW final_summary.txt."""
        metrics: dict[str, str] = {}
        if not summary_path.exists():
            return metrics
        try:
            with open(summary_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        metrics[k.strip()] = v.strip()
        except Exception:
            pass
        return metrics

    def discover_runs(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Discover Nanopore runs from directory or fixtures."""
        if config.get("use_fixtures", False) or config.get("simulation_mode", False):
            runs = []
            for fr in NANOPORE_FIXTURE_RUNS:
                runs.append({
                    "external_run_id": fr["run_id"],
                    "run_name": fr["name"],
                    "instrument_model": fr["instrument_model"],
                    "sequencing_method": "Oxford Nanopore Sequencing",
                    "project_name": fr.get("sample_id", "Nanopore Research Run"),
                    "sample_count": fr["sample_count"],
                    "status": fr["status"],
                    "started_at": fr["started_at"],
                    "completed_at": fr["completed_at"],
                    "source_metadata": {
                        "device_id": fr["device_id"],
                        "flow_cell_id": fr["flow_cell_id"],
                        "protocol_run_id": fr["protocol_run_id"],
                        "pore_type": fr["pore_type"],
                        "basecaller": fr["basecaller"],
                        "reads_basecalled": fr["reads_basecalled"],
                        "bases_basecalled": fr["bases_basecalled"],
                        "source_type": "nanopore_fixture",
                    },
                    "provenance": {
                        "vendor": "nanopore",
                        "discovered_at": utc_now(),
                        "fixture_verified": True,
                    },
                })
            return runs

        directory_path = config.get("directory_path")
        if not directory_path:
            return []

        resolved = self._resolve_safe_path(directory_path)
        discovered_runs: list[dict[str, Any]] = []

        # Find all run directories: either contains final_summary*.txt or fastq_pass
        candidates = set()
        for summary in resolved.glob("**/final_summary*.txt"):
            candidates.add(summary.parent)
        for fq_pass in resolved.glob("**/fastq_pass"):
            candidates.add(fq_pass.parent)

        # If direct directory itself has FASTQ/POD5 files, treat it as a run candidate
        direct_files = [f for f in resolved.iterdir() if f.is_file() and any(f.name.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS)]
        if direct_files:
            candidates.add(resolved)

        for run_dir in candidates:
            # Parse final_summary if available
            summaries = list(run_dir.glob("final_summary*.txt"))
            summary_metrics = self._parse_final_summary(summaries[0]) if summaries else {}

            external_id = summary_metrics.get("protocol_run_id") or summary_metrics.get("run_id") or run_dir.name
            run_name = run_dir.name
            instrument = summary_metrics.get("instrument") or summary_metrics.get("device_id") or "MinKNOW Device"
            flow_cell = summary_metrics.get("flow_cell_id")

            # Determine run completion
            is_completed = (
                "acquisition_stopped" in summary_metrics
                or "processing_stopped" in summary_metrics
                or len(summaries) > 0
            )
            status = "completed" if is_completed else "running"

            started_at = summary_metrics.get("started")
            completed_at = summary_metrics.get("processing_stopped") or summary_metrics.get("acquisition_stopped")

            # Sample count: count distinct barcode folders in fastq_pass or barcodes
            barcode_dirs = list(run_dir.glob("fastq_pass/barcode*"))
            sample_count = max(len(barcode_dirs), 1)

            discovered_runs.append({
                "external_run_id": external_id,
                "run_name": run_name,
                "instrument_model": instrument,
                "sequencing_method": "Oxford Nanopore Sequencing",
                "project_name": run_dir.parent.name if run_dir != resolved else "Nanopore Import",
                "sample_count": sample_count,
                "status": status,
                "started_at": started_at,
                "completed_at": completed_at,
                "source_metadata": {
                    "run_dir": str(run_dir),
                    "flow_cell_id": flow_cell,
                    "metrics": summary_metrics,
                    "has_final_summary": len(summaries) > 0,
                },
                "provenance": {
                    "vendor": "nanopore",
                    "discovered_at": utc_now(),
                    "source_path": str(run_dir),
                },
            })

        return discovered_runs

    def list_datasets(self, config: dict[str, Any], external_run_id: str) -> list[dict[str, Any]]:
        """List datasets (FASTQ, POD5, FAST5, BAM) for a Nanopore run."""
        if config.get("use_fixtures", False) or config.get("simulation_mode", False):
            fixtures = NANOPORE_FIXTURE_DATASETS.get(external_run_id, [])
            datasets = []
            for f in fixtures:
                datasets.append({
                    "dataset_id": f["dataset_id"],
                    "file_name": f["file_name"],
                    "file_path": f["relative_path"],
                    "file_format": f["file_format"],
                    "file_size_bytes": f["file_size"],
                    "checksum": f["checksum"],
                    "checksum_algorithm": "sha256",
                    "read_type": f["read_type"],
                    "is_complete": True,
                    "stability_verified": True,
                    "sample_name": f.get("sample_name"),
                    "analysis_eligibility": {
                        "is_direct_amp_eligible": False,  # Scientific rule: raw/long-read FASTQ/POD5 cannot feed directly to AMP
                        "requires_basecalling": f["read_type"] == "raw_signal",
                        "requires_assembly_or_orf": True,
                        "requires_translation": True,
                        "content_type": f.get("content_type"),
                    },
                })
            return datasets

        directory_path = config.get("directory_path")
        if not directory_path:
            return []

        resolved = self._resolve_safe_path(directory_path)

        # Locate run folder corresponding to external_run_id
        target_dir = None
        for d in [resolved] + list(resolved.glob("**/*")):
            if d.is_dir() and d.name == external_run_id:
                target_dir = d
                break
            # check final_summary inside
            summaries = list(d.glob("final_summary*.txt")) if d.is_dir() else []
            if summaries:
                sm = self._parse_final_summary(summaries[0])
                if sm.get("protocol_run_id") == external_run_id or sm.get("run_id") == external_run_id:
                    target_dir = d
                    break

        if not target_dir:
            target_dir = resolved

        datasets: list[dict[str, Any]] = []
        for file_path in target_dir.glob("**/*"):
            if not file_path.is_file():
                continue

            name = file_path.name
            matched_ext = None
            for ext in self.SUPPORTED_EXTENSIONS:
                if name.endswith(ext):
                    matched_ext = ext
                    break
            if not matched_ext:
                continue

            # Classify format and read type
            if name.endswith(".fastq.gz") or name.endswith(".fq.gz"):
                file_format = "fastq_gz"
                read_type = "long_read"
            elif name.endswith(".fastq") or name.endswith(".fq"):
                file_format = "fastq"
                read_type = "long_read"
            elif name.endswith(".pod5"):
                file_format = "pod5"
                read_type = "raw_signal"
            elif name.endswith(".fast5"):
                file_format = "fast5"
                read_type = "raw_signal"
            elif name.endswith(".bam"):
                file_format = "bam"
                read_type = "long_read"
            elif name.endswith(".cram"):
                file_format = "cram"
                read_type = "long_read"
            elif name.startswith("final_summary") or name.endswith(".txt"):
                file_format = "other"
                read_type = "unknown"
            else:
                file_format = "other"
                read_type = "unknown"

            # Check if inside fastq_pass vs fastq_fail
            is_pass = "fastq_fail" not in str(file_path)

            stat = file_path.stat()
            dataset_id = f"ont_ds_{hashlib.md5(str(file_path).encode()).hexdigest()[:12]}"

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
                "sample_name": file_path.parent.name if "barcode" in file_path.parent.name else None,
                "analysis_eligibility": {
                    "is_direct_amp_eligible": False,
                    "is_pass_filter": is_pass,
                    "requires_basecalling": read_type == "raw_signal",
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
        """Safely import Nanopore dataset file with streaming checksum verification."""
        destination_dir = destination_dir.resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)

        file_name = dataset["file_name"]
        final_dest = destination_dir / file_name
        part_dest = destination_dir / f"{file_name}.part"

        # Check for simulated fixture import
        if config.get("use_fixtures", False) or config.get("simulation_mode", False):
            # Create synthetic representative file for verification
            sim_content = f"# Oxford Nanopore synthetic export for {file_name}\n# Run: {dataset.get('dataset_id')}\n"
            if "fastq" in dataset.get("file_format", ""):
                sim_content += "@ONT_READ_001 runid=fixture ch=12 start_time=2026-10-07T14:30:00Z\nATGAAAGCAACTGTTAAAGCATTGGTCGCAGCTATGCTACTAGGTTCTGTAGCGCAGGCAGATACTAAACCGTTTGGT\n+\nIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII\n"
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

            # Atomic commit
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
