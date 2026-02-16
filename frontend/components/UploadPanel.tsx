"use client";

import { useState, type FormEvent } from "react";

import type { Subject } from "@/lib/types";

interface UploadPanelProps {
  isSubmitting: boolean;
  onSubmit: (payload: {
    solutionImage: File;
    problemImage?: File;
    subject: Subject;
    highlightMode: "tap" | "ocr_box";
  }) => Promise<void>;
}

export function UploadPanel({ isSubmitting, onSubmit }: UploadPanelProps) {
  const [solutionImage, setSolutionImage] = useState<File | null>(null);
  const [problemImage, setProblemImage] = useState<File | null>(null);
  const [subject, setSubject] = useState<Subject>("math");
  const [highlightMode, setHighlightMode] = useState<"tap" | "ocr_box">("tap");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!solutionImage) {
      setError("풀이 이미지는 필수입니다.");
      return;
    }
    setError(null);
    await onSubmit({
      solutionImage,
      problemImage: problemImage ?? undefined,
      subject,
      highlightMode,
    });
  };

  return (
    <section className="panel">
      <h2>업로드</h2>
      <form className="uploadForm" onSubmit={handleSubmit}>
        <label>
          풀이 이미지 (필수)
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => setSolutionImage(event.target.files?.[0] ?? null)}
          />
        </label>

        <label>
          문제 이미지 (선택)
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => setProblemImage(event.target.files?.[0] ?? null)}
          />
        </label>

        <div className="inlineGrid">
          <label>
            과목
            <select value={subject} onChange={(event) => setSubject(event.target.value as Subject)}>
              <option value="math">수학</option>
              <option value="physics">물리</option>
            </select>
          </label>

          <label>
            하이라이트 모드
            <select
              value={highlightMode}
              onChange={(event) => setHighlightMode(event.target.value as "tap" | "ocr_box")}
            >
              <option value="tap">탭 기반 (안정)</option>
              <option value="ocr_box">OCR 보조 박스</option>
            </select>
          </label>
        </div>

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "채점 중..." : "채점하기"}
        </button>
      </form>
      {error && <p className="errorText">{error}</p>}
    </section>
  );
}

