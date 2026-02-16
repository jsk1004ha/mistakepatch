from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .db import get_connection, transaction


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_submission(subject: str, solution_img_path: str, problem_img_path: str | None) -> str:
    submission_id = f"s_{uuid.uuid4().hex}"
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO submissions (id, created_at, subject, solution_img_path, problem_img_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (submission_id, _now_iso(), subject, solution_img_path, problem_img_path),
        )
    return submission_id


def create_analysis(submission_id: str) -> str:
    analysis_id = f"a_{uuid.uuid4().hex}"
    now = _now_iso()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO analyses (
                id, submission_id, status, score_total, rubric_json, result_json, confidence,
                error_code, fallback_used, created_at, updated_at
            ) VALUES (?, ?, 'queued', NULL, NULL, NULL, NULL, NULL, 0, ?, ?)
            """,
            (analysis_id, submission_id, now, now),
        )
    return analysis_id


def set_analysis_status(analysis_id: str, status: str, error_code: str | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            """
            UPDATE analyses
            SET status = ?, error_code = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, error_code, _now_iso(), analysis_id),
        )


def save_analysis_result(
    analysis_id: str,
    result: dict[str, Any],
    fallback_used: bool = False,
    error_code: str | None = None,
) -> None:
    rubric_json = json.dumps(result.get("rubric_scores", {}), ensure_ascii=False)
    result_json = json.dumps(result, ensure_ascii=False)
    score_total = result.get("score_total")
    confidence = result.get("confidence")

    with transaction() as conn:
        conn.execute(
            """
            UPDATE analyses
            SET status = 'done',
                score_total = ?,
                rubric_json = ?,
                result_json = ?,
                confidence = ?,
                fallback_used = ?,
                error_code = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                score_total,
                rubric_json,
                result_json,
                confidence,
                1 if fallback_used else 0,
                error_code,
                _now_iso(),
                analysis_id,
            ),
        )

        conn.execute("DELETE FROM mistakes WHERE analysis_id = ?", (analysis_id,))
        for idx, mistake in enumerate(result.get("mistakes", [])):
            mistake_id = f"m_{uuid.uuid4().hex}"
            conn.execute(
                """
                INSERT INTO mistakes (
                    id, analysis_id, order_idx, type, severity, points_deducted,
                    evidence, fix_instruction, location_hint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mistake_id,
                    analysis_id,
                    idx,
                    mistake.get("type"),
                    mistake.get("severity"),
                    mistake.get("points_deducted"),
                    mistake.get("evidence"),
                    mistake.get("fix_instruction"),
                    mistake.get("location_hint"),
                ),
            )


def mark_analysis_failed(analysis_id: str, error_code: str) -> None:
    with transaction() as conn:
        conn.execute(
            """
            UPDATE analyses
            SET status = 'failed', error_code = ?, updated_at = ?
            WHERE id = ?
            """,
            (error_code, _now_iso(), analysis_id),
        )


def get_submission(submission_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, created_at, subject, solution_img_path, problem_img_path
            FROM submissions
            WHERE id = ?
            """,
            (submission_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        header = conn.execute(
            """
            SELECT a.id, a.submission_id, a.status, a.result_json, a.error_code, a.fallback_used,
                   a.created_at, a.updated_at,
                   s.subject, s.solution_img_path, s.problem_img_path
            FROM analyses a
            INNER JOIN submissions s ON s.id = a.submission_id
            WHERE a.id = ?
            """,
            (analysis_id,),
        ).fetchone()
        if not header:
            return None

        result_obj: dict[str, Any] | None = None
        if header["result_json"]:
            result_obj = json.loads(header["result_json"])

        mistake_rows = conn.execute(
            """
            SELECT id, order_idx
            FROM mistakes
            WHERE analysis_id = ?
            ORDER BY order_idx ASC
            """,
            (analysis_id,),
        ).fetchall()
        annotations = conn.execute(
            """
            SELECT mistake_id, mode, shape, x, y, w, h
            FROM annotations
            WHERE analysis_id = ?
            ORDER BY created_at DESC
            """,
            (analysis_id,),
        ).fetchall()
        annotation_by_mistake = {}
        for row in annotations:
            row_dict = dict(row)
            annotation_by_mistake.setdefault(row_dict["mistake_id"], row_dict)

        if result_obj:
            for idx, mistake in enumerate(result_obj.get("mistakes", [])):
                if idx < len(mistake_rows):
                    mistake_id = mistake_rows[idx]["id"]
                    mistake["mistake_id"] = mistake_id
                    annotation = annotation_by_mistake.get(mistake_id)
                    if annotation:
                        highlight = dict(mistake.get("highlight") or {})
                        highlight.update(
                            {
                                "mode": annotation["mode"],
                                "shape": annotation["shape"],
                                "x": annotation["x"],
                                "y": annotation["y"],
                                "w": annotation["w"],
                                "h": annotation["h"],
                            }
                        )
                        mistake["highlight"] = highlight

        return {
            "analysis_id": header["id"],
            "submission_id": header["submission_id"],
            "status": header["status"],
            "subject": header["subject"],
            "solution_img_path": header["solution_img_path"],
            "problem_img_path": header["problem_img_path"],
            "result": result_obj,
            "fallback_used": bool(header["fallback_used"]),
            "error_code": header["error_code"],
            "created_at": header["created_at"],
            "updated_at": header["updated_at"],
        }


def create_annotation(
    analysis_id: str,
    mistake_id: str,
    mode: str,
    shape: str,
    x: float | None,
    y: float | None,
    w: float | None,
    h: float | None,
) -> str:
    annotation_id = f"ann_{uuid.uuid4().hex}"
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO annotations (id, analysis_id, mistake_id, mode, shape, x, y, w, h, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (annotation_id, analysis_id, mistake_id, mode, shape, x, y, w, h, _now_iso()),
        )
    return annotation_id


def mistake_exists(analysis_id: str, mistake_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM mistakes
            WHERE analysis_id = ? AND id = ?
            """,
            (analysis_id, mistake_id),
        ).fetchone()
        return row is not None


def list_history(limit: int = 5) -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id AS analysis_id,
                   s.subject AS subject,
                   a.score_total AS score_total,
                   a.status AS status,
                   a.created_at AS created_at,
                   m.type AS top_tag
            FROM analyses a
            INNER JOIN submissions s ON s.id = a.submission_id
            LEFT JOIN mistakes m ON m.analysis_id = a.id AND m.order_idx = 0
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        tags = conn.execute(
            """
            SELECT m.type AS type, COUNT(*) AS count
            FROM mistakes m
            INNER JOIN analyses a ON a.id = m.analysis_id
            WHERE a.status = 'done'
            GROUP BY m.type
            ORDER BY count DESC
            LIMIT 3
            """
        ).fetchall()

    return {
        "items": [dict(row) for row in rows],
        "top_tags": [dict(row) for row in tags],
    }

