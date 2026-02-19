import React from "react";
import type { AnalysisResult, Mistake, PatchChange } from "@/lib/types";
import styles from "./StudyNote.module.css";

interface StudyNoteProps {
  result: AnalysisResult | null;
}

export function StudyNote({ result }: StudyNoteProps) {
  if (!result) {
    return (
      <div className={styles.container}>
        <p className={styles.emptyState}>No analysis result available.</p>
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
        <h1 className={styles.title}>Study Note</h1>
        <div className={styles.score}>
          {score_total != null ? score_total.toFixed(1) : "-"} <span style={{ fontSize: "1rem", fontWeight: 400 }}>/ 10</span>
        </div>
      </header>
      <p className={styles.emptyState}>
        {answer_verdict === "correct" ? "정답" : answer_verdict === "incorrect" ? "오답" : "판정보류"} · {answer_verdict_reason}
      </p>

      {/* Rubric Breakdown */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <span>Rubric Breakdown</span>
        </div>
        <div className={styles.rubricGrid}>
          <RubricItem label="Conditions" value={rubric_scores?.conditions} />
          <RubricItem label="Modeling" value={rubric_scores?.modeling} />
          <RubricItem label="Logic" value={rubric_scores?.logic} />
          <RubricItem label="Calculation" value={rubric_scores?.calculation} />
          <RubricItem label="Final Answer" value={rubric_scores?.final} />
        </div>
      </section>

      {/* Mistakes */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <span>Mistakes Identified</span>
          <span style={{ fontSize: "0.8em", color: "#888", fontWeight: 400 }}>
            ({mistakes.length})
          </span>
        </div>
        
        {mistakes.length === 0 ? (
          <p className={styles.emptyState}>No mistakes found. Great job!</p>
        ) : (
          <div className={styles.mistakeList}>
            {mistakes.map((mistake, index) => (
              <MistakeCard 
                key={mistake.mistake_id ?? index} 
                mistake={mistake} 
              />
            ))}
          </div>
        )}
      </section>

      {/* Patch */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <span>Recommended Patch</span>
        </div>
        <div className={styles.patchContainer}>
          {patch?.patched_solution_brief ? (
             <p className={styles.patchBrief}>&ldquo;{patch.patched_solution_brief}&rdquo;</p>
          ) : (
             <p className={styles.emptyState}>No patch summary available.</p>
          )}

          {patch?.minimal_changes?.length > 0 ? (
            <div className={styles.changeList}>
              {patch.minimal_changes.map((change, index) => (
                <PatchChangeItem key={index} change={change} />
              ))}
            </div>
          ) : (
             <p className={styles.emptyState}>No specific changes recommended.</p>
          )}
        </div>
      </section>

      {/* Checklist */}
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <span>Next Checklist</span>
        </div>
        {next_checklist.length === 0 ? (
          <p className={styles.emptyState}>No checklist items provided.</p>
        ) : (
          <ul className={styles.checklist}>
            {next_checklist.map((item, index) => (
              <li key={index} className={styles.checklistItem}>
                <div className={styles.checkbox} />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      
      {/* Footer / Meta */}
      <div style={{ textAlign: "right", fontSize: "0.75rem", color: "#aaa", marginTop: "2rem" }}>
        Confidence: {confidence != null ? (confidence * 100).toFixed(0) : 0}%
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
      ? "On hold"
      : `-${points != null ? points.toFixed(1) : "?"} pts`;

  return (
    <div className={styles.mistakeCard}>
      <div className={styles.mistakeHeader}>
        <span className={styles.mistakeType}>{mistake.type}</span>
        <span className={styles.mistakeDeduction}>{deductionLabel}</span>
      </div>
      <div className={styles.mistakeDetails}>
        <div><strong>Fix:</strong> {mistake.fix_instruction}</div>
        
        <div className={styles.mistakeDetailRow}>
           <span className={styles.detailLabel}>Evidence:</span>
           <span>{mistake.evidence}</span>
        </div>
        {mistake.location_hint && (
           <div className={styles.mistakeDetailRow}>
              <span className={styles.detailLabel}>Loc:</span>
              <span>{mistake.location_hint}</span>
           </div>
        )}
      </div>
    </div>
  );
}

function PatchChangeItem({ change }: { change: PatchChange }) {
  return (
    <div className={styles.changeItem}>
      <div className={styles.changeText}>{change.change}</div>
      <div className={styles.changeRationale}>{change.rationale}</div>
    </div>
  );
}
