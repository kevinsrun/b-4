"""Isolated, inference-only adapters with pinned artifact and runtime identity."""

from __future__ import annotations

import abc
import csv
import errno
import hashlib
import json
import math
import os
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .catalog import CATALOG
from .schemas import Prediction, PredictRequest, SequenceInput


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def process_env() -> dict[str, str]:
    # Workers do not need API/cloud credentials from the backend's environment.
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "HOME", "TMPDIR", "SYSTEMROOT", "LANG", "LC_ALL"}
    }
    env.update(
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        VECLIB_MAXIMUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        TF_NUM_INTEROP_THREADS="1",
        TF_NUM_INTRAOP_THREADS="1",
    )
    return env


class AdapterError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ModelAdapter(abc.ABC):
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.metadata = CATALOG[model_id]

    def eligibility(self, sequence: SequenceInput) -> bool:
        upper = self.metadata["max_length"]
        return len(sequence.sequence) >= self.metadata["min_length"] and (
            upper is None or len(sequence.sequence) <= upper
        )

    @abc.abstractmethod
    def identity(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def health(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def run(
        self, sequences: list[SequenceInput], request: PredictRequest, identity: dict[str, Any]
    ) -> list[Prediction]: ...

    def record(self, sequence: SequenceInput, request: PredictRequest, **kwargs: Any) -> Prediction:
        return Prediction(
            sequence_id=sequence.sequence_id,
            sequence_checksum=sequence.checksum,
            model_id=self.model_id,
            model_version=self.metadata["model_version"],
            model_variant=(
                request.ampir_model
                if self.model_id == "ampir"
                else request.amplify_model
                if self.model_id == "amplify"
                else "021820_FULL_MODEL"
                if self.model_id == "ampscanner_v2"
                else "pretrained"
                if self.model_id == "ampeppy"
                else None
            ),
            score_interpretation=self.metadata["score_interpretation"],
            timestamp=timestamp(),
            **kwargs,
        )


class DisabledAdapter(ModelAdapter):
    def identity(self) -> dict[str, Any]:
        raise AdapterError(
            "MODEL_UNAVAILABLE", self.metadata.get("blocker", "runtime not configured")
        )

    def health(self) -> dict[str, Any]:
        return {
            **self.metadata,
            "model_id": self.model_id,
            "status": "BLOCKED",
            "available": False,
            "reason": self.metadata.get("blocker", "runtime not configured"),
        }

    def run(
        self, sequences: list[SequenceInput], request: PredictRequest, identity: dict[str, Any]
    ) -> list[Prediction]:
        self.identity()
        return []


class SubprocessAdapter(ModelAdapter):
    """Server-owned configuration cannot enable training or a disabled predictor."""

    def __init__(self, model_id: str, config: dict[str, Any]):
        super().__init__(model_id)
        if model_id not in {"ampir", "ampeppy"}:
            raise ValueError("only audited inference adapters may be configured")
        self.config = config
        self.worker = Path(__file__).with_name(
            "ampir_worker.R" if model_id == "ampir" else "ampeppy_worker.py"
        )
        self._probe: tuple[float, dict[str, str]] | None = None
        self._lock = threading.Lock()

    def _runtime(self) -> dict[str, str]:
        with self._lock:
            if self._probe and time.monotonic() - self._probe[0] < 60:
                return self._probe[1]
            executable = self.config["executable"]
            if self.model_id == "ampir":
                cmd = [executable, "--vanilla", str(self.worker), "--probe"]
                output = self._execute(cmd, Path(tempfile.gettempdir()), 15)
                runtime = dict(line.split("\t", 1) for line in output.splitlines())
            else:
                code = (
                    "import sys,json,importlib.metadata as m; "
                    "print(json.dumps(dict(python=sys.version.split()[0], "
                    "**{p:m.version(p) for p in ['amPEPpy','numpy','pandas','scikit-learn',"
                    "'scipy','biopython','joblib','threadpoolctl']})))"
                )
                runtime = json.loads(
                    self._execute([executable, "-c", code], Path(tempfile.gettempdir()), 15)
                )
            if runtime != self.config["runtime_versions"]:
                raise AdapterError(
                    "RUNTIME_MISMATCH", "installed versions differ from pinned manifest"
                )
            self._probe = (time.monotonic(), runtime)
            return runtime

    def identity(self) -> dict[str, Any]:
        try:
            if self.config["source_commit"] != self.metadata["source_commit"]:
                raise AdapterError(
                    "SOURCE_MISMATCH", "source revision differs from audited catalog"
                )
            artifacts = {}
            for name, entry in self.config["artifacts"].items():
                actual = file_hash(entry["path"])
                if actual != entry["sha256"]:
                    raise AdapterError("ARTIFACT_MISMATCH", f"pinned artifact changed: {name}")
                artifacts[name] = actual
            if not artifacts:
                raise AdapterError("ARTIFACT_MISSING", "artifact manifest is empty")
            runtime = self._runtime()
            identity = {
                "source_commit": self.config["source_commit"],
                "artifacts": artifacts,
                "runtime_versions": runtime,
                "adapter_revision": "1",
                "model_metadata_sha256": digest(self.metadata),
                "adapter_sha256": file_hash(__file__),
                "schema_sha256": file_hash(Path(__file__).with_name("schemas.py")),
                "executable_sha256": file_hash(self.config["executable"]),
                "worker_sha256": file_hash(self.worker),
                "threads": 1,
                "training_performed": False,
            }
            identity["fingerprint"] = digest(identity)
            return identity
        except AdapterError:
            raise
        except (OSError, KeyError, ValueError) as exc:
            raise AdapterError(
                "MODEL_UNAVAILABLE", "runtime or pinned artifact missing/invalid"
            ) from exc

    def health(self) -> dict[str, Any]:
        try:
            identity = self.identity()
            proof = self.config.get("verification", {})
            ready = (
                proof.get("fingerprint") == identity["fingerprint"]
                and proof.get("reference_agreement") is True
                and proof.get("inference_passed") is True
                and bool(proof.get("evidence_path"))
                and Path(proof["evidence_path"]).is_file()
                and file_hash(proof["evidence_path"]) == proof.get("evidence_sha256")
            )
            return {
                **self.metadata,
                "model_id": self.model_id,
                "available": True,
                "status": "READY" if ready else "PARTIAL",
                "reproducibility": identity,
                "verification": proof if ready else None,
                "reason": None
                if ready
                else "reference inference has not been verified for this runtime",
            }
        except AdapterError as exc:
            return {
                **self.metadata,
                "model_id": self.model_id,
                "available": False,
                "status": "BLOCKED",
                "reason": str(exc),
                "error_code": exc.code,
            }

    @staticmethod
    def _execute(
        command: list[str],
        cwd: Path,
        timeout: float,
        statistics: dict | None = None,
        memory_limit_mib: int | None = None,
    ) -> str:
        if memory_limit_mib is not None and (
            type(memory_limit_mib) is not int or not 16 <= memory_limit_mib <= 16384
        ):
            raise ValueError("memory limit must be an integer in 16..16384 MiB")
        if memory_limit_mib is not None and statistics is None:
            statistics = {}
        # Files bound memory use even when a broken predictor writes excessive logs.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=process_env(),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
            except OSError as exc:
                raise AdapterError(
                    "WORKER_START_FAILED",
                    "could not start model process",
                    retryable=exc.errno in {errno.EAGAIN, errno.EMFILE, errno.ENFILE},
                ) from exc
            deadline = time.monotonic() + timeout
            try:
                while True:
                    if statistics is not None:
                        # Sample this worker only. Model workers do not fork computation children.
                        try:
                            sample = subprocess.run(
                                ["/bin/ps", "-o", "rss=", "-p", str(proc.pid)],
                                capture_output=True,
                                text=True,
                                timeout=0.1,
                                check=False,
                                env=process_env(),
                            )
                            if sample.stdout.strip():
                                rss = int(sample.stdout.strip())
                                if memory_limit_mib is not None and rss > memory_limit_mib * 1024:
                                    raise AdapterError(
                                        "MODEL_MEMORY_LIMIT",
                                        "sampled worker RSS exceeded configured memory limit",
                                    )
                                statistics["worker_peak_rss_kib_sampled"] = max(
                                    rss, statistics.get("worker_peak_rss_kib_sampled", 0)
                                )
                            elif memory_limit_mib is not None and proc.poll() is None:
                                raise AdapterError(
                                    "RESOURCE_MONITOR_UNAVAILABLE",
                                    "worker RSS could not be sampled",
                                )
                        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                            if memory_limit_mib is not None and proc.poll() is None:
                                raise AdapterError(
                                    "RESOURCE_MONITOR_UNAVAILABLE", "worker RSS monitor failed"
                                ) from exc
                    try:
                        proc.wait(timeout=max(0.001, min(0.2, deadline - time.monotonic())))
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            raise
            except subprocess.TimeoutExpired as exc:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise AdapterError(
                    "MODEL_TIMEOUT", "model process exceeded execution timeout"
                ) from exc
            except AdapterError:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise
            if proc.returncode != 0:
                # Do not return arbitrary process output or inherited machine details to clients.
                raise AdapterError(
                    "WORKER_FAILED", f"model process exited with code {proc.returncode}"
                )
            stdout.seek(0)
            return stdout.read(65536).decode("utf-8")

    def _command(self, input_path: Path, output_path: Path, request: PredictRequest) -> list[str]:
        executable = self.config["executable"]
        if self.model_id == "ampir":
            return [
                executable,
                "--vanilla",
                str(self.worker),
                str(input_path),
                str(output_path),
                request.ampir_model,
            ]
        return [
            executable,
            str(self.worker),
            str(input_path),
            str(output_path),
            self.config["artifacts"]["weights"]["path"],
        ]

    def _output_columns(self) -> tuple[str, str]:
        return (
            ("seq_name", "prob_AMP") if self.model_id == "ampir" else ("seq_id", "probability_AMP")
        )

    def _native_scores(self, row: dict, score: float) -> dict[str, float]:
        return {}

    def run(
        self, sequences: list[SequenceInput], request: PredictRequest, identity: dict[str, Any]
    ) -> list[Prediction]:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="b4-amp-") as directory:
            cwd = Path(directory)
            input_path, output_path = cwd / "input.fasta", cwd / "output.tsv"
            # Internal IDs avoid FASTA header parsing ambiguities and preserve caller order.
            input_path.write_text(
                "".join(f">q{i}\n{s.sequence}\n" for i, s in enumerate(sequences))
            )
            command = self._command(input_path, output_path, request)
            statistics = {
                "sampling_interval_seconds": 0.2,
                "threads": 1,
                "memory_limit_mib": self.config.get("memory_limit_mib", 2048),
                "memory_enforcement": "sampled worker RSS; not a kernel-enforced ceiling",
            }
            self._execute(
                command,
                cwd,
                request.timeout_seconds,
                statistics,
                memory_limit_mib=statistics["memory_limit_mib"],
            )
            try:
                if output_path.stat().st_size > 1024 * 1024:
                    raise ValueError("output too large")
                with output_path.open() as stream:
                    rows = list(csv.DictReader(stream, delimiter="\t"))
                id_column, score_column = self._output_columns()
                mapped = {r[id_column]: r for r in rows}
                if len(mapped) != len(rows) or set(mapped) != {
                    f"q{i}" for i in range(len(sequences))
                }:
                    raise ValueError("missing, duplicate or unexpected output identifiers")
                predictions = []
                for i, sequence in enumerate(sequences):
                    row = mapped[f"q{i}"]
                    score = float(row[score_column])
                    if not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError("invalid score")
                    threshold = request.ampir_threshold if self.model_id == "ampir" else 0.5
                    if self.model_id in {"ampeppy", "amplify", "ampscanner_v2"}:
                        if row["predicted"] not in {"AMP", "nonAMP"}:
                            raise ValueError("invalid class label")
                        binary = row["predicted"] == "AMP"
                        if self.model_id in {"amplify", "ampscanner_v2"} and binary != (
                            score > 0.5
                        ):
                            raise ValueError(
                                "legacy class does not match upstream probability threshold"
                            )
                    else:
                        binary = score >= threshold if threshold is not None else None
                    warnings = list(self.metadata["limitations"])
                    if (
                        self.model_id == "ampir"
                        and request.ampir_model == "mature"
                        and len(sequence.sequence) >= 60
                    ):
                        warnings.append(
                            "outside recommended mature-model length; consider precursor model"
                        )
                    predictions.append(
                        self.record(
                            sequence,
                            request,
                            status="succeeded",
                            native_scores=self._native_scores(row, score),
                            raw_score=score,
                            binary_prediction=binary,
                            threshold=threshold,
                            threshold_interpretation=(
                                "caller-selected descriptive cutoff; not locally validated"
                                if self.model_id == "ampir" and threshold is not None
                                else "upstream class prediction; ties resolve to nonAMP"
                                if self.model_id in {"ampeppy", "amplify", "ampscanner_v2"}
                                else None
                            ),
                            duration_seconds=time.monotonic() - started,
                            warnings=warnings,
                            reproducibility={
                                **identity,
                                "seed": 2012 if self.model_id == "ampeppy" else None,
                                "resource_usage": statistics,
                            },
                        )
                    )
                return predictions
            except (OSError, ValueError, KeyError) as exc:
                raise AdapterError(
                    "OUTPUT_INVALID", "model output failed schema/identifier/score checks"
                ) from exc


def load_adapters(config_path: Path) -> dict[str, ModelAdapter]:
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    from .legacy import LegacyTensorFlowAdapter

    return {
        model_id: LegacyTensorFlowAdapter(model_id, config[model_id])
        if model_id in {"amplify", "ampscanner_v2"} and model_id in config
        else SubprocessAdapter(model_id, config[model_id])
        if model_id in {"ampir", "ampeppy"} and model_id in config
        else DisabledAdapter(model_id)
        for model_id in CATALOG
    }
