export type Subject = "math" | "physics";
export type AnalyzeStatus = "queued" | "processing" | "done" | "failed";
export type ProgressStep = "upload_complete" | "ocr_analyzing" | "ai_grading" | "completed" | "failed";
export type HighlightMode = "tap" | "ocr_box" | "region_box";
export type HighlightShape = "circle" | "box";
export type Severity = "low" | "med" | "high";
export type AnswerVerdict = "correct" | "incorrect" | "unknown";

export type MistakeType =
  | "CONDITION_MISSED"
  | "SIGN_ERROR"
  | "UNIT_ERROR"
  | "DEFINITION_CONFUSION"
  | "ALGEBRA_ERROR"
  | "LOGIC_GAP"
  | "CASE_MISS"
  | "GRAPH_MISREAD"
  | "ARITHMETIC_ERROR"
  | "FINAL_FORM_ERROR";

export interface Highlight {
  mode: HighlightMode;
  shape?: HighlightShape;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
}

export interface Mistake {
  type: MistakeType;
  severity: Severity;
  points_deducted: number;
  evidence: string;
  fix_instruction: string;
  location_hint: string;
  highlight: Highlight;
  mistake_id?: string;
}

export interface RubricScores {
  conditions: number;
  modeling: number;
  logic: number;
  calculation: number;
  final: number;
}

export interface PatchChange {
  change: string;
  rationale: string;
}

export interface PatchResult {
  minimal_changes: PatchChange[];
  patched_solution_brief: string;
}

export interface AnalysisResult {
  score_total: number;
  rubric_scores: RubricScores;
  mistakes: Mistake[];
  patch: PatchResult;
  next_checklist: string[];
  confidence: number;
  missing_info: string[];
  answer_verdict: AnswerVerdict;
  answer_verdict_reason: string;
}

export interface AnalyzeQueuedResponse {
  analysis_id: string;
  status: AnalyzeStatus;
  result: AnalysisResult | null;
}

export interface AnalysisDetail {
  analysis_id: string;
  submission_id: string;
  status: AnalyzeStatus;
  progress_step?: ProgressStep;
  progress_percent?: number;
  progress_message?: string | null;
  subject: Subject;
  solution_image_url: string;
  problem_image_url: string | null;
  result: AnalysisResult | null;
  fallback_used: boolean;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnalysisProgressEvent {
  analysis_id: string;
  status: AnalyzeStatus;
  progress_step: ProgressStep;
  progress_percent: number;
  progress_message: string | null;
  updated_at: string;
}

export interface AnnotationPayload {
  analysis_id: string;
  mistake_id: string;
  mode: HighlightMode;
  shape: HighlightShape;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
}

export interface HistoryItem {
  analysis_id: string;
  subject: Subject;
  score_total: number | null;
  status: AnalyzeStatus;
  top_tag: MistakeType | null;
  created_at: string;
}

export interface HistoryResponse {
  items: HistoryItem[];
  top_tags: Array<{ type: MistakeType; count: number }>;
}
