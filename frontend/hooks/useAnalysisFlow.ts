"use client";

import { useCallback, useEffect, useMemo, useState, type RefObject } from "react";

import type { NoteCanvasHandle } from "@/components/NoteCanvas";
import { createAnalysis, createAnnotation, fetchAnalysis, fetchHistory } from "@/lib/api";
import { wait } from "@/lib/home/pageUtils";
import type { AnalysisDetail, HistoryResponse, Subject } from "@/lib/types";

const EMPTY_HISTORY: HistoryResponse = {
  items: [],
  top_tags: [],
};

type FeedbackTab = "mistakes" | "patch" | "checklist";

interface UseAnalysisFlowParams {
  subject: Subject;
  highlightMode: "tap" | "ocr_box";
  problemImage: File | null;
  canvasRef: RefObject<NoteCanvasHandle | null>;
  selectedIndex: number;
  setSelectedIndex: (index: number) => void;
  setActiveTab: (tab: FeedbackTab) => void;
  setError: (message: string | null) => void;
  setInfo: (message: string | null) => void;
  persistAutoSavedNote: (detail: AnalysisDetail) => void;
}

export function useAnalysisFlow({
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
}: UseAnalysisFlowParams) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [history, setHistory] = useState<HistoryResponse>(EMPTY_HISTORY);

  const refreshHistory = useCallback(async () => {
    const response = await fetchHistory(5);
    setHistory(response);
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

  useEffect(() => {
    refreshHistory().catch((err) => {
      setError(err instanceof Error ? err.message : String(err));
    });
  }, [refreshHistory, setError]);

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
        if (typeof h.x !== "number" || typeof h.y !== "number" || typeof h.w !== "number" || typeof h.h !== "number") {
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
  }, [canvasRef, highlightMode, pollAnalysis, problemImage, setActiveTab, setError, setInfo, setSelectedIndex, subject]);

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
    [pollAnalysis, setActiveTab, setError, setInfo, setSelectedIndex],
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
    [analysis, needsTapAnnotation, selectedMistake, setError, setInfo],
  );

  const clearCurrentAnalysis = useCallback(() => {
    setAnalysis(null);
  }, []);

  return {
    isSubmitting,
    analysis,
    history,
    overlays,
    needsTapAnnotation,
    refreshHistory,
    runAnalysis,
    handleSelectHistory,
    handleAnnotationTap,
    clearCurrentAnalysis,
  };
}
