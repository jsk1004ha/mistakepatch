"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { FloatingFeedback } from "@/components/FloatingFeedback";
import { NoteCanvas, type NoteCanvasHandle } from "@/components/NoteCanvas";
import { createAnalysis, createAnnotation, fetchAnalysis, fetchHistory } from "@/lib/api";
import type { AnalysisDetail, HistoryResponse, Subject } from "@/lib/types";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const EMPTY_HISTORY: HistoryResponse = {
  items: [],
  top_tags: [],
};

type FeedbackTab = "mistakes" | "patch" | "checklist";

export default function HomePage() {
  const canvasRef = useRef<NoteCanvasHandle | null>(null);

  const [subject, setSubject] = useState<Subject>("math");
  const [highlightMode, setHighlightMode] = useState<"tap" | "ocr_box">("tap");
  const [problemImage, setProblemImage] = useState<File | null>(null);
  const [problemPreviewUrl, setProblemPreviewUrl] = useState<string | null>(null);

  const [brushColor, setBrushColor] = useState("#17212a");
  const [brushSize, setBrushSize] = useState(3);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [history, setHistory] = useState<HistoryResponse>(EMPTY_HISTORY);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<FeedbackTab>("mistakes");
  const [selectedIndex, setSelectedIndex] = useState(0);

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

  const pollAnalysis = useCallback(
    async (analysisId: string) => {
      for (let attempt = 0; attempt < 40; attempt += 1) {
        const detail = await fetchAnalysis(analysisId);
        setAnalysis(detail);
        if (detail.status === "done" || detail.status === "failed") {
          await refreshHistory();
          return;
        }
        await wait(1200);
      }
    },
    [refreshHistory],
  );

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
          <button className="primaryBtn" onClick={runAnalysis} disabled={isSubmitting}>
            {isSubmitting ? "채점 중..." : "채점 실행"}
          </button>
        </div>
      </header>

      {error && <p className="errorText">{error}</p>}
      {info && <p className="okText">{info}</p>}

      <section className="workspace">
        {problemPreviewUrl && (
          <aside className="problemPreview">
            <strong>문제 이미지</strong>
            <img src={problemPreviewUrl} alt="problem preview" />
          </aside>
        )}

        <NoteCanvas
          ref={canvasRef}
          brushColor={brushColor}
          brushSize={brushSize}
          overlays={overlays}
          annotationMode={needsTapAnnotation}
          onAnnotationTap={handleAnnotationTap}
        />

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
    </main>
  );
}

