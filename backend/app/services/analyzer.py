from __future__ import annotations

import json
from numbers import Number
from pathlib import Path
import re
from typing import Any

from jsonschema import ValidationError, validate

from ..config import settings
from ..models import AnalysisResult, MistakeType, Severity
from ..repositories import mark_analysis_failed, save_analysis_result, set_analysis_status
from ..schemas import ANALYSIS_RESULT_JSON_SCHEMA
from .ocr import extract_image_text, suggest_ocr_boxes
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
        detail = str(exc).strip().replace("\n", " ")
        if detail:
            detail = detail[:120]
            error_code = f"analysis_error:{type(exc).__name__}:{detail}"
        else:
            error_code = f"analysis_error:{type(exc).__name__}"
        validated = _load_fallback_result()

    _apply_simple_equation_consistency(validated, solution_image_path, problem_image_path)
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
    normalized_input = _normalize_result_candidate(data)
    try:
        validate(instance=normalized_input, schema=ANALYSIS_RESULT_JSON_SCHEMA)
    except ValidationError as exc:
        raise RuntimeError(f"schema_validation_failed:{exc.message}") from exc

    # Secondary strict validation through pydantic model.
    parsed = AnalysisResult.model_validate(normalized_input)
    normalized = parsed.model_dump()
    return normalized


def _normalize_result_candidate(data: dict[str, Any]) -> dict[str, Any]:
    candidate = _unwrap_result_container(data)
    _apply_aliases(candidate)
    _normalize_numeric_fields(candidate)
    _prune_to_schema_shape(candidate)
    _ensure_required_defaults(candidate)
    return candidate


def _unwrap_result_container(data: dict[str, Any]) -> dict[str, Any]:
    if _looks_like_result_payload(data):
        return dict(data)

    preferred_keys = ("analysis_result", "result", "output", "data", "json", "response")
    for key in preferred_keys:
        nested = _coerce_json_object(data.get(key))
        if nested is not None:
            if _looks_like_result_payload(nested) or _looks_like_partial_payload(nested):
                return dict(nested)
            for child in nested.values():
                child_obj = _coerce_json_object(child)
                if child_obj is not None and _looks_like_result_payload(child_obj):
                    return dict(child_obj)
                if isinstance(child, list):
                    for item in child:
                        item_obj = _coerce_json_object(item)
                        if item_obj is not None and _looks_like_result_payload(item_obj):
                            return dict(item_obj)

    for value in data.values():
        value_obj = _coerce_json_object(value)
        if value_obj is not None and _looks_like_result_payload(value_obj):
            return dict(value_obj)

    return dict(data)


def _coerce_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = _parse_json_object(value)
        if parsed is not None:
            return parsed
    return None


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        snippet = text[start : end + 1]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _apply_aliases(payload: dict[str, Any]) -> None:
    if "score_total" not in payload:
        for alias in ("total_score", "score", "final_score", "overall_score", "scoreTotal"):
            if alias in payload:
                payload["score_total"] = payload[alias]
                break

    if "rubric_scores" not in payload:
        for alias in ("rubric", "rubric_score", "rubricScores"):
            if alias in payload:
                payload["rubric_scores"] = payload[alias]
                break

    if "next_checklist" not in payload:
        for alias in ("checklist", "next_steps", "nextChecklist", "review_checklist"):
            if alias in payload:
                payload["next_checklist"] = payload[alias]
                break

    rubric = payload.get("rubric_scores")
    if isinstance(rubric, dict):
        alias_map = {
            "condition": "conditions",
            "model": "modeling",
            "cal": "calculation",
        }
        for source, target in alias_map.items():
            if target not in rubric and source in rubric:
                rubric[target] = rubric[source]
        payload["rubric_scores"] = rubric


def _normalize_numeric_fields(payload: dict[str, Any]) -> None:
    score = _to_float(payload.get("score_total"))
    if score is not None:
        payload["score_total"] = score

    rubric = payload.get("rubric_scores")
    if isinstance(rubric, dict):
        for key in ("conditions", "modeling", "logic", "calculation", "final"):
            value = _to_float(rubric.get(key))
            if value is not None:
                rubric[key] = value
        payload["rubric_scores"] = rubric

    mistakes = payload.get("mistakes")
    if isinstance(mistakes, list):
        for item in mistakes:
            if not isinstance(item, dict):
                continue
            points = _to_float(item.get("points_deducted"))
            if points is not None:
                item["points_deducted"] = points


