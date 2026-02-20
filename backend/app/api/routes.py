from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from ..config import settings
from ..models import (
    AnalysisMeta,
    AnalyzeDetailResponse,
    AnalyzeResponse,
    AnalyzeStatus,
    AnnotationRequest,
    AnnotationResponse,
    HealthResponse,
    HistoryResponse,
    ProgressStep,
)
from ..repositories import (
    create_analysis,
    create_annotation,
    create_submission,
    get_analysis,
    list_history,
    mistake_exists,
)
from ..services.analyzer import process_analysis_job
from ..services.queue_manager import queue_manager

router = APIRouter(prefix="/api/v1", tags=["v1"])

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


def _validate_upload(upload: UploadFile) -> None:
    if upload.content_type not in ALLOWED_IMAGE_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {upload.content_type}. Allowed: jpeg/png/webp",
        )


def _save_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "upload.jpg").suffix.lower() or ".jpg"
    filename = f"{uuid.uuid4().hex}{suffix}"
    target_path = Path(settings.storage_path) / filename
    payload = upload.file.read()
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(status_code=400, detail="File too large.")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _ = target_path.write_bytes(payload)
    return str(target_path.resolve())


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError:
        return None


def _progress_for_record(record: dict[str, Any]) -> tuple[ProgressStep, int, str]:
    status = record["status"]
    if status == "queued":
        return ProgressStep.upload_complete, 20, "이미지 업로드 완료"
    if status == "processing":
        updated_at = _parse_timestamp(record.get("updated_at"))
        now = datetime.now(UTC)
        elapsed_seconds = max(0.0, (now - updated_at).total_seconds()) if updated_at else 0.0
        if elapsed_seconds < 3:
            percent = min(58, 35 + int(elapsed_seconds * 8))
            return ProgressStep.ocr_analyzing, percent, "OCR 분석 중"
        percent = min(96, 58 + int((elapsed_seconds - 3) * 4))
        return ProgressStep.ai_grading, percent, "AI 채점 중"
    if status == "done":
        return ProgressStep.completed, 100, "분석 완료"
    return ProgressStep.failed, 100, "분석 실패"


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    background_tasks: BackgroundTasks,
    solution_image: UploadFile | None = File(default=None),
    problem_image: UploadFile | None = File(default=None),
    meta: str = Form(default="{}"),
) -> AnalyzeResponse:
    if solution_image is None:
        raise HTTPException(status_code=400, detail="solution_image is required.")

    _validate_upload(solution_image)
    if problem_image:
        _validate_upload(problem_image)

    try:
        meta_obj = AnalysisMeta.model_validate(json.loads(meta))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid meta payload: {exc}") from exc

    solution_path = _save_upload(solution_image)
    problem_path = _save_upload(problem_image) if problem_image else None

    try:
        submission_id = create_submission(
            subject=meta_obj.subject.value,
            solution_img_path=solution_path,
            problem_img_path=problem_path,
        )
        analysis_id = create_analysis(submission_id=submission_id)
    except Exception as exc:
        for path in (solution_path, problem_path):
            if not path:
                continue
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to create analysis record: {exc}") from exc

    payload = {
        "analysis_id": analysis_id,
        "submission_id": submission_id,
        "subject": meta_obj.subject.value,
        "highlight_mode": meta_obj.highlight_mode.value,
        "solution_image_path": solution_path,
        "problem_image_path": problem_path,
    }

    try:
        queued = queue_manager.enqueue_analysis(payload)
    except Exception:
        queued = False
    if not queued:
        background_tasks.add_task(process_analysis_job, payload)

    return AnalyzeResponse(analysis_id=analysis_id, status=AnalyzeStatus.queued)


@router.get("/analysis/{analysis_id}", response_model=AnalyzeDetailResponse)
async def analysis_detail(analysis_id: str) -> AnalyzeDetailResponse:
    record = get_analysis(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    progress_step, progress_percent, progress_message = _progress_for_record(record)
    solution_image_url = f"/uploads/{Path(record['solution_img_path']).name}"
    problem_image_url = (
        f"/uploads/{Path(record['problem_img_path']).name}" if record.get("problem_img_path") else None
    )

    return AnalyzeDetailResponse(
        analysis_id=record["analysis_id"],
        submission_id=record["submission_id"],
        status=record["status"],
        progress_step=progress_step,
        progress_percent=progress_percent,
        progress_message=progress_message,
        subject=record["subject"],
        solution_image_url=solution_image_url,
        problem_image_url=problem_image_url,
        result=record["result"],
        fallback_used=record["fallback_used"],
        error_code=record["error_code"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


@router.get("/analysis/{analysis_id}/events")
async def analysis_events(analysis_id: str) -> StreamingResponse:
    initial = get_analysis(analysis_id)
    if not initial:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    async def event_stream():
        last_fingerprint: tuple[str, str | None, ProgressStep, int] | None = None
        while True:
            record = get_analysis(analysis_id)
            if not record:
                break

            progress_step, progress_percent, progress_message = _progress_for_record(record)
            fingerprint = (record["status"], record.get("updated_at"), progress_step, progress_percent)
            if fingerprint != last_fingerprint:
                payload = {
                    "analysis_id": record["analysis_id"],
                    "status": record["status"],
                    "progress_step": progress_step.value,
                    "progress_percent": progress_percent,
                    "progress_message": progress_message,
                    "updated_at": record["updated_at"],
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_fingerprint = fingerprint

            if record["status"] in {"done", "failed"}:
                break

            yield ": ping\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/annotations", response_model=AnnotationResponse)
async def add_annotation(payload: AnnotationRequest) -> AnnotationResponse:
    if not mistake_exists(payload.analysis_id, payload.mistake_id):
        raise HTTPException(status_code=404, detail="Mistake not found for this analysis.")

    annotation_id = create_annotation(
        analysis_id=payload.analysis_id,
        mistake_id=payload.mistake_id,
        mode=payload.mode.value,
        shape=payload.shape.value,
        x=payload.x,
        y=payload.y,
        w=payload.w,
        h=payload.h,
    )
    return AnnotationResponse(
        annotation_id=annotation_id,
        analysis_id=payload.analysis_id,
        mistake_id=payload.mistake_id,
    )


@router.get("/history", response_model=HistoryResponse)
async def history(limit: int = Query(default=5, ge=1, le=20)) -> HistoryResponse:
    data = list_history(limit=limit)
    return HistoryResponse(items=data["items"], top_tags=data["top_tags"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        queue_mode=queue_manager.mode,
        enable_ocr_hints=settings.enable_ocr_hints,
    )
