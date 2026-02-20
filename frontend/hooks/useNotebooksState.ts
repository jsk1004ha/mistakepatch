"use client";

import { useCallback, useEffect, useState } from "react";

import { createNoteId } from "@/lib/home/pageUtils";
import { loadState, saveState, SYSTEM_NOTEBOOK_IDS } from "@/lib/notebooks/storage";
import type { NotebooksState } from "@/lib/notebooks/types";

type SetInfo = React.Dispatch<React.SetStateAction<string | null>>;

type AutosaveToastState = { noteId: string; analysisId: string } | null;

type UseNotebooksStateOptions = {
  setInfo: SetInfo;
};

export function useNotebooksState({ setInfo }: UseNotebooksStateOptions) {
  const [notebooksState, setNotebooksState] = useState<NotebooksState | null>(null);
  const [selectedNotebookId, setSelectedNotebookId] = useState<string | null>(null);
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [autosaveToast, setAutosaveToast] = useState<AutosaveToastState>(null);

  useEffect(() => {
    const state = loadState();
    setNotebooksState(state);
    if (state.notebooks[SYSTEM_NOTEBOOK_IDS.INBOX]) {
      setSelectedNotebookId(SYSTEM_NOTEBOOK_IDS.INBOX);
    }
  }, []);

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
  }, [autosaveToast, setInfo]);

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
      setInfo("자동 저장한 노트를 휴지통으로 이동했습니다.");
      setAutosaveToast(null);
    } catch (err) {
      if (err instanceof Error && err.message === "STORAGE_WRITE_FAILURE") {
        setInfo("휴지통 이동에 실패했습니다. 브라우저 저장 공간을 확인해 주세요.");
        return;
      }
      setInfo("휴지통 이동 중 오류가 발생했습니다.");
    }
  }, [autosaveToast, setInfo]);

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
  }, [setInfo]);

  const handleEmptyTrash = useCallback(() => {
    const currentState = loadState();
    const nextNotes = { ...currentState.notes };

    Object.values(nextNotes).forEach((note) => {
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
  }, [setInfo]);

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
  }, [setInfo]);

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
  }, [setInfo]);

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
  }, [setInfo]);

  const handleDeleteNotebook = useCallback((id: string) => {
    const currentState = loadState();
    const notebook = currentState.notebooks[id];
    if (!notebook || notebook.system) return;

    const nextNotebooks = { ...currentState.notebooks };
    delete nextNotebooks[id];

    const nextNotes = { ...currentState.notes };
    Object.values(nextNotes).forEach((note) => {
      if (note.notebookId === id) {
        nextNotes[note.id] = {
          ...note,
          notebookId: SYSTEM_NOTEBOOK_IDS.TRASH,
          previousNotebookId: id,
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
  }, [selectedNotebookId, setInfo]);

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
  }, [setInfo]);

  const handleDeleteNote = useCallback((noteId: string) => {
    const currentState = loadState();
    const note = currentState.notes[noteId];
    if (!note) return;

    const previousNotebookId = note.notebookId === SYSTEM_NOTEBOOK_IDS.TRASH ? note.previousNotebookId : note.notebookId;

    const nextState: NotebooksState = {
      ...currentState,
      notes: {
        ...currentState.notes,
        [noteId]: {
          ...note,
          notebookId: SYSTEM_NOTEBOOK_IDS.TRASH,
          previousNotebookId,
          trashedAt: new Date().toISOString(),
        },
      },
    };

    try {
      saveState(nextState);
      setNotebooksState(nextState);
      setSelectedNoteId(null);
      setInfo("노트를 휴지통으로 이동했습니다.");
    } catch (err) {
      if (err instanceof Error && err.message === "STORAGE_WRITE_FAILURE") {
        setInfo("노트 삭제에 실패했습니다. 브라우저 저장 공간을 확인해 주세요.");
        return;
      }
      setInfo("노트 삭제 중 오류가 발생했습니다.");
    }
  }, [setInfo]);

  return {
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
  };
}
