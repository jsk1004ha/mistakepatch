from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from ..config import settings
from ..models import AnalysisResult
from ..repositories import mark_analysis_failed, save_analysis_result, set_analysis_status
from ..schemas import ANALYSIS_RESULT_JSON_SCHEMA
from .ocr import suggest_ocr_boxes
from .openai_service import OpenAIService


def process_analysis_job(payload: dict[str, Any]) -> None:
    analysis_id = payload["analysis_id"]
    subject = payload["subject"]
    highlight_mode = payload["highlight_mode"]
    solution_image_path = payload["solution_image_path"]
    problem_image_path = payload.get("problem_image_path")

    set_analysis_status(analysis_id, "processing")
    fallback_used = False
    error_code: str | None = None

    try:
        raw_result = _get_llm_result(solution_image_path, problem_image_path, subject, highlight_mode)
        validated = _validate_result(raw_result)
    except Exception as exc:
        fallback_used = True
        error_code = f"analysis_error:{type(exc).__name__}"
        validated = _load_fallback_result()

    if highlight_mode == "ocr_box" and settings.enable_ocr_hints:
        _inject_ocr_hints(validated, solution_image_path)

    try:
        save_analysis_result(analysis_id, validated, fallback_used=fallback_used, error_code=error_code)
    except Exception:
        mark_analysis_failed(analysis_id, "db_write_failed")
        raise


def _get_llm_result(
    solution_image_path: str,
    problem_image_path: str | None,
    subject: str,
    highlight_mode: str,
) -> dict[str, Any]:
    service = OpenAIService()
    return service.analyze_solution(
        solution_image_path=solution_image_path,
        problem_image_path=problem_image_path,
        subject=subject,
        highlight_mode=highlight_mode,
    )


def _validate_result(data: dict[str, Any]) -> dict[str, Any]:
    try:
        validate(instance=data, schema=ANALYSIS_RESULT_JSON_SCHEMA)
    except ValidationError as exc:
        raise RuntimeError(f"schema_validation_failed:{exc.message}") from exc

    # Secondary strict validation through pydantic model.
    parsed = AnalysisResult.model_validate(data)
    normalized = parsed.model_dump()
    return normalized


def _load_fallback_result() -> dict[str, Any]:
    path = settings.fallback_path
    if not path.exists():
        raise RuntimeError(f"Fallback file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _validate_result(payload)


def _inject_ocr_hints(result: dict[str, Any], image_path: str) -> None:
    if not Path(image_path).exists():
        return
    boxes = suggest_ocr_boxes(image_path, max_boxes=len(result.get("mistakes", [])))
    if not boxes:
        return

    for idx, mistake in enumerate(result.get("mistakes", [])):
        hint = boxes[idx % len(boxes)]
        highlight = dict(mistake.get("highlight") or {})
        if not all(highlight.get(key) is not None for key in ("x", "y", "w", "h")):
            highlight.update(hint)
            mistake["highlight"] = highlight

