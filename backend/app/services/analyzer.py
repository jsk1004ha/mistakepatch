from __future__ import annotations

import ast
import json
import math
from numbers import Number
from pathlib import Path
import re
from dataclasses import dataclass
from statistics import median
from typing import Any

from jsonschema import ValidationError, validate

from ..config import settings
from ..models import AnalysisResult, AnswerVerdict, MistakeType, Severity
from ..repositories import mark_analysis_failed, save_analysis_result, set_analysis_status
from ..schemas import ANALYSIS_RESULT_JSON_SCHEMA
from .ocr import extract_image_lines, extract_image_text, suggest_ocr_boxes
from .openai_service import OpenAIService


@dataclass(frozen=True)
class ConsensusMeta:
    runs_requested: int
    runs_used: int
    agreement: float
    score_spread: float


@dataclass(frozen=True)
class ExtractedStep:
    step_id: str
    text: str
    equation: str


@dataclass(frozen=True)
class VerificationFinding:
    step_id: str
    rule: str
    passed: bool
    reason: str
    counterexample: str | None = None


@dataclass(frozen=True)
class VerificationReport:
    steps: list[ExtractedStep]
    findings: list[VerificationFinding]
    expected_x: float | None
    observed_x: float | None
    confidence: float
    requires_review: bool


@dataclass(frozen=True)
class LinearExpression:
    a: float
    b: float


@dataclass(frozen=True)
class LinearEquation:
    a: float
    b: float
    raw: str


_PROVENANCE_PATTERN = re.compile(
    r"\[step:(?P<step>[^\]]+)\]\s*\[rule:(?P<rule>[^\]]+)\]\s*(?P<body>.*)",
    flags=re.IGNORECASE,
)
_ALLOWED_EXPR_CHARS = re.compile(r"^[0-9xX\+\-\*/\(\)\.\s]+$")
_ALLOWED_EQUATION_CHARS = re.compile(r"^[0-9xX\+\-\*/\(\)\.\s=<>]+$")
_DEFAULT_GENERIC_EVIDENCE = {
    "근거가 부족해 보완 설명이 필요합니다.",
    "핵심 감점 구간을 한 줄씩 다시 전개해 수정하세요.",
}

def process_analysis_job(payload: dict[str, Any]) -> None:
    analysis_id = payload["analysis_id"]
    subject = payload["subject"]
    highlight_mode = payload["highlight_mode"]
    solution_image_path = payload["solution_image_path"]
    problem_image_path = payload.get("problem_image_path")

    set_analysis_status(analysis_id, "processing")
    fallback_used = False
    error_code: str | None = None
    consensus_meta = ConsensusMeta(runs_requested=1, runs_used=1, agreement=1.0, score_spread=0.0)

    try:
        raw_runs = _get_llm_results(solution_image_path, problem_image_path, subject, highlight_mode)
        validated_runs: list[dict[str, Any]] = []
        validation_errors: list[str] = []
        for raw in raw_runs:
            try:
                validated_runs.append(_validate_result(raw))
            except Exception as exc:
                validation_errors.append(str(exc))

        if not validated_runs:
            joined = "; ".join(validation_errors)[:200]
            raise RuntimeError(f"all_consensus_runs_invalid:{joined or 'unknown'}")

        validated, consensus_meta = _merge_consensus_results(
            validated_runs=validated_runs,
            runs_requested=max(1, settings.consensus_runs),
        )
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
    _apply_reasoning_guardrails(
        result=validated,
        solution_image_path=solution_image_path,
        problem_image_path=problem_image_path,
        consensus_meta=consensus_meta,
    )
    _inject_ocr_hints(validated, solution_image_path)

    try:
        save_analysis_result(analysis_id, validated, fallback_used=fallback_used, error_code=error_code)
    except Exception:
        mark_analysis_failed(analysis_id, "db_write_failed")
        raise


def _get_llm_results(
    solution_image_path: str,
    problem_image_path: str | None,
    subject: str,
    highlight_mode: str,
) -> list[dict[str, Any]]:
    service = OpenAIService()
    runs_requested = max(1, settings.consensus_runs)
    payloads: list[dict[str, Any]] = []
    errors: list[str] = []
    for _ in range(runs_requested):
        try:
            payloads.append(
                service.analyze_solution(
                    solution_image_path=solution_image_path,
                    problem_image_path=problem_image_path,
                    subject=subject,
                    highlight_mode=highlight_mode,
                )
            )
        except Exception as exc:
            errors.append(str(exc))

    if not payloads:
        joined = "; ".join(errors)[:200]
        raise RuntimeError(f"model_request_failed:{joined or 'unknown'}")
    return payloads


