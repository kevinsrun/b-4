"""AMP transport mounted on the existing application; science belongs to the service."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from bacteriocin_lab.amp.schemas import JobResponse, PredictionReport, PredictRequest, SequenceInput
from bacteriocin_lab.amp.service import InferenceService
from bacteriocin_lab.amp.store import CapacityExceeded, JobConflict

MAX_BODY_BYTES = 512 * 1024


class AMPBodyLimit:
    """Bound declared and chunked AMP bodies before JSON parsing/allocation."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/v1/amp/"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": {"code": "INVALID_CONTENT_LENGTH"}}, 400)(
                scope, receive, send
            )
        if length > MAX_BODY_BYTES:
            return await JSONResponse({"detail": {"code": "REQUEST_TOO_LARGE"}}, 413)(
                scope, receive, send
            )
        parts, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > MAX_BODY_BYTES:
                return await JSONResponse({"detail": {"code": "REQUEST_TOO_LARGE"}}, 413)(
                    scope, receive, send
                )
            parts.append(body)
            if not message.get("more_body", False):
                break
        replayed = False

        async def bounded_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(parts), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


def install_amp_routes(app: FastAPI, service: InferenceService | None = None):
    router = APIRouter(prefix="/api/v1", tags=["AMP inference"])
    lock = threading.Lock()
    app.state.amp_service = service

    def get_service() -> InferenceService:
        with lock:
            if app.state.amp_service is None:
                app.state.amp_service = InferenceService(
                    database_path=Path(
                        os.environ.get("AMP_DATABASE_PATH", "artifacts/amp/amp.sqlite3")
                    ).resolve(),
                    config_path=Path(
                        os.environ.get("AMP_CONFIG_PATH", "artifacts/amp/config.json")
                    ).resolve(),
                )
            return app.state.amp_service

    def validate(body: PredictRequest, svc: InferenceService):
        try:
            svc.validate_models(body)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "UNKNOWN_MODEL", "message": str(exc)}) from exc

    @router.post("/amp/predict", response_model=PredictionReport)
    def predict(body: PredictRequest):
        svc = get_service()
        validate(body, svc)
        return svc.predict(body)

    @router.post("/amp/batch", response_model=JobResponse, status_code=202)
    def batch(
        body: PredictRequest,
        idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None,
    ):
        svc = get_service()
        validate(body, svc)
        try:
            return svc.submit(body, idempotency_key)
        except JobConflict as exc:
            raise HTTPException(
                409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)}
            ) from exc
        except CapacityExceeded as exc:
            raise HTTPException(
                429, detail={"code": "JOB_CAPACITY_EXCEEDED", "message": str(exc)}
            ) from exc

    @router.get("/amp/jobs/{job_id}", response_model=JobResponse)
    def job(job_id: str):
        record = get_service().store.job(job_id)
        if record is None:
            raise HTTPException(404, detail={"code": "JOB_NOT_FOUND"})
        return record

    @router.get("/amp/models")
    def models():
        return {"models": [adapter.health() for adapter in get_service().adapters.values()]}

    @router.get("/amp/models/health")
    def health():
        return get_service().health()

    @router.get("/dramp/search", tags=["DRAMP reference"])
    def dramp_search(
        sequence: str | None = Query(default=None, min_length=1, max_length=10000),
        record_id: str | None = Query(default=None, min_length=1, max_length=100),
        dataset_id: str | None = Query(default=None, pattern="^[a-f0-9]{64}$"),
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=1000000),
    ):
        if sequence:
            try:
                SequenceInput(sequence_id="query", sequence=sequence)
            except ValueError as exc:
                raise HTTPException(422, detail={"code": "INVALID_SEQUENCE"}) from exc
        if not sequence and not record_id:
            raise HTTPException(422, detail={"code": "SEARCH_FILTER_REQUIRED"})
        return get_service().store.dramp_search(
            sequence=sequence,
            record_id=record_id,
            dataset_id=dataset_id,
            limit=limit,
            offset=offset,
        )

    @router.get("/dramp/records/{record_id}", tags=["DRAMP reference"])
    def dramp_record(record_id: str):
        result = get_service().store.dramp_search(record_id=record_id, limit=50)
        if not result["records"]:
            raise HTTPException(
                404,
                detail={
                    "code": "DRAMP_RECORD_NOT_FOUND",
                    "database_available": result["database_available"],
                },
            )
        return result

    app.include_router(router)
    app.add_middleware(AMPBodyLimit)
