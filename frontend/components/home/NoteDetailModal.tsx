"use client";

import { StudyNote } from "@/components/StudyNote";
import { SYSTEM_NOTEBOOK_IDS } from "@/lib/notebooks/storage";
import type { Note, Notebook } from "@/lib/notebooks/types";
import type { AnalysisResult } from "@/lib/types";

type NoteDetailModalProps = {
  note: Note | null;
  notebooks: Notebook[];
  onClose: () => void;
  onMoveNote: (noteId: string, targetNotebookId: string) => void;
  onDeleteNote: (noteId: string) => void;
};

export function NoteDetailModal({ note, notebooks, onClose, onMoveNote, onDeleteNote }: NoteDetailModalProps) {
  if (!note) return null;

  const { fallback_used, error_code, ...snapshotResult } = note.snapshot;
  const studyResult: AnalysisResult = {
    ...snapshotResult,
    missing_info: [],
  };

  return (
    <div
      className="noteDetailBackdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          onClose();
        }
      }}
      role="dialog"
      aria-modal="true"
      tabIndex={-1}
      data-testid="note-detail"
    >
      <div className="noteDetailPanel">
        <div className="noteDetailHeader">
          <h2>노트 상세</h2>
          <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.9rem" }}>
              이동
              <select
                value={note.notebookId}
                onChange={(e) => onMoveNote(note.id, e.target.value)}
                data-testid="note-move-select"
                style={{ padding: "4px", borderRadius: "4px", border: "1px solid #ddd" }}
              >
                {notebooks
                  .filter((nb) => nb.id !== SYSTEM_NOTEBOOK_IDS.TRASH)
                  .map((nb) => (
                    <option key={nb.id} value={nb.id}>
                      {nb.name}
                    </option>
                  ))}
              </select>
            </label>
            <button
              type="button"
              className="ghostBtn"
              style={{ color: "#d32f2f" }}
              onClick={() => onDeleteNote(note.id)}
              data-testid="note-delete"
            >
              삭제
            </button>
            <button type="button" className="ghostBtn" onClick={onClose}>
              닫기
            </button>
          </div>
        </div>
        <div className="noteDetailContent">
          <StudyNote result={studyResult} />
        </div>
      </div>
    </div>
  );
}
