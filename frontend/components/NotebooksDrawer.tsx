"use client";

import { useState } from "react";
import { Notebook, Note } from "@/lib/notebooks/types";
import { SYSTEM_NOTEBOOK_IDS } from "@/lib/notebooks/storage";

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

  if (!isOpen) return null;

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

  return (
    <>
      <div className="drawerBackdrop" onClick={onClose} />
      <aside className="notebooksDrawer" data-testid="notebooks-drawer">
        <header className="drawerHeader">
          <h2>{isTrashSelected ? "Trash" : "Notebooks"}</h2>
          <button className="ghostBtn" onClick={onClose}>
            Close
          </button>
        </header>

        {isTrashSelected ? (
          <div className="trashSection">
            <div className="trashActions">
              <button 
                className="ghostBtn" 
                onClick={() => onSelectNotebook(SYSTEM_NOTEBOOK_IDS.INBOX)}
              >
                ← Back to Notebooks
              </button>
              {trashedNotes.length > 0 && (
                <button 
                  className="destructiveBtn"
                  onClick={() => {
                    if (confirm("Are you sure you want to permanently delete all notes in Trash?")) {
                      onEmptyTrash();
                    }
                  }}
                  data-testid="trash-empty"
                >
                  Empty Trash
                </button>
              )}
            </div>

            <div className="trashedNotesList">
              {trashedNotes.length === 0 ? (
                <p className="emptyState">Trash is empty</p>
              ) : (
                trashedNotes.map((note) => (
                  <div key={note.id} className="trashedNoteItem">
                    <div className="trashedNoteInfo">
                      <span className="noteSubject">[{note.subject}]</span>
                      <span className="noteScore">
                        {note.scoreTotal !== null ? `${note.scoreTotal}pts` : "No score"}
                      </span>
                      <span className="noteDate">
                        {new Date(note.createdAt).toLocaleDateString()}
                      </span>
                    </div>
                    <button
                      className="restoreBtn"
                      onClick={() => onRestoreNote(note.id)}
                      data-testid={`trash-restore-${note.id}`}
                    >
                      Restore
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
            <button className="ghostBtn fullWidth" onClick={() => setIsCreating(true)}>
              + New Notebook
            </button>
          ) : (
            <form onSubmit={handleCreateSubmit} className="createNotebookForm">
              <input
                autoFocus
                type="text"
                placeholder="Notebook Name"
                value={newNotebookName}
                onChange={(e) => setNewNotebookName(e.target.value)}
              />
              <div className="formActions">
                <button type="submit" className="primaryBtn small">
                  Create
                </button>
                <button
                  type="button"
                  className="ghostBtn small"
                  onClick={() => {
                    setIsCreating(false);
                    setNewNotebookName("");
                  }}
                >
                  Cancel
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
                      autoFocus
                      type="text"
                      value={editingName}
                      onChange={(e) => setEditingName(e.target.value)}
                    />
                    <div className="renameActions">
                        <button type="submit" className="iconBtn">Save</button>
                        <button type="button" className="iconBtn" onClick={() => setEditingId(null)}>Cancel</button>
                    </div>
                  </form>
                ) : (
                  <div className="notebookItemInner">
                    <button
                      className="notebookItemMain"
                      onClick={() => onSelectNotebook(notebook.id)}
                      data-testid={`notebook-item-${notebook.id.toLowerCase()}`}
                    >
                      <span className="notebookIcon">
                        {notebook.id === SYSTEM_NOTEBOOK_IDS.TRASH ? "[Trash]" : notebook.id === SYSTEM_NOTEBOOK_IDS.INBOX ? "[Inbox]" : "[NB]"}
                      </span>
                      <span className="notebookName">{notebook.name}</span>
                    </button>
                    
                    <div className="notebookItemControls">
                        {!isSystem && (
                            <>
                                <button
                                    className="iconBtn"
                                    title="Rename"
                                    onClick={(e) => {
                                    e.stopPropagation();
                                    startRenaming(notebook);
                                    }}
                                >
                                    Rename
                                </button>
                                <button
                                    className="iconBtn"
                                    title="Delete"
                                    onClick={(e) => {
                                    e.stopPropagation();
                                    if (confirm(`Delete "${notebook.name}" and move notes to Trash?`)) {
                                        onDeleteNotebook(notebook.id);
                                    }
                                    }}
                                >
                                    Delete
                                </button>
                            </>
                        )}
                        
                        <div className="reorderControls">
                            <button
                            className="iconBtn upBtn"
                            disabled={index === 0 || isSystem}
                            onClick={(e) => {
                                e.stopPropagation();
                                onReorderNotebook(notebook.id, "up");
                            }}
                            >
                            Up
                            </button>
                            <button
                            className="iconBtn downBtn"
                            disabled={index === notebooks.length - 1 || isSystem}
                            onClick={(e) => {
                                e.stopPropagation();
                                onReorderNotebook(notebook.id, "down");
                            }}
                            >
                            Down
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
      <style jsx>{`
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
