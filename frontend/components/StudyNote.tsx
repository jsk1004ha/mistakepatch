import React from "react";
import type { AnalysisResult, Mistake, PatchChange } from "@/lib/types";
import { formatMistakeType } from "@/lib/mistakeTypeLabels";
import { MathText } from "@/components/MathText";
import styles from "./StudyNote.module.css";

interface StudyNoteProps {
  result: AnalysisResult | null;
}

export function StudyNote({ result }: StudyNoteProps) {
  if (!result) {
    return (
      <div className={styles.container}>
        <p className={styles.emptyState}>분석 결과가 없습니다.</p>
      </div>
    );
  }

  const {
    score_total,
    rubric_scores,
    mistakes = [],
    patch,
    next_checklist = [],
    confidence,
    answer_verdict,
    answer_verdict_reason,
  } = result;

  return (
    <div className={styles.container}>
      {/* Header */}
      <header className={styles.header}>
        <h1 className={styles.title}>학습 노트</h1>
        <div className={styles.score}>
          {score_total != null ? score_total.toFixed(1) : "-"} <span style={{ fontSize: "1rem", fontWeight: 400 }}>/ 10</span>
        </div>
      </header>
      <p className={styles.emptyState}>
        {answer_verdict === "correct" ? "정답" : answer_verdict === "incorrect" ? "오답" : "판정보류"} ·{" "}
        <MathText text={answer_verdict_reason} />
      </p>

      {/* Rubric Breakdown */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <span>루브릭 점수</span>
        </div>
        <div className={styles.rubricGrid}>
          <RubricItem label="조건" value={rubric_scores?.conditions} />
          <RubricItem label="모델링" value={rubric_scores?.modeling} />
          <RubricItem label="논리" value={rubric_scores?.logic} />
          <RubricItem label="계산" value={rubric_scores?.calculation} />
          <RubricItem label="최종 답" value={rubric_scores?.final} />
        </div>
      </section>

      {/* Mistakes */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <span>감점 포인트</span>
          <span style={{ fontSize: "0.8em", color: "#888", fontWeight: 400 }}>
            ({mistakes.length})
          </span>
        </div>
        
        {mistakes.length === 0 ? (
          <p className={styles.emptyState}>실수가 발견되지 않았어요. 잘했어요!</p>
        ) : (
          <div className={styles.mistakeList}>
            {mistakes.map((mistake) => (
              <MistakeCard 
                key={
                  mistake.mistake_id ??
                  `${mistake.type}-${mistake.location_hint ?? ""}-${mistake.points_deducted ?? ""}-${mistake.evidence ?? ""}`
                }
                mistake={mistake} 
              />
            ))}
          </div>
        )}
      </section>

      {/* Patch */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <span>패치 제안</span>
        </div>
        <div className={styles.patchContainer}>
          {patch?.patched_solution_brief ? (
             <p className={styles.patchBrief}>
               &ldquo;<MathText text={patch.patched_solution_brief} />&rdquo;
             </p>
          ) : (
             <p className={styles.emptyState}>패치 요약이 없습니다.</p>
          )}

          {patch?.minimal_changes?.length > 0 ? (
            <div className={styles.changeList}>
              {patch.minimal_changes.map((change) => (
                <PatchChangeItem key={`${change.change}-${change.rationale}`} change={change} />
              ))}
            </div>
          ) : (
             <p className={styles.emptyState}>추천 변경사항이 없습니다.</p>
          )}
        </div>
      </section>

      {/* Checklist */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <span>다음 체크리스트</span>
        </div>
        {next_checklist.length === 0 ? (
          <p className={styles.emptyState}>체크리스트가 없습니다.</p>
        ) : (
          <ul className={styles.checklist}>
            {next_checklist.map((item) => (
              <li key={item} className={styles.checklistItem}>
                <div className={styles.checkbox} />
                <span>
                  <MathText text={item} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      
      {/* Footer / Meta */}
      <div style={{ textAlign: "right", fontSize: "0.75rem", color: "#aaa", marginTop: "2rem" }}>
        신뢰도: {confidence != null ? (confidence * 100).toFixed(0) : 0}%
      </div>
    </div>
  );
}

function RubricItem({ label, value }: { label: string; value?: number }) {
  return (
    <div className={styles.rubricItem}>
      <span className={styles.rubricLabel}>{label}</span>
      <span className={styles.rubricValue}>{value != null ? value : "-"}</span>
    </div>
  );
}

function MistakeCard({ mistake }: { mistake: Mistake }) {
  const points = mistake.points_deducted;
  const deductionLabel =
    typeof points === "number" && Number.isFinite(points) && Math.abs(points) < 0.05
      ? "보류"
      : `-${points != null ? points.toFixed(1) : "?"}점`;

  return (
      <div className={styles.mistakeCard}>
        <div className={styles.mistakeHeader}>
          <span className={styles.mistakeType} title={mistake.type}>
            {formatMistakeType(mistake.type)}
          </span>
          <span className={styles.mistakeDeduction}>{deductionLabel}</span>
        </div>
      <div className={styles.mistakeDetails}>
        <div>
          <strong>수정:</strong> <MathText text={mistake.fix_instruction} />
        </div>
        
        <div className={styles.mistakeDetailRow}>
           <span className={styles.detailLabel}>근거:</span>
           <span>
             <MathText text={mistake.evidence} />
           </span>
        </div>
        {mistake.location_hint && (
           <div className={styles.mistakeDetailRow}>
              <span className={styles.detailLabel}>위치:</span>
              <span>
                <MathText text={mistake.location_hint} />
              </span>
           </div>
        )}
      </div>
    </div>
  );
}

function PatchChangeItem({ change }: { change: PatchChange }) {
  return (
    <div className={styles.changeItem}>
      <div className={styles.changeText}>
        <MathText text={change.change} />
      </div>
      <div className={styles.changeRationale}>
        <MathText text={change.rationale} />
      </div>
    </div>
  );
}
