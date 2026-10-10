"""Bounded independent inference and durable local jobs, without model-score averaging."""

from __future__ import annotations

import logging
import resource
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .adapters import AdapterError, ModelAdapter, digest, load_adapters, timestamp
from .schemas import Prediction, PredictionReport, PredictRequest, SequenceEvidence
from .store import Store

logger = logging.getLogger(__name__)


class InferenceService:
    def __init__(
        self,
        *,
        database_path: Path,
        config_path: Path | None = None,
        adapters: dict[str, ModelAdapter] | None = None,
        max_model_workers: int = 2,
    ):
        self.database_path = database_path
        self.adapters = (
            adapters
            if adapters is not None
            else load_adapters(config_path or Path("artifacts/amp/config.json"))
        )
        self.max_model_workers = max_model_workers
        self._models = ThreadPoolExecutor(
            max_workers=max_model_workers, thread_name_prefix="amp-model"
        )
        self._jobs = ThreadPoolExecutor(max_workers=4, thread_name_prefix="amp-job")
        self._store: Store | None = None
        self._lock = threading.Lock()
        self._active_models = 0
        self._closed = False

    @property
    def store(self) -> Store:
        with self._lock:
            if self._store is None:
                self._store = Store(self.database_path)
                self._store.recover_dead_jobs()
            return self._store

    def close(self):
        # Running processes each have a hard timeout; finish durable jobs before closing workers.
        self._jobs.shutdown(wait=True)
        self._models.shutdown(wait=True)
        self._closed = True

    def validate_models(self, request: PredictRequest):
        unknown = set(request.models) - self.adapters.keys()
        if unknown:
            raise ValueError(f"unknown models: {sorted(unknown)}")

    def health(self) -> dict[str, Any]:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return {
            "models": [a.health() for a in self.adapters.values()],
            "resources": {
                "max_concurrent_model_processes": self.max_model_workers,
                "active_model_tasks": self._active_models,
                "api_process_peak_rss_kib": usage.ru_maxrss / 1024
                if sys.platform == "darwin"
                else usage.ru_maxrss,
                "rss_scope": "API process only; worker memory is not included",
                "cpu_seconds": usage.ru_utime + usage.ru_stime,
            },
        }

    def _identity_snapshot(self, request: PredictRequest) -> dict[str, Any]:
        identities = {}
        for model in request.models:
            try:
                identities[model] = self.adapters[model].identity()
            except AdapterError as exc:
                identities[model] = {"unavailable": exc.code}
        return identities

    def submit(self, request: PredictRequest, key: str | None = None) -> dict[str, Any]:
        self.validate_models(request)
        with self._lock:
            if self._closed:
                raise RuntimeError("service closed")
        job, created = self.store.create_job(
            request.model_dump(), self._identity_snapshot(request), key
        )
        if created:
            self._jobs.submit(self._execute_job, job["job_id"], request)
        return job

    def _execute_job(self, job_id: str, request: PredictRequest):
        self.store.update_job(job_id, "running")
        try:
            report = self.predict(request)
            self.store.update_job(job_id, report.status, report=report.model_dump(mode="json"))
        except Exception:
            logger.exception("amp_job_failed", extra={"job_id": job_id})
            self.store.update_job(
                job_id,
                "failed",
                error={"code": "COORDINATOR_FAILED", "message": "inference coordinator failed"},
            )

    @staticmethod
    def _cache_key(sequence, adapter, request, identity):
        return digest(
            {
                "sequence": sequence.checksum,
                "model": adapter.model_id,
                "identity": identity,
                "variant": (
                    request.ampir_model
                    if adapter.model_id == "ampir"
                    else request.amplify_model
                    if adapter.model_id == "amplify"
                    else None
                ),
                "threshold": request.ampir_threshold if adapter.model_id == "ampir" else 0.5,
                "output_schema": "amp-inference/1",
            }
        )

    def _predict_model(self, adapter: ModelAdapter, request: PredictRequest) -> list[Prediction]:
        with self._lock:
            self._active_models += 1
        started = time.monotonic()
        try:
            return self._predict_model_inner(adapter, request)
        finally:
            with self._lock:
                self._active_models -= 1
            logger.info(
                "amp_model_finished",
                extra={
                    "model_id": adapter.model_id,
                    "duration_seconds": time.monotonic() - started,
                },
            )

    def _predict_model_inner(
        self, adapter: ModelAdapter, request: PredictRequest
    ) -> list[Prediction]:
        results, pending = {}, []
        for sequence in request.sequences:
            if not adapter.eligibility(sequence):
                results[sequence.sequence_id] = adapter.record(
                    sequence,
                    request,
                    status="ineligible",
                    warnings=["sequence outside supported length range"],
                    error={"code": "SEQUENCE_INELIGIBLE", "retryable": False},
                )
            else:
                pending.append(sequence)
        if not pending:
            return [results[s.sequence_id] for s in request.sequences]
        try:
            identity = adapter.identity()
        except AdapterError as exc:
            for sequence in pending:
                results[sequence.sequence_id] = adapter.record(
                    sequence,
                    request,
                    status="unavailable",
                    error={"code": exc.code, "message": str(exc), "retryable": exc.retryable},
                )
            return [results[s.sequence_id] for s in request.sequences]
        uncached = []
        for sequence in pending:
            cached = self.store.cached(self._cache_key(sequence, adapter, request, identity))
            if cached:
                cached.update(sequence_id=sequence.sequence_id, cached=True)
                results[sequence.sequence_id] = Prediction.model_validate(cached)
            else:
                uncached.append(sequence)
        if uncached:
            started, attempts = time.monotonic(), 0
            deadline = started + request.timeout_seconds
            while True:
                attempts += 1
                try:
                    remaining = max(0.001, deadline - time.monotonic())
                    execution_request = request.model_copy(update={"timeout_seconds": remaining})
                    predictions = adapter.run(uncached, execution_request, identity)
                    if len(predictions) != len(uncached) or {
                        p.sequence_id for p in predictions
                    } != {s.sequence_id for s in uncached}:
                        raise AdapterError(
                            "OUTPUT_INVALID", "adapter did not return exactly one record per input"
                        )
                    for prediction in predictions:
                        expected = next(
                            s for s in uncached if s.sequence_id == prediction.sequence_id
                        )
                        if (
                            prediction.model_id != adapter.model_id
                            or prediction.sequence_checksum != expected.checksum
                        ):
                            raise AdapterError(
                                "OUTPUT_INVALID", "adapter returned a different model or sequence"
                            )
                        prediction.reproducibility["attempts"] = attempts
                        results[prediction.sequence_id] = prediction
                    for sequence in uncached:
                        prediction = results[sequence.sequence_id]
                        if prediction.status == "succeeded":
                            self.store.cache(
                                self._cache_key(sequence, adapter, request, identity),
                                prediction.model_dump(mode="json"),
                            )
                    break
                except AdapterError as exc:
                    if exc.retryable and attempts < 2 and deadline - time.monotonic() > 0.1:
                        time.sleep(0.1)
                        continue
                    for sequence in uncached:
                        results[sequence.sequence_id] = adapter.record(
                            sequence,
                            request,
                            status="timeout" if exc.code == "MODEL_TIMEOUT" else "failed",
                            duration_seconds=time.monotonic() - started,
                            reproducibility={**identity, "attempts": attempts},
                            error={
                                "code": exc.code,
                                "message": str(exc),
                                "retryable": exc.retryable,
                            },
                        )
                    break
        return [results[s.sequence_id] for s in request.sequences]

    def predict(self, request: PredictRequest) -> PredictionReport:
        self.validate_models(request)
        started, now = time.monotonic(), timestamp()
        # One shared executor bounds all callers, not merely each individual batch.
        futures = {
            model: self._models.submit(self._predict_model, self.adapters[model], request)
            for model in request.models
        }
        outputs = {}
        for model, future in futures.items():
            try:
                outputs[model] = future.result()
            except Exception:
                logger.exception("amp_adapter_failed", extra={"model_id": model})
                outputs[model] = [
                    self.adapters[model].record(
                        sequence,
                        request,
                        status="failed",
                        error={
                            "code": "ADAPTER_FAILED",
                            "message": "unexpected adapter failure",
                            "retryable": False,
                        },
                    )
                    for sequence in request.sequences
                ]
        evidence, successes, failures = [], 0, 0
        for i, sequence in enumerate(request.sequences):
            predictions = [outputs[model][i] for model in request.models]
            successful = [p for p in predictions if p.status == "succeeded"]
            successes += len(successful)
            failures += len(predictions) - len(successful)
            votes = [p.binary_prediction for p in successful if p.binary_prediction is not None]
            refs = self.store.dramp_search(sequence=sequence.sequence, limit=50)
            warnings = []
            if not refs["database_available"]:
                warnings.append(
                    "DRAMP dataset not ingested; absence of matches is not an absence finding"
                )
            if refs["total"] > 50:
                warnings.append(
                    "DRAMP matches truncated at 50; use paginated search for all annotations"
                )
            evidence.append(
                SequenceEvidence(
                    sequence_id=sequence.sequence_id,
                    sequence_checksum=sequence.checksum,
                    predictions=predictions,
                    agreement={
                        "interpretation": (
                            "descriptive, uncalibrated votes; not experimental evidence"
                        ),
                        "positive_votes": sum(votes),
                        "negative_votes": len(votes) - sum(votes),
                        "classified_models": len(votes),
                        "successful_models": len(successful),
                        "unclassified_successful_models": len(successful) - len(votes),
                        "disagreement": len(set(votes)) > 1,
                        "all_classified_models_agree": len(votes) >= 2 and len(set(votes)) == 1,
                    },
                    dramp_matches=refs["records"],
                    warnings=warnings,
                )
            )
        return PredictionReport(
            status="partial_success"
            if successes and failures
            else "succeeded"
            if successes
            else "failed",
            timestamp=now,
            sequences=evidence,
            execution={
                "duration_seconds": time.monotonic() - started,
                "successful_predictions": successes,
                "unsuccessful_predictions": failures,
                "cache_hits": sum(p.cached for row in evidence for p in row.predictions),
                "max_concurrent_model_processes": self.max_model_workers,
                "timeout_scope": "each model execution, excluding queue and runtime probe",
            },
        )
