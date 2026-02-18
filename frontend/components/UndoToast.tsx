"use client";

import { useEffect } from "react";

import styles from "./UndoToast.module.css";

type UndoToastProps = {
  isOpen: boolean;
  durationMs?: number;
  onUndo: () => void;
  onMoveToTrash: () => void;
  onMoveToNotebook: () => void;
  onClose: () => void;
};

export function UndoToast({
  isOpen,
  durationMs = 9000,
  onUndo,
  onMoveToTrash,
  onMoveToNotebook,
  onClose,
}: UndoToastProps) {
  useEffect(() => {
    if (!isOpen) return;
    const timeoutId = window.setTimeout(onClose, durationMs);
    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [durationMs, isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className={styles.toast} role="status" aria-live="polite" data-testid="autosave-toast">
      <p className={styles.message}>Analysis saved to Inbox.</p>
      <div className={styles.actions}>
        <button type="button" onClick={onUndo} className={styles.actionPrimary} data-testid="autosave-undo">
          Undo
        </button>
        <button type="button" onClick={onMoveToTrash} className={styles.action} data-testid="autosave-trash">
          Move to Trash
        </button>
        <button type="button" onClick={onMoveToNotebook} className={styles.action}>
          Move to Notebook (Coming soon)
        </button>
      </div>
    </div>
  );
}