def _prune_to_schema_shape(payload: dict[str, Any]) -> None:
    allowed_top = {
        "score_total",
        "rubric_scores",
        "mistakes",
        "patch",
        "next_checklist",
        "confidence",
        "missing_info",
    }
    for key in list(payload.keys()):
        if key not in allowed_top:
            payload.pop(key, None)

    rubric = payload.get("rubric_scores")
    if isinstance(rubric, dict):
        allowed_rubric = {"conditions", "modeling", "logic", "calculation", "final"}
        for key in list(rubric.keys()):
            if key not in allowed_rubric:
                rubric.pop(key, None)
        payload["rubric_scores"] = rubric

    mistakes = payload.get("mistakes")
    if isinstance(mistakes, list):
        allowed_mistake = {
            "type",
            "severity",
            "points_deducted",
            "evidence",
            "fix_instruction",
            "location_hint",
            "highlight",
        }
        allowed_highlight = {"mode", "shape", "x", "y", "w", "h"}
        for item in mistakes:
            if not isinstance(item, dict):
                continue
            for key in list(item.keys()):
                if key not in allowed_mistake:
                    item.pop(key, None)
            highlight = item.get("highlight")
            if isinstance(highlight, dict):
                for key in list(highlight.keys()):
                    if key not in allowed_highlight:
                        highlight.pop(key, None)
                item["highlight"] = highlight
        payload["mistakes"] = mistakes

    patch = payload.get("patch")
    if isinstance(patch, dict):
        allowed_patch = {"minimal_changes", "patched_solution_brief"}
        for key in list(patch.keys()):
            if key not in allowed_patch:
                patch.pop(key, None)
        minimal_changes = patch.get("minimal_changes")
        if isinstance(minimal_changes, list):
            allowed_change = {"change", "rationale"}
            for item in minimal_changes:
                if not isinstance(item, dict):
                    continue
                for key in list(item.keys()):
                    if key not in allowed_change:
                        item.pop(key, None)
            patch["minimal_changes"] = minimal_changes
        payload["patch"] = patch


def _ensure_required_defaults(payload: dict[str, Any]) -> None:
    score = _to_float(payload.get("score_total"))
    if score is None:
        inferred = _infer_score_total(payload)
        score = inferred if inferred is not None else 0.0
    payload["score_total"] = _clamp(score, 0.0, 10.0)

    rubric = payload.get("rubric_scores")
    if not isinstance(rubric, dict):
        rubric = {}
    rubric_keys = ("conditions", "modeling", "logic", "calculation", "final")
    per_bucket = round(payload["score_total"] / 5.0, 2)
    normalized_rubric: dict[str, float] = {}
    for key in rubric_keys:
        value = _to_float(rubric.get(key))
        if value is None:
            value = per_bucket
        normalized_rubric[key] = round(_clamp(value, 0.0, 2.0), 2)
    payload["rubric_scores"] = normalized_rubric

    mistakes = payload.get("mistakes")
    if not isinstance(mistakes, list):
        mistakes = []
    normalized_mistakes: list[dict[str, Any]] = []
    for raw in mistakes[:20]:
        if not isinstance(raw, dict):
            continue
        normalized_mistakes.append(_normalize_mistake(raw))
    payload["mistakes"] = normalized_mistakes

    patch = payload.get("patch")
    if not isinstance(patch, dict):
        patch = {}
    changes = patch.get("minimal_changes")
    normalized_changes: list[dict[str, str]] = []
    if isinstance(changes, list):
        for raw in changes[:6]:
            if not isinstance(raw, dict):
                continue
            change = _clean_text(raw.get("change"), "", 220)
            rationale = _clean_text(raw.get("rationale"), "", 160)
            if not change:
                continue
            if not rationale:
                rationale = "정답 형태를 유지하면서 감점 원인만 최소 수정합니다."
            normalized_changes.append({"change": change, "rationale": rationale})
    if not normalized_changes:
        seed = (
            normalized_mistakes[0]["fix_instruction"]
            if normalized_mistakes
            else "최종 답을 식에 대입해 검산하고 단위/부호를 점검하세요."
        )
        normalized_changes.append(
            {
                "change": _clean_text(seed, "중간 계산/기호를 다시 검토해 감점 포인트를 수정합니다.", 220),
                "rationale": "핵심 오류를 먼저 보정하면 전체 점수 회복 효과가 큽니다.",
            }
        )
    brief = _clean_text(
        patch.get("patched_solution_brief"),
        "핵심 감점 포인트를 최소 수정해 기존 풀이 흐름을 유지합니다.",
        600,
    )
    payload["patch"] = {
        "minimal_changes": normalized_changes,
        "patched_solution_brief": brief,
    }

    checklist = payload.get("next_checklist")
    checklist_items: list[str] = []
    if isinstance(checklist, list):
        for raw in checklist:
            text = _clean_text(raw, "", 80)
            if text and text not in checklist_items:
                checklist_items.append(text)
            if len(checklist_items) >= 3:
                break
    if not checklist_items:
        candidates = [
            normalized_mistakes[0]["fix_instruction"] if normalized_mistakes else "최종 답 검산 수행",
            "최종 줄의 단위/기호/부호를 다시 확인하세요.",
            "조건 누락 여부를 체크한 뒤 답을 마무리하세요.",
        ]
        for item in candidates:
            text = _clean_text(item, "", 80)
            if text and text not in checklist_items:
                checklist_items.append(text)
            if len(checklist_items) >= 3:
                break
    payload["next_checklist"] = checklist_items[:3] if checklist_items else ["핵심 계산 단계를 다시 확인하세요."]

    confidence = _to_float(payload.get("confidence"))
    if confidence is None:
        confidence = 0.62
    payload["confidence"] = round(_clamp(confidence, 0.0, 1.0), 2)

    missing_info = payload.get("missing_info")
    if not isinstance(missing_info, list):
        missing_info = []
    normalized_missing: list[str] = []
    for raw in missing_info[:6]:
        text = _clean_text(raw, "", 80)
        if text:
            normalized_missing.append(text)
    payload["missing_info"] = normalized_missing


