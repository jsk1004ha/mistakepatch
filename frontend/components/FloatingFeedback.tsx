"use client";

import { useState } from "react";

import type { AnalysisDetail, AnalyzeStatus, Mistake } from "@/lib/types";
import { formatMistakeType } from "@/lib/mistakeTypeLabels";

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
  const isLikelyCorrect = Boolean(result && mistakes.length === 0 && result.score_total >= 9.5);

  return (
    <aside className={`floatingFeedback ${collapsed ? "collapsed" : ""}`}>
      <header className="floatingHeader">
        <div>
          <strong>MistakePatch Assistant</strong>
          <span>
            {analysis ? statusText(analysis.status) : isSubmitting ? "분석 요청 중" : "대기"}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed((prev) => !prev)}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "피드백 패널 열기" : "피드백 패널 접기"}
        >
          {collapsed ? "열기" : "닫기"}
        </button>
      </header>

      {!collapsed && (
        <div className="floatingBody">
          {!analysis && <p>필기를 작성한 뒤 &quot;채점 실행&quot;을 누르면 피드백이 여기에 표시됩니다.</p>}
          {analysis && !result && <p>분석 중입니다. 잠시만 기다려 주세요.</p>}

          {result && (
            <>
              <div className="floatingScore">
                <strong>{result.score_total.toFixed(1)} / 10</strong>
                <span>confidence {(result.confidence * 100).toFixed(0)}%</span>
              </div>
              {isLikelyCorrect && (
                <p className="okText">정답으로 판단했습니다. (자동 감점 포인트 없음)</p>
              )}

              {analysis?.fallback_used && (
                <p className="warningText">
                  모델 응답 오류로 fallback 결과가 표시되었습니다.
                  {analysis.error_code ? ` (${analysis.error_code})` : ""}
                </p>
              )}

              <div className="tabRow">
                <button
                  type="button"
                  className={activeTab === "mistakes" ? "active" : ""}
                  onClick={() => onTabChange("mistakes")}
                  data-testid="feedback-tab-mistakes"
                >
                  감점
                </button>
                <button
                  type="button"
                  className={activeTab === "patch" ? "active" : ""}
                  onClick={() => onTabChange("patch")}
                  data-testid="feedback-tab-patch"
                >
                  패치
                </button>
                <button
                  type="button"
                  className={activeTab === "checklist" ? "active" : ""}
                  onClick={() => onTabChange("checklist")}
                  data-testid="feedback-tab-checklist"
                >
                  체크
                </button>
              </div>

              {activeTab === "mistakes" && (
                <div className="cardList compact">
                  {mistakes.length === 0 && (
                    <p className="hintText">감점 포인트를 찾지 못했습니다. 현재 풀이는 정답으로 판단됩니다.</p>
                  )}
                  {mistakes.map((mistake, index) => (
                    <button
                      type="button"
                      key={mistake.mistake_id ?? `${mistake.type}-${index}`}
                      className={`mistakeCard ${index === selectedIndex ? "active" : ""}`}
                      onClick={() => onSelectIndex(index)}
                      data-testid={`mistake-card-${index}`}
                    >
                      <div className="cardTop">
                        <strong title={mistake.type}>{formatMistakeType(mistake.type)}</strong>
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
