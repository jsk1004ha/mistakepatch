import { AnalysisResult, Subject } from "../types";

export interface Notebook {
  id: string;
  name: string;
  system?: boolean;
  sortOrder: number;
  createdAt: string;
}

export interface NoteSnapshot extends Omit<AnalysisResult, "missing_info"> {
  fallback_used?: boolean;
  error_code?: string | null;
}

export interface Note {
  id: string;
  analysisId: string;
  subject: Subject;
  createdAt: string;
  scoreTotal: number | null;
  notebookId: string;
  previousNotebookId?: string | null;
  trashedAt?: string | null;
  tags: string[];
  snapshot: NoteSnapshot;
}

export interface NotebooksState {
  notebooks: Record<string, Notebook>;
  notes: Record<string, Note>;
}

export interface VersionedState {
  v: number;
  state: NotebooksState;
}