def _normalize_mistake(item: dict[str, Any]) -> dict[str, Any]:
    valid_types = {member.value for member in MistakeType}
    valid_severity = {member.value for member in Severity}

    mistake_type = str(item.get("type") or MistakeType.logic_gap.value).strip().upper()
    if mistake_type not in valid_types:
        mistake_type = MistakeType.logic_gap.value

    severity = str(item.get("severity") or Severity.med.value).strip().lower()
    if severity not in valid_severity:
        severity = Severity.med.value

    points = _to_float(item.get("points_deducted"))
    if points is None:
        points = 0.5
    points = round(_clamp(points, 0.0, 2.0), 2)

    highlight = item.get("highlight")
    if not isinstance(highlight, dict):
        highlight = {}
    mode = str(highlight.get("mode") or "tap").strip()
    if mode not in {"tap", "ocr_box", "region_box"}:
        mode = "tap"
    shape = str(highlight.get("shape") or "circle").strip()
    if shape not in {"circle", "box"}:
        shape = "circle"
    normalized_highlight: dict[str, Any] = {"mode": mode, "shape": shape}
    for key in ("x", "y", "w", "h"):
        value = _to_float(highlight.get(key))
        if value is not None:
            normalized_highlight[key] = value

    return {
        "type": mistake_type,
        "severity": severity,
        "points_deducted": points,
        "evidence": _clean_text(item.get("evidence"), "근거가 부족해 보완 설명이 필요합니다.", 240),
        "fix_instruction": _clean_text(
            item.get("fix_instruction"),
            "핵심 감점 구간을 한 줄씩 다시 전개해 수정하세요.",
            240,
        ),
        "location_hint": _clean_text(item.get("location_hint"), "풀이 중간 구간", 120),
        "highlight": normalized_highlight,
    }


def _clean_text(value: Any, default: str, max_len: int) -> str:
    if isinstance(value, str):
        normalized = " ".join(value.split())
        if normalized:
            return normalized[:max_len]
    return default[:max_len]


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _to_float(value: Any) -> float | None:
    if isinstance(value, Number):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _looks_like_result_payload(payload: dict[str, Any]) -> bool:
    keys = set(payload.keys())
    if "score_total" in keys:
        return True
    return "rubric_scores" in keys and "mistakes" in keys and "patch" in keys


