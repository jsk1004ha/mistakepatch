"use client";

import { useMemo, useState, type MouseEvent } from "react";

import { toAbsoluteImageUrl } from "@/lib/api";
import type { AnalysisDetail, AnnotationPayload, Mistake } from "@/lib/types";

type ResultTab = "mistakes" | "patch" | "checklist";

interface AnalysisPanelProps {
  analysis: AnalysisDetail;
  onReload: () => Promise<void>;
  onCreateAnnotation: (payload: AnnotationPayload) => Promise<void>;
}

function hasBox(mistake: Mistake): boolean {
  const h = mistake.highlight;
  return (
    typeof h.x === "number" &&
    typeof h.y === "number" &&
    typeof h.w === "number" &&
    typeof h.h === "number"
  );
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

export function AnalysisPanel({ analysis, onReload, onCreateAnnotation }: AnalysisPanelProps) {
  const [activeTab, setActiveTab] = useState<ResultTab>("mistakes");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  const result = analysis.result;
  const mistakes = result?.mistakes ?? [];
  const selectedMistake = mistakes[selectedIndex];
  const imageUrl = toAbsoluteImageUrl(analysis.solution_image_url);
  const fallbackHint = getFallbackHint(analysis.error_code);

  const overlays = useMemo(
    () =>
      mistakes
        .map((mistake, index) => ({ mistake, index }))
        .filter(({ mistake }) => hasBox(mistake)),
    [mistakes],
  );

  const handleImageClick = async (event: MouseEvent<HTMLImageElement>) => {
    if (!selectedMistake || !selectedMistake.mistake_id) return;
    if (selectedMistake.highlight.mode !== "tap") return;
    if (hasBox(selectedMistake)) return;

    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;

    await onCreateAnnotation({
      analysis_id: analysis.analysis_id,
      mistake_id: selectedMistake.mistake_id,
      mode: "tap",
      shape: "circle",
      x: Number(x.toFixed(4)),
      y: Number(y.toFixed(4)),
      w: 0.12,
      h: 0.12,
    });
    setNotice("하이라이트 위치를 저장했습니다.");
    await onReload();
  };

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

      {!result && <p>분석 중입니다. 자동으로 결과를 갱신합니다.</p>}
      {result && (
        <div className="resultGrid">
          <div className="imagePane">
            <div className="scoreCard">
              <strong>{result.score_total.toFixed(1)} / 10</strong>
              <span>confidence: {(result.confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="imageWrap">
              <img src={imageUrl} alt="solution" onClick={handleImageClick} />
              {overlays.map(({ mistake, index }) => {
                const highlight = mistake.highlight;
                return (
                  <span
                    key={`${mistake.mistake_id ?? index}-overlay`}
                    className={`overlay ${highlight.shape ?? "circle"} ${
                      index === selectedIndex ? "selected" : ""
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
            </div>
            {selectedMistake && selectedMistake.highlight.mode === "tap" && !hasBox(selectedMistake) && (
              <p className="hintText">선택된 감점 카드의 위치를 이미지에서 한 번 탭하세요.</p>
            )}
          </div>

          <div className="detailPane">
            <div className="tabRow">
              <button
                className={activeTab === "mistakes" ? "active" : ""}
                onClick={() => setActiveTab("mistakes")}
              >
                감점 포인트
              </button>
              <button
                className={activeTab === "patch" ? "active" : ""}
                onClick={() => setActiveTab("patch")}
              >
                최소 수정 패치
              </button>
              <button
                className={activeTab === "checklist" ? "active" : ""}
                onClick={() => setActiveTab("checklist")}
              >
                체크리스트
              </button>
            </div>

            {activeTab === "mistakes" && (
              <div className="cardList">
                {mistakes.map((mistake, index) => (
                  <button
                    key={mistake.mistake_id ?? `${mistake.type}-${index}`}
                    className={`mistakeCard ${index === selectedIndex ? "active" : ""}`}
                    onClick={() => setSelectedIndex(index)}
                  >
                    <div className="cardTop">
                      <strong>{mistake.type}</strong>
                      <span>-{mistake.points_deducted.toFixed(1)}점</span>
                    </div>
                    <p>{mistake.evidence}</p>
                    <p className="fixText">{mistake.fix_instruction}</p>
                  </button>
                ))}
              </div>
            )}

            {activeTab === "patch" && (
              <div className="patchBox">
                {result.patch.minimal_changes.map((change, index) => (
                  <div key={`${index}-${change.change}`} className="patchItem">
                    <strong>{change.change}</strong>
                    <p>{change.rationale}</p>
                  </div>
                ))}
                <p className="patchedBrief">{result.patch.patched_solution_brief}</p>
              </div>
            )}

            {activeTab === "checklist" && (
              <ol className="checklist">
                {result.next_checklist.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

