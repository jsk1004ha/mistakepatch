"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Notebook, Note } from "@/lib/notebooks/types";
import { SYSTEM_NOTEBOOK_IDS } from "@/lib/notebooks/storage";

type ConfirmState =
  | { kind: "emptyTrash" }
  | { kind: "deleteNotebook"; notebookId: string; notebookName: string };

interface NotebooksDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  notebooks: Notebook[];
  notes: Note[];
  selectedNotebookId: string | null;
  onSelectNotebook: (id: string) => void;
  onCreateNotebook: (name: string) => void;
  onRenameNotebook: (id: string, newName: string) => void;
  onReorderNotebook: (id: string, direction: "up" | "down") => void;
  onDeleteNotebook: (id: string) => void;
  onRestoreNote: (noteId: string) => void;
  onEmptyTrash: () => void;
}

export function NotebooksDrawer({
  isOpen,
  onClose,
  notebooks,
  notes,
  selectedNotebookId,
  onSelectNotebook,
  onCreateNotebook,
  onRenameNotebook,
  onReorderNotebook,
  onDeleteNotebook,
  onRestoreNote,
  onEmptyTrash,
}: NotebooksDrawerProps) {
  const [isCreating, setIsCreating] = useState(false);
  const [newNotebookName, setNewNotebookName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);

  const createInputRef = useRef<HTMLInputElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newNotebookName.trim()) {
      onCreateNotebook(newNotebookName);
      setNewNotebookName("");
      setIsCreating(false);
    }
  };

  const startRenaming = (notebook: Notebook) => {
    setEditingId(notebook.id);
    setEditingName(notebook.name);
  };

  const handleRenameSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingId && editingName.trim()) {
      onRenameNotebook(editingId, editingName);
      setEditingId(null);
      setEditingName("");
    }
  };

  const isTrashSelected = selectedNotebookId === SYSTEM_NOTEBOOK_IDS.TRASH;
  const trashedNotes = notes.filter((n) => n.notebookId === SYSTEM_NOTEBOOK_IDS.TRASH);

  const confirmTitle = useMemo(() => {
    if (!confirmState) return "";
    if (confirmState.kind === "emptyTrash") return "휴지통 비우기";
    return "노트북 삭제";
  }, [confirmState]);

  const confirmMessage = useMemo(() => {
    if (!confirmState) return "";
    if (confirmState.kind === "emptyTrash") {
      return "휴지통의 노트를 영구 삭제할까요? (되돌릴 수 없습니다)";
    }
    return `"${confirmState.notebookName}"을 삭제하고, 포함된 노트를 휴지통으로 이동할까요?`;
  }, [confirmState]);

  const confirmCta = useMemo(() => {
    if (!confirmState) return "";
    if (confirmState.kind === "emptyTrash") return "영구 삭제";
    return "삭제";
  }, [confirmState]);

  const handleConfirm = useCallback(() => {
    if (!confirmState) return;
    if (confirmState.kind === "emptyTrash") {
      onEmptyTrash();
      setConfirmState(null);
      return;
    }

    onDeleteNotebook(confirmState.notebookId);
    setConfirmState(null);
  }, [confirmState, onDeleteNotebook, onEmptyTrash]);

  useEffect(() => {
    if (!isOpen) return;
    if (!isCreating) return;
    createInputRef.current?.focus();
  }, [isCreating, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    if (!editingId) return;
    renameInputRef.current?.focus();
  }, [editingId, isOpen]);

  if (!isOpen) return null;

  return (
    <>
      <button type="button" className="drawerBackdrop" aria-label="닫기" onClick={onClose} />
      <aside className="notebooksDrawer" data-testid="notebooks-drawer">
        <header className="drawerHeader">
          <h2>{isTrashSelected ? "휴지통" : "노트북"}</h2>
          <button type="button" className="ghostBtn" onClick={onClose} data-testid="drawer-close">
            닫기
          </button>
        </header>

        {isTrashSelected ? (
          <div className="trashSection">
            <div className="trashActions">
              <button
                type="button"
                className="ghostBtn" 
                onClick={() => onSelectNotebook(SYSTEM_NOTEBOOK_IDS.INBOX)}
                data-testid="drawer-back"
              >
                ← 노트북으로
              </button>
              {trashedNotes.length > 0 && (
                <button
                  type="button"
                  className="destructiveBtn"
                  onClick={() => {
                    setConfirmState({ kind: "emptyTrash" });
                  }}
                  data-testid="trash-empty"
                >
                  휴지통 비우기
                </button>
              )}
            </div>

            <div className="trashedNotesList">
              {trashedNotes.length === 0 ? (
                <p className="emptyState">휴지통이 비어 있어요</p>
              ) : (
                trashedNotes.map((note) => (
                  <div key={note.id} className="trashedNoteItem">
                    <div className="trashedNoteInfo">
                      <span className="noteSubject">[{note.subject}]</span>
                      <span className="noteScore">
                        {note.scoreTotal !== null ? `${note.scoreTotal}점` : "점수 없음"}
                      </span>
                      <span className="noteDate">
                        {new Date(note.createdAt).toLocaleDateString()}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="restoreBtn"
                      onClick={() => onRestoreNote(note.id)}
                      data-testid={`trash-restore-${note.id}`}
                    >
                      복원
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="drawerActions">
              {!isCreating ? (
                <button
                  type="button"
                  className="ghostBtn fullWidth"
                  onClick={() => setIsCreating(true)}
                  data-testid="drawer-new-notebook"
                >
                  + 새 노트북
                </button>
          ) : (
            <form onSubmit={handleCreateSubmit} className="createNotebookForm">
              <input
                ref={createInputRef}
                type="text"
                placeholder="노트북 이름"
                value={newNotebookName}
                onChange={(e) => setNewNotebookName(e.target.value)}
                data-testid="drawer-new-notebook-name"
              />
              <div className="formActions">
                <button type="submit" className="primaryBtn small" data-testid="drawer-create-notebook">
                  생성
                </button>
                <button
                  type="button"
                  className="ghostBtn small"
                  onClick={() => {
                    setIsCreating(false);
                    setNewNotebookName("");
                  }}
                  data-testid="drawer-cancel-create-notebook"
                >
                  취소
                </button>
              </div>
            </form>
          )}
        </div>

        <nav className="notebookList">
          {notebooks.map((notebook, index) => {
            const isSystem = notebook.system || notebook.id === SYSTEM_NOTEBOOK_IDS.INBOX || notebook.id === SYSTEM_NOTEBOOK_IDS.TRASH;
            const isEditing = editingId === notebook.id;
            const isActive = selectedNotebookId === notebook.id;

            return (
              <div
                key={notebook.id}
                className={`notebookItemWrapper ${isActive ? "active" : ""}`}
              >
                {isEditing ? (
                  <form onSubmit={handleRenameSubmit} className="renameNotebookForm">
                    <input
                      ref={renameInputRef}
                      type="text"
                      value={editingName}
                      onChange={(e) => setEditingName(e.target.value)}
                    />
                    <div className="renameActions">
                        <button type="submit" className="iconBtn">저장</button>
                        <button type="button" className="iconBtn" onClick={() => setEditingId(null)}>취소</button>
                    </div>
                  </form>
                ) : (
                  <div className="notebookItemInner">
                    <button
                      type="button"
                      className="notebookItemMain"
                      onClick={() => onSelectNotebook(notebook.id)}
                      data-testid={`notebook-item-${notebook.id.toLowerCase()}`}
                    >
                      <span className="notebookIcon">
                        {notebook.id === SYSTEM_NOTEBOOK_IDS.TRASH ? "[휴지통]" : notebook.id === SYSTEM_NOTEBOOK_IDS.INBOX ? "[수신함]" : "[노트]"}
                      </span>
                      <span className="notebookName">{notebook.name}</span>
                    </button>
                    
                    <div className="notebookItemControls">
                        {!isSystem && (
                            <>
                                  <button
                                    type="button"
                                     className="iconBtn"
                                     title="이름 변경"
                                     aria-label="노트북 이름 변경"
                                     data-testid={`drawer-rename-${notebook.id}`}
                                     onClick={(e) => {
                                      e.stopPropagation();
                                      startRenaming(notebook);
                                     }}
                                  >
                                     이름 변경
                                 </button>
                                  <button
                                    type="button"
                                     className="iconBtn"
                                     title="삭제"
                                     aria-label="노트북 삭제"
                                     data-testid={`drawer-delete-${notebook.id}`}
                                     onClick={(e) => {
                                      e.stopPropagation();
                                      setConfirmState({ kind: "deleteNotebook", notebookId: notebook.id, notebookName: notebook.name });
                                     }}
                                  >
                                     삭제
                                 </button>
                             </>
                         )}
                        
                        <div className="reorderControls">
                            <button
                            type="button"
                            className="iconBtn upBtn"
                            disabled={index === 0 || isSystem}
                            onClick={(e) => {
                                e.stopPropagation();
                                onReorderNotebook(notebook.id, "up");
                            }}
                            >
                            위
                            </button>
                            <button
                            type="button"
                            className="iconBtn downBtn"
                            disabled={index === notebooks.length - 1 || isSystem}
                            onClick={(e) => {
                                e.stopPropagation();
                                onReorderNotebook(notebook.id, "down");
                            }}
                            >
                            아래
                            </button>
                        </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </nav>
        </>
        )}
      </aside>

      {confirmState && (
        <div
          className="noteDetailBackdrop"
          role="dialog"
          aria-modal="true"
          tabIndex={-1}
          onKeyDown={(event) => {
            if (event.key === "Escape") setConfirmState(null);
          }}
          onClick={(event) => {
            if (event.currentTarget === event.target) setConfirmState(null);
          }}
          data-testid="confirm-dialog"
        >
          <div className="noteDetailPanel confirmPanel">
            <div className="noteDetailHeader">
              <h2>{confirmTitle}</h2>
              <button type="button" className="ghostBtn" onClick={() => setConfirmState(null)} data-testid="confirm-cancel">
                취소
              </button>
            </div>
            <div className="noteDetailContent">
              <p className="confirmMessage">{confirmMessage}</p>
              <div className="confirmActions">
                <button type="button" className="ghostBtn" onClick={() => setConfirmState(null)}>
                  취소
                </button>
                <button type="button" className="destructiveBtn" onClick={handleConfirm} data-testid="confirm-ok">
                  {confirmCta}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .confirmPanel {
          max-width: 520px;
        }
        .confirmMessage {
          margin: 0 0 0.75rem;
          color: #1b1c1d;
          line-height: 1.4;
        }
        .confirmActions {
          display: flex;
          justify-content: flex-end;
          gap: 0.5rem;
        }
        .trashSection {
            display: flex;
            flex-direction: column;
            gap: 1rem;
            padding: 0 1rem;
            height: 100%;
            overflow: hidden;
        }
        .trashActions {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.5rem;
        }
        .destructiveBtn {
            background: #ffebee;
            color: #d32f2f;
            border: 1px solid #ffcdd2;
            padding: 0.3rem 0.6rem;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8rem;
        }
        .destructiveBtn:hover {
            background: #ffcdd2;
        }
        .trashedNotesList {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            overflow-y: auto;
            flex: 1;
        }
        .trashedNoteItem {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem;
            background: #fff;
            border: 1px solid #eee;
            border-radius: 4px;
        }
        .trashedNoteInfo {
            display: flex;
            flex-direction: column;
            gap: 2px;
            font-size: 0.85rem;
        }
        .noteSubject {
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.7rem;
            color: #666;
        }
        .noteDate {
            font-size: 0.75rem;
            color: #999;
        }
        .restoreBtn {
            background: #e3f2fd;
            color: #1976d2;
            border: none;
            padding: 0.3rem 0.6rem;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8rem;
        }
        .restoreBtn:hover {
            background: #bbdefb;
        }
        .emptyState {
            text-align: center;
            color: #999;
            font-size: 0.9rem;
            margin-top: 2rem;
        }

        .drawerActions {
            padding: 0 1rem 0.5rem 1rem;
        }
        .fullWidth {
            width: 100%;
            text-align: center;
            border: 1px dashed #ccc;
        }
        .createNotebookForm {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            background: #f9f9f9;
            padding: 0.5rem;
            border-radius: 6px;
            border: 1px solid #eee;
        }
        .createNotebookForm input {
            padding: 0.4rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 0.9rem;
        }
        .formActions {
            display: flex;
            gap: 0.5rem;
            justify-content: flex-end;
        }
        .small {
            font-size: 0.8rem;
            padding: 0.3rem 0.6rem;
        }

        .notebookList {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .notebookItemWrapper {
            position: relative;
        }
        .notebookItemWrapper.active {
            background-color: #f0f7ff;
            font-weight: 500;
        }
        .notebookItemWrapper:hover {
            background-color: #f5f5f5;
        }
        .notebookItemWrapper.active:hover {
            background-color: #e6f3ff;
        }

        .notebookItemInner {
            display: flex;
            align-items: center;
            padding: 0.5rem 0.8rem;
            min-height: 40px;
        }
        .notebookItemMain {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            background: none;
            border: none;
            cursor: pointer;
            text-align: left;
            font-size: 0.95rem;
            color: inherit;
            overflow: hidden;
            padding: 0;
        }
        .notebookName {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .notebookItemControls {
            display: flex;
            align-items: center;
            gap: 2px;
            opacity: 0;
            transition: opacity 0.2s;
        }
        .notebookItemWrapper:hover .notebookItemControls,
        .notebookItemWrapper:focus-within .notebookItemControls {
            opacity: 1;
        }

        .reorderControls {
            display: flex;
            flex-direction: column;
            gap: 1px;
            margin-left: 4px;
        }
        
        .iconBtn {
            background: none;
            border: none;
            cursor: pointer;
            font-size: 0.8rem;
            padding: 4px;
            opacity: 0.5;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .iconBtn:hover {
            opacity: 1;
            background-color: rgba(0,0,0,0.05);
        }
        .iconBtn:disabled {
            opacity: 0.1;
            cursor: default;
        }
        
        .reorderControls .iconBtn {
            font-size: 0.5rem;
            padding: 0 4px;
            height: 10px;
            line-height: 1;
        }

        .renameNotebookForm {
            padding: 0.4rem;
            display: flex;
            gap: 0.3rem;
            align-items: center;
        }
        .renameNotebookForm input {
            flex: 1;
            padding: 0.3rem;
            font-size: 0.9rem;
            border: 1px solid #ccc;
            border-radius: 4px;
        }
        .renameActions {
            display: flex;
        }
      `}</style>
    </>
  );
}
