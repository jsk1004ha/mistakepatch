from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile

from ..config import settings
from ..models import (
    AnalysisMeta,
    AnalyzeDetailResponse,
    AnalyzeResponse,
    AnnotationRequest,
    AnnotationResponse,
    HealthResponse,
    HistoryResponse,
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
    target_path.write_bytes(payload)
    return str(target_path.resolve())


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

    submission_id = create_submission(
        subject=meta_obj.subject.value,
        solution_img_path=solution_path,
        problem_img_path=problem_path,
    )
    analysis_id = create_analysis(submission_id=submission_id)

    payload = {
        "analysis_id": analysis_id,
        "submission_id": submission_id,
        "subject": meta_obj.subject.value,
        "highlight_mode": meta_obj.highlight_mode.value,
        "solution_image_path": solution_path,
        "problem_image_path": problem_path,
    }

    queued = queue_manager.enqueue_analysis(payload)
    if not queued:
        background_tasks.add_task(process_analysis_job, payload)

    return AnalyzeResponse(analysis_id=analysis_id, status="queued")


@router.get("/analysis/{analysis_id}", response_model=AnalyzeDetailResponse)
async def analysis_detail(analysis_id: str) -> AnalyzeDetailResponse:
    record = get_analysis(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    solution_image_url = f"/uploads/{Path(record['solution_img_path']).name}"
    problem_image_url = (
        f"/uploads/{Path(record['problem_img_path']).name}" if record.get("problem_img_path") else None
    )

    return AnalyzeDetailResponse(
        analysis_id=record["analysis_id"],
        submission_id=record["submission_id"],
        status=record["status"],
        subject=record["subject"],
        solution_image_url=solution_image_url,
        problem_image_url=problem_image_url,
        result=record["result"],
        fallback_used=record["fallback_used"],
        error_code=record["error_code"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
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