def _merge_consensus_results(
    validated_runs: list[dict[str, Any]],
    runs_requested: int,
) -> tuple[dict[str, Any], ConsensusMeta]:
    if len(validated_runs) == 1:
        return dict(validated_runs[0]), ConsensusMeta(
            runs_requested=runs_requested,
            runs_used=1,
            agreement=1.0,
            score_spread=0.0,
        )

    scores = [_to_float(item.get("score_total")) or 0.0 for item in validated_runs]
    score_median = round(float(median(scores)), 2)
    score_spread = max(scores) - min(scores)
    score_agreement = 1.0 - min(1.0, score_spread / 3.0)

    rubric_keys = ("conditions", "modeling", "logic", "calculation", "final")
    rubric_merged: dict[str, float] = {}
    for key in rubric_keys:
        vals: list[float] = []
        for item in validated_runs:
            rubric = item.get("rubric_scores")
            if isinstance(rubric, dict):
                value = _to_float(rubric.get(key))
                if value is not None:
                    vals.append(value)
        rubric_merged[key] = round(_clamp(float(median(vals)) if vals else score_median / 5.0, 0.0, 2.0), 2)

    mistake_buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in validated_runs:
        for mistake in item.get("mistakes", []):
            if not isinstance(mistake, dict):
                continue
            key = _consensus_mistake_key(mistake)
            mistake_buckets.setdefault(key, []).append(mistake)

    vote_threshold = max(1, math.ceil(len(validated_runs) / 2))
    merged_mistakes: list[dict[str, Any]] = []
    for key, bucket in mistake_buckets.items():
        if len(bucket) < vote_threshold:
            continue
        bucket_sorted = sorted(
            bucket,
            key=lambda item: (
                _to_float(item.get("points_deducted")) or 0.0,
                _severity_rank(str(item.get("severity") or Severity.low.value)),
            ),
            reverse=True,
        )
        representative = dict(bucket_sorted[0])
        representative["location_hint"] = _clean_text(
            representative.get("location_hint"),
            key[1] if key[1] else "풀이 중간 구간",
            120,
        )
        merged_mistakes.append(representative)

    merged_mistakes.sort(
        key=lambda item: (_to_float(item.get("points_deducted")) or 0.0, item.get("type", "")),
        reverse=True,
    )

    mistake_agreement = (
        len(merged_mistakes) / len(mistake_buckets) if mistake_buckets else 1.0
    )
    agreement = round(_clamp((score_agreement + mistake_agreement) / 2.0, 0.0, 1.0), 2)

    chosen = min(
        validated_runs,
        key=lambda item: abs((_to_float(item.get("score_total")) or 0.0) - score_median),
    )
    merged = dict(chosen)
    merged["score_total"] = score_median
    merged["rubric_scores"] = rubric_merged
    merged["mistakes"] = merged_mistakes[:20]

    checklist_votes: dict[str, int] = {}
    for item in validated_runs:
        checklist = item.get("next_checklist")
        if not isinstance(checklist, list):
            continue
        for entry in checklist:
            text = _clean_text(entry, "", 80)
            if text:
                checklist_votes[text] = checklist_votes.get(text, 0) + 1
    if checklist_votes:
        merged["next_checklist"] = [
            text
            for text, _ in sorted(checklist_votes.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
        ]

    avg_conf = sum((_to_float(item.get("confidence")) or 0.0) for item in validated_runs) / len(validated_runs)
    merged["confidence"] = round(_clamp(avg_conf - (1.0 - agreement) * 0.25, 0.0, 1.0), 2)

    missing: list[str] = []
    for item in validated_runs:
        info = item.get("missing_info")
        if not isinstance(info, list):
            continue
        for raw in info:
            text = _clean_text(raw, "", 80)
            if text and text not in missing:
                missing.append(text)
    note = _clean_text(
        f"consensus_runs={len(validated_runs)}/{runs_requested}, agreement={agreement:.2f}",
        "",
        80,
    )
    if note and note not in missing:
        missing.append(note)
    merged["missing_info"] = missing[:6]

    return merged, ConsensusMeta(
        runs_requested=runs_requested,
        runs_used=len(validated_runs),
        agreement=agreement,
        score_spread=round(score_spread, 3),
    )


def _consensus_mistake_key(mistake: dict[str, Any]) -> tuple[str, str]:
    mtype = str(mistake.get("type") or MistakeType.logic_gap.value).strip().upper()
    location = _clean_text(mistake.get("location_hint"), "풀이 중간 구간", 80).lower()
    location = re.sub(r"\s+", " ", location)
    return mtype, location


def _severity_rank(severity: str) -> int:
    order = {Severity.low.value: 0, Severity.med.value: 1, Severity.high.value: 2}
    normalized = _normalize_severity(severity)
    return order.get(normalized, 0)


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

    if "answer_verdict" not in payload:
        for alias in ("verdict", "is_correct", "correctness", "answerVerdict"):
            if alias in payload:
                payload["answer_verdict"] = payload[alias]
                break

    if "answer_verdict_reason" not in payload:
        for alias in ("verdict_reason", "correctness_reason", "answerVerdictReason"):
            if alias in payload:
                payload["answer_verdict_reason"] = payload[alias]
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
        "answer_verdict",
        "answer_verdict_reason",
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
    normalized_mistakes = _deduplicate_mistakes(normalized_mistakes)
    normalized_mistakes = _sort_mistakes(normalized_mistakes)
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
        checklist_items.extend(_build_checklist_from_mistakes(normalized_mistakes))
        if len(checklist_items) < 3:
            candidates = [
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
    payload["confidence"] = _calibrate_confidence(
        base_confidence=confidence,
        mistakes=normalized_mistakes,
        score_total=payload["score_total"],
        missing_info=payload.get("missing_info"),
    )

    verdict = _normalize_answer_verdict(payload.get("answer_verdict"))
    payload["answer_verdict"] = verdict
    payload["answer_verdict_reason"] = _clean_text(
        payload.get("answer_verdict_reason"),
        "정오 판단 정보가 부족합니다.",
        120,
    )

    missing_info = payload.get("missing_info")
    if not isinstance(missing_info, list):
        missing_info = []
    normalized_missing: list[str] = []
    for raw in missing_info[:6]:
        text = _clean_text(raw, "", 80)
        if text:
            normalized_missing.append(text)
    payload["missing_info"] = normalized_missing

    _harmonize_score_with_deductions(payload)
    _reconcile_rubric_with_score(payload)
    _inject_uncertainty_hint(payload)


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
    points = _normalize_points_by_severity(points, severity)
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
            normalized_highlight[key] = _normalize_highlight_value(key, value)

    if mode in {"ocr_box", "region_box"} and not all(
        key in normalized_highlight for key in ("x", "y", "w", "h")
    ):
        # Incomplete non-tap highlights are misleading; fall back to tap mode.
        normalized_highlight = {"mode": "tap", "shape": shape}

    return {
        "type": mistake_type,
        "severity": severity,
        "points_deducted": points,
        "evidence": _normalize_evidence(
            _clean_text(item.get("evidence"), "근거가 부족해 보완 설명이 필요합니다.", 240),
            mistake_type,
        ),
        "fix_instruction": _normalize_fix_instruction(
            _clean_text(
                item.get("fix_instruction"),
                "핵심 감점 구간을 한 줄씩 다시 전개해 수정하세요.",
                240,
            ),
            mistake_type,
        ),
        "location_hint": _normalize_location_hint(
            _clean_text(item.get("location_hint"), "풀이 중간 구간", 120),
            mistake_type,
        ),
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
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _round_to_tenth(value: float) -> float:
    return round(value + 1e-9, 1)


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
        "answer_verdict",
        "verdict",
        "is_correct",
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
    text = _normalize_ocr_symbol_text(solution_text).lower()
    text = text.replace(",", ".")
    candidates = re.findall(r"x\s*=\s*([^\n\r;,\]]+)", text)
    if not candidates:
        return None

    parsed_values: list[float] = []
    for raw in candidates:
        expr = _normalize_numeric_expression(raw)
        if not expr:
            continue
        value = _safe_eval_numeric_expression(expr)
        if value is not None and math.isfinite(value):
            parsed_values.append(value)

    if not parsed_values:
        return None
    return parsed_values[-1]


def _extract_last_rhs_numeric_value(solution_text: str) -> float | None:
    text = _normalize_ocr_symbol_text(solution_text).replace(",", ".")
    candidates = re.findall(r"=\s*([^\n\r;,\]]+)", text)
    if not candidates:
        return None

    parsed_values: list[float] = []
    for raw in candidates:
        expr = _normalize_numeric_expression(raw)
        if not expr:
            continue
        value = _safe_eval_numeric_expression(expr)
        if value is not None and math.isfinite(value):
            parsed_values.append(value)

    if not parsed_values:
        return None
    return parsed_values[-1]


def _normalize_numeric_expression(raw: str) -> str:
    candidate = _clean_text(raw, "", 80)
    if not candidate:
        return ""
    candidate = _normalize_ocr_symbol_text(candidate)
    candidate = _normalize_ocr_digit_text(candidate)
    candidate = re.sub(r"(?<=\d)x(?=\d|\()", "*", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"(?<=\))x(?=\d|\()", "*", candidate, flags=re.IGNORECASE)
    candidate = candidate.replace(",", ".")
    candidate = re.sub(r"\s+", "", candidate)
    if "x" in candidate.lower():
        return ""
    # Keep only the leading numeric expression segment (drop OCR tail text).
    match = re.match(r"^[\+\-\*/\(\)\.\d]+", candidate)
    if not match:
        return ""
    expr = match.group(0)
    if not expr or not re.fullmatch(r"[\+\-\*/\(\)\.\d]+", expr):
        return ""
    return expr


def _safe_eval_numeric_expression(expr: str) -> float | None:
    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def _eval(node: ast.AST) -> float | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, Number):
            return float(node.value)
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if operand is None:
                return None
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand
            return None
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if abs(right) <= 1e-9:
                    return None
                return left / right
            return None
        return None

    return _eval(parsed.body)


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
    result["answer_verdict"] = AnswerVerdict.correct.value
    result["answer_verdict_reason"] = _clean_text(
        f"맞음: 단순식 검산 결과 x={given:g} (기대값 x={expected:g})",
        "맞음: 단순식 검산 결과가 일치합니다.",
        120,
    )
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
    result["answer_verdict"] = AnswerVerdict.incorrect.value
    result["answer_verdict_reason"] = _clean_text(
        f"틀림: 단순식 검산 결과 x={given:g}, 기대값 x={expected:g}",
        "틀림: 단순식 검산 결과가 일치하지 않습니다.",
        120,
    )

    checklist = [
        _clean_text("최종 답을 원식에 대입해 성립 여부 확인", "최종 답 검산 수행", 80),
        _clean_text("이항 시 부호/연산 오류 재점검", "이항 부호 점검", 80),
        _clean_text("정답 기재 전 마지막 한 줄 검산", "마지막 검산", 80),
    ]
    result["next_checklist"] = checklist


def _apply_reasoning_guardrails(
    result: dict[str, Any],
    solution_image_path: str,
    problem_image_path: str | None,
    consensus_meta: ConsensusMeta,
) -> None:
    report = _build_verification_report(solution_image_path, problem_image_path)
    _inject_verification_findings(result, report)
    _enforce_evidence_gate(result, report)
    _dedupe_mistakes_by_step_rule(result)
    _apply_verified_wrong_final_cap(result, report)
    _apply_uncertainty_policy(result, report, consensus_meta)
    _apply_answer_verdict_policy(result, report)
    _ensure_mistake_coverage(result, report)
    _reconcile_score_from_deductions(result)


def _build_verification_report(
    solution_image_path: str,
    problem_image_path: str | None,
) -> VerificationReport:
    steps = _extract_solution_steps(solution_image_path)
    expected_equation = _extract_problem_equation(problem_image_path)
    parsed_expected = _parse_linear_equation(expected_equation) if expected_equation else None
    expected_x_simple: float | None = None
    if problem_image_path and Path(problem_image_path).exists():
        expected_x_simple = _solve_simple_x(extract_image_text(problem_image_path))

    findings: list[VerificationFinding] = []
    parsed_steps: list[tuple[ExtractedStep, LinearEquation]] = []
    for step in steps:
        parsed = _parse_linear_equation(step.equation)
        if parsed is None:
            continue
        parsed_steps.append((step, parsed))

    if parsed_expected is None and parsed_steps:
        # If problem OCR fails, infer baseline equation from the first parsed step.
        parsed_expected = parsed_steps[0][1]

    for idx in range(1, len(parsed_steps)):
        prev_step, prev_eq = parsed_steps[idx - 1]
        step, eq = parsed_steps[idx]
        if _equations_equivalent(prev_eq, eq):
            findings.append(
                VerificationFinding(
                    step_id=step.step_id,
                    rule="RULE_EQUIV_TRANSFORM",
                    passed=True,
                    reason="연속 식 변형이 동치입니다.",
                )
            )
        else:
            prev_solution = _equation_solution_text(prev_eq)
            cur_solution = _equation_solution_text(eq)
            findings.append(
                VerificationFinding(
                    step_id=step.step_id,
                    rule="RULE_EQUIV_TRANSFORM",
                    passed=False,
                    reason="연속 식 변형 전후의 해가 일치하지 않습니다.",
                    counterexample=f"{prev_step.step_id}={prev_solution}, {step.step_id}={cur_solution}",
                )
            )

    observed_x = _extract_last_x_value_from_steps(steps, solution_image_path)
    expected_x_value = _extract_solution_value_from_equation(parsed_expected)
    if expected_x_value is None:
        expected_x_value = expected_x_simple

    if parsed_expected is not None and observed_x is not None:
        residual = parsed_expected.a * observed_x + parsed_expected.b
        if abs(residual) <= 0.05:
            findings.append(
                VerificationFinding(
                    step_id=steps[-1].step_id if steps else "s0",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=True,
                    reason="최종 답을 원식에 대입했을 때 성립합니다.",
                )
            )
        else:
            expected_text = _equation_solution_text(parsed_expected)
            findings.append(
                VerificationFinding(
                    step_id=steps[-1].step_id if steps else "s0",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=False,
                    reason="최종 답 대입 시 원식이 성립하지 않습니다.",
                    counterexample=f"x={observed_x:g}, expected={expected_text}",
                )
            )
    elif expected_x_value is not None and observed_x is not None:
        if abs(expected_x_value - observed_x) <= 0.05:
            findings.append(
                VerificationFinding(
                    step_id=steps[-1].step_id if steps else "s0",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=True,
                    reason="최종 답이 추정 정답과 일치합니다.",
                )
            )
        else:
            findings.append(
                VerificationFinding(
                    step_id=steps[-1].step_id if steps else "s0",
                    rule="RULE_FINAL_SUBSTITUTION",
                    passed=False,
                    reason="최종 답이 추정 정답과 일치하지 않습니다.",
                    counterexample=f"x={observed_x:g}, expected=x={expected_x_value:g}",
                )
            )
    elif expected_x_value is not None and observed_x is None:
        findings.append(
            VerificationFinding(
                step_id=steps[-1].step_id if steps else "s0",
                rule="RULE_FINAL_SUBSTITUTION",
                passed=False,
                reason="최종 x 값을 확인하지 못해 원식 대입 검증이 불가합니다.",
            )
        )

    equation_step_count = max(1, len(steps))
    coverage = len(parsed_steps) / equation_step_count
    pass_ratio = (
        len([item for item in findings if item.passed]) / len(findings)
        if findings
        else 0.55
    )
    confidence = 0.35 + 0.35 * coverage + 0.3 * pass_ratio
    if parsed_expected is None:
        confidence -= 0.08
    if parsed_expected is None and expected_x_value is not None:
        confidence += 0.04
    if observed_x is None:
        confidence -= 0.1
    confidence = round(_clamp(confidence, 0.0, 1.0), 2)
    requires_review = coverage < 0.34 and expected_x_value is not None and observed_x is None

    return VerificationReport(
        steps=steps,
        findings=findings,
        expected_x=expected_x_value,
        observed_x=observed_x,
        confidence=confidence,
        requires_review=requires_review,
    )


def _extract_solution_steps(solution_image_path: str) -> list[ExtractedStep]:
    if not Path(solution_image_path).exists():
        return []
    lines = extract_image_lines(solution_image_path, max_lines=18, max_chars_per_line=160)
    candidates = _equation_candidates_from_lines(lines)
    if not candidates:
        text = extract_image_text(solution_image_path)
        if text:
            candidates = _equation_candidates_from_lines([text])
    if not candidates:
        return []

    steps: list[ExtractedStep] = []
    for idx, equation in enumerate(candidates[:12], start=1):
        steps.append(ExtractedStep(step_id=f"s{idx}", text=equation, equation=equation))
    return steps


def _extract_problem_equation(problem_image_path: str | None) -> str | None:
    if not problem_image_path or not Path(problem_image_path).exists():
        return None
    lines = extract_image_lines(problem_image_path, max_lines=8, max_chars_per_line=160)
    candidates = _equation_candidates_from_lines(lines)
    if not candidates:
        text = extract_image_text(problem_image_path)
        if text:
            candidates = _equation_candidates_from_lines([text])
    return candidates[0] if candidates else None


def _equation_candidates_from_lines(lines: list[str]) -> list[str]:
    candidates: list[str] = []
    for raw_line in lines:
        line = _clean_text(raw_line, "", 180)
        if not line:
            continue
        for part in re.split(r"[;,]", line):
            for segment in _split_equation_like_segments(part):
                if not _contains_variable_token(segment):
                    continue
                equation = _normalize_equation_text(segment)
                if equation and equation not in candidates:
                    candidates.append(equation)
    return candidates


def _split_equation_like_segments(raw: str) -> list[str]:
    text = _clean_text(raw, "", 180)
    if not text:
        return []
    chunks = re.split(r"(?<=\d)\s+(?=[xX×✕✖χΧⅹｘ]\s*[\+\-\=])", text)
    segments = [_clean_text(chunk, "", 180) for chunk in chunks]
    return [item for item in segments if item]


def _contains_variable_token(text: str) -> bool:
    return bool(re.search(r"[xX×✕✖χΧⅹｘ]", text))


def _normalize_ocr_symbol_text(text: str) -> str:
    normalized = text
    normalized = normalized.replace("−", "-").replace("—", "-").replace("–", "-")
    normalized = normalized.replace("＝", "=")
    normalized = normalized.replace("⇒", "=").replace("→", "=").replace("⟶", "=")
    normalized = normalized.replace("÷", "/")
    for token in ("×", "✕", "✖", "χ", "Χ", "ⅹ", "ｘ", "X"):
        normalized = normalized.replace(token, "x")
    return normalized


def _normalize_ocr_digit_text(text: str) -> str:
    return text.translate(
        str.maketrans(
            {
                "O": "0",
                "o": "0",
                "I": "1",
                "l": "1",
                "|": "1",
                "S": "5",
                "B": "8",
                "Z": "2",
            }
        )
    )


def _normalize_equation_text(text: str) -> str:
    normalized = _normalize_ocr_symbol_text(text)
    normalized = _normalize_ocr_digit_text(normalized)
    normalized = normalized.replace(",", ".")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("=>", "=").replace("->", "=")
    if normalized.count("=") == 0 and normalized.count(">") == 1:
        normalized = normalized.replace(">", "=")
    if not _ALLOWED_EQUATION_CHARS.match(normalized):
        return ""
    if normalized.count("=") != 1:
        return ""
    left_raw, right_raw = normalized.split("=", 1)
    right_raw = _normalize_ocr_digit_text(right_raw)
    normalized = f"{left_raw}={right_raw}"
    return normalized


def _parse_linear_equation(equation_text: str) -> LinearEquation | None:
    if "=" not in equation_text:
        return None
    left_raw, right_raw = equation_text.split("=", 1)
    left = _parse_linear_expression(left_raw)
    right = _parse_linear_expression(right_raw)
    if left is None or right is None:
        return None
    return LinearEquation(
        a=left.a - right.a,
        b=left.b - right.b,
        raw=equation_text,
    )


def _parse_linear_expression(expression_text: str) -> LinearExpression | None:
    normalized = _normalize_ocr_symbol_text(expression_text)
    normalized = _normalize_ocr_digit_text(normalized)
    normalized = normalized.replace(",", ".")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"(\d)(x)", r"\1*x", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\))(\d|x)", r"\1*\2", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d|\))\(", r"\1*(", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"x\(", "x*(", normalized, flags=re.IGNORECASE)
    if not normalized or not _ALLOWED_EXPR_CHARS.match(normalized):
        return None

    try:
        parsed = ast.parse(normalized, mode="eval")
    except SyntaxError:
        return None

    return _eval_linear_node(parsed.body)


