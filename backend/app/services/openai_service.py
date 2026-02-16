from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

try:
    from openai import APITimeoutError, OpenAI
except Exception:  # pragma: no cover - optional dependency at runtime
    APITimeoutError = TimeoutError  # type: ignore[assignment]
    OpenAI = None  # type: ignore[assignment]

from ..config import settings
from ..schemas import ANALYSIS_RESULT_JSON_SCHEMA, SYSTEM_PROMPT


class OpenAIService:
    def __init__(self) -> None:
        if OpenAI is None:
            raise RuntimeError("openai package is not installed.")
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        self._client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds)

    def analyze_solution(
        self,
        solution_image_path: str,
        problem_image_path: str | None,
        subject: str,
        highlight_mode: str,
    ) -> dict[str, Any]:
        messages = self._build_input(solution_image_path, problem_image_path, subject, highlight_mode)
        payload: dict[str, Any] | None = None
        try:
            payload = self._request(messages)
        except APITimeoutError:
            payload = self._request(messages)
        if payload is None:
            raise RuntimeError("Failed to parse model response.")
        return payload

    def _request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._client.responses.create(
            model=settings.openai_model,
            input=messages,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "analysis_result",
                    "schema": ANALYSIS_RESULT_JSON_SCHEMA,
                    "strict": True,
                }
            },
        )
        parsed = self._extract_json(response)
        if parsed is None:
            raise RuntimeError("Model response did not contain valid JSON.")
        return parsed

    def _build_input(
        self,
        solution_image_path: str,
        problem_image_path: str | None,
        subject: str,
        highlight_mode: str,
    ) -> list[dict[str, Any]]:
        user_text = (
            f"subject={subject}\n"
            f"highlight_mode={highlight_mode}\n"
            "Score with rubric and return mistakes, patch, checklist in Korean."
        )
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": user_text},
            self._image_content(solution_image_path),
        ]
        if problem_image_path:
            content.append(self._image_content(problem_image_path))

        return [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {"role": "user", "content": content},
        ]

    def _image_content(self, image_path: str) -> dict[str, Any]:
        path = Path(image_path)
        image_bytes = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any] | None:
        if hasattr(response, "output_text") and response.output_text:
            try:
                return json.loads(response.output_text)
            except json.JSONDecodeError:
                pass

        output = getattr(response, "output", None)
        if not output:
            return None

        for item in output:
            content_items = getattr(item, "content", None)
            if not content_items:
                continue
            for content in content_items:
                text = getattr(content, "text", None)
                if not text:
                    continue
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    continue
        return None
