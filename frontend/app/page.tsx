"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { FloatingFeedback } from "@/components/FloatingFeedback";
import { NotebooksDrawer } from "@/components/NotebooksDrawer";
import { NoteCanvas, type NoteCanvasHandle } from "@/components/NoteCanvas";
import { UndoToast } from "@/components/UndoToast";
import { StudyNote } from "@/components/StudyNote";
import { createAnalysis, createAnnotation, fetchAnalysis, fetchHealth, fetchHistory } from "@/lib/api";
import type { HealthResponse } from "@/lib/api";
import { loadState, saveState, SYSTEM_NOTEBOOK_IDS } from "@/lib/notebooks/storage";
import type { Note, NotebooksState } from "@/lib/notebooks/types";
import type { AnalysisDetail, HistoryResponse, Subject } from "@/lib/types";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const EMPTY_HISTORY: HistoryResponse = {
  items: [],
  top_tags: [],
};

const AUTOSAVE_DEDUPE_KEY = "mistakepatch:notebooks:autosaved-analysis-ids";
const AUTOSAVE_TOAST_DURATION_MS = 9000;

type FeedbackTab = "mistakes" | "patch" | "checklist";

function createNoteId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadAutosavedAnalysisIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(AUTOSAVE_DEDUPE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    const ids = parsed.filter((item): item is string => typeof item === "string");
    return new Set(ids);
  } catch {
    return new Set();
  }
}

function saveAutosavedAnalysisIds(ids: Set<string>) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(AUTOSAVE_DEDUPE_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    // Non-blocking best effort key for dedupe across reloads.
  }
}

function buildNoteTags(detail: AnalysisDetail): string[] {
  if (!detail.result?.mistakes?.length) return [];
  const uniqueTags = new Set<string>();
  for (const mistake of detail.result.mistakes) {
    uniqueTags.add(mistake.type);
    if (uniqueTags.size >= 3) break;
  }
  return Array.from(uniqueTags);
}

