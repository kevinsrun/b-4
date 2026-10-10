"""Partial legacy adapters: configured weights never bypass native reference verification."""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

from .adapters import AdapterError, ModelAdapter, SubprocessAdapter, digest, file_hash
from .schemas import PredictRequest


class LegacyTensorFlowAdapter(SubprocessAdapter):
    def __init__(self, model_id: str, config: dict):
        if model_id not in {"amplify", "ampscanner_v2"}:
            raise ValueError("not an audited legacy inference path")
        ModelAdapter.__init__(self, model_id)
        self.config = config
        self.worker = Path(__file__).with_name("tf1_worker.py")
        self._probe = None
        self._lock = threading.Lock()

    def _runtime(self) -> dict:
        # Import the actual computation backend, not just package metadata.
        code = (
            "import sys,json,tensorflow as tf,keras,numpy,h5py; "
            "print(json.dumps(dict(python=sys.version.split()[0],tensorflow=tf.__version__,"
            "keras=keras.__version__,numpy=numpy.__version__,h5py=h5py.__version__)))"
        )
        try:
            runtime = json.loads(
                self._execute([self.config["executable"], "-c", code], Path("/tmp"), 15)
            )
        except AdapterError as exc:
            raise AdapterError(
                "LEGACY_RUNTIME_UNAVAILABLE",
                "TensorFlow 1.12 CPU import failed; compatible AVX runtime required",
            ) from exc
        expected = {
            "python": "3.6.15",
            "tensorflow": "1.12.0",
            "keras": "2.2.4",
            "numpy": "1.16.6",
            "h5py": "2.10.0",
        }
        if runtime != self.config["runtime_versions"] or runtime != expected:
            raise AdapterError(
                "RUNTIME_MISMATCH",
                "legacy runtime differs from pinned TensorFlow 1.12 configuration",
            )
        return runtime

    def _unverified_identity(self) -> dict:
        """For the explicit reference-verification harness only, not API inference."""
        names = set(self.config["artifacts"])
        required = (
            {"AMPlify.py", "layers.py"} | {f"weights_{i}" for i in range(1, 6)}
            if self.model_id == "amplify"
            else {"predictor.py", "weights"}
        )
        if not required.issubset(names):
            raise AdapterError("ARTIFACT_MISSING", "native source/checkpoint manifest incomplete")
        if self.config.get("variant") != (
            "balanced" if self.model_id == "amplify" else "021820_FULL_MODEL"
        ):
            raise AdapterError(
                "MODEL_VARIANT_MISMATCH", "only audited balanced/021820 configurations supported"
            )
        for name, expected in self.metadata["pinned_artifacts"].items():
            if self.config["artifacts"][name].get("sha256") != expected:
                raise AdapterError(
                    "ARTIFACT_MISMATCH", "not the audited official checkpoint/source"
                )
        identity = super().identity()
        identity.pop("fingerprint", None)
        identity["legacy_adapter_sha256"] = file_hash(__file__)
        identity["fingerprint"] = digest(identity)
        return identity

    def _verified(self, identity: dict) -> bool:
        proof = self.config.get("verification", {})
        path = Path(proof.get("evidence_path", ""))
        return (
            proof.get("fingerprint") == identity["fingerprint"]
            and proof.get("inference_passed") is True
            and proof.get("reference_agreement") is True
            and path.is_file()
            and file_hash(path) == proof.get("evidence_sha256")
        )

    def identity(self) -> dict:
        identity = self._unverified_identity()
        if not self._verified(identity):
            raise AdapterError(
                "REFERENCE_NOT_VERIFIED",
                "legacy predictor disabled until native/API reference verification",
            )
        return identity

    def health(self) -> dict:
        try:
            identity = self._unverified_identity()
            verified = self._verified(identity)
            return {
                **self.metadata,
                "model_id": self.model_id,
                "status": "READY" if verified else "PARTIAL",
                "available": verified,
                "reproducibility": identity,
                "independent_benchmark": "BLOCKED",
                "reason": None if verified else "native/API reference agreement not verified",
            }
        except (AdapterError, OSError, KeyError, ValueError) as exc:
            return {
                **self.metadata,
                "model_id": self.model_id,
                "status": "PARTIAL",
                "available": False,
                "independent_benchmark": "BLOCKED",
                "reason": str(exc),
                "error_code": getattr(exc, "code", "MODEL_UNAVAILABLE"),
            }

    def _command(self, input_path: Path, output_path: Path, request: PredictRequest) -> list[str]:
        config_path = input_path.with_suffix(".config.json")
        config_path.write_text(
            json.dumps(
                {
                    "model_id": self.model_id,
                    "variant": self.config["variant"],
                    "artifacts": self.config["artifacts"],
                }
            )
        )
        return [
            self.config["executable"],
            str(self.worker),
            str(input_path),
            str(output_path),
            str(config_path),
        ]

    def _native_scores(self, row: dict, score: float) -> dict[str, float]:
        if self.model_id != "amplify":
            return {}
        scores = {
            k: float(row[k]) for k in ["log_scaled_score", *[f"submodel_{i}" for i in range(1, 6)]]
        }
        if any(not math.isfinite(s) for s in scores.values()):
            raise ValueError("non-finite native score")
        if any(not 0 <= scores[f"submodel_{i}"] <= 1 for i in range(1, 6)):
            raise ValueError("invalid submodel probability")
        return scores
