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
    <div className={styles.toast} aria-live="polite" data-testid="autosave-toast">
      <p className={styles.message}>분석 결과를 수신함에 저장했어요.</p>
      <div className={styles.actions}>
        <button type="button" onClick={onUndo} className={styles.actionPrimary} data-testid="autosave-undo">
          되돌리기
        </button>
        <button type="button" onClick={onMoveToTrash} className={styles.action} data-testid="autosave-trash">
          휴지통으로
        </button>
        <button type="button" onClick={onMoveToNotebook} className={styles.action} disabled>
          노트북으로 이동(준비중)
        </button>
      </div>
    </div>
  );
}
