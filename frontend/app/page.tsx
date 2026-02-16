"use client";

import { useCallback, useEffect, useState } from "react";

import { AnalysisPanel } from "@/components/AnalysisPanel";
import { HistoryPanel } from "@/components/HistoryPanel";
import { UploadPanel } from "@/components/UploadPanel";
import {
  createAnalysis,
  createAnnotation,
  fetchAnalysis,
  fetchHistory,
} from "@/lib/api";
import type { AnalysisDetail, HistoryResponse } from "@/lib/types";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const EMPTY_HISTORY: HistoryResponse = {
  items: [],
  top_tags: [],
};

export default function HomePage() {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [history, setHistory] = useState<HistoryResponse>(EMPTY_HISTORY);
  const [error, setError] = useState<string | null>(null);

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
          await refreshHistory();
          return;
        }
        await wait(1500);
      }
    },
    [refreshHistory],
  );

  useEffect(() => {
    refreshHistory().catch((err) => {
      setError(err instanceof Error ? err.message : String(err));
    });
  }, [refreshHistory]);

  const handleSubmit = useCallback(
    async (payload: {
      solutionImage: File;
      problemImage?: File;
      subject: "math" | "physics";
      highlightMode: "tap" | "ocr_box";
    }) => {
      setError(null);
      setIsSubmitting(true);
      try {
        const queued = await createAnalysis(payload);
        await pollAnalysis(queued.analysis_id);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsSubmitting(false);
      }
    },
    [pollAnalysis],
  );

  const handleSelectHistory = useCallback(
    async (analysisId: string) => {
      setError(null);
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

  const handleCreateAnnotation = useCallback(
    async (payload: {
      analysis_id: string;
      mistake_id: string;
      mode: "tap" | "ocr_box" | "region_box";
      shape: "circle" | "box";
      x?: number;
      y?: number;
      w?: number;
      h?: number;
    }) => {
      await createAnnotation(payload);
    },
    [],
  );

  const handleReload = useCallback(async () => {
    if (!analysis) return;
    const detail = await fetchAnalysis(analysis.analysis_id);
    setAnalysis(detail);
  }, [analysis]);

  return (
    <main className="shell">
      <header>
        <h1>MistakePatch</h1>
        <p>풀이 업로드 → 채점 → 감점/패치 → 히스토리</p>
      </header>

      {error && <p className="errorText">{error}</p>}

      <section className="topGrid">
        <UploadPanel isSubmitting={isSubmitting} onSubmit={handleSubmit} />
        <HistoryPanel
          items={history.items}
          topTags={history.top_tags}
          onSelect={handleSelectHistory}
        />
      </section>

      {analysis && (
        <AnalysisPanel
          analysis={analysis}
          onReload={handleReload}
          onCreateAnnotation={handleCreateAnnotation}
        />
      )}
    </main>
  );
}

