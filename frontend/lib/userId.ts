const USER_ID_STORAGE_KEY = "mistakepatch:user-id";
const USER_ID_FALLBACK = "u_local_runtime";

function buildRandomUserId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `u_${crypto.randomUUID().replace(/-/g, "")}`;
  }
  const time = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2);
  return `u_${time}_${random}`;
}

function normalizeUserId(raw: string): string {
  const cleaned = raw.trim().replace(/[^A-Za-z0-9._-]/g, "");
  if (!cleaned) {
    return "";
  }
  return cleaned.slice(0, 64);
}

export function getOrCreateUserId(): string {
  if (typeof window === "undefined") {
    return USER_ID_FALLBACK;
  }

  const stored = window.localStorage.getItem(USER_ID_STORAGE_KEY);
  const normalizedStored = stored ? normalizeUserId(stored) : "";
  if (normalizedStored) {
    if (stored !== normalizedStored) {
      window.localStorage.setItem(USER_ID_STORAGE_KEY, normalizedStored);
    }
    return normalizedStored;
  }

  const generated = normalizeUserId(buildRandomUserId()) || USER_ID_FALLBACK;
  window.localStorage.setItem(USER_ID_STORAGE_KEY, generated);
  return generated;
}