def _eval_linear_node(node: ast.AST) -> LinearExpression | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, Number):
        return LinearExpression(a=0.0, b=float(node.value))

    if isinstance(node, ast.Name) and node.id.lower() == "x":
        return LinearExpression(a=1.0, b=0.0)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_linear_node(node.operand)
        if operand is None:
            return None
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return LinearExpression(a=-operand.a, b=-operand.b)
        return None

    if isinstance(node, ast.BinOp):
        left = _eval_linear_node(node.left)
        right = _eval_linear_node(node.right)
        if left is None or right is None:
            return None

        if isinstance(node.op, ast.Add):
            return LinearExpression(a=left.a + right.a, b=left.b + right.b)
        if isinstance(node.op, ast.Sub):
            return LinearExpression(a=left.a - right.a, b=left.b - right.b)
        if isinstance(node.op, ast.Mult):
            left_is_constant = abs(left.a) <= 1e-9
            right_is_constant = abs(right.a) <= 1e-9
            if left_is_constant and right_is_constant:
                return LinearExpression(a=0.0, b=left.b * right.b)
            if left_is_constant and not right_is_constant:
                return LinearExpression(a=right.a * left.b, b=right.b * left.b)
            if right_is_constant and not left_is_constant:
                return LinearExpression(a=left.a * right.b, b=left.b * right.b)
            return None
        if isinstance(node.op, ast.Div):
            if abs(right.a) > 1e-9 or abs(right.b) <= 1e-9:
                return None
            return LinearExpression(a=left.a / right.b, b=left.b / right.b)
        return None

    return None


def _equations_equivalent(first: LinearEquation, second: LinearEquation) -> bool:
    f_type, f_value = _solve_linear_equation(first)
    s_type, s_value = _solve_linear_equation(second)
    if f_type != s_type:
        return False
    if f_type == "single" and f_value is not None and s_value is not None:
        return abs(f_value - s_value) <= 0.05
    return True


def _solve_linear_equation(equation: LinearEquation) -> tuple[str, float | None]:
    if abs(equation.a) <= 1e-9:
        if abs(equation.b) <= 1e-9:
            return "identity", None
        return "inconsistent", None
    return "single", -equation.b / equation.a


def _equation_solution_text(equation: LinearEquation) -> str:
    mode, value = _solve_linear_equation(equation)
    if mode == "single" and value is not None:
        return f"x={value:g}"
    if mode == "identity":
        return "항상 참"
    return "모순"


def _extract_solution_value_from_equation(equation: LinearEquation | None) -> float | None:
    if equation is None:
        return None
    mode, value = _solve_linear_equation(equation)
    if mode == "single":
        return value
    return None


def _extract_last_x_value_from_steps(
    steps: list[ExtractedStep],
    solution_image_path: str,
) -> float | None:
    if steps:
        joined = " ".join(step.text for step in steps)
        extracted = _extract_last_x_value(joined)
        if extracted is not None:
            return extracted
        extracted_rhs = _extract_last_rhs_numeric_value(joined)
        if extracted_rhs is not None:
            return extracted_rhs
    if Path(solution_image_path).exists():
        text = extract_image_text(solution_image_path)
        extracted = _extract_last_x_value(text)
        if extracted is not None:
            return extracted
        return _extract_last_rhs_numeric_value(text)
    return None


def _inject_verification_findings(result: dict[str, Any], report: VerificationReport) -> None:
    mistakes = result.get("mistakes")
    if not isinstance(mistakes, list):
        mistakes = []

    failed = [finding for finding in report.findings if not finding.passed]
    if not failed:
        result["mistakes"] = mistakes
        return

    location_by_step = {step.step_id: step.text for step in report.steps}
    generated: list[dict[str, Any]] = []
    for finding in failed:
        if finding.rule == "RULE_FINAL_SUBSTITUTION":
            mistake_type = MistakeType.final_form_error.value
            severity = Severity.high.value
            points = 1.5
            fix = "최종 값을 원식에 대입해 성립 여부를 확인한 뒤 답을 수정하세요."
        else:
            mistake_type = MistakeType.logic_gap.value
            severity = Severity.med.value
            points = 0.5
            fix = "전후 식의 해가 같아지는지 한 줄씩 다시 전개해 수정하세요."

        evidence = _format_provenance_evidence(
            step_id=finding.step_id,
            rule=finding.rule,
            reason=finding.reason,
            counterexample=finding.counterexample,
        )
        generated.append(
            {
                "type": mistake_type,
                "severity": severity,
                "points_deducted": points,
                "evidence": evidence,
                "fix_instruction": _clean_text(fix, "핵심 감점 구간을 다시 검토하세요.", 240),
                "location_hint": _clean_text(
                    location_by_step.get(finding.step_id),
                    f"{finding.step_id} 단계",
                    120,
                ),
                "highlight": {"mode": "ocr_box", "shape": "box"},
            }
        )

    result["mistakes"] = (generated + mistakes)[:20]


