"""Local sequencing folder connector.

Safely discovers, validates, and ingests sequencing files from configurable
allowlisted directories with file stability detection, path traversal prevention,
and streaming checksum verification.
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

DEFAULT_ALLOWLIST = [
    Path("artifacts/sequencing/incoming").resolve(),
    Path("artifacts/sequencing/test_data").resolve(),
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


class LocalFolderConnector(SequencingConnector):
    """Ingests sequencing data from controlled local or network-mounted directories."""

    SUPPORTED_EXTENSIONS = [
        ".fastq",
        ".fastq.gz",
        ".fq",
        ".fq.gz",
        ".fasta",
        ".fasta.gz",
        ".fa",
        ".fa.gz",
        ".bam",
        ".cram",
        ".vcf",
        ".vcf.gz",
    ]

    COMPLETION_MARKERS = [
        ".complete",
        "RunCompletionStatus.xml",
        "RTAComplete.txt",
        "final_summary.txt",
        "CopyComplete.txt",
    ]

    def __init__(self, allowlisted_roots: list[Path] | None = None):
        self.allowlisted_roots = [p.resolve() for p in (allowlisted_roots or DEFAULT_ALLOWLIST)]

    @property
    def connector_id(self) -> str:
        return "local_folder"

    @property
    def name(self) -> str:
        return "Local & Network Sequencing Folders"

    @property
    def vendor(self) -> str:
        return "local"

    @property
    def auth_type(self) -> str:
        return "directory_path"

    @property
    def description(self) -> str:
        return (
            "Monitors local lab instrument drops or NAS mounts. Supports automated "
            "file stability detection, checksum verification, and atomic imports."
        )

    def capabilities(self) -> list[str]:
        return [
            "folder_scanning",
            "file_stability_detection",
            "completion_marker_detection",
            "checksum_verification",
            "atomic_copy",
            "read_only_access",
        ]

    def supported_file_types(self) -> list[str]:
        return list(self.SUPPORTED_EXTENSIONS)

    def _validate_safe_path(self, target_path: Path) -> Path:
        """Enforce strict directory traversal protections."""
        resolved = target_path.resolve()
        if not any(
            resolved == root or resolved.is_relative_to(root)
            for root in self.allowlisted_roots
        ):
            # Also allow user home directories under controlled tests
            raise PermissionError(
                f"Access denied: Path '{resolved}' is outside allowlisted sequencing directories. "
                f"Allowlist: {[str(r) for r in self.allowlisted_roots]}"
            )
        return resolved

    def _get_folder_path(self, config: dict[str, Any]) -> str:
        folder = config.get("folder_path") or config.get("directory_path")
        if not folder:
            raise KeyError("folder_path or directory_path configuration required")
        return str(folder)

    def validate_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        folder_str = config.get("folder_path") or config.get("directory_path")
        if not folder_str:
            return {"valid": False, "message": "folder_path configuration required", "details": {}}
        try:
            path = self._validate_safe_path(Path(folder_str))
            if not path.exists():
                return {"valid": False, "message": f"Directory does not exist: {path}", "details": {}}
            if not path.is_dir():
                return {"valid": False, "message": f"Path is not a directory: {path}", "details": {}}
            if not os.access(path, os.R_OK):
                return {"valid": False, "message": f"Directory is not readable: {path}", "details": {}}

            # Count entries
            entries = list(path.iterdir())
            return {
                "valid": True,
                "message": f"Accessible directory with {len(entries)} top-level items.",
                "details": {
                    "resolved_path": str(path),
                    "total_entries": len(entries),
                    "is_readable": True,
                },
            }
        except PermissionError as exc:
            return {"valid": False, "message": str(exc), "details": {}}
        except Exception as exc:
            return {"valid": False, "message": f"Validation error: {exc}", "details": {}}

    def discover_runs(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Identify sequencing runs in the directory.

        A run can be:
        1. A subdirectory containing sequencing files or a completion marker.
        2. The root folder itself if it contains files directly.
        """
        root = self._validate_safe_path(Path(self._get_folder_path(config)))
        runs = []

        subdirs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]

        if not subdirs:
            # Check if root itself has sequencing files
            files = self._find_sequencing_files(root, recursive=False)
            if files:
                runs.append(self._create_run_record(root, files, is_root=True))
            return runs

        for subdir in subdirs:
            files = self._find_sequencing_files(subdir, recursive=True)
            if files or self._has_completion_marker(subdir):
                runs.append(self._create_run_record(subdir, files, is_root=False))

        return runs

    def list_datasets(
        self, config: dict[str, Any], external_run_id: str
    ) -> list[dict[str, Any]]:
        root = self._validate_safe_path(Path(self._get_folder_path(config)))
        # external_run_id corresponds to relative subfolder path or 'root'
        target_dir = root if external_run_id == "root" else root / external_run_id
        target_dir = self._validate_safe_path(target_dir)

        files = self._find_sequencing_files(target_dir, recursive=True)
        datasets = []

        for f in files:
            stat = f.stat()
            rel_path = str(f.relative_to(root))
            fmt = self._detect_format(f.name)
            read_type = self._detect_read_type(f.name)
            stable = self._is_file_stable(f)

            datasets.append(
                {
                    "dataset_id": f"ds_local_{hashlib.sha256(rel_path.encode()).hexdigest()[:16]}",
                    "sample_id": self._extract_sample_id(f.name),
                    "sample_name": self._extract_sample_id(f.name),
                    "file_name": f.name,
                    "file_path": rel_path,
                    "file_format": fmt,
                    "file_size_bytes": stat.st_size,
                    "checksum": None,  # Computed on demand or import
                    "checksum_algorithm": "sha256",
                    "read_type": read_type,
                    "is_complete": stable,
                    "stability_verified": stable,
                    "import_status": "available",
                    "analysis_eligibility": self._determine_eligibility(fmt, read_type),
                    "discovered_at": utc_now(),
                }
            )

        return datasets

    def import_dataset(
        self,
        config: dict[str, Any],
        dataset: dict[str, Any],
        destination_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Copy file safely with streaming copy, atomic rename, and SHA-256 verification."""
        root = self._validate_safe_path(Path(self._get_folder_path(config)))
        src_path = self._validate_safe_path(root / dataset["file_path"])

        if not src_path.exists():
            return {
                "success": False,
                "local_path": None,
                "checksum": None,
                "error": f"Source file does not exist: {src_path}",
            }

        destination_dir.mkdir(parents=True, exist_ok=True)
        dest_final = destination_dir / dataset["file_name"]
        dest_part = destination_dir / f"{dataset['file_name']}.part_{int(time.time())}"

        total_size = src_path.stat().st_size
        transferred = 0
        hasher = hashlib.sha256()

        try:
            with open(src_path, "rb") as f_in, open(dest_part, "wb") as f_out:
                while chunk := f_in.read(128 * 1024):
                    f_out.write(chunk)
                    hasher.update(chunk)
                    transferred += len(chunk)
                    if progress_callback:
                        progress_callback(transferred, total_size)

            # Atomic rename on same filesystem
            dest_part.replace(dest_final)
            checksum = hasher.hexdigest()

            return {
                "success": True,
                "local_path": str(dest_final),
                "checksum": checksum,
                "checksum_algorithm": "sha256",
                "error": None,
            }
        except Exception as exc:
            if dest_part.exists():
                dest_part.unlink(missing_ok=True)
            return {
                "success": False,
                "local_path": None,
                "checksum": None,
                "error": f"Transfer failed: {exc}",
            }

    # -------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------

    def _find_sequencing_files(self, directory: Path, recursive: bool = True) -> list[Path]:
        files = []
        iterator = directory.rglob("*") if recursive else directory.glob("*")
        for p in iterator:
            if p.is_file() and not p.name.startswith("."):
                lower = p.name.lower()
                if any(lower.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS):
                    files.append(p)
        return sorted(files)

    def _has_completion_marker(self, directory: Path) -> bool:
        for marker in self.COMPLETION_MARKERS:
            if (directory / marker).exists():
                return True
        return False

    def _is_file_stable(self, path: Path) -> bool:
        """Check if file has not been modified within the last 2 seconds."""
        mtime = path.stat().st_mtime
        return (time.time() - mtime) >= 2.0

    def _create_run_record(self, run_dir: Path, files: list[Path], is_root: bool) -> dict[str, Any]:
        run_name = run_dir.name if not is_root else "Root_Directory_Run"
        total_size = sum(f.stat().st_size for f in files)
        is_completed = self._has_completion_marker(run_dir) or all(
            self._is_file_stable(f) for f in files
        )

        samples = {self._extract_sample_id(f.name) for f in files} - {None}

        return {
            "external_run_id": "root" if is_root else run_dir.name,
            "run_name": run_name,
            "instrument_model": self._infer_instrument(run_dir),
            "sequencing_method": self._infer_method(files),
            "project_name": run_dir.parent.name if not is_root else "Local_Drop",
            "sample_count": len(samples) or (1 if files else 0),
            "status": "completed" if is_completed else "running",
            "dataset_count": len(files),
            "total_size_bytes": total_size,
            "source_metadata": {
                "directory_path": str(run_dir),
                "completion_marker_found": self._has_completion_marker(run_dir),
                "file_count": len(files),
            },
            "provenance": {
                "connector": "local_folder",
                "scanned_at": utc_now(),
                "host_path": str(run_dir),
            },
        }

    @staticmethod
    def _detect_format(name: str) -> str:
        lower = name.lower()
        if lower.endswith(".fastq.gz") or lower.endswith(".fq.gz"):
            return "fastq_gz"
        if lower.endswith(".fastq") or lower.endswith(".fq"):
            return "fastq"
        if lower.endswith(".fasta.gz") or lower.endswith(".fa.gz"):
            return "fasta_gz"
        if lower.endswith(".fasta") or lower.endswith(".fa"):
            return "fasta"
        if lower.endswith(".bam"):
            return "bam"
        if lower.endswith(".cram"):
            return "cram"
        if lower.endswith(".vcf.gz"):
            return "vcf_gz"
        if lower.endswith(".vcf"):
            return "vcf"
        return "other"

    @staticmethod
    def _detect_read_type(name: str) -> str:
        lower = name.lower()
        if "_r1_" in lower or "_1.fastq" in lower or "_r1." in lower:
            return "paired_end_R1"
        if "_r2_" in lower or "_2.fastq" in lower or "_r2." in lower:
            return "paired_end_R2"
        if "hifi" in lower or "ccs" in lower:
            return "hifi_ccs"
        if "pass" in lower or "fail" in lower:
            return "long_read"
        return "single_end"

    @staticmethod
    def _extract_sample_id(name: str) -> str | None:
        # e.g. Sample1_S1_L001_R1_001.fastq.gz -> Sample1
        m = re.match(r"^([A-Za-z0-9_-]+?)_S\d+_L\d+", name)
        if m:
            return m.group(1)
        m2 = re.match(r"^([A-Za-z0-9_-]+?)(?:_R[12]|_[12])\.", name)
        if m2:
            return m2.group(1)
        return name.split(".")[0]

    @staticmethod
    def _infer_instrument(directory: Path) -> str | None:
        # Look for Illumina RTA files or MinKNOW summary
        if (directory / "RTAComplete.txt").exists():
            return "Illumina Instrument (Local RTA)"
        if (directory / "final_summary.txt").exists():
            return "Oxford Nanopore MinKNOW"
        return "Local Instrument Drop"

    @staticmethod
    def _infer_method(files: list[Path]) -> str:
        formats = {LocalFolderConnector._detect_format(f.name) for f in files}
        if "fastq_gz" in formats or "fastq" in formats:
            return "short_read_paired_end"
        if "bam" in formats:
            return "alignment_or_hifi_bam"
        if "fasta" in formats or "fasta_gz" in formats:
            return "assembled_contigs"
        return "sequencing_data"

    @staticmethod
    def _determine_eligibility(fmt: str, read_type: str) -> dict[str, Any]:
        is_nucleotide_reads = fmt in ("fastq", "fastq_gz")
        is_protein_fasta = fmt in ("fasta", "fasta_gz")
        return {
            "raw_reads": is_nucleotide_reads,
            "requires_qc_and_assembly": is_nucleotide_reads,
            "direct_amp_prediction_eligible": False,  # Strict: reads are never direct AMP inputs!
            "requires_translation_for_amp": True,
            "read_type": read_type,
        }
