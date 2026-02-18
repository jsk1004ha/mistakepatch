from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, conlist, confloat


class Subject(str, Enum):
    math = "math"
    physics = "physics"


class HighlightMode(str, Enum):
    tap = "tap"
    ocr_box = "ocr_box"
    region_box = "region_box"


class HighlightShape(str, Enum):
    circle = "circle"
    box = "box"


class Severity(str, Enum):
    low = "low"
    med = "med"
    high = "high"


class MistakeType(str, Enum):
    condition_missed = "CONDITION_MISSED"
    sign_error = "SIGN_ERROR"
    unit_error = "UNIT_ERROR"
    definition_confusion = "DEFINITION_CONFUSION"
    algebra_error = "ALGEBRA_ERROR"
    logic_gap = "LOGIC_GAP"
    case_miss = "CASE_MISS"
    graph_misread = "GRAPH_MISREAD"
    arithmetic_error = "ARITHMETIC_ERROR"
    final_form_error = "FINAL_FORM_ERROR"


class AnalysisMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: Subject = Subject.math
    highlight_mode: HighlightMode = HighlightMode.tap


class Highlight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: HighlightMode = HighlightMode.tap
    shape: HighlightShape = HighlightShape.circle
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None


class Mistake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mistake_id: str | None = None
    type: MistakeType
    severity: Severity
    points_deducted: confloat(ge=0, le=2)
    evidence: str = Field(min_length=1, max_length=240)
    fix_instruction: str = Field(min_length=1, max_length=240)
    location_hint: str = Field(min_length=1, max_length=120)
    highlight: Highlight = Field(default_factory=Highlight)


class RubricScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conditions: confloat(ge=0, le=2)
    modeling: confloat(ge=0, le=2)
    logic: confloat(ge=0, le=2)
    calculation: confloat(ge=0, le=2)
    final: confloat(ge=0, le=2)


class PatchChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change: str = Field(min_length=1, max_length=220)
    rationale: str = Field(min_length=1, max_length=160)


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimal_changes: conlist(PatchChange, min_length=1, max_length=6)
    patched_solution_brief: str = Field(min_length=1, max_length=600)


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score_total: confloat(ge=0, le=10)
    rubric_scores: RubricScores
    mistakes: conlist(Mistake, min_length=0, max_length=20)
    patch: Patch
    next_checklist: conlist(str, min_length=1, max_length=3)
    confidence: confloat(ge=0, le=1)
    missing_info: list[str] = Field(default_factory=list, max_length=6)


class AnalyzeStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    done = "done"
    failed = "failed"


class ProgressStep(str, Enum):
    upload_complete = "upload_complete"
    ocr_analyzing = "ocr_analyzing"
    ai_grading = "ai_grading"
    completed = "completed"
    failed = "failed"


class AnalyzeResponse(BaseModel):
    analysis_id: str
    status: AnalyzeStatus
    result: AnalysisResult | None = None


class AnalyzeDetailResponse(BaseModel):
    analysis_id: str
    submission_id: str
    status: AnalyzeStatus
    progress_step: ProgressStep
    progress_percent: int = Field(ge=0, le=100)
    progress_message: str | None = None
    subject: Subject
    solution_image_url: str
    problem_image_url: str | None = None
    result: AnalysisResult | None = None
    fallback_used: bool = False
    error_code: str | None = None
    created_at: str
    updated_at: str


class AnnotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    mistake_id: str
    mode: HighlightMode
    shape: HighlightShape = HighlightShape.circle
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None


class AnnotationResponse(BaseModel):
    annotation_id: str
    analysis_id: str
    mistake_id: str


class HistoryItem(BaseModel):
    analysis_id: str
    subject: Subject
    score_total: float | None = None
    status: AnalyzeStatus
    top_tag: MistakeType | None = None
    created_at: str


class TopTagCount(BaseModel):
    type: MistakeType
    count: int


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    top_tags: list[TopTagCount]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    queue_mode: Literal["redis", "background"]
    enable_ocr_hints: bool
