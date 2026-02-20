import { NotebooksState, VersionedState, Notebook } from "./types";

export const STORAGE_KEY = "mistakepatch:notebooks";
export const CURRENT_VERSION = 3;

export const SYSTEM_NOTEBOOK_IDS = {
  INBOX: "inbox",
  TRASH: "trash",
} as const;

export function createDefaultState(): NotebooksState {
  return {
    notebooks: {
      [SYSTEM_NOTEBOOK_IDS.INBOX]: {
        id: SYSTEM_NOTEBOOK_IDS.INBOX,
        name: "수신함",
        system: true,
        sortOrder: 0,
        createdAt: new Date().toISOString(),
      },
      [SYSTEM_NOTEBOOK_IDS.TRASH]: {
        id: SYSTEM_NOTEBOOK_IDS.TRASH,
        name: "휴지통",
        system: true,
        sortOrder: 1,
        createdAt: new Date().toISOString(),
      },
    },
    notes: {},
  };
}

export function resetState(): NotebooksState {
  const state = createDefaultState();
  if (typeof window === "undefined") return state;

  const versioned: VersionedState = {
    v: CURRENT_VERSION,
    state,
  };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(versioned));
  } catch (e) {
    console.error("Failed to reset localStorage", e);
  }
  return state;
}

export function loadState(): NotebooksState {
  if (typeof window === "undefined") return createDefaultState();

  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return resetState();

  try {
    const parsed = JSON.parse(raw);
    
    // Basic structural check
    if (!parsed || typeof parsed !== "object" || !("v" in parsed)) {
      console.warn("Invalid storage format, resetting...");
      return resetState();
    }

    const versioned = parsed as VersionedState;

    if (versioned.v > CURRENT_VERSION) {
      console.warn("Future version detected, resetting to avoid corruption...");
      return resetState();
    }

    if (versioned.v < CURRENT_VERSION) {
      return migrate(versioned);
    }

    // Validation: ensure system notebooks exist
    if (!versioned.state.notebooks[SYSTEM_NOTEBOOK_IDS.INBOX] || 
        !versioned.state.notebooks[SYSTEM_NOTEBOOK_IDS.TRASH]) {
      console.warn("Missing system notebooks, resetting...");
      return resetState();
    }

    return versioned.state;
  } catch (e) {
    console.error("Failed to parse localStorage", e);
    return resetState();
  }
}

export function saveState(state: NotebooksState): void {
  if (typeof window === "undefined") return;

  const versioned: VersionedState = {
    v: CURRENT_VERSION,
    state,
  };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(versioned));
  } catch (e) {
    console.error("Failed to save to localStorage", e);
    throw new Error("STORAGE_WRITE_FAILURE");
  }
}

export function ensureInitialized(): NotebooksState {
  return loadState();
}

function migrate(old: VersionedState): NotebooksState {
  let currentState = old.state;
  let currentV = old.v;
  let migrated = false;

  // v1 -> v2: Add previousNotebookId to all notes
  if (currentV === 1) {
    const notes = { ...currentState.notes };
    for (const id in notes) {
      notes[id] = { ...notes[id], previousNotebookId: null };
    }
    currentState = { ...currentState, notes };
    currentV = 2;
    migrated = true;
  }

  // v2 -> v3: Ensure system notebooks exist and normalize system names
  if (currentV === 2) {
    const defaults = createDefaultState().notebooks;
    const notebooks = { ...currentState.notebooks };

    const inbox: Notebook = {
      ...(notebooks[SYSTEM_NOTEBOOK_IDS.INBOX] ?? defaults[SYSTEM_NOTEBOOK_IDS.INBOX]),
      id: SYSTEM_NOTEBOOK_IDS.INBOX,
      name: "수신함",
      system: true,
      sortOrder: 0,
    };

    const trash: Notebook = {
      ...(notebooks[SYSTEM_NOTEBOOK_IDS.TRASH] ?? defaults[SYSTEM_NOTEBOOK_IDS.TRASH]),
      id: SYSTEM_NOTEBOOK_IDS.TRASH,
      name: "휴지통",
      system: true,
      sortOrder: 1,
    };

    notebooks[SYSTEM_NOTEBOOK_IDS.INBOX] = inbox;
    notebooks[SYSTEM_NOTEBOOK_IDS.TRASH] = trash;

    currentState = { ...currentState, notebooks };
    currentV = 3;
    migrated = true;
  }
  
  // For now, if it's not current, we just reset or handle specific jumps
  if (currentV !== CURRENT_VERSION) {
    return resetState();
  }

  if (migrated && typeof window !== "undefined") {
    const versioned: VersionedState = {
      v: currentV,
      state: currentState,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(versioned));
    } catch (e) {
      console.warn("Failed to persist migrated localStorage state", e);
    }
  }

  return currentState;
}
