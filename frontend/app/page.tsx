"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { FloatingFeedback } from "@/components/FloatingFeedback";
import { NotebooksDrawer } from "@/components/NotebooksDrawer";
import { NoteCanvas, type NoteCanvasHandle } from "@/components/NoteCanvas";
import { NoteDetailModal } from "@/components/home/NoteDetailModal";
import { UndoToast } from "@/components/UndoToast";
import { useAnalysisFlow } from "@/hooks/useAnalysisFlow";
import { useNotebooksState } from "@/hooks/useNotebooksState";
import { fetchHealth } from "@/lib/api";
import type { HealthResponse } from "@/lib/api";
import { loadState, saveState, SYSTEM_NOTEBOOK_IDS } from "@/lib/notebooks/storage";
import type { Note, NotebooksState } from "@/lib/notebooks/types";
import type { AnalysisDetail, Subject } from "@/lib/types";
import { createNoteId, buildNoteTags, loadAutosavedAnalysisIds, saveAutosavedAnalysisIds } from "@/lib/home/pageUtils";

const AUTOSAVE_TOAST_DURATION_MS = 9000;

type FeedbackTab = "mistakes" | "patch" | "checklist";

export default function HomePage() {
  const canvasRef = useRef<NoteCanvasHandle | null>(null);

  const [subject, setSubject] = useState<Subject>("math");
  const [highlightMode, setHighlightMode] = useState<"tap" | "ocr_box">("tap");
  const [problemImage, setProblemImage] = useState<File | null>(null);
  const [problemPreviewUrl, setProblemPreviewUrl] = useState<string | null>(null);

  const [brushColor, setBrushColor] = useState("#17212a");
  const [brushSize, setBrushSize] = useState(3);
  const [isEraserMode, setIsEraserMode] = useState(false);

  const [backendHealth, setBackendHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<boolean>(false);

  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<FeedbackTab>("mistakes");
  const [selectedIndex, setSelectedIndex] = useState(0);

  const [isNotebooksOpen, setIsNotebooksOpen] = useState(false);
  const {
    notebooksState,
    selectedNotebookId,
    selectedNoteId,
    autosaveToast,
    setNotebooksState,
    setSelectedNotebookId,
    setSelectedNoteId,
    setAutosaveToast,
    handleUndoAutoSavedNote,
    handleMoveAutoSavedNoteToTrash,
    handleCreateNotebook,
    handleRenameNotebook,
    handleReorderNotebook,
    handleDeleteNotebook,
    handleMoveNote,
    handleDeleteNote,
    handleRestoreNote,
    handleEmptyTrash,
  } = useNotebooksState({ setInfo });

  useEffect(() => {
    fetchHealth()
      .then(setBackendHealth)
      .catch(() => setHealthError(true));
  }, []);

  useEffect(() => {
    if (!problemImage) {
      setProblemPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(problemImage);
    setProblemPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [problemImage]);

  const persistAutoSavedNote = useCallback((detail: AnalysisDetail) => {
    if (detail.status !== "done" || !detail.result) return;

    const dedupeIds = loadAutosavedAnalysisIds();
    if (dedupeIds.has(detail.analysis_id)) return;

    const currentState = loadState();
    const alreadySaved = Object.values(currentState.notes).some((note) => note.analysisId === detail.analysis_id);
    if (alreadySaved) {
      dedupeIds.add(detail.analysis_id);
      saveAutosavedAnalysisIds(dedupeIds);
      return;
    }

    const { missing_info: _missingInfo, ...snapshotBase } = detail.result;
    const createdNote: Note = {
      id: createNoteId(),
      analysisId: detail.analysis_id,
      subject: detail.subject,
      createdAt: new Date().toISOString(),
      scoreTotal: detail.result.score_total,
      notebookId: SYSTEM_NOTEBOOK_IDS.INBOX,
      trashedAt: null,
      tags: buildNoteTags(detail),
      snapshot: {
        ...snapshotBase,
        fallback_used: detail.fallback_used,
        error_code: detail.error_code,
      },
    };

    const nextState: NotebooksState = {
      ...currentState,
      notes: {
        ...currentState.notes,
        [createdNote.id]: createdNote,
      },
    };

    try {
      saveState(nextState);
      dedupeIds.add(detail.analysis_id);
      saveAutosavedAnalysisIds(dedupeIds);
      setNotebooksState(nextState);
      setAutosaveToast({ noteId: createdNote.id, analysisId: detail.analysis_id });
      setInfo("분석 완료 노트를 Inbox에 자동 저장했습니다.");
    } catch (err) {
      if (err instanceof Error && err.message === "STORAGE_WRITE_FAILURE") {
        setInfo("노트 자동 저장에 실패했습니다. 브라우저 저장 공간을 확인해 주세요.");
        return;
      }
      setInfo("노트 자동 저장 중 오류가 발생했습니다.");
    }
  }, [setAutosaveToast, setNotebooksState]);

  const handleMoveAutoSavedNoteToNotebook = useCallback(() => {
    setIsNotebooksOpen(true);
    setInfo("노트북 이동 기능은 곧 지원됩니다.");
  }, []);

  const {
    isSubmitting,
    analysis,
    history,
    overlays,
    needsTapAnnotation,
    refreshHistory,
    runAnalysis,
    handleSelectHistory,
    handleAnnotationTap,
  } = useAnalysisFlow({
    subject,
    highlightMode,
    problemImage,
    canvasRef,
    selectedIndex,
    setSelectedIndex,
    setActiveTab,
    setError,
    setInfo,
    persistAutoSavedNote,
  });

  const filteredNotes = useMemo(() => {
    if (!notebooksState || !selectedNotebookId) return [];
    if (selectedNotebookId === SYSTEM_NOTEBOOK_IDS.TRASH) return [];

    return Object.values(notebooksState.notes)
      .filter((note) => note.notebookId === selectedNotebookId)
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [notebooksState, selectedNotebookId]);

  const selectedNote = useMemo(() => {
    if (!notebooksState || !selectedNoteId) return null;
    return notebooksState.notes[selectedNoteId] ?? null;
  }, [notebooksState, selectedNoteId]);

  const notebooksList = useMemo(() => {
    if (!notebooksState) return [];
    return Object.values(notebooksState.notebooks).sort((a, b) => a.sortOrder - b.sortOrder);
  }, [notebooksState]);

  const topTagsFromNotes = useMemo(() => {
    if (!notebooksState) return [];

    const notePool = Object.values(notebooksState.notes).filter((note) => {
      if (note.notebookId === SYSTEM_NOTEBOOK_IDS.TRASH) return false;
      if (!selectedNotebookId || selectedNotebookId === SYSTEM_NOTEBOOK_IDS.TRASH) return true;
      return note.notebookId === selectedNotebookId;
    });

    const counts = new Map<string, number>();
    for (const note of notePool) {
      const uniqueTags = new Set(note.tags.filter((tag) => tag.trim().length > 0));
      for (const tag of uniqueTags) {
        counts.set(tag, (counts.get(tag) ?? 0) + 1);
      }
    }

    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 3)
      .map(([type, count]) => ({ type, count }));
  }, [notebooksState, selectedNotebookId]);

  const dashboardTopTags = notebooksState ? topTagsFromNotes : history.top_tags;

  return (
    <main className="noteShell">
      <header className="noteHeader">
        <div className="brandBlock">
          <h1>MistakePatch Notes</h1>
          <p>필기앱 기반 오답 피드백: 필기하면서 바로 감점/패치 확인</p>
        </div>

        <div className="toolbar">
          <button
            type="button"
            className="ghostBtn"
            onClick={() => setIsNotebooksOpen(true)}
            data-testid="notebooks-toggle"
          >
            Notebooks
          </button>

          <label>
            과목
            <select value={subject} onChange={(event) => setSubject(event.target.value as Subject)}>
              <option value="math">수학</option>
              <option value="physics">물리</option>
            </select>
          </label>

          <label>
            하이라이트
            <select
              value={highlightMode}
              onChange={(event) => setHighlightMode(event.target.value as "tap" | "ocr_box")}
            >
              <option value="tap">탭 기반</option>
              <option value="ocr_box">OCR 보조</option>
            </select>
          </label>

          <span className="healthIndicator">
            OCR hints: {healthError ? "?" : backendHealth?.enable_ocr_hints ? "On" : "Off"}
          </span>

          <label>
            문제 이미지
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => setProblemImage(event.target.files?.[0] ?? null)}
            />
          </label>

          <label>
            펜 색
            <input type="color" value={brushColor} onChange={(event) => setBrushColor(event.target.value)} />
          </label>

          <label>
            펜 두께
            <input
              type="range"
              min={1}
              max={12}
              value={brushSize}
              onChange={(event) => setBrushSize(Number(event.target.value))}
            />
          </label>

          <button
            type="button"
            className={`ghostBtn toolToggle ${!isEraserMode ? "active" : ""}`}
            onClick={() => setIsEraserMode(false)}
          >
            펜
          </button>
          <button
            type="button"
            className={`ghostBtn toolToggle ${isEraserMode ? "active" : ""}`}
            onClick={() => setIsEraserMode(true)}
          >
            지우개
          </button>
          <button type="button" className="ghostBtn" onClick={() => canvasRef.current?.undo()}>
            되돌리기
          </button>
          <button type="button" className="ghostBtn" onClick={() => canvasRef.current?.redo()}>
            앞으로
          </button>
          <button type="button" className="ghostBtn" onClick={() => canvasRef.current?.clear()}>
            전체 지우기
          </button>
          <button
            type="button"
            className="primaryBtn"
            onClick={runAnalysis}
            disabled={isSubmitting}
            data-testid="analyze-button"
          >
            {isSubmitting ? "채점 중..." : "채점 실행"}
          </button>
        </div>
      </header>

      {error && <p className="errorText">{error}</p>}
      {info && <p className="okText">{info}</p>}
      {highlightMode === "ocr_box" && backendHealth?.enable_ocr_hints === false && (
        <p className="okText" style={{ color: "#666" }}>
          Tip: set ENABLE_OCR_HINTS=true on backend for OCR box hints.
        </p>
      )}

      <section className="workspace">
        {problemPreviewUrl && (
          <aside className="problemPreview">
            <strong>문제 이미지</strong>
            <img src={problemPreviewUrl} alt="problem preview" />
          </aside>
        )}

          <div data-testid="canvas-root" style={{ width: "100%", height: "100%" }}>
            <NoteCanvas
              ref={canvasRef}
              brushColor={brushColor}
              brushSize={brushSize}
              eraserMode={isEraserMode}
              overlays={overlays}
              annotationMode={needsTapAnnotation}
              onAnnotationTap={handleAnnotationTap}
            />
          </div>

        <FloatingFeedback
          analysis={analysis}
          isSubmitting={isSubmitting}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          selectedIndex={selectedIndex}
          onSelectIndex={setSelectedIndex}
        />
      </section>

      <section className="historyDock">
        {/* Top Tags Dashboard */}
        {dashboardTopTags && dashboardTopTags.length > 0 && (
          <div className="topTagsDashboard" data-testid="top-tags">
            <span className="topTagsLabel">Top Tags:</span>
            {dashboardTopTags.slice(0, 3).map((tag) => (
              <span key={`${tag.type}-${tag.count}`} className="topTagChip">
                {tag.type} <small>x{tag.count}</small>
              </span>
            ))}
          </div>
        )}

        {/* Current Notebook Notes */}
        {selectedNotebookId && selectedNotebookId !== SYSTEM_NOTEBOOK_IDS.TRASH && (
          <div className="notesBrowser">
            <div className="notesHeader">
              <h3>
                {notebooksState?.notebooks[selectedNotebookId]?.name ?? "Notebook"}
                <span className="noteCount">({filteredNotes.length})</span>
              </h3>
            </div>
            
            {filteredNotes.length === 0 ? (
              <div className="emptyNotes">Run grading to create notes</div>
            ) : (
              <div className="notesGrid">
                {filteredNotes.map((note) => (
                  <button
                    type="button"
                    key={note.id}
                    className="noteCard"
                    onClick={() => setSelectedNoteId(note.id)}
                    data-testid={`note-card-${note.id}`}
                  >
                    <div className="noteCardHeader">
                      <span className="noteSubject">{note.subject}</span>
                      <span className="noteDate">
                        {new Date(note.createdAt).toLocaleDateString()}
                      </span>
                    </div>
                    <div className="noteScore">
                      {note.scoreTotal != null ? note.scoreTotal.toFixed(1) : "-"}
                      <span className="scoreMax">/10</span>
                    </div>
                    {note.tags && note.tags.length > 0 && (
                      <div className="noteTags">
                        {note.tags.slice(0, 2).map((t) => (
                          <span key={`${note.id}-${t}`} className="miniTag">#{t}</span>
                        ))}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="historyHeader">
          <h2>최근 분석</h2>
          <button type="button" className="ghostBtn" onClick={() => refreshHistory()}>
            새로고침
          </button>
        </div>
        <div className="historyChipRow">
          {history.items.length === 0 && <p>분석 기록이 아직 없습니다.</p>}
          {history.items.map((item) => (
            <button
              type="button"
              key={item.analysis_id}
              className="historyChip"
              onClick={() => handleSelectHistory(item.analysis_id)}
            >
              <strong>{item.subject === "math" ? "수학" : "물리"}</strong>
              <span>{item.score_total !== null ? `${item.score_total.toFixed(1)}점` : "진행중"}</span>
              {item.top_tag && <small>#{item.top_tag}</small>}
            </button>
          ))}
        </div>
      </section>

      <NotebooksDrawer
        isOpen={isNotebooksOpen}
        onClose={() => setIsNotebooksOpen(false)}
        notebooks={notebooksList}
        notes={notebooksState ? Object.values(notebooksState.notes) : []}
        selectedNotebookId={selectedNotebookId}
        onSelectNotebook={setSelectedNotebookId}
        onCreateNotebook={handleCreateNotebook}
        onRenameNotebook={handleRenameNotebook}
        onReorderNotebook={handleReorderNotebook}
        onDeleteNotebook={handleDeleteNotebook}
        onRestoreNote={handleRestoreNote}
        onEmptyTrash={handleEmptyTrash}
      />

      <UndoToast
        isOpen={Boolean(autosaveToast)}
        durationMs={AUTOSAVE_TOAST_DURATION_MS}
        onUndo={handleUndoAutoSavedNote}
        onMoveToTrash={handleMoveAutoSavedNoteToTrash}
        onMoveToNotebook={handleMoveAutoSavedNoteToNotebook}
        onClose={() => setAutosaveToast(null)}
      />

      <NoteDetailModal
        note={selectedNote}
        notebooks={notebooksList}
        onClose={() => setSelectedNoteId(null)}
        onMoveNote={handleMoveNote}
        onDeleteNote={handleDeleteNote}
      />
    </main>
  );
}
