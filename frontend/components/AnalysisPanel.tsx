"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
  type TouchEvent,
} from "react";
import Image from "next/image";

import { getAnalysisEventsUrl, toAbsoluteImageUrl } from "@/lib/api";
import { formatMistakeType } from "@/lib/mistakeTypeLabels";
import type {
  AnswerVerdict,
  AnalysisDetail,
  AnalysisProgressEvent,
  AnnotationPayload,
  Mistake,
  ProgressStep,
} from "@/lib/types";
import { MathText } from "@/components/MathText";

type ResultTab = "mistakes" | "patch" | "checklist";
type CompareMode = "slider" | "overlay";

interface AnalysisPanelProps {
  analysis: AnalysisDetail;
  onReload: () => Promise<void>;
  onCreateAnnotation: (payload: AnnotationPayload) => Promise<void>;
}

interface ProgressViewState {
  step: ProgressStep;
  percent: number;
  message: string;
}

const STEP_SEQUENCE: Array<{ step: Exclude<ProgressStep, "failed">; label: string }> = [
  { step: "upload_complete", label: "이미지 업로드 완료" },
  { step: "ocr_analyzing", label: "OCR 분석 중" },
  { step: "ai_grading", label: "AI 채점 중" },
  { step: "completed", label: "완료" },
];

