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
            "minItems": 1,
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
                        "required": ["mode"],
                        "additionalProperties": False,
                        "properties": {
                            "mode": {"type": "string", "enum": ["tap", "ocr_box", "region_box"]},
                            "shape": {"type": "string", "enum": ["circle", "box"]},
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "w": {"type": "number"},
                            "h": {"type": "number"},
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
    },
}


SYSTEM_PROMPT = """
You are a strict grading assistant for math and physics handwritten solutions.
Return only concise grading feedback in Korean.
Do not provide full final solutions unless needed for minimal correction.
Always output valid JSON following the provided schema.
Prefer minimal patch instructions over long explanations.
If image quality is low, reduce confidence and fill missing_info.
""".strip()

