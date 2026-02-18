"use client";

import { useState } from "react";

import type { AnalysisDetail, AnalyzeStatus, Mistake } from "@/lib/types";

type FeedbackTab = "mistakes" | "patch" | "checklist";

interface FloatingFeedbackProps {
  analysis: AnalysisDetail | null;
  isSubmitting: boolean;
  activeTab: FeedbackTab;
  onTabChange: (tab: FeedbackTab) => void;
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
}

function statusText(status: AnalyzeStatus) {
  if (status === "queued" || status === "processing") return "분석 중";
  if (status === "done") return "완료";
  return "실패";
}

function needsTap(mistake: Mistake | undefined) {
  if (!mistake) return false;
  if (mistake.highlight.mode !== "tap") return false;
  return typeof mistake.highlight.x !== "number" || typeof mistake.highlight.y !== "number";
}

export function FloatingFeedback({
  analysis,
  isSubmitting,
  activeTab,
  onTabChange,
  selectedIndex,
  onSelectIndex,
}: FloatingFeedbackProps) {
  const [collapsed, setCollapsed] = useState(false);
  const result = analysis?.result ?? null;
  const mistakes = result?.mistakes ?? [];
  const selectedMistake = mistakes[selectedIndex];

  return (
    <aside className={`floatingFeedback ${collapsed ? "collapsed" : ""}`}>
      <header className="floatingHeader">
        <div>
          <strong>MistakePatch Assistant</strong>
          <span>
            {analysis ? statusText(analysis.status) : isSubmitting ? "분석 요청 중" : "대기"}
          </span>
        </div>
        <button onClick={() => setCollapsed((prev) => !prev)}>{collapsed ? "열기" : "닫기"}</button>
      </header>

      {!collapsed && (
        <div className="floatingBody">
          {!analysis && <p>필기를 작성한 뒤 `채점 실행`을 누르면 피드백이 여기에 표시됩니다.</p>}
          {analysis && !result && <p>분석 중입니다. 잠시만 기다려 주세요.</p>}

          {result && (
            <>
              <div className="floatingScore">
                <strong>{result.score_total.toFixed(1)} / 10</strong>
                <span>confidence {(result.confidence * 100).toFixed(0)}%</span>
              </div>

              {analysis?.fallback_used && (
                <p className="warningText">모델 응답 오류로 fallback 결과가 표시되었습니다.</p>
              )}

              <div className="tabRow">
                <button
                  className={activeTab === "mistakes" ? "active" : ""}
                  onClick={() => onTabChange("mistakes")}
                  data-testid="feedback-tab-mistakes"
                >
                  감점
                </button>
                <button
                  className={activeTab === "patch" ? "active" : ""}
                  onClick={() => onTabChange("patch")}
                  data-testid="feedback-tab-patch"
                >
                  패치
                </button>
                <button
                  className={activeTab === "checklist" ? "active" : ""}
                  onClick={() => onTabChange("checklist")}
                  data-testid="feedback-tab-checklist"
                >
                  체크
                </button>
              </div>

              {activeTab === "mistakes" && (
                <div className="cardList compact">
                  {mistakes.map((mistake, index) => (
                    <button
                      key={mistake.mistake_id ?? `${mistake.type}-${index}`}
                      className={`mistakeCard ${index === selectedIndex ? "active" : ""}`}
                      onClick={() => onSelectIndex(index)}
                      data-testid={`mistake-card-${index}`}
                    >
                      <div className="cardTop">
                        <strong>{mistake.type}</strong>
                        <span>-{mistake.points_deducted.toFixed(1)}점</span>
                      </div>
                      <p>{mistake.fix_instruction}</p>
                    </button>
                  ))}
                  {needsTap(selectedMistake) && (
                    <p className="hintText">현재 선택된 감점 포인트는 필기 화면 탭으로 위치 지정이 필요합니다.</p>
                  )}
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
                </div>
              )}

              {activeTab === "checklist" && (
                <ol className="checklist">
                  {result.next_checklist.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ol>
              )}
            </>
          )}
        </div>
      )}
    </aside>
  );
}