def _looks_like_partial_payload(payload: dict[str, Any]) -> bool:
    keys = set(payload.keys())
    candidate_keys = {
        "score_total",
        "total_score",
        "score",
        "final_score",
        "overall_score",
        "scoreTotal",
        "rubric_scores",
        "rubric",
        "rubric_score",
        "rubricScores",
        "mistakes",
        "patch",
        "next_checklist",
        "confidence",
    }
    return len(keys.intersection(candidate_keys)) >= 2


def _infer_score_total(payload: dict[str, Any]) -> float | None:
    rubric = payload.get("rubric_scores")
    if isinstance(rubric, dict):
        rubric_keys = ("conditions", "modeling", "logic", "calculation", "final")
        rubric_values = [_to_float(rubric.get(key)) for key in rubric_keys]
        if all(value is not None for value in rubric_values):
            score = sum(value for value in rubric_values if value is not None)
            return round(max(0.0, min(10.0, score)), 2)

    mistakes = payload.get("mistakes")
    if isinstance(mistakes, list):
        deduction = 0.0
        for item in mistakes:
            if not isinstance(item, dict):
                continue
            points = _to_float(item.get("points_deducted"))
            if points is not None:
                deduction += points
        return round(max(0.0, min(10.0, 10.0 - deduction)), 2)

    return None


def _apply_simple_equation_consistency(
    result: dict[str, Any],
    solution_image_path: str,
    problem_image_path: str | None,
) -> None:
    if not problem_image_path or not Path(problem_image_path).exists():
        return
    if not Path(solution_image_path).exists():
        return

    problem_text = extract_image_text(problem_image_path)
    solution_text = extract_image_text(solution_image_path)
    expected = _solve_simple_x(problem_text)
    given = _extract_last_x_value(solution_text)
    if expected is None or given is None:
        return

    if abs(expected - given) <= 0.05:
        _apply_correct_answer_adjustment(result, expected, given)
    else:
        _apply_wrong_answer_adjustment(result, expected, given)


def _solve_simple_x(problem_text: str) -> float | None:
    text = problem_text.lower()
    text = text.replace("−", "-").replace("—", "-")
    text = text.replace(",", ".")
    text = re.sub(r"\s+", "", text)

    direct = re.search(r"([+-]?\d*(?:\.\d+)?)x([+-]\d+(?:\.\d+)?)?=([+-]?\d+(?:\.\d+)?)", text)
    if direct:
        a = _parse_coefficient(direct.group(1))
        b = float(direct.group(2)) if direct.group(2) else 0.0
        c = float(direct.group(3))
        if abs(a) < 1e-9:
            return None
        return (c - b) / a

    swapped = re.search(r"([+-]?\d+(?:\.\d+)?)=([+-]?\d*(?:\.\d+)?)x([+-]\d+(?:\.\d+)?)?", text)
    if swapped:
        c = float(swapped.group(1))
        a = _parse_coefficient(swapped.group(2))
        b = float(swapped.group(3)) if swapped.group(3) else 0.0
        if abs(a) < 1e-9:
            return None
        return (c - b) / a

    divided = re.search(r"x/([+-]?\d+(?:\.\d+)?)=([+-]?\d+(?:\.\d+)?)", text)
    if divided:
        divisor = float(divided.group(1))
        rhs = float(divided.group(2))
        return divisor * rhs

    return None


def _parse_coefficient(token: str) -> float:
    if token in ("", "+"):
        return 1.0
    if token == "-":
        return -1.0
    return float(token)