def _enforce_evidence_gate(result: dict[str, Any], report: VerificationReport) -> None:
    mistakes = result.get("mistakes")
    if not isinstance(mistakes, list):
        result["mistakes"] = []
        return

    adjusted: list[dict[str, Any]] = []
    missing_info = result.get("missing_info")
    if not isinstance(missing_info, list):
        missing_info = []
    has_verification_context = bool(report.findings) or bool(report.steps)

    for idx, raw in enumerate(mistakes):
        if not isinstance(raw, dict):
            continue
        mistake = dict(raw)
        parsed = _parse_provenance(mistake.get("evidence"))
        inferred_step = (
            parsed[0]
            or _infer_step_id(mistake.get("location_hint"), report.steps)
            or (report.steps[-1].step_id if report.steps else "s0")
        )
        inferred_rule = parsed[1] or _default_rule_for_mistake_type(str(mistake.get("type") or ""))
        reason_text = parsed[2] or _clean_text(mistake.get("evidence"), "", 180)
        has_reason = _has_actionable_reason(reason_text)

        if not has_reason:
            if has_verification_context:
                mistake["points_deducted"] = 0.0
                mistake["severity"] = Severity.low.value
                reason_text = "근거 부족으로 자동 감점을 보류했습니다."
                hold_note = _clean_text(f"mistake#{idx + 1}: evidence_gate_hold", "", 80)
            else:
                # Keep model deductions when we cannot independently verify steps.
                existing_points = _to_float(mistake.get("points_deducted")) or 0.0
                if existing_points <= 0:
                    mistake["points_deducted"] = 0.3
                    mistake["severity"] = Severity.low.value
                reason_text = "OCR 검증 정보 부족: 모델 감점 근거를 보류 없이 반영"
                hold_note = _clean_text(f"mistake#{idx + 1}: evidence_unverified_model", "", 80)
            if hold_note and hold_note not in missing_info:
                missing_info.append(hold_note)

        mistake["evidence"] = _format_provenance_evidence(
            step_id=inferred_step,
            rule=inferred_rule,
            reason=reason_text,
        )
        adjusted.append(mistake)

    result["mistakes"] = adjusted[:20]
    result["missing_info"] = missing_info[:6]


def _dedupe_mistakes_by_step_rule(result: dict[str, Any]) -> None:
    mistakes = result.get("mistakes")
    if not isinstance(mistakes, list):
        result["mistakes"] = []
        return

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in mistakes:
        if not isinstance(raw, dict):
            continue
        mistake = dict(raw)
        step_id, rule, body = _parse_provenance(mistake.get("evidence"))
        key = (step_id or "s0", rule or _default_rule_for_mistake_type(str(mistake.get("type") or "")))
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = mistake
            continue

        existing_step, existing_rule, existing_body = _parse_provenance(existing.get("evidence"))
        similarity = _text_similarity(body, existing_body)
        existing_points = _to_float(existing.get("points_deducted")) or 0.0
        current_points = _to_float(mistake.get("points_deducted")) or 0.0

        if current_points > existing_points:
            existing["type"] = mistake.get("type", existing.get("type"))
            existing["fix_instruction"] = mistake.get("fix_instruction", existing.get("fix_instruction"))
            existing["location_hint"] = mistake.get("location_hint", existing.get("location_hint"))
            existing["highlight"] = mistake.get("highlight", existing.get("highlight"))
            existing["severity"] = _higher_severity(existing.get("severity"), mistake.get("severity"))
            existing["points_deducted"] = current_points
            if similarity >= 0.7:
                existing["evidence"] = mistake.get("evidence", existing.get("evidence"))
            else:
                merged_reason = _clean_text(
                    f"{existing_body} 추가근거: {body}",
                    existing_body or body,
                    180,
                )
                existing["evidence"] = _format_provenance_evidence(
                    step_id=existing_step or key[0],
                    rule=existing_rule or key[1],
                    reason=merged_reason,
                )
        else:
            existing["points_deducted"] = max(existing_points, current_points)
            existing["severity"] = _higher_severity(existing.get("severity"), mistake.get("severity"))
            if similarity < 0.7:
                merged_reason = _clean_text(
                    f"{existing_body} 추가근거: {body}",
                    existing_body or body,
                    180,
                )
                existing["evidence"] = _format_provenance_evidence(
                    step_id=existing_step or key[0],
                    rule=existing_rule or key[1],
                    reason=merged_reason,
                )

    deduped = list(grouped.values())
    deduped.sort(
        key=lambda item: (
            _to_float(item.get("points_deducted")) or 0.0,
            _severity_rank(str(item.get("severity") or Severity.low.value)),
        ),
        reverse=True,
    )
    result["mistakes"] = deduped[:20]


def _apply_uncertainty_policy(
    result: dict[str, Any],
    report: VerificationReport,
    consensus_meta: ConsensusMeta,
) -> None:
    model_conf = _to_float(result.get("confidence")) or 0.0
    blended_conf = round(
        _clamp(
            model_conf * 0.5 + report.confidence * 0.3 + consensus_meta.agreement * 0.2,
            0.0,
            1.0,
        ),
        2,
    )
    result["confidence"] = blended_conf

    has_verified_critical_failure = any(
        (not finding.passed)
        and finding.rule in {"RULE_FINAL_SUBSTITUTION", "RULE_EQUIV_TRANSFORM"}
        and bool(finding.counterexample)
        for finding in report.findings
    )
    has_verification_context = (
        bool(report.findings) or report.expected_x is not None or report.observed_x is not None
    )

    should_hold = (
        blended_conf < settings.uncertainty_threshold
        or consensus_meta.agreement < settings.consensus_min_agreement
        or report.requires_review
    )
    if has_verified_critical_failure:
        should_hold = False
    if not has_verification_context:
        should_hold = False
    if not should_hold:
        return

    mistakes = result.get("mistakes")
    if not isinstance(mistakes, list):
        mistakes = []

    if not mistakes:
        mistakes = [_make_review_placeholder()]

    for mistake in mistakes:
        if not isinstance(mistake, dict):
            continue
        mistake["points_deducted"] = 0.0
        mistake["severity"] = Severity.low.value
        step_id, rule, body = _parse_provenance(mistake.get("evidence"))
        reason = _clean_text(
            f"{body or '근거 불충분'} -> 자동 감점 보류(검토 필요)",
            "근거 부족으로 자동 감점을 보류했습니다.",
            180,
        )
        mistake["evidence"] = _format_provenance_evidence(
            step_id=step_id or "s0",
            rule=rule or "RULE_REVIEW_REQUIRED",
            reason=reason,
        )

    result["mistakes"] = mistakes[:20]
    current_score = _to_float(result.get("score_total")) or 0.0
    review_ceiling = 8.8
    if current_score > review_ceiling:
        result["score_total"] = review_ceiling
        rubric = result.get("rubric_scores")
        if isinstance(rubric, dict):
            keys = ("conditions", "modeling", "logic", "calculation", "final")
            values = [_to_float(rubric.get(key)) or 0.0 for key in keys]
            total = sum(values)
            if total > 0:
                scale = review_ceiling / total
                for key, value in zip(keys, values, strict=True):
                    rubric[key] = round(_clamp(value * scale, 0.0, 2.0), 2)
            else:
                per_bucket = round(review_ceiling / 5.0, 2)
                for key in keys:
                    rubric[key] = min(2.0, per_bucket)
            result["rubric_scores"] = rubric
        current_score = review_ceiling

    score_floor = 8.0
    if current_score < score_floor:
        result["score_total"] = score_floor
        rubric = result.get("rubric_scores")
        if isinstance(rubric, dict):
            per_bucket = round(score_floor / 5.0, 2)
            for key in ("conditions", "modeling", "logic", "calculation", "final"):
                rubric[key] = max(_to_float(rubric.get(key)) or 0.0, per_bucket)
            result["rubric_scores"] = rubric

    missing_info = result.get("missing_info")
    if not isinstance(missing_info, list):
        missing_info = []
    review_note = _clean_text(
        (
            "검토 필요: 자동 감점 보류 "
            f"(confidence={blended_conf:.2f}, agreement={consensus_meta.agreement:.2f})"
        ),
        "",
        80,
    )
    if review_note and review_note not in missing_info:
        missing_info.append(review_note)
    result["missing_info"] = missing_info[:6]

    checklist = result.get("next_checklist")
    if isinstance(checklist, list):
        if checklist:
            checklist[0] = _clean_text("검토 필요 항목 우선 확인: 자동 감점은 보류됨", checklist[0], 80)
        else:
            checklist.append("검토 필요 항목 우선 확인: 자동 감점은 보류됨")
        result["next_checklist"] = checklist[:3]


