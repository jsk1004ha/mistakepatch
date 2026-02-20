import type {
  AnalysisDetail,
  AnalyzeQueuedResponse,
  AnnotationPayload,
  HistoryResponse,
  HighlightMode,
  Subject,
} from "@/lib/types";
import { getOrCreateUserId } from "@/lib/userId";

export type HealthResponse = {
  status: string;
  queue_mode: string;
  enable_ocr_hints: boolean;
};

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function toAbsoluteImageUrl(relativePath: string): string {
  if (!relativePath) return "";
  if (relativePath.startsWith("http://") || relativePath.startsWith("https://")) {
    return relativePath;
  }
  return `${API_BASE_URL}${relativePath}`;
}

export function getAnalysisEventsUrl(analysisId: string): string {
  const userId = encodeURIComponent(getOrCreateUserId());
  return `${API_BASE_URL}/api/v1/analysis/${analysisId}/events?user_id=${userId}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const userId = getOrCreateUserId();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "X-User-Id": userId,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body?.detail ?? message;
    } catch {
      // Ignore parse errors.
    }
    throw new Error(`${response.status}: ${message}`);
  }
  return (await response.json()) as T;
}

export async function createAnalysis(params: {
  solutionImage: File;
  problemImage?: File;
  subject: Subject;
  highlightMode: Extract<HighlightMode, "tap" | "ocr_box">;
}): Promise<AnalyzeQueuedResponse> {
  const formData = new FormData();
  formData.append("solution_image", params.solutionImage);
  if (params.problemImage) {
    formData.append("problem_image", params.problemImage);
  }
  formData.append(
    "meta",
    JSON.stringify({
      subject: params.subject,
      highlight_mode: params.highlightMode,
    }),
  );

  return requestJson<AnalyzeQueuedResponse>("/api/v1/analyze", {
    method: "POST",
    body: formData,
  });
}

export async function fetchAnalysis(analysisId: string): Promise<AnalysisDetail> {
  return requestJson<AnalysisDetail>(`/api/v1/analysis/${analysisId}`);
}

export async function createAnnotation(payload: AnnotationPayload): Promise<void> {
  await requestJson("/api/v1/annotations", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function fetchHistory(limit = 5): Promise<HistoryResponse> {
  return requestJson<HistoryResponse>(`/api/v1/history?limit=${limit}`);
}

export async function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/v1/health");
}