def _extract_last_x_value(solution_text: str) -> float | None:
    text = solution_text.lower().replace("−", "-").replace("—", "-").replace(",", ".")
    matches = re.findall(r"x\s*=\s*([+-]?\d+(?:\.\d+)?)", text)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def _apply_correct_answer_adjustment(result: dict[str, Any], expected: float, given: float) -> None:
    mistakes = result.get("mistakes")
    if isinstance(mistakes, list):
        for item in mistakes:
            if not isinstance(item, dict):
                continue
            mtype = str(item.get("type") or "")
            if mtype in {MistakeType.final_form_error.value, MistakeType.arithmetic_error.value}:
                item["severity"] = Severity.low.value
                points = _to_float(item.get("points_deducted")) or 0.2
                item["points_deducted"] = round(_clamp(min(points, 0.2), 0.0, 2.0), 2)
                item["evidence"] = _clean_text(
                    f"최종 답 x={given:g}는 식과 일치합니다. 표현/검산 보완 위주로 수정하세요.",
                    "최종 답은 일치하며 표현 보완이 필요합니다.",
                    240,
                )
        result["mistakes"] = mistakes

    rubric = result.get("rubric_scores")
    if isinstance(rubric, dict):
        rubric["final"] = 2.0
        rubric["logic"] = max(_to_float(rubric.get("logic")) or 1.8, 1.8)
        total = sum(_to_float(rubric.get(key)) or 0.0 for key in ("conditions", "modeling", "logic", "calculation", "final"))
        target = max(total, 9.5 if not result.get("mistakes") else 8.8)
        result["score_total"] = round(_clamp(target, 0.0, 10.0), 2)
        result["rubric_scores"] = rubric

    confidence = _to_float(result.get("confidence")) or 0.75
    result["confidence"] = round(_clamp(max(confidence, 0.82), 0.0, 1.0), 2)
    checklist = result.get("next_checklist")
    if isinstance(checklist, list) and checklist:
        checklist[0] = _clean_text(f"정답 확인 완료: x={expected:g}. 최종 검산 습관 유지", checklist[0], 80)
        result["next_checklist"] = checklist[:3]


def _apply_wrong_answer_adjustment(result: dict[str, Any], expected: float, given: float) -> None:
    mistakes = result.get("mistakes")
    if not isinstance(mistakes, list):
        mistakes = []

    final_error = None
    for item in mistakes:
        if isinstance(item, dict) and item.get("type") == MistakeType.final_form_error.value:
            final_error = item
            break

    evidence = _clean_text(
        f"최종 답이 x={given:g}로 기록됐지만 식 해는 x={expected:g}입니다.",
        "최종 답이 식과 일치하지 않습니다.",
        240,
    )
    fix_instruction = _clean_text(
        "이항/계산 후 x 값을 다시 대입해 참/거짓을 검산하세요.",
        "최종 답을 식에 대입해 검산하세요.",
        240,
    )

    if final_error is None:
        mistakes.insert(
            0,
            {
                "type": MistakeType.final_form_error.value,
                "severity": Severity.high.value,
                "points_deducted": 2.0,
                "evidence": evidence,
                "fix_instruction": fix_instruction,
                "location_hint": "최종 답 줄",
                "highlight": {"mode": "ocr_box", "shape": "box"},
            },
        )
    else:
        final_error["severity"] = Severity.high.value
        points = _to_float(final_error.get("points_deducted")) or 1.5
        final_error["points_deducted"] = round(_clamp(max(points, 1.5), 0.0, 2.0), 2)
        final_error["evidence"] = evidence
        final_error["fix_instruction"] = fix_instruction
        highlight = final_error.get("highlight")
        if not isinstance(highlight, dict):
            highlight = {}
        highlight["mode"] = "ocr_box"
        highlight["shape"] = "box"
        final_error["highlight"] = highlight

    result["mistakes"] = mistakes[:20]

    rubric = result.get("rubric_scores")
    if not isinstance(rubric, dict):
        rubric = {}
    rubric["final"] = min(_to_float(rubric.get("final")) or 0.4, 0.4)
    rubric["logic"] = min(_to_float(rubric.get("logic")) or 1.0, 1.0)
    for key in ("conditions", "modeling", "calculation"):
        rubric[key] = _clamp(_to_float(rubric.get(key)) or 1.2, 0.0, 2.0)
    raw_sum = sum(_to_float(rubric.get(key)) or 0.0 for key in ("conditions", "modeling", "logic", "calculation", "final"))
    target = min(_to_float(result.get("score_total")) or raw_sum, raw_sum, 5.0)
    result["score_total"] = round(_clamp(target, 0.0, 10.0), 2)
    result["rubric_scores"] = rubric

    confidence = _to_float(result.get("confidence")) or 0.6
    result["confidence"] = round(_clamp(min(confidence, 0.58), 0.0, 1.0), 2)

    checklist = [
        _clean_text("최종 답을 원식에 대입해 성립 여부 확인", "최종 답 검산 수행", 80),
        _clean_text("이항 시 부호/연산 오류 재점검", "이항 부호 점검", 80),
        _clean_text("정답 기재 전 마지막 한 줄 검산", "마지막 검산", 80),
    ]
    result["next_checklist"] = checklist


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