export default function HomePage() {
  const canvasRef = useRef<NoteCanvasHandle | null>(null);

  const [subject, setSubject] = useState<Subject>("math");
  const [highlightMode, setHighlightMode] = useState<"tap" | "ocr_box">("tap");
  const [problemImage, setProblemImage] = useState<File | null>(null);
  const [problemPreviewUrl, setProblemPreviewUrl] = useState<string | null>(null);

  const [brushColor, setBrushColor] = useState("#17212a");
  const [brushSize, setBrushSize] = useState(3);

  const [backendHealth, setBackendHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<boolean>(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [history, setHistory] = useState<HistoryResponse>(EMPTY_HISTORY);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<FeedbackTab>("mistakes");
  const [selectedIndex, setSelectedIndex] = useState(0);

  const [isNotebooksOpen, setIsNotebooksOpen] = useState(false);
  const [notebooksState, setNotebooksState] = useState<NotebooksState | null>(null);
  const [selectedNotebookId, setSelectedNotebookId] = useState<string | null>(null);
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [autosaveToast, setAutosaveToast] = useState<{ noteId: string; analysisId: string } | null>(null);

  useEffect(() => {
    // Load notebooks state
    const state = loadState();
    setNotebooksState(state);
    // Select Inbox by default if exists
    if (state.notebooks[SYSTEM_NOTEBOOK_IDS.INBOX]) {
      setSelectedNotebookId(SYSTEM_NOTEBOOK_IDS.INBOX);
    }

    // Fetch backend health
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

  const refreshHistory = useCallback(async () => {
    const response = await fetchHistory(5);
    setHistory(response);
  }, []);

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
  }, []);

  const pollAnalysis = useCallback(
    async (analysisId: string) => {
      for (let attempt = 0; attempt < 40; attempt += 1) {
        const detail = await fetchAnalysis(analysisId);
        setAnalysis(detail);
        if (detail.status === "done" || detail.status === "failed") {
          if (detail.status === "done") {
            persistAutoSavedNote(detail);
          }
          await refreshHistory();
          return;
        }
        await wait(1200);
      }
    },
    [persistAutoSavedNote, refreshHistory],
  );

  const handleUndoAutoSavedNote = useCallback(() => {
    if (!autosaveToast) return;
    const currentState = loadState();
    if (!currentState.notes[autosaveToast.noteId]) {
      setAutosaveToast(null);
      return;
    }
    const nextNotes = { ...currentState.notes };
    delete nextNotes[autosaveToast.noteId];

    const nextState: NotebooksState = {
      ...currentState,
      notes: nextNotes,
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setInfo("자동 저장한 노트를 되돌렸습니다.");
      setAutosaveToast(null);
    } catch (err) {
      if (err instanceof Error && err.message === "STORAGE_WRITE_FAILURE") {
        setInfo("되돌리기에 실패했습니다. 브라우저 저장 공간을 확인해 주세요.");
        return;
      }
      setInfo("되돌리기 중 오류가 발생했습니다.");
    }
  }, [autosaveToast]);

  const handleMoveAutoSavedNoteToTrash = useCallback(() => {
    if (!autosaveToast) return;
    const currentState = loadState();
    const currentNote = currentState.notes[autosaveToast.noteId];
    if (!currentNote) {
      setAutosaveToast(null);
      return;
    }

    const nextState: NotebooksState = {
      ...currentState,
      notes: {
        ...currentState.notes,
        [autosaveToast.noteId]: {
          ...currentNote,
          notebookId: SYSTEM_NOTEBOOK_IDS.TRASH,
          previousNotebookId: currentNote.notebookId,
          trashedAt: new Date().toISOString(),
        },
      },
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setInfo("자동 저장한 노트를 Trash로 이동했습니다.");
      setAutosaveToast(null);
    } catch (err) {
      if (err instanceof Error && err.message === "STORAGE_WRITE_FAILURE") {
        setInfo("Trash 이동에 실패했습니다. 브라우저 저장 공간을 확인해 주세요.");
        return;
      }
      setInfo("Trash 이동 중 오류가 발생했습니다.");
    }
  }, [autosaveToast]);

  const handleRestoreNote = useCallback((noteId: string) => {
    const currentState = loadState();
    const note = currentState.notes[noteId];
    if (!note) return;

    let targetNotebookId: string = SYSTEM_NOTEBOOK_IDS.INBOX;
    if (note.previousNotebookId && currentState.notebooks[note.previousNotebookId]) {
      targetNotebookId = note.previousNotebookId;
    }

    const nextState: NotebooksState = {
      ...currentState,
      notes: {
        ...currentState.notes,
        [noteId]: {
          ...note,
          notebookId: targetNotebookId,
          previousNotebookId: null,
          trashedAt: null,
        },
      },
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setInfo("노트를 복구했습니다.");
    } catch (err) {
      setInfo("노트 복구 중 오류가 발생했습니다.");
    }
  }, []);

  const handleEmptyTrash = useCallback(() => {
    const currentState = loadState();
    const nextNotes = { ...currentState.notes };
    
    // Remove all notes in Trash
    Object.values(nextNotes).forEach(note => {
      if (note.notebookId === SYSTEM_NOTEBOOK_IDS.TRASH) {
        delete nextNotes[note.id];
      }
    });

    const nextState: NotebooksState = {
      ...currentState,
      notes: nextNotes,
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setInfo("휴지통을 비웠습니다.");
    } catch (err) {
      setInfo("휴지통 비우기 중 오류가 발생했습니다.");
    }
  }, []);

  const handleMoveAutoSavedNoteToNotebook = useCallback(() => {
    setIsNotebooksOpen(true);
    setInfo("노트북 이동 기능은 곧 지원됩니다.");
  }, []);

  const handleCreateNotebook = useCallback((name: string) => {
    const currentState = loadState();
    const newId = createNoteId();
    const existingNotebooks = Object.values(currentState.notebooks);
    const maxSortOrder = existingNotebooks.reduce((max, nb) => Math.max(max, nb.sortOrder), 0);

    const newNotebook = {
      id: newId,
      name: name.trim(),
      sortOrder: maxSortOrder + 1,
      createdAt: new Date().toISOString(),
    };

    const nextState: NotebooksState = {
      ...currentState,
      notebooks: {
        ...currentState.notebooks,
        [newId]: newNotebook,
      },
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setInfo(`새 노트북 "${name}"을(를) 생성했습니다.`);
    } catch (err) {
      setInfo("노트북 생성 중 오류가 발생했습니다.");
    }
  }, []);

  const handleRenameNotebook = useCallback((id: string, newName: string) => {
    const currentState = loadState();
    const notebook = currentState.notebooks[id];
    if (!notebook || notebook.system) return;

    const nextState: NotebooksState = {
      ...currentState,
      notebooks: {
        ...currentState.notebooks,
        [id]: {
          ...notebook,
          name: newName.trim(),
        },
      },
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
    } catch (err) {
      setInfo("이름 변경 중 오류가 발생했습니다.");
    }
  }, []);

  const handleReorderNotebook = useCallback((id: string, direction: "up" | "down") => {
    if (id === SYSTEM_NOTEBOOK_IDS.INBOX || id === SYSTEM_NOTEBOOK_IDS.TRASH) return;
    const currentState = loadState();
    const notebooks = Object.values(currentState.notebooks).sort((a, b) => a.sortOrder - b.sortOrder);
    const index = notebooks.findIndex((nb) => nb.id === id);
    if (index === -1) return;

    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= notebooks.length) return;

    const targetNotebook = notebooks[targetIndex];
    const sourceNotebook = notebooks[index];

    // Swap sortOrders
    const nextState: NotebooksState = {
      ...currentState,
      notebooks: {
        ...currentState.notebooks,
        [sourceNotebook.id]: { ...sourceNotebook, sortOrder: targetNotebook.sortOrder },
        [targetNotebook.id]: { ...targetNotebook, sortOrder: sourceNotebook.sortOrder },
      },
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
    } catch (err) {
      setInfo("순서 변경 중 오류가 발생했습니다.");
    }
  }, []);

  const handleDeleteNotebook = useCallback((id: string) => {
    const currentState = loadState();
    const notebook = currentState.notebooks[id];
    if (!notebook || notebook.system) return;

    const nextNotebooks = { ...currentState.notebooks };
    delete nextNotebooks[id];

    // Move notes to Trash
    const nextNotes = { ...currentState.notes };
    Object.values(nextNotes).forEach((note) => {
      if (note.notebookId === id) {
        nextNotes[note.id] = {
          ...note,
          notebookId: SYSTEM_NOTEBOOK_IDS.TRASH,
          previousNotebookId: id, // Track where it came from (even though deleted, we might want to know)
          trashedAt: new Date().toISOString(),
        };
      }
    });

    const nextState: NotebooksState = {
      ...currentState,
      notebooks: nextNotebooks,
      notes: nextNotes,
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setInfo(`노트북 "${notebook.name}"을(를) 삭제하고 노트를 휴지통으로 이동했습니다.`);
      if (selectedNotebookId === id) {
        setSelectedNotebookId(SYSTEM_NOTEBOOK_IDS.INBOX);
      }
    } catch (err) {
      setInfo("노트북 삭제 중 오류가 발생했습니다.");
    }
  }, [selectedNotebookId]);

  const handleMoveNote = useCallback((noteId: string, targetNotebookId: string) => {
    const currentState = loadState();
    const note = currentState.notes[noteId];
    if (!note) return;

    const nextState: NotebooksState = {
      ...currentState,
      notes: {
        ...currentState.notes,
        [noteId]: {
          ...note,
          notebookId: targetNotebookId,
        },
      },
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setInfo("노트를 이동했습니다.");
    } catch (err) {
      if (err instanceof Error && err.message === "STORAGE_WRITE_FAILURE") {
        setInfo("노트 이동에 실패했습니다. 브라우저 저장 공간을 확인해 주세요.");
        return;
      }
      setInfo("노트 이동 중 오류가 발생했습니다.");
    }
  }, []);

  const handleDeleteNote = useCallback((noteId: string) => {
    const currentState = loadState();
    const note = currentState.notes[noteId];
    if (!note) return;

    const previousNotebookId = note.notebookId === SYSTEM_NOTEBOOK_IDS.TRASH 
      ? note.previousNotebookId 
      : note.notebookId;

    const nextState: NotebooksState = {
      ...currentState,
      notes: {
        ...currentState.notes,
        [noteId]: {
          ...note,
          notebookId: SYSTEM_NOTEBOOK_IDS.TRASH,
          previousNotebookId: previousNotebookId,
          trashedAt: new Date().toISOString(),
        },
      },
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setSelectedNoteId(null); // Close modal
      setInfo("노트를 휴지통으로 이동했습니다.");
    } catch (err) {
      if (err instanceof Error && err.message === "STORAGE_WRITE_FAILURE") {
        setInfo("노트 삭제에 실패했습니다. 브라우저 저장 공간을 확인해 주세요.");
        return;
      }
      setInfo("노트 삭제 중 오류가 발생했습니다.");
    }
  }, []);

  useEffect(() => {
    refreshHistory().catch((err) => {
      setError(err instanceof Error ? err.message : String(err));
    });
  }, [refreshHistory]);

  const selectedMistake = analysis?.result?.mistakes[selectedIndex];
  const needsTapAnnotation = Boolean(
    selectedMistake &&
      selectedMistake.mistake_id &&
      selectedMistake.highlight.mode === "tap" &&
      (typeof selectedMistake.highlight.x !== "number" || typeof selectedMistake.highlight.y !== "number"),
  );

  const overlays = useMemo(() => {
    const mistakes = analysis?.result?.mistakes ?? [];
    return mistakes
      .map((mistake, index) => {
        const h = mistake.highlight;
        if (
          typeof h.x !== "number" ||
          typeof h.y !== "number" ||
          typeof h.w !== "number" ||
          typeof h.h !== "number"
        ) {
          return null;
        }
        return {
          id: mistake.mistake_id ?? `mistake-${index}`,
          x: h.x,
          y: h.y,
          w: h.w,
          h: h.h,
          shape: h.shape ?? "circle",
          selected: index === selectedIndex,
        };
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item));
  }, [analysis, selectedIndex]);

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

  const runAnalysis = useCallback(async () => {
    setError(null);
    setInfo(null);
    setActiveTab("mistakes");
    setSelectedIndex(0);
    setIsSubmitting(true);
    try {
      const noteImage = await canvasRef.current?.exportAsFile();
      if (!noteImage) {
        throw new Error("필기 캔버스를 이미지로 변환하지 못했습니다.");
      }
      const queued = await createAnalysis({
        solutionImage: noteImage,
        problemImage: problemImage ?? undefined,
        subject,
        highlightMode,
      });
      setInfo(`분석 요청 완료: ${queued.analysis_id}`);
      await pollAnalysis(queued.analysis_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSubmitting(false);
    }
  }, [highlightMode, pollAnalysis, problemImage, subject]);

  const handleSelectHistory = useCallback(
    async (analysisId: string) => {
      setError(null);
      setInfo(null);
      setActiveTab("mistakes");
      setSelectedIndex(0);
      try {
        const detail = await fetchAnalysis(analysisId);
        setAnalysis(detail);
        if (detail.status === "queued" || detail.status === "processing") {
          await pollAnalysis(analysisId);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [pollAnalysis],
  );

  const handleAnnotationTap = useCallback(
    async (point: { x: number; y: number }) => {
      if (!needsTapAnnotation || !selectedMistake || !analysis) return;
      try {
        await createAnnotation({
          analysis_id: analysis.analysis_id,
          mistake_id: selectedMistake.mistake_id!,
          mode: "tap",
          shape: "circle",
          x: Number(point.x.toFixed(4)),
          y: Number(point.y.toFixed(4)),
          w: 0.12,
          h: 0.12,
        });
        const detail = await fetchAnalysis(analysis.analysis_id);
        setAnalysis(detail);
        setInfo("감점 위치를 필기 화면에 반영했습니다.");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [analysis, needsTapAnnotation, selectedMistake],
  );

  return (
    <main className="noteShell">
      <header className="noteHeader">
        <div className="brandBlock">
          <h1>MistakePatch Notes</h1>
          <p>필기앱 기반 오답 피드백: 필기하면서 바로 감점/패치 확인</p>
        </div>

        <div className="toolbar">
          <button
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

          <button className="ghostBtn" onClick={() => canvasRef.current?.clear()}>
            필기 지우기
          </button>
          <button className="primaryBtn" onClick={runAnalysis} disabled={isSubmitting} data-testid="analyze-button">
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
        {history.top_tags && history.top_tags.length > 0 && (
          <div className="topTagsDashboard" data-testid="top-tags">
            <span className="topTagsLabel">Top Tags:</span>
            {history.top_tags.slice(0, 3).map((tag, i) => (
              <span key={i} className="topTagChip">
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
                        {note.tags.slice(0, 2).map((t, idx) => (
                          <span key={idx} className="miniTag">#{t}</span>
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
          <button className="ghostBtn" onClick={() => refreshHistory()}>
            새로고침
          </button>
        </div>
        <div className="historyChipRow">
          {history.items.length === 0 && <p>분석 기록이 아직 없습니다.</p>}
          {history.items.map((item) => (
            <button key={item.analysis_id} className="historyChip" onClick={() => handleSelectHistory(item.analysis_id)}>
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

      {/* Note Detail Modal */}
      {selectedNote && (
        <div className="noteDetailBackdrop" onClick={() => setSelectedNoteId(null)} data-testid="note-detail">
          <div className="noteDetailPanel" onClick={(e) => e.stopPropagation()}>
            <div className="noteDetailHeader">
              <h2>Note Detail</h2>
              <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.9rem" }}>
                  Move to
                  <select
                    value={selectedNote.notebookId}
                    onChange={(e) => handleMoveNote(selectedNote.id, e.target.value)}
                    data-testid="note-move-select"
                    style={{ padding: "4px", borderRadius: "4px", border: "1px solid #ddd" }}
                  >
                    {notebooksList
                      .filter((nb) => nb.id !== SYSTEM_NOTEBOOK_IDS.TRASH)
                      .map((nb) => (
                        <option key={nb.id} value={nb.id}>
                          {nb.name}
                        </option>
                      ))}
                  </select>
                </label>
                <button
                  className="ghostBtn"
                  style={{ color: "#d32f2f" }}
                  onClick={() => handleDeleteNote(selectedNote.id)}
                  data-testid="note-delete"
                >
                  Delete
                </button>
                <button className="ghostBtn" onClick={() => setSelectedNoteId(null)}>
                  Close
                </button>
              </div>
            </div>
            <div className="noteDetailContent">
              <StudyNote result={selectedNote.snapshot as any} />
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