def _apply_verified_wrong_final_cap(result: dict[str, Any], report: VerificationReport) -> None:
    final_failures = [
        finding
        for finding in report.findings
        if (not finding.passed) and finding.rule == "RULE_FINAL_SUBSTITUTION"
    ]
    if not final_failures:
        return

    mistakes = result.get("mistakes")
    if not isinstance(mistakes, list):
        mistakes = []

    final_mistake: dict[str, Any] | None = None
    for item in mistakes:
        if isinstance(item, dict) and item.get("type") == MistakeType.final_form_error.value:
            final_mistake = item
            break

    failure = final_failures[0]
    if final_mistake is None:
        final_mistake = {
            "type": MistakeType.final_form_error.value,
            "severity": Severity.high.value,
            "points_deducted": 1.8,
            "evidence": _format_provenance_evidence(
                step_id=failure.step_id,
                rule=failure.rule,
                reason=failure.reason,
                counterexample=failure.counterexample,
            ),
            "fix_instruction": "최종 값을 원식에 대입해 성립 여부를 확인한 뒤 정답을 수정하세요.",
            "location_hint": "최종 답 줄",
            "highlight": {"mode": "ocr_box", "shape": "box"},
        }
        mistakes.insert(0, final_mistake)
    else:
        final_mistake["severity"] = Severity.high.value
        final_mistake["points_deducted"] = max(
            _to_float(final_mistake.get("points_deducted")) or 0.0,
            1.8,
        )
        final_mistake["evidence"] = _format_provenance_evidence(
            step_id=failure.step_id,
            rule=failure.rule,
            reason=failure.reason,
            counterexample=failure.counterexample,
        )
        final_mistake["fix_instruction"] = "최종 값을 원식에 대입해 성립 여부를 확인한 뒤 정답을 수정하세요."

    result["mistakes"] = mistakes[:20]
    score_cap = 7.0
    current_score = _to_float(result.get("score_total")) or 10.0
    if current_score > score_cap:
        result["score_total"] = score_cap
    rubric = result.get("rubric_scores")
    if isinstance(rubric, dict):
        rubric["final"] = min(_to_float(rubric.get("final")) or 0.6, 0.8)
        rubric["logic"] = min(_to_float(rubric.get("logic")) or 1.1, 1.6)
        for key in ("conditions", "modeling", "calculation"):
            rubric[key] = _clamp(_to_float(rubric.get(key)) or 1.2, 0.0, 2.0)
        rubric_sum = sum(
            _to_float(rubric.get(key)) or 0.0
            for key in ("conditions", "modeling", "logic", "calculation", "final")
        )
        result["score_total"] = round(min(_to_float(result.get("score_total")) or score_cap, rubric_sum, score_cap), 2)
        result["rubric_scores"] = rubric

    confidence = _to_float(result.get("confidence")) or 0.7
    result["confidence"] = round(min(confidence, 0.72), 2)


def _reconcile_score_from_deductions(result: dict[str, Any]) -> None:
    mistakes = result.get("mistakes")
    if not isinstance(mistakes, list):
        return
    deduction = 0.0
    for item in mistakes:
        if not isinstance(item, dict):
            continue
        deduction += _to_float(item.get("points_deducted")) or 0.0
    score_ceiling = _round_to_tenth(_clamp(10.0 - deduction, 0.0, 10.0))
    current_score = _round_to_tenth(_to_float(result.get("score_total")) or 0.0)
    if current_score <= score_ceiling:
        return
    result["score_total"] = score_ceiling
    rubric = result.get("rubric_scores")
    if isinstance(rubric, dict):
        keys = ("conditions", "modeling", "logic", "calculation", "final")
        values = [_to_float(rubric.get(key)) or 0.0 for key in keys]
        total = sum(values)
        if total > 0:
            scale = score_ceiling / total
            for key, value in zip(keys, values, strict=True):
                rubric[key] = round(_clamp(value * scale, 0.0, 2.0), 2)
        else:
            per_bucket = round(score_ceiling / 5.0, 2)
            for key in keys:
                rubric[key] = min(2.0, per_bucket)
        result["rubric_scores"] = rubric


def _apply_answer_verdict_policy(result: dict[str, Any], report: VerificationReport) -> None:
    verdict, reason = _derive_answer_verdict(report)
    current_score = _to_float(result.get("score_total")) or 0.0
    existing_verdict = _normalize_answer_verdict(result.get("answer_verdict"))
    used_existing_signal = False
    if verdict == AnswerVerdict.unknown.value and existing_verdict in {
        AnswerVerdict.correct.value,
        AnswerVerdict.incorrect.value,
    }:
        verdict = existing_verdict
        used_existing_signal = True

    reason = _stable_verdict_reason(verdict, report, used_existing_signal=used_existing_signal)

    result["answer_verdict"] = verdict
    result["answer_verdict_reason"] = _clean_text(reason, "정오 판단 정보가 부족합니다.", 120)

    logic_quality = _estimate_logic_quality(result, report)

    if verdict == AnswerVerdict.correct.value:
        target_score = round(_clamp(7.0 + logic_quality * 3.0, 7.0, 10.0), 2)
        # Keep existing higher score only if still inside the correct-answer band.
        if 7.0 <= current_score <= 10.0 and current_score > target_score:
            target_score = current_score
    elif verdict == AnswerVerdict.incorrect.value:
        target_score = round(_clamp(logic_quality * 7.0, 0.0, 7.0), 2)
        if current_score < target_score:
            target_score = current_score
    else:
        # Unknown verdict keeps current score band but avoids impossible values.
        target_score = round(_clamp(current_score, 0.0, 10.0), 2)

    result["score_total"] = target_score
    _rescale_rubric_to_score(result, target_score, verdict)


def _derive_answer_verdict(report: VerificationReport) -> tuple[str, str]:
    final_checks = [item for item in report.findings if item.rule == "RULE_FINAL_SUBSTITUTION"]
    for item in final_checks:
        if not item.passed and item.counterexample:
            return (
                AnswerVerdict.incorrect.value,
                _clean_text(f"틀림: {item.counterexample}", "틀림: 최종 대입이 성립하지 않습니다.", 120),
            )
    for item in final_checks:
        if item.passed:
            return (AnswerVerdict.correct.value, "맞음: 최종 답 대입 검증 통과")

    transform_failures = [
        item
        for item in report.findings
        if item.rule == "RULE_EQUIV_TRANSFORM" and (not item.passed) and bool(item.counterexample)
    ]
    if transform_failures:
        finding = transform_failures[0]
        return (
            AnswerVerdict.incorrect.value,
            _clean_text(
                f"틀림: 단계 식 변형 불일치 ({finding.counterexample})",
                "틀림: 단계 식 변형에서 동치가 깨졌습니다.",
                120,
            ),
        )

    if report.expected_x is not None and report.observed_x is not None:
        if abs(report.expected_x - report.observed_x) <= 0.05:
            return (AnswerVerdict.correct.value, "맞음: 추정 해와 최종 답이 일치")
        return (
            AnswerVerdict.incorrect.value,
            _clean_text(
                f"틀림: 최종 답 x={report.observed_x:g}, 정답 x={report.expected_x:g}",
                "틀림: 최종 답과 정답이 일치하지 않습니다.",
                120,
            ),
        )

    return (AnswerVerdict.unknown.value, "정오 판단 보류: 검증 정보 부족")


def _stable_verdict_reason(
    verdict: str,
    report: VerificationReport,
    *,
    used_existing_signal: bool = False,
) -> str:
    if verdict == AnswerVerdict.correct.value:
        if used_existing_signal:
            return "맞음: 보조 검산 기준에서 일치가 확인되었습니다."
        if any(item.rule == "RULE_FINAL_SUBSTITUTION" and item.passed for item in report.findings):
            return "맞음: 최종 답 검증을 통과했습니다."
        if report.expected_x is not None and report.observed_x is not None:
            return "맞음: 최종 답이 정답과 일치합니다."
        return "맞음: 검증 기준에서 정답으로 판단했습니다."

    if verdict == AnswerVerdict.incorrect.value:
        if used_existing_signal:
            return "틀림: 보조 검산 기준에서 불일치가 확인되었습니다."
        if any((not item.passed) and item.rule == "RULE_FINAL_SUBSTITUTION" for item in report.findings):
            return "틀림: 최종 답 검증에서 불일치가 확인되었습니다."
        if any((not item.passed) and item.rule == "RULE_EQUIV_TRANSFORM" for item in report.findings):
            return "틀림: 중간 식 변형에서 동치가 깨졌습니다."
        if report.expected_x is not None and report.observed_x is not None:
            return "틀림: 최종 답이 정답과 일치하지 않습니다."
        return "틀림: 검증 근거에서 오답 신호가 확인되었습니다."

    return "정오 판단 보류: 검증 정보 부족"


def _estimate_logic_quality(result: dict[str, Any], report: VerificationReport) -> float:
    rubric = result.get("rubric_scores")
    rubric_quality = 0.5
    if isinstance(rubric, dict):
        base = sum(
            _to_float(rubric.get(key)) or 0.0
            for key in ("conditions", "modeling", "logic", "calculation")
        )
        rubric_quality = _clamp(base / 8.0, 0.0, 1.0)

    transform_findings = [item for item in report.findings if item.rule == "RULE_EQUIV_TRANSFORM"]
    if transform_findings:
        transform_pass = len([item for item in transform_findings if item.passed])
        process_quality = transform_pass / len(transform_findings)
    else:
        process_quality = rubric_quality

    return round(_clamp(rubric_quality * 0.65 + process_quality * 0.35, 0.0, 1.0), 4)


def _rescale_rubric_to_score(result: dict[str, Any], score_total: float, verdict: str) -> None:
    rubric = result.get("rubric_scores")
    if not isinstance(rubric, dict):
        return

    keys = ("conditions", "modeling", "logic", "calculation", "final")
    values = [_to_float(rubric.get(key)) or 0.0 for key in keys]
    current_sum = sum(values)
    if current_sum <= 0:
        per_bucket = round(score_total / 5.0, 2)
        for key in keys:
            rubric[key] = round(_clamp(per_bucket, 0.0, 2.0), 2)
    else:
        scale = score_total / current_sum
        for key, value in zip(keys, values, strict=True):
            rubric[key] = round(_clamp(value * scale, 0.0, 2.0), 2)

    if verdict == AnswerVerdict.incorrect.value:
        rubric["final"] = min(_to_float(rubric.get("final")) or 0.0, 0.8)
    if verdict == AnswerVerdict.correct.value:
        rubric["final"] = max(_to_float(rubric.get("final")) or 0.0, 1.2)
    result["rubric_scores"] = rubric


