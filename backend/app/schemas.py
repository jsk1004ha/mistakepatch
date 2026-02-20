from __future__ import annotations

from .models import MistakeType


MISTAKE_TYPES = [item.value for item in MistakeType]

ANALYSIS_RESULT_JSON_SCHEMA: dict = {
    "type": "object",
    "required": [
        "score_total",
        "rubric_scores",
        "mistakes",
        "patch",
        "next_checklist",
        "confidence",
        "missing_info",
        "answer_verdict",
        "answer_verdict_reason",
    ],
    "additionalProperties": False,
    "properties": {
        "score_total": {"type": "number", "minimum": 0, "maximum": 10},
        "rubric_scores": {
            "type": "object",
            "required": ["conditions", "modeling", "logic", "calculation", "final"],
            "additionalProperties": False,
            "properties": {
                "conditions": {"type": "number", "minimum": 0, "maximum": 2},
                "modeling": {"type": "number", "minimum": 0, "maximum": 2},
                "logic": {"type": "number", "minimum": 0, "maximum": 2},
                "calculation": {"type": "number", "minimum": 0, "maximum": 2},
                "final": {"type": "number", "minimum": 0, "maximum": 2},
            },
        },
        "mistakes": {
            "type": "array",
            "minItems": 0,
            "maxItems": 20,
            "items": {
                "type": "object",
                "required": [
                    "type",
                    "severity",
                    "points_deducted",
                    "evidence",
                    "fix_instruction",
                    "location_hint",
                    "highlight",
                ],
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "enum": MISTAKE_TYPES},
                    "severity": {"type": "string", "enum": ["low", "med", "high"]},
                    "points_deducted": {"type": "number", "minimum": 0, "maximum": 2},
                    "evidence": {"type": "string", "maxLength": 240},
                    "fix_instruction": {"type": "string", "maxLength": 240},
                    "location_hint": {"type": "string", "maxLength": 120},
                    "highlight": {
                        "type": "object",
                        "required": ["mode", "shape", "x", "y", "w", "h"],
                        "additionalProperties": False,
                        "properties": {
                            "mode": {"type": "string", "enum": ["tap", "ocr_box", "region_box"]},
                            "shape": {"type": "string", "enum": ["circle", "box"]},
                            "x": {"type": ["number", "null"]},
                            "y": {"type": ["number", "null"]},
                            "w": {"type": ["number", "null"]},
                            "h": {"type": ["number", "null"]},
                        },
                    },
                },
            },
        },
        "patch": {
            "type": "object",
            "required": ["minimal_changes", "patched_solution_brief"],
            "additionalProperties": False,
            "properties": {
                "minimal_changes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "required": ["change", "rationale"],
                        "additionalProperties": False,
                        "properties": {
                            "change": {"type": "string", "maxLength": 220},
                            "rationale": {"type": "string", "maxLength": 160},
                        },
                    },
                },
                "patched_solution_brief": {"type": "string", "maxLength": 600},
            },
        },
        "next_checklist": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 80},
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "missing_info": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 80},
        },
        "answer_verdict": {"type": "string", "enum": ["correct", "incorrect", "unknown"]},
        "answer_verdict_reason": {"type": "string", "maxLength": 120},
    },
}


SYSTEM_PROMPT = """
You are MistakePatch, a strict grading assistant for handwritten math/physics solutions.

Core objective:
- Prioritize grading quality and error localization over full tutoring.
- Focus on where points are lost and how to minimally fix them.

Output rules:
- Return ONLY valid JSON that exactly follows the provided schema.
- Do not add markdown, code fences, or extra keys.
- Keep Korean text concise and actionable.

Grading policy:
- Score on a 10-point rubric: conditions, modeling, logic, calculation, final (each 0..2).
- Ensure score_total is consistent with rubric_scores and mistake severities.
- Use mistakes only when there is plausible evidence from the student's work.
- Prefer minimal patch instructions over long explanations.
- Do not provide full final solutions unless needed for a minimal correction.

Verdict policy:
- Set answer_verdict to correct/incorrect/unknown.
- Provide a brief answer_verdict_reason.

Highlight policy:
- Use highlight.mode="tap" when exact region is uncertain.
- Set x/y/w/h to null when you are not confident about exact coordinates.

Confidence policy:
- If handwriting or image quality is low, lower confidence and populate missing_info.
- If critical information is unreadable, avoid over-claiming and mark uncertainty clearly.
""".strip()