const STEP_LABEL: Record<ProgressStep, string> = {
  upload_complete: "이미지 업로드 완료",
  ocr_analyzing: "OCR 분석 중",
  ai_grading: "AI 채점 중",
  completed: "분석 완료",
  failed: "분석 실패",
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function hasBox(mistake: Mistake): boolean {
  const h = mistake.highlight;
  if (mistake.points_deducted <= 0.04) return false;
  return (
    typeof h.x === "number" &&
    typeof h.y === "number" &&
    typeof h.w === "number" &&
    typeof h.h === "number"
  );
}

function formatDeductionLabel(points: number): string {
  if (!Number.isFinite(points)) return "-?점";
  const rounded = Math.round(points * 10) / 10;
  if (Math.abs(rounded) < 0.05) return "보류";
  return `-${rounded.toFixed(1)}점`;
}

function formatVerdictLabel(verdict: AnswerVerdict): string {
  if (verdict === "correct") return "정답";
  if (verdict === "incorrect") return "오답";
  return "판정보류";
}

function getFallbackHint(errorCode: string | null): string | null {
  if (!errorCode) return null;
  const normalized = errorCode.toLowerCase();

  const isQuotaIssue =
    normalized.includes("ratelimiterror") &&
    (normalized.includes("quota") ||
      normalized.includes("insufficient_quota") ||
      normalized.includes("billing") ||
      normalized.includes("429"));
  if (isQuotaIssue) {
    return "API 할당량/결제 한도를 확인하세요. OPENAI_ORGANIZATION/OPENAI_PROJECT를 지정하지 않으면 기본 조직으로 과금될 수 있습니다.";
  }

  return null;
}

function isProgressStep(value: unknown): value is ProgressStep {
  return (
    value === "upload_complete" ||
    value === "ocr_analyzing" ||
    value === "ai_grading" ||
    value === "completed" ||
    value === "failed"
  );
}

function parseProgressEvent(rawData: string): AnalysisProgressEvent | null {
  try {
    const parsed: unknown = JSON.parse(rawData);
    if (!parsed || typeof parsed !== "object") return null;

    const record = parsed as Record<string, unknown>;
    const analysisId = record.analysis_id;
    const status = record.status;
    const step = record.progress_step;
    const percent = record.progress_percent;
    const updatedAt = record.updated_at;

    if (typeof analysisId !== "string") return null;
    if (status !== "queued" && status !== "processing" && status !== "done" && status !== "failed") {
      return null;
    }
    if (!isProgressStep(step)) return null;
    if (typeof percent !== "number") return null;
    if (typeof updatedAt !== "string") return null;

    const messageValue = record.progress_message;
    const message = typeof messageValue === "string" ? messageValue : null;

    return {
      analysis_id: analysisId,
      status,
      progress_step: step,
      progress_percent: percent,
      progress_message: message,
      updated_at: updatedAt,
    };
  } catch {
    return null;
  }
}

function resolveProgressState(
  analysis: AnalysisDetail,
  tick: number,
  liveEvent: AnalysisProgressEvent | null,
): ProgressViewState {
  if (liveEvent && liveEvent.analysis_id === analysis.analysis_id) {
    return {
      step: liveEvent.progress_step,
      percent: clamp(Math.round(liveEvent.progress_percent), 0, 100),
      message: liveEvent.progress_message ?? STEP_LABEL[liveEvent.progress_step],
    };
  }

  if (analysis.progress_step && typeof analysis.progress_percent === "number") {
    return {
      step: analysis.progress_step,
      percent: clamp(Math.round(analysis.progress_percent), 0, 100),
      message: analysis.progress_message ?? STEP_LABEL[analysis.progress_step],
    };
  }

  if (analysis.status === "done") {
    return {
      step: "completed",
      percent: 100,
      message: analysis.progress_message ?? STEP_LABEL.completed,
    };
  }

  if (analysis.status === "failed") {
    return {
      step: "failed",
      percent: 100,
      message: analysis.progress_message ?? STEP_LABEL.failed,
    };
  }

  if (analysis.status === "queued") {
    return {
      step: "upload_complete",
      percent: clamp(14 + tick * 2, 12, 30),
      message: STEP_LABEL.upload_complete,
    };
  }

  if (tick < 4) {
    return {
      step: "ocr_analyzing",
      percent: clamp(34 + tick * 6, 34, 58),
      message: STEP_LABEL.ocr_analyzing,
    };
  }

  return {
    step: "ai_grading",
    percent: clamp(58 + (tick - 4) * 3, 58, 96),
    message: STEP_LABEL.ai_grading,
  };
}

export function AnalysisPanel({ analysis, onReload, onCreateAnnotation }: AnalysisPanelProps) {
  const [activeTab, setActiveTab] = useState<ResultTab>("mistakes");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [compareMode, setCompareMode] = useState<CompareMode>("slider");
  const [compareRatio, setCompareRatio] = useState(50);
  const [overlayOpacity, setOverlayOpacity] = useState(70);
  const [progressTick, setProgressTick] = useState(0);
  const [liveProgress, setLiveProgress] = useState<AnalysisProgressEvent | null>(null);
  const [isSseConnected, setIsSseConnected] = useState(false);
  const [streamFallback, setStreamFallback] = useState(false);
  const lastReloadTokenRef = useRef<string | null>(null);

  const result = analysis.result;
  const patchChanges = result?.patch?.minimal_changes ?? [];
  const analysisId = analysis.analysis_id;
  const mistakes = useMemo(() => result?.mistakes ?? [], [result?.mistakes]);
  const displayMistakes = useMemo(() => {
    if (!result) return mistakes;
    if (mistakes.length > 0) return mistakes;

    const inferredPoints = Math.round(Math.max(0, 10 - result.score_total) * 10) / 10;
    if (inferredPoints <= 0.04) return mistakes;

    const firstPatch = patchChanges[0];
    const inferred: Mistake = {
      type: "LOGIC_GAP",
      severity: inferredPoints >= 1.0 ? "med" : "low",
      points_deducted: inferredPoints,
      evidence: result.answer_verdict_reason || "총점 기준 감점이 반영되었습니다.",
      fix_instruction:
        firstPatch?.change || "더 나은 풀이 제안: 패치 탭의 최소 수정안을 확인해 근거를 보강하세요.",
      location_hint: "풀이 중간 구간",
      highlight: { mode: "ocr_box", shape: "box" },
    };
    return [inferred];
  }, [mistakes, patchChanges, result]);
  const activeIndex = selectedIndex >= 0 && selectedIndex < displayMistakes.length ? selectedIndex : 0;
  const selectedMistake = displayMistakes[activeIndex];
  const imageUrl = toAbsoluteImageUrl(analysis.solution_image_url);
  const fallbackHint = getFallbackHint(analysis.error_code);
  const selectedPatchChange =
    patchChanges[activeIndex] ?? patchChanges[0] ?? null;
  const patchPreviewText = selectedPatchChange?.change ?? selectedMistake?.fix_instruction ?? "";
  const patchTextOpacity =
    compareMode === "slider" ? clamp(compareRatio / 100, 0, 1) : clamp(overlayOpacity / 100, 0.1, 1);
  const mistakeTextOpacity =
    compareMode === "slider" ? clamp(1 - compareRatio / 100, 0.2, 1) : 0.95;
  const isAnalyzing = !result && (analysis.status === "queued" || analysis.status === "processing");

  const overlays = useMemo(
    () =>
      displayMistakes
        .map((mistake, index) => ({ mistake, index }))
        .filter(({ mistake }) => hasBox(mistake)),
    [displayMistakes],
  );

  const progressState = useMemo(
    () => resolveProgressState(analysis, progressTick, liveProgress),
    [analysis, liveProgress, progressTick],
  );
  const activeStep = progressState.step === "failed" ? "ai_grading" : progressState.step;
  const activeStepIndex = STEP_SEQUENCE.findIndex((item) => item.step === activeStep);

  const selectedHighlightStyle = useMemo<CSSProperties | null>(() => {
    if (!selectedMistake || !hasBox(selectedMistake)) return null;
    const highlight = selectedMistake.highlight;
    return {
      left: `${(highlight.x ?? 0) * 100}%`,
      top: `${(highlight.y ?? 0) * 100}%`,
      width: `${(highlight.w ?? 0.12) * 100}%`,
      height: `${(highlight.h ?? 0.12) * 100}%`,
    };
  }, [selectedMistake]);

  const compareCalloutStyle = useMemo<CSSProperties | null>(() => {
    if (!selectedMistake || !hasBox(selectedMistake)) return null;
    const highlight = selectedMistake.highlight;
    const left = clamp(((highlight.x ?? 0.5) + (highlight.w ?? 0.12) * 0.55 + 0.02) * 100, 8, 77);
    const top = clamp(((highlight.y ?? 0.5) - (highlight.h ?? 0.12) * 0.45) * 100, 7, 84);
    return {
      left: `${left}%`,
      top: `${top}%`,
    };
  }, [selectedMistake]);

  useEffect(() => {
    void analysisId;
    setProgressTick(0);
    setLiveProgress(null);
    setIsSseConnected(false);
    setStreamFallback(false);
    lastReloadTokenRef.current = null;
  }, [analysisId]);

  useEffect(() => {
    if (selectedIndex < displayMistakes.length) return;
    setSelectedIndex(Math.max(0, displayMistakes.length - 1));
  }, [displayMistakes.length, selectedIndex]);

  useEffect(() => {
    if (!isAnalyzing) return;
    void analysisId;
    const timer = window.setInterval(() => {
      setProgressTick((prev) => prev + 1);
    }, 900);
    return () => window.clearInterval(timer);
  }, [analysisId, isAnalyzing]);

  useEffect(() => {
    if (!isAnalyzing) return;
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      setStreamFallback(true);
      return;
    }

    const stream = new EventSource(getAnalysisEventsUrl(analysisId));
    let closed = false;

    stream.onopen = () => {
      setIsSseConnected(true);
      setStreamFallback(false);
    };

    stream.onmessage = (event) => {
      const nextProgress = parseProgressEvent(event.data);
      if (!nextProgress || nextProgress.analysis_id !== analysisId) return;

      setLiveProgress(nextProgress);

      if (nextProgress.updated_at !== lastReloadTokenRef.current) {
        lastReloadTokenRef.current = nextProgress.updated_at;
        void onReload().catch(() => undefined);
      }

      if (nextProgress.status === "done" || nextProgress.status === "failed") {
        stream.close();
        closed = true;
        setIsSseConnected(false);
      }
    };

    stream.onerror = () => {
      if (!closed) {
        stream.close();
        closed = true;
      }
      setIsSseConnected(false);
      setStreamFallback(true);
    };

    return () => {
      if (!closed) {
        stream.close();
      }
      setIsSseConnected(false);
    };
  }, [analysisId, isAnalyzing, onReload]);

  useEffect(() => {
    if (!isAnalyzing) return;
    void analysisId;
    const intervalMs = isSseConnected ? 4200 : 1600;
    const timer = window.setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void onReload().catch(() => undefined);
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [analysisId, isAnalyzing, isSseConnected, onReload]);

  const handleAnnotationFromPoint = useCallback(
    async (clientX: number, clientY: number, target: HTMLElement, isTouchInput: boolean) => {
      if (!selectedMistake || !selectedMistake.mistake_id) return;
      if (selectedMistake.highlight.mode !== "tap") return;
      if (hasBox(selectedMistake)) return;

      const rect = target.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;

      let x = clientX - rect.left;
      let y = clientY - rect.top;

      if (isTouchInput) {
        const safetyPadding = Math.min(28, Math.max(12, Math.min(rect.width, rect.height) * 0.04));
        x = clamp(x, safetyPadding, rect.width - safetyPadding);
        y = clamp(y, safetyPadding, rect.height - safetyPadding);
      }

      await onCreateAnnotation({
        analysis_id: analysisId,
        mistake_id: selectedMistake.mistake_id,
        mode: "tap",
        shape: "circle",
        x: Number((x / rect.width).toFixed(4)),
        y: Number((y / rect.height).toFixed(4)),
        w: 0.12,
        h: 0.12,
      });
      setNotice("하이라이트 위치를 저장했습니다.");
      await onReload();
    },
    [analysisId, onCreateAnnotation, onReload, selectedMistake],
  );

  const handleImageClick = useCallback(
    async (event: MouseEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return;
      await handleAnnotationFromPoint(event.clientX, event.clientY, event.currentTarget, false);
    },
    [handleAnnotationFromPoint],
  );

  const handleImageTouchStart = useCallback(
    async (event: TouchEvent<HTMLButtonElement>) => {
      if (event.touches.length === 0) return;
      event.preventDefault();
      const touch = event.touches[0];
      await handleAnnotationFromPoint(touch.clientX, touch.clientY, event.currentTarget, true);
    },
    [handleAnnotationFromPoint],
  );

  return (
    <section className="panel resultPanel">
      <div className="resultHeader">
        <h2>채점 결과</h2>
        <span className={`status ${analysis.status}`}>{analysis.status}</span>
      </div>
      {analysis.fallback_used && (
        <>
          <p className="warningText">
            모델 응답 오류로 fallback 결과를 표시했습니다.
            {analysis.error_code ? ` (${analysis.error_code})` : ""}
          </p>
          {fallbackHint && <p className="warningText">{fallbackHint}</p>}
        </>
      )}
      {notice && <p className="okText">{notice}</p>}

      {!result && (
        <div className="analysisProgressCard">
          <div className="analysisProgressTop">
            <strong>{progressState.message}</strong>
            <span>{progressState.percent}%</span>
          </div>
          <div className="progressTrack">
            <span style={{ width: `${progressState.percent}%` }} />
          </div>
          <ol className="stepIndicator">
            {STEP_SEQUENCE.map((item, index) => (
              <li
                key={item.step}
                className={`${index < activeStepIndex ? "done" : ""} ${
                  index === activeStepIndex ? "active" : ""
                }`}
              >
                <span className="stepDot" />
                <span>{item.label}</span>
              </li>
            ))}
          </ol>
          <p className="hintText">
            {isSseConnected
              ? "실시간 진행 상태를 수신 중입니다."
              : streamFallback
                ? "SSE 연결이 없어 자동 폴링으로 상태를 갱신합니다."
                : "분석 상태를 확인 중입니다."}
          </p>
        </div>
      )}
      {result && (
        <div className="resultGrid">
          <div className="imagePane">
            <div className="scoreCard">
              <strong>{result.score_total.toFixed(1)} / 10</strong>
              <span>
                {formatVerdictLabel(result.answer_verdict)} | 신뢰도 {(result.confidence * 100).toFixed(0)}%
              </span>
              <span>
                <MathText text={result.answer_verdict_reason} />
              </span>
            </div>
            <div className="imageWrap">
              <button
                type="button"
                className="analysisImageButton"
                onClick={handleImageClick}
                onTouchStart={handleImageTouchStart}
                aria-label="감점 위치 지정 (클릭/터치)"
              >
                <Image
                  src={imageUrl}
                  alt="풀이"
                  className="analysisImage"
                  width={1600}
                  height={1200}
                  unoptimized
                  style={{ width: "100%", height: "auto" }}
                />
              </button>
              {overlays.map(({ mistake, index }) => {
                const highlight = mistake.highlight;
                return (
                  <span
                    key={`${mistake.mistake_id ?? index}-overlay`}
                    className={`overlay ${highlight.shape ?? "circle"} ${
                      index === activeIndex ? "selected" : ""
                    }`}
                    style={{
                      left: `${(highlight.x ?? 0) * 100}%`,
                      top: `${(highlight.y ?? 0) * 100}%`,
                      width: `${(highlight.w ?? 0.12) * 100}%`,
                      height: `${(highlight.h ?? 0.12) * 100}%`,
                    }}
                  />
                );
              })}
              {activeTab === "patch" && selectedHighlightStyle && (
                <>
                  <span className="compareRegion mistake" style={selectedHighlightStyle} />
                  <span
                    className="compareRegion patch"
                    style={{
                      ...selectedHighlightStyle,
                      opacity: patchTextOpacity,
                    }}
                  />
                </>
              )}
              {activeTab === "patch" && selectedMistake && hasBox(selectedMistake) && compareCalloutStyle && (
                <div className="compareCallout" style={compareCalloutStyle}>
                  <span className="compareTag mistake">감점</span>
                  <p className="compareText mistake" style={{ opacity: mistakeTextOpacity }}>
                    <MathText text={selectedMistake.evidence} />
                  </p>
                  <span className="compareTag patch">패치</span>
                  <p className="compareText patch" style={{ opacity: patchTextOpacity }}>
                    <MathText text={patchPreviewText} />
                  </p>
                  {selectedPatchChange?.rationale && (
                    <p className="compareRationale">
                      <MathText text={selectedPatchChange.rationale} />
                    </p>
                  )}
                </div>
              )}
            </div>
            {selectedMistake && selectedMistake.highlight.mode === "tap" && !hasBox(selectedMistake) && (
              <p className="hintText">선택된 감점 카드의 위치를 이미지에서 탭하세요. (터치 보정 적용)</p>
            )}
          </div>

          <div className="detailPane">
            <div className="tabRow">
              <button
                type="button"
                className={activeTab === "mistakes" ? "active" : ""}
                onClick={() => setActiveTab("mistakes")}
              >
                감점 포인트
              </button>
              <button
                type="button"
                className={activeTab === "patch" ? "active" : ""}
                onClick={() => setActiveTab("patch")}
              >
                최소 수정 패치
              </button>
              <button
                type="button"
                className={activeTab === "checklist" ? "active" : ""}
                onClick={() => setActiveTab("checklist")}
              >
                체크리스트
              </button>
            </div>

            {activeTab === "mistakes" && (
              <div className="cardList">
                {displayMistakes.length === 0 && (
                    <>
                      <p className="hintText">감점 포인트를 찾지 못했습니다.</p>
                    {patchChanges.length > 0 && (
                      <button type="button" className="ghostBtn" onClick={() => setActiveTab("patch")}>
                        패치 탭으로 이동
                      </button>
                    )}
                  </>
                )}
                {displayMistakes.map((mistake, index) => (
                  <button
                    type="button"
                    key={mistake.mistake_id ?? `${mistake.type}-${index}`}
                    className={`mistakeCard ${index === activeIndex ? "active" : ""}`}
                    onClick={() => setSelectedIndex(index)}
                  >
                    <div className="cardTop">
                      <strong title={mistake.type}>{formatMistakeType(mistake.type)}</strong>
                      <span>{formatDeductionLabel(mistake.points_deducted)}</span>
                    </div>
                    <p>
                      <MathText text={mistake.evidence} />
                    </p>
                    <p className="fixText">
                      <MathText text={mistake.fix_instruction} />
                    </p>
                  </button>
                ))}
              </div>
            )}

            {activeTab === "patch" && (
              <div className="patchBox">
                <div className="compareControls">
                  <button
                    type="button"
                    className={compareMode === "slider" ? "active" : ""}
                    onClick={() => setCompareMode("slider")}
                  >
                    Before / After
                  </button>
                  <button
                    type="button"
                    className={compareMode === "overlay" ? "active" : ""}
                    onClick={() => setCompareMode("overlay")}
                  >
                    Overlay
                  </button>
                </div>
                {compareMode === "slider" && (
                  <label className="compareRange">
                    Mistake ↔ Patch 슬라이더
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={compareRatio}
                      onChange={(event) => setCompareRatio(Number(event.target.value))}
                    />
                  </label>
                )}
                {compareMode === "overlay" && (
                  <label className="compareRange">
                    Patch 오버레이 투명도
                    <input
                      type="range"
                      min={10}
                      max={100}
                      value={overlayOpacity}
                      onChange={(event) => setOverlayOpacity(Number(event.target.value))}
                    />
                  </label>
                )}
                {selectedMistake && hasBox(selectedMistake) ? (
                  <p className="hintText">
                    이미지 위 오버레이에서 Mistake와 Patch를 겹쳐 비교할 수 있습니다.
                  </p>
                ) : (
                  <p className="hintText">
                    비교 뷰를 쓰려면 감점 포인트 위치가 필요합니다. 감점 탭에서 항목을 선택하고 이미지를 탭하세요.
                  </p>
                )}
                {patchChanges.map((change, index) => (
                  <div key={`${index}-${change.change}`} className="patchItem">
                    <strong>
                      <MathText text={change.change} />
                    </strong>
                    <p>
                      <MathText text={change.rationale} />
                    </p>
                  </div>
                ))}
                <p className="patchedBrief">
                  <MathText text={result.patch.patched_solution_brief} />
                </p>
              </div>
            )}

            {activeTab === "checklist" && (
              <ol className="checklist">
                {result.next_checklist.map((item) => (
                  <li key={item}>
                    <MathText text={item} />
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