def _ensure_mistake_coverage(result: dict[str, Any], report: VerificationReport) -> None:
    mistakes_raw = result.get("mistakes")
    mistakes = [dict(item) for item in mistakes_raw if isinstance(item, dict)] if isinstance(mistakes_raw, list) else []
    # Drop display-only zero deductions; actual deduction factors must be positive.
    mistakes = [item for item in mistakes if (_to_float(item.get("points_deducted")) or 0.0) > 0.04]
    verdict = _normalize_answer_verdict(result.get("answer_verdict"))
    has_failed_finding = any(not finding.passed for finding in report.findings)

    # Verified-correct paths should not receive synthetic deduction cards generated
    # only to fit score narratives.
    if verdict == AnswerVerdict.correct.value and not has_failed_finding:
        mistakes.sort(key=lambda item: _to_float(item.get("points_deducted")) or 0.0, reverse=True)
        result["mistakes"] = mistakes[:20]
        if mistakes:
            total_deduction = _round_to_tenth(
                sum((_to_float(item.get("points_deducted")) or 0.0) for item in result["mistakes"])
            )
            score_ceiling = _round_to_tenth(_clamp(10.0 - total_deduction, 0.0, 10.0))
            current_score = _round_to_tenth(_to_float(result.get("score_total")) or 0.0)
            if current_score > score_ceiling:
                result["score_total"] = score_ceiling
        return

    score_total = _round_to_tenth(_clamp(_to_float(result.get("score_total")) or 0.0, 0.0, 10.0))
    target_deduction = _round_to_tenth(10.0 - score_total)
    actual_deduction = round(
        sum((_to_float(item.get("points_deducted")) or 0.0) for item in mistakes),
        2,
    )
    gap = round(target_deduction - actual_deduction, 2)

    if gap > 0.1:
        additions = _build_rubric_gap_mistakes(result, report, gap)
        mistakes.extend(additions)
        actual_deduction = round(
            sum((_to_float(item.get("points_deducted")) or 0.0) for item in mistakes),
            2,
        )
        gap = round(target_deduction - actual_deduction, 2)
        if gap > 0.1:
            # Final balancing entry if rubric gap items were insufficient.
            step_id = _infer_step_id("풀이 중간 구간", report.steps) or "s1"
            mistakes.append(
                {
                    "type": MistakeType.logic_gap.value,
                    "severity": Severity.med.value if gap < 1.0 else Severity.high.value,
                    "points_deducted": round(_clamp(gap, 0.1, 2.0), 2),
                    "evidence": _format_provenance_evidence(
                        step_id=step_id,
                        rule="RULE_SCORE_BALANCE",
                        reason="루브릭 총점 대비 누락된 감점 요인 보완",
                    ),
                    "fix_instruction": "핵심 논리/계산/최종답 검증을 단계별로 다시 점검하세요.",
                    "location_hint": "풀이 중간 구간",
                    "highlight": {"mode": "ocr_box", "shape": "box"},
                }
            )

    mistakes = _normalize_deductions_to_target(mistakes, target_deduction)
    mistakes.sort(key=lambda item: _to_float(item.get("points_deducted")) or 0.0, reverse=True)
    result["mistakes"] = mistakes[:20]
    total_deduction = _round_to_tenth(
        sum((_to_float(item.get("points_deducted")) or 0.0) for item in result["mistakes"])
    )
    result["score_total"] = _round_to_tenth(10.0 - total_deduction)


def _build_rubric_gap_mistakes(
    result: dict[str, Any],
    report: VerificationReport,
    gap: float,
) -> list[dict[str, Any]]:
    rubric = result.get("rubric_scores")
    if not isinstance(rubric, dict):
        return []

    dims = [
        ("conditions", MistakeType.condition_missed.value, "RULE_RUBRIC_CONDITIONS", "조건 반영"),
        ("modeling", MistakeType.definition_confusion.value, "RULE_RUBRIC_MODELING", "식 세우기"),
        ("logic", MistakeType.logic_gap.value, "RULE_RUBRIC_LOGIC", "논리 전개"),
        ("calculation", MistakeType.arithmetic_error.value, "RULE_RUBRIC_CALC", "계산"),
        ("final", MistakeType.final_form_error.value, "RULE_RUBRIC_FINAL", "최종 답 검산"),
    ]
    deficits: list[tuple[str, str, str, str, float]] = []
    for key, mtype, rule, label in dims:
        value = _to_float(rubric.get(key)) or 0.0
        deficit = round(_clamp(2.0 - value, 0.0, 2.0), 3)
        if deficit > 0.05:
            deficits.append((key, mtype, rule, label, deficit))

    if not deficits:
        return []

    deficit_sum = sum(item[4] for item in deficits)
    scale = gap / deficit_sum if deficit_sum > 0 else 0.0
    additions: list[dict[str, Any]] = []

    for idx, (key, mtype, rule, label, deficit) in enumerate(deficits, start=1):
        points = round(_clamp(deficit * scale, 0.0, 2.0), 2)
        if points < 0.1:
            continue
        step_id = _default_step_for_dimension(key, report.steps, idx)
        location_hint = _default_location_for_dimension(key)
        severity = (
            Severity.high.value if points >= 1.2 else Severity.med.value if points >= 0.6 else Severity.low.value
        )
        additions.append(
            {
                "type": mtype,
                "severity": severity,
                "points_deducted": points,
                "evidence": _format_provenance_evidence(
                    step_id=step_id,
                    rule=rule,
                    reason=f"{label} 루브릭 점수 부족으로 감점",
                ),
                "fix_instruction": f"{label} 관련 줄을 다시 전개해 감점 요인을 수정하세요.",
                "location_hint": location_hint,
                "highlight": {"mode": "ocr_box", "shape": "box"},
            }
        )
    return additions


def _normalize_deductions_to_target(
    mistakes: list[dict[str, Any]],
    target_deduction: float,
) -> list[dict[str, Any]]:
    if not mistakes:
        return []

    target_units = int(round(_round_to_tenth(_clamp(target_deduction, 0.0, 10.0)) * 10))
    if target_units <= 0:
        return []

    normalized = [dict(item) for item in mistakes if isinstance(item, dict)]
    if not normalized:
        return []

    while len(normalized) * 20 < target_units and len(normalized) < 20:
        normalized.append(
            {
                "type": MistakeType.logic_gap.value,
                "severity": Severity.high.value,
                "points_deducted": 1.0,
                "evidence": _format_provenance_evidence(
                    step_id="s0",
                    rule="RULE_SCORE_BALANCE",
                    reason="점수 총합 정규화를 위한 감점 분배",
                ),
                "fix_instruction": "핵심 줄의 전개를 순서대로 다시 확인하세요.",
                "location_hint": "풀이 중간 구간",
                "highlight": {"mode": "ocr_box", "shape": "box"},
            }
        )

    weights: list[float] = []
    for item in normalized:
        points = _to_float(item.get("points_deducted")) or 0.0
        weights.append(max(points, 0.1))

    raw_alloc = _allocate_weighted_with_cap(weights, target_units / 10.0, cap=2.0)
    point_units = [max(0, int(math.floor(value * 10 + 1e-9))) for value in raw_alloc]
    used_units = sum(point_units)
    deficit_units = target_units - used_units

    if deficit_units > 0:
        order = sorted(
            range(len(normalized)),
            key=lambda idx: ((raw_alloc[idx] * 10.0) - point_units[idx], weights[idx], -idx),
            reverse=True,
        )
        while deficit_units > 0:
            moved = False
            for idx in order:
                if point_units[idx] >= 20:
                    continue
                point_units[idx] += 1
                deficit_units -= 1
                moved = True
                if deficit_units <= 0:
                    break
            if not moved:
                break
    elif deficit_units < 0:
        overflow_units = -deficit_units
        order = sorted(
            range(len(normalized)),
            key=lambda idx: (point_units[idx], weights[idx], idx),
        )
        while overflow_units > 0:
            moved = False
            for idx in order:
                if point_units[idx] <= 0:
                    continue
                point_units[idx] -= 1
                overflow_units -= 1
                moved = True
                if overflow_units <= 0:
                    break
            if not moved:
                break

    output: list[dict[str, Any]] = []
    for idx, item in enumerate(normalized):
        points = _round_to_tenth(_clamp(point_units[idx] / 10.0, 0.0, 2.0))
        if points < 0.1:
            continue
        item["points_deducted"] = points
        inferred_severity = (
            Severity.high.value if points >= 1.2 else Severity.med.value if points >= 0.6 else Severity.low.value
        )
        item["severity"] = _higher_severity(item.get("severity"), inferred_severity)
        output.append(item)

    # Keep a non-empty deduction list when target_deduction is positive.
    if not output and target_units > 0:
        fallback_points = _round_to_tenth(min(2.0, target_units / 10.0))
        output.append(
            {
                "type": MistakeType.logic_gap.value,
                "severity": Severity.high.value if fallback_points >= 1.2 else Severity.med.value,
                "points_deducted": fallback_points,
                "evidence": _format_provenance_evidence(
                    step_id="s0",
                    rule="RULE_SCORE_BALANCE",
                    reason="점수 총합 정규화를 위한 최소 감점 항목",
                ),
                "fix_instruction": "핵심 줄의 논리 전개를 다시 확인하세요.",
                "location_hint": "풀이 중간 구간",
                "highlight": {"mode": "ocr_box", "shape": "box"},
            }
        )
    return output[:20]


def _allocate_weighted_with_cap(weights: list[float], target: float, cap: float) -> list[float]:
    if not weights:
        return []
    count = len(weights)
    safe_cap = max(0.0, cap)
    remaining_target = _clamp(target, 0.0, safe_cap * count)
    allocations = [0.0 for _ in range(count)]
    remaining = list(range(count))

    while remaining and remaining_target > 1e-9:
        weight_sum = sum(max(weights[idx], 0.0) for idx in remaining)
        if weight_sum <= 1e-9:
            share = remaining_target / len(remaining)
            for idx in remaining:
                allocations[idx] = min(safe_cap, share)
            break

        saturated: list[int] = []
        for idx in remaining:
            proportional = remaining_target * (max(weights[idx], 0.0) / weight_sum)
            if proportional >= safe_cap - 1e-9:
                allocations[idx] = safe_cap
                saturated.append(idx)

        if saturated:
            remaining_target = max(0.0, remaining_target - safe_cap * len(saturated))
            remaining = [idx for idx in remaining if idx not in saturated]
            continue

        for idx in remaining:
            allocations[idx] = remaining_target * (max(weights[idx], 0.0) / weight_sum)
        remaining_target = 0.0

    return allocations


