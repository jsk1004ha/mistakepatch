from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import settings


def _resolve(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (settings.base_dir / path).resolve()


def ensure_paths() -> None:
    db_parent = _resolve(settings.db_path).parent
    db_parent.mkdir(parents=True, exist_ok=True)
    _resolve(settings.storage_path).mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_paths()
    conn = sqlite3.connect(_resolve(settings.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction() -> sqlite3.Connection:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with transaction() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                subject TEXT NOT NULL,
                solution_img_path TEXT NOT NULL,
                problem_img_path TEXT
            );

            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL,
                status TEXT NOT NULL,
                score_total REAL,
                rubric_json TEXT,
                result_json TEXT,
                confidence REAL,
                error_code TEXT,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mistakes (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                order_idx INTEGER NOT NULL,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                points_deducted REAL NOT NULL,
                evidence TEXT NOT NULL,
                fix_instruction TEXT NOT NULL,
                location_hint TEXT NOT NULL,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS annotations (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                mistake_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                shape TEXT NOT NULL,
                x REAL,
                y REAL,
                w REAL,
                h REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
                FOREIGN KEY (mistake_id) REFERENCES mistakes(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mistakes_analysis_id ON mistakes(analysis_id, order_idx);
            CREATE INDEX IF NOT EXISTS idx_annotations_analysis_id ON annotations(analysis_id);
            """
        )

