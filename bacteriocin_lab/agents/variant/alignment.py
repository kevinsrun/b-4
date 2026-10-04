from __future__ import annotations

import abc
import contextlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import (
    AlignmentError,
    AlignmentExecutionError,
    AlignmentTimeoutError,
    AlignmentUnavailableError,
)

logger = logging.getLogger("b4_variant.alignment")


def parse_fasta_alignment(aligned_fasta_text: str) -> dict[str, str]:
    """Parse aligned FASTA text into an ordered mapping of sequence_id -> aligned_sequence.

    Preserves gap characters ('-'). Verifies that all aligned sequences share identical length.
    """
    if not aligned_fasta_text or not aligned_fasta_text.strip():
        return {}

    aligned: dict[str, str] = {}
    current_id: str | None = None
    current_lines: list[str] = []

    for line in aligned_fasta_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_id is not None:
                aligned[current_id] = "".join(current_lines).upper()
                current_lines = []
            header = line[1:].strip()
            current_id = header.split()[0] if header else "seq"
        else:
            current_lines.append(line)

    if current_id is not None:
        aligned[current_id] = "".join(current_lines).upper()

    if not aligned:
        return {}

    lengths = {len(seq) for seq in aligned.values()}
    if len(lengths) > 1:
        raise AlignmentError(
            f"Aligned sequences have inconsistent lengths: {sorted(lengths)}"
        )

    return aligned


class AlignmentBackend(abc.ABC):
    """Abstract base class for multiple sequence alignment tools."""

    @abc.abstractmethod
    def align(
        self,
        sequences: dict[str, str],
        timeout_seconds: float | None = None,
    ) -> dict[str, str]:
        """Align input unaligned sequences.

        Args:
            sequences: mapping of sequence_id -> amino acid sequence string.
            timeout_seconds: optional timeout bound in seconds.

        Returns:
            mapping of sequence_id -> aligned amino acid sequence with gaps ('-').
        """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True if backend executable is available on system."""


class MafftBackend(AlignmentBackend):
    """Multiple sequence alignment using the MAFFT executable."""

    def __init__(self, executable: str | None = None, default_timeout: float = 60.0) -> None:
        self.executable = executable or os.getenv("MAFFT_EXECUTABLE", "mafft")
        self.default_timeout = default_timeout

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None

    def align(
        self,
        sequences: dict[str, str],
        timeout_seconds: float | None = None,
    ) -> dict[str, str]:
        if not self.is_available():
            raise AlignmentUnavailableError(
                f"MAFFT executable '{self.executable}' not found on PATH"
            )

        if len(sequences) <= 1:
            return dict(sequences)

        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout

        temp_path: str | None = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fasta", delete=False) as tf:
            temp_path = tf.name
            for seq_id, seq in sequences.items():
                tf.write(f">{seq_id}\n{seq}\n")

        cmd = [self.executable, "--auto", temp_path]

        try:
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AlignmentTimeoutError(f"MAFFT alignment timed out after {timeout:.1f}s") from exc
        except OSError as exc:
            raise AlignmentExecutionError(f"Failed to execute MAFFT: {exc}", cmd=cmd) from exc
        finally:
            if temp_path:
                with contextlib.suppress(OSError):
                    Path(temp_path).unlink(missing_ok=True)

        if proc.returncode != 0:
            raise AlignmentExecutionError(
                f"MAFFT exited with code {proc.returncode}: {proc.stderr.strip()}",
                returncode=proc.returncode,
                stderr=proc.stderr,
                cmd=cmd,
            )

        return parse_fasta_alignment(proc.stdout)


class ClustalOmegaBackend(AlignmentBackend):
    """Multiple sequence alignment using Clustal Omega."""

    def __init__(self, executable: str | None = None, default_timeout: float = 60.0) -> None:
        self.executable = executable or os.getenv("CLUSTALO_EXECUTABLE", "clustalo")
        self.default_timeout = default_timeout

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None

    def align(
        self,
        sequences: dict[str, str],
        timeout_seconds: float | None = None,
    ) -> dict[str, str]:
        if not self.is_available():
            raise AlignmentUnavailableError(
                f"Clustal Omega executable '{self.executable}' not found on PATH"
            )

        if len(sequences) <= 1:
            return dict(sequences)

        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout

        temp_path: str | None = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fasta", delete=False) as tf:
            temp_path = tf.name
            for seq_id, seq in sequences.items():
                tf.write(f">{seq_id}\n{seq}\n")

        cmd = [self.executable, "-i", temp_path, "--outfmt=fa", "--threads=1"]

        try:
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AlignmentTimeoutError(
                f"Clustal Omega alignment timed out after {timeout:.1f}s"
            ) from exc
        except OSError as exc:
            raise AlignmentExecutionError(
                f"Failed to execute Clustal Omega: {exc}", cmd=cmd
            ) from exc
        finally:
            if temp_path:
                with contextlib.suppress(OSError):
                    Path(temp_path).unlink(missing_ok=True)

        if proc.returncode != 0:
            raise AlignmentExecutionError(
                f"Clustal Omega exited with code {proc.returncode}: {proc.stderr.strip()}",
                returncode=proc.returncode,
                stderr=proc.stderr,
                cmd=cmd,
            )

        return parse_fasta_alignment(proc.stdout)


class FixtureAlignmentBackend(AlignmentBackend):
    """Deterministic fixture backend for tests and offline alignment replay."""

    def __init__(self, pre_aligned: dict[str, str] | None = None) -> None:
        self.pre_aligned = pre_aligned or {}

    def is_available(self) -> bool:
        return True

    def align(
        self,
        sequences: dict[str, str],
        timeout_seconds: float | None = None,
    ) -> dict[str, str]:
        if self.pre_aligned:
            # Check if all requested sequences are present
            result: dict[str, str] = {}
            for k in sequences:
                if k in self.pre_aligned:
                    result[k] = self.pre_aligned[k]
                else:
                    result[k] = sequences[k]
            # Ensure equal length
            max_len = max(len(s) for s in result.values())
            for k, s in result.items():
                if len(s) < max_len:
                    result[k] = s + "-" * (max_len - len(s))
            return result

        # If already same length, return as is
        lengths = {len(s) for s in sequences.values()}
        if len(lengths) <= 1:
            return dict(sequences)

        # Pad with gaps to longest for basic offline fallback
        max_len = max(lengths)
        return {k: v + "-" * (max_len - len(v)) for k, v in sequences.items()}


class AutoAlignmentBackend(AlignmentBackend):
    """Composite backend that prefers MAFFT and falls back to Clustal Omega."""

    def __init__(
        self,
        mafft_backend: MafftBackend | None = None,
        clustalo_backend: ClustalOmegaBackend | None = None,
    ) -> None:
        self.mafft = mafft_backend or MafftBackend()
        self.clustalo = clustalo_backend or ClustalOmegaBackend()

    def is_available(self) -> bool:
        return self.mafft.is_available() or self.clustalo.is_available()

    def align(
        self,
        sequences: dict[str, str],
        timeout_seconds: float | None = None,
    ) -> dict[str, str]:
        if self.mafft.is_available():
            logger.info("AutoAlignmentBackend: using MAFFT")
            return self.mafft.align(sequences, timeout_seconds=timeout_seconds)

        if self.clustalo.is_available():
            logger.info("AutoAlignmentBackend: MAFFT unavailable; using Clustal Omega")
            return self.clustalo.align(sequences, timeout_seconds=timeout_seconds)

        raise AlignmentUnavailableError(
            "No alignment tool available. Install MAFFT or Clustal Omega."
        )
