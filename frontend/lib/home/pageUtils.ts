import type { AnalysisDetail } from "@/lib/types";

export const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function createNoteId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const AUTOSAVE_DEDUPE_KEY = "mistakepatch:notebooks:autosaved-analysis-ids";

export function loadAutosavedAnalysisIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(AUTOSAVE_DEDUPE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    const ids = parsed.filter((item): item is string => typeof item === "string");
    return new Set(ids);
  } catch {
    return new Set();
  }
}

export function saveAutosavedAnalysisIds(ids: Set<string>) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(AUTOSAVE_DEDUPE_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    // Non-blocking best effort key for dedupe across reloads.
  }
}

export function buildNoteTags(detail: AnalysisDetail): string[] {
  if (!detail.result?.mistakes?.length) return [];
  const uniqueTags = new Set<string>();
  for (const mistake of detail.result.mistakes) {
    uniqueTags.add(mistake.type);
    if (uniqueTags.size >= 3) break;
  }
  return Array.from(uniqueTags);
}