def _default_step_for_dimension(key: str, steps: list[ExtractedStep], fallback_idx: int) -> str:
    if steps:
        if key == "final":
            return steps[-1].step_id
        if key in {"conditions", "modeling"}:
            return steps[0].step_id
        if key == "calculation":
            return steps[min(len(steps) - 1, max(1, len(steps) // 2))].step_id
        return steps[min(len(steps) - 1, max(0, len(steps) // 2))].step_id
    # Pseudo step ids keep OCR box mapping stable even without parsed steps.
    return f"s{min(max(fallback_idx, 1), 6)}"


def _default_location_for_dimension(key: str) -> str:
    mapping = {
        "conditions": "첫 줄(조건 해석)",
        "modeling": "식 세우는 줄",
        "logic": "중간 전개 줄",
        "calculation": "계산 줄",
        "final": "최종 답 줄",
    }
    return mapping.get(key, "풀이 중간 구간")


def _format_provenance_evidence(
    step_id: str,
    rule: str,
    reason: str,
    counterexample: str | None = None,
) -> str:
    body = f"근거: {_clean_text(reason, '근거 부족으로 자동 감점을 보류했습니다.', 160)}"
    if counterexample:
        body = f"{body} 반례: {_clean_text(counterexample, '', 60)}"
    return _clean_text(f"[step:{step_id}][rule:{rule}] {body}", body, 240)


def _parse_provenance(evidence: Any) -> tuple[str | None, str | None, str]:
    text = _clean_text(evidence, "", 240)
    if not text:
        return None, None, ""
    match = _PROVENANCE_PATTERN.match(text)
    if not match:
        return None, None, text
    step_id = _clean_text(match.group("step"), "", 20)
    rule = _clean_text(match.group("rule"), "", 40)
    body = _clean_text(match.group("body"), "", 180)
    return step_id or None, rule or None, body


def _infer_step_id(location_hint: Any, steps: list[ExtractedStep]) -> str | None:
    if not steps:
        return None
    hint = _clean_text(location_hint, "", 120).lower()
    if not hint:
        return steps[-1].step_id
    if "마지막" in hint or "최종" in hint:
        return steps[-1].step_id
    if "첫" in hint:
        return steps[0].step_id
    if "두" in hint and len(steps) >= 2:
        return steps[1].step_id
    if "세" in hint and len(steps) >= 3:
        return steps[2].step_id

    hint_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", hint))
    if not hint_tokens:
        return steps[-1].step_id

    scored: list[tuple[float, str]] = []
    for step in steps:
        step_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", step.text.lower()))
        if not step_tokens:
            continue
        overlap = len(hint_tokens.intersection(step_tokens))
        union = len(hint_tokens.union(step_tokens))
        if union <= 0:
            continue
        scored.append((overlap / union, step.step_id))
    if not scored:
        return steps[-1].step_id
    scored.sort(reverse=True)
    return scored[0][1]


def _default_rule_for_mistake_type(mtype: str) -> str:
    normalized = mtype.strip().upper()
    rule_map = {
        MistakeType.final_form_error.value: "RULE_FINAL_SUBSTITUTION",
        MistakeType.sign_error.value: "RULE_EQUIV_TRANSFORM",
        MistakeType.arithmetic_error.value: "RULE_EQUIV_TRANSFORM",
        MistakeType.algebra_error.value: "RULE_EQUIV_TRANSFORM",
        MistakeType.logic_gap.value: "RULE_EQUIV_TRANSFORM",
    }
    return rule_map.get(normalized, "RULE_GENERAL_CONSISTENCY")


def _has_actionable_reason(reason: str) -> bool:
    cleaned = _clean_text(reason, "", 180)
    if len(cleaned) < 8:
        return False
    return cleaned not in _DEFAULT_GENERIC_EVIDENCE


def _normalize_severity(value: Any) -> str:
    if isinstance(value, Severity):
        return value.value
    text = str(value or "").strip().lower()
    if text.startswith("severity."):
        text = text.split(".", 1)[1]
    if text in {Severity.low.value, Severity.med.value, Severity.high.value}:
        return text
    return Severity.low.value


def _normalize_answer_verdict(value: Any) -> str:
    if isinstance(value, AnswerVerdict):
        return value.value
    if isinstance(value, bool):
        return AnswerVerdict.correct.value if value else AnswerVerdict.incorrect.value
    text = str(value or "").strip().lower()
    alias_map = {
        "correct": AnswerVerdict.correct.value,
        "맞음": AnswerVerdict.correct.value,
        "정답": AnswerVerdict.correct.value,
        "true": AnswerVerdict.correct.value,
        "incorrect": AnswerVerdict.incorrect.value,
        "틀림": AnswerVerdict.incorrect.value,
        "오답": AnswerVerdict.incorrect.value,
        "false": AnswerVerdict.incorrect.value,
        "unknown": AnswerVerdict.unknown.value,
        "uncertain": AnswerVerdict.unknown.value,
    }
    return alias_map.get(text, AnswerVerdict.unknown.value)


def _higher_severity(existing: Any, current: Any) -> str:
    existing_value = _normalize_severity(existing)
    current_value = _normalize_severity(current)
    return current_value if _severity_rank(current_value) > _severity_rank(existing_value) else existing_value


def _text_similarity(first: str, second: str) -> float:
    first_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", first.lower()))
    second_tokens = set(re.findall(r"[0-9a-zA-Z가-힣]+", second.lower()))
    if not first_tokens and not second_tokens:
        return 1.0
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens.intersection(second_tokens)) / len(first_tokens.union(second_tokens))


def _make_review_placeholder() -> dict[str, Any]:
    return {
        "type": MistakeType.logic_gap.value,
        "severity": Severity.low.value,
        "points_deducted": 0.0,
        "evidence": _format_provenance_evidence(
            step_id="s0",
            rule="RULE_REVIEW_REQUIRED",
            reason="자동 판정 근거가 부족해 감점을 보류했습니다.",
        ),
        "fix_instruction": "핵심 줄의 식 변형을 한 줄씩 확인해 검토하세요.",
        "location_hint": "전체 풀이",
        "highlight": {"mode": "ocr_box", "shape": "box"},
    }


def _load_fallback_result() -> dict[str, Any]:
    path = settings.fallback_path
    if not path.exists():
        raise RuntimeError(f"Fallback file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _validate_result(payload)


def _inject_ocr_hints(result: dict[str, Any], image_path: str) -> None:
    if not Path(image_path).exists():
        return
    mistake_count = len(result.get("mistakes", []))
    boxes = suggest_ocr_boxes(image_path, max_boxes=max(mistake_count, 6))
    boxes = _collapse_same_line_boxes(boxes)
    if not boxes:
        return

    fallback_index = 0
    for idx, mistake in enumerate(result.get("mistakes", [])):
        step_id, _, _ = _parse_provenance(mistake.get("evidence"))
        hint_index = _step_id_to_hint_index(step_id, len(boxes))
        if hint_index is None:
            hint_index = min(fallback_index, len(boxes) - 1)
            fallback_index += 1
        hint = boxes[hint_index]
        highlight = dict(mistake.get("highlight") or {})
        if not all(highlight.get(key) is not None for key in ("x", "y", "w", "h")):
            highlight.update(hint)
            mistake["highlight"] = highlight


def _step_id_to_hint_index(step_id: str | None, box_count: int) -> int | None:
    if not step_id or box_count <= 0:
        return None
    match = re.match(r"^[sS](\d+)$", step_id.strip())
    if not match:
        return None
    step_number = int(match.group(1))
    if step_number <= 0:
        return None
    return min(step_number - 1, box_count - 1)


def _collapse_same_line_boxes(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in boxes:
        if not isinstance(raw, dict):
            continue
        x = _to_float(raw.get("x"))
        y = _to_float(raw.get("y"))
        w = _to_float(raw.get("w"))
        h = _to_float(raw.get("h"))
        if x is None or y is None or w is None or h is None:
            continue
        if w <= 0 or h <= 0:
            continue
        normalized.append(
            {
                "mode": "ocr_box",
                "shape": str(raw.get("shape") or "box"),
                "x": _clamp(x, 0.0, 1.0),
                "y": _clamp(y, 0.0, 1.0),
                "w": _clamp(w, 0.02, 1.0),
                "h": _clamp(h, 0.02, 1.0),
            }
        )

    if not normalized:
        return []
    normalized.sort(key=lambda item: item["y"])

    merged: list[dict[str, Any]] = []
    for box in normalized:
        if not merged:
            merged.append(box)
            continue
        prev = merged[-1]
        if _is_same_line_box(prev, box):
            merged[-1] = _merge_box_pair(prev, box)
        else:
            merged.append(box)
    return merged


def _is_same_line_box(first: dict[str, Any], second: dict[str, Any]) -> bool:
    f = _box_bounds(first)
    s = _box_bounds(second)
    if f is None or s is None:
        return False
    fx0, fy0, fx1, fy1 = f
    sx0, sy0, sx1, sy1 = s
    overlap_w = max(0.0, min(fx1, sx1) - max(fx0, sx0))
    min_w = min(fx1 - fx0, sx1 - sx0)
    x_overlap_ratio = overlap_w / min_w if min_w > 1e-9 else 0.0
    overlap_h = max(0.0, min(fy1, sy1) - max(fy0, sy0))
    min_h = min(fy1 - fy0, sy1 - sy0)
    y_overlap_ratio = overlap_h / min_h if min_h > 1e-9 else 0.0
    y_gap = max(0.0, max(fy0, sy0) - min(fy1, sy1))
    return (x_overlap_ratio >= 0.55 and y_overlap_ratio >= 0.18) or (
        x_overlap_ratio >= 0.7 and y_gap <= min_h * 0.1
    )


def _merge_box_pair(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    f = _box_bounds(first)
    s = _box_bounds(second)
    if f is None:
        return second
    if s is None:
        return first
    fx0, fy0, fx1, fy1 = f
    sx0, sy0, sx1, sy1 = s
    x0 = min(fx0, sx0)
    y0 = min(fy0, sy0)
    x1 = max(fx1, sx1)
    y1 = max(fy1, sy1)
    return {
        "mode": "ocr_box",
        "shape": "box",
        "x": round(_clamp((x0 + x1) / 2.0, 0.0, 1.0), 4),
        "y": round(_clamp((y0 + y1) / 2.0, 0.0, 1.0), 4),
        "w": round(_clamp(x1 - x0, 0.02, 1.0), 4),
        "h": round(_clamp(y1 - y0, 0.02, 1.0), 4),
    }


def _box_bounds(box: dict[str, Any]) -> tuple[float, float, float, float] | None:
    x = _to_float(box.get("x"))
    y = _to_float(box.get("y"))
    w = _to_float(box.get("w"))
    h = _to_float(box.get("h"))
    if x is None or y is None or w is None or h is None:
        return None
    if w <= 0 or h <= 0:
        return None
    x0 = _clamp(x - (w / 2.0), 0.0, 1.0)
    y0 = _clamp(y - (h / 2.0), 0.0, 1.0)
    x1 = _clamp(x + (w / 2.0), 0.0, 1.0)
    y1 = _clamp(y + (h / 2.0), 0.0, 1.0)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)

def _normalize_points_by_severity(points: float, severity: str) -> float:
    if severity == Severity.high.value:
        return max(points, 1.0)
    if severity == Severity.med.value:
        return max(points, 0.4)
    # low
    return min(points, 0.8)


def _normalize_highlight_value(key: str, value: float) -> float:
    if key in {"x", "y"}:
        return round(_clamp(value, 0.0, 1.0), 4)
    # w/h
    return round(_clamp(value, 0.02, 1.0), 4)


def _deduplicate_mistakes(mistakes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}

    for mistake in mistakes:
        key = "|".join(
            [
                str(mistake.get("type") or ""),
                _signature_text(mistake.get("location_hint")),
                _signature_text(mistake.get("fix_instruction")),
            ]
        )
        existing_idx = index_by_key.get(key)
        if existing_idx is None:
            index_by_key[key] = len(deduped)
            deduped.append(mistake)
            continue

        existing = deduped[existing_idx]
        existing_points = _to_float(existing.get("points_deducted")) or 0.0
        new_points = _to_float(mistake.get("points_deducted")) or 0.0
        if new_points > existing_points:
            deduped[existing_idx] = mistake

    return deduped[:20]


def _sort_mistakes(mistakes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        mistakes,
        key=lambda item: (
            _severity_rank(str(item.get("severity") or Severity.med.value)),
            _to_float(item.get("points_deducted")) or 0.0,
        ),
        reverse=True,
    )[:20]


def _signature_text(value: Any) -> str:
    text = _clean_text(value, "", 120).lower()
    text = re.sub(r"\d+", "#", text)
    return text


def _build_checklist_from_mistakes(mistakes: list[dict[str, Any]]) -> list[str]:
    ranked = sorted(
        mistakes,
        key=lambda item: (_severity_rank(str(item.get("severity") or "med")), _to_float(item.get("points_deducted")) or 0.0),
        reverse=True,
    )
    checklist: list[str] = []
    for item in ranked:
        instruction = _clean_text(item.get("fix_instruction"), "", 80)
        if instruction and instruction not in checklist:
            checklist.append(instruction)
        if len(checklist) >= 3:
            break
    if not checklist and mistakes:
        fallback = _clean_text(mistakes[0].get("fix_instruction"), "최종 답 검산 수행", 80)
        if fallback:
            checklist.append(fallback)
    return checklist[:3]


def _normalize_fix_instruction(text: str, mistake_type: str) -> str:
    normalized = text.strip()
    if len(normalized) >= 12 and normalized not in {
        "핵심 감점 구간을 한 줄씩 다시 전개해 수정하세요.",
        "수정 필요",
        "다시 풀기",
    }:
        return normalized

    template_map = {
        MistakeType.sign_error.value: "이항과 전개 단계의 부호를 한 줄씩 다시 대조하세요.",
        MistakeType.unit_error.value: "최종 줄과 중간 계산의 단위를 동일 기준으로 정리하세요.",
        MistakeType.condition_missed.value: "문제 조건을 식 옆에 적고 누락 없이 반영하세요.",
        MistakeType.algebra_error.value: "식 전개와 약분을 단계별로 나눠 재계산하세요.",
        MistakeType.final_form_error.value: "최종 답을 원식에 다시 대입해 성립 여부를 확인하세요.",
        MistakeType.logic_gap.value: "단계 간 연결 근거를 한 줄씩 보강하고 점프를 줄이세요.",
    }
    return template_map.get(mistake_type, "핵심 감점 구간을 한 줄씩 다시 전개해 수정하세요.")


def _normalize_location_hint(text: str, mistake_type: str) -> str:
    normalized = text.strip()
    if normalized and normalized not in {"풀이 중간 구간", "해당 부분"}:
        return normalized

    template_map = {
        MistakeType.final_form_error.value: "최종 답 줄",
        MistakeType.unit_error.value: "단위 표기 줄",
        MistakeType.sign_error.value: "이항/부호 처리 줄",
        MistakeType.condition_missed.value: "초기 조건 정리 줄",
    }
    return template_map.get(mistake_type, "풀이 중간 구간")


def _normalize_evidence(text: str, mistake_type: str) -> str:
    normalized = text.strip()
    generic_phrases = {
        "근거가 부족해 보완 설명이 필요합니다.",
        "근거 부족",
        "검토 필요",
    }
    if normalized and normalized not in generic_phrases and len(normalized) >= 10:
        return normalized

    template_map = {
        MistakeType.final_form_error.value: "최종 답이 문제 조건 또는 식 검산 결과와 일치하지 않습니다.",
        MistakeType.sign_error.value: "이항/전개 단계에서 부호 처리 불일치가 보입니다.",
        MistakeType.unit_error.value: "중간 계산과 최종 답의 단위 표기가 일관되지 않습니다.",
        MistakeType.algebra_error.value: "식 전개 또는 약분 과정의 계산 일관성이 부족합니다.",
    }
    return template_map.get(mistake_type, "감점 근거가 명확하지 않아 보수적으로 해석했습니다.")


def _calibrate_confidence(
    base_confidence: float,
    mistakes: list[dict[str, Any]],
    score_total: float,
    missing_info: Any,
) -> float:
    confidence = _clamp(base_confidence, 0.0, 1.0)

    missing_count = 0
    if isinstance(missing_info, list):
        missing_count = len([item for item in missing_info if _clean_text(item, "", 80)])
    confidence -= min(0.32, missing_count * 0.08)

    if not mistakes and score_total < 9.0:
        confidence -= 0.1

    incomplete_highlight_penalty = 0.0
    for item in mistakes:
        if not isinstance(item, dict):
            continue
        highlight = item.get("highlight")
        if not isinstance(highlight, dict):
            continue
        mode = str(highlight.get("mode") or "tap")
        if mode in {"ocr_box", "region_box"} and not all(
            highlight.get(key) is not None for key in ("x", "y", "w", "h")
        ):
            incomplete_highlight_penalty += 0.06
    confidence -= min(0.18, incomplete_highlight_penalty)

    return round(_clamp(confidence, 0.0, 1.0), 2)


def _harmonize_score_with_deductions(payload: dict[str, Any]) -> None:
    mistakes = payload.get("mistakes")
    if not isinstance(mistakes, list):
        return

    deduction_sum = 0.0
    for item in mistakes:
        if not isinstance(item, dict):
            continue
        deduction_sum += _to_float(item.get("points_deducted")) or 0.0

    deduction_score = round(_clamp(10.0 - deduction_sum, 0.0, 10.0), 2)
    score_total = _to_float(payload.get("score_total"))
    if score_total is None:
        payload["score_total"] = deduction_score
        return

    # Keep score and deduction narrative roughly aligned without hard overriding
    # rubric-driven adjustments. Clamp only if wildly inconsistent.
    if abs(score_total - deduction_score) > 3.0:
        payload["score_total"] = round((score_total + deduction_score) / 2.0, 2)


def _reconcile_rubric_with_score(payload: dict[str, Any]) -> None:
    rubric = payload.get("rubric_scores")
    if not isinstance(rubric, dict):
        return

    keys = ("conditions", "modeling", "logic", "calculation", "final")
    values = [_to_float(rubric.get(key)) for key in keys]
    if any(value is None for value in values):
        return

    score_total = _to_float(payload.get("score_total"))
    if score_total is None:
        return

    rubric_sum = sum(value for value in values if value is not None)
    delta = score_total - rubric_sum
    if abs(delta) <= 0.25:
        return

    step = round(delta / 5.0, 3)
    adjusted: dict[str, float] = {}
    for key in keys:
        base = _to_float(rubric.get(key)) or 0.0
        adjusted[key] = round(_clamp(base + step, 0.0, 2.0), 2)

    adjusted_sum = sum(adjusted.values())
    if abs(adjusted_sum - score_total) > 0.4:
        # keep score narrative stable by nudging score toward feasible rubric sum
        payload["score_total"] = round((score_total + adjusted_sum) / 2.0, 2)

    payload["rubric_scores"] = adjusted


def _inject_uncertainty_hint(payload: dict[str, Any]) -> None:
    confidence = _to_float(payload.get("confidence"))
    if confidence is None:
        return
    if confidence >= 0.45:
        return

    missing = payload.get("missing_info")
    if not isinstance(missing, list):
        missing = []

    hint = "필기 가독성이 낮아 일부 단계 판단은 보수적으로 처리했습니다."
    if hint not in missing:
        missing.append(hint)
    payload["missing_info"] = missing[:6]
