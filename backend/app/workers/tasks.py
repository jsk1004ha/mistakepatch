from __future__ import annotations

from typing import Any

from app.services.analyzer import process_analysis_job


def run_analysis_job(payload: dict[str, Any]) -> None:
    process_analysis_job(payload)

