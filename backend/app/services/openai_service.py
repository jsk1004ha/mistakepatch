from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

try:
    from openai import APITimeoutError, OpenAI
    _OPENAI_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - optional dependency at runtime
    APITimeoutError = TimeoutError  # type: ignore[assignment]
    OpenAI = None  # type: ignore[assignment]
    _OPENAI_IMPORT_ERROR = exc

from ..config import settings
from ..schemas import ANALYSIS_RESULT_JSON_SCHEMA, SYSTEM_PROMPT


class OpenAIService:
    def __init__(self) -> None:
        if OpenAI is None:
            reason = str(_OPENAI_IMPORT_ERROR) if _OPENAI_IMPORT_ERROR else "unknown import error"
            raise RuntimeError(
                "openai package is not installed or failed to import. "
                f"Reason: {reason}. Install backend dependencies first."
            )
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            organization=settings.openai_organization or None,
            project=settings.openai_project or None,
            timeout=settings.openai_timeout_seconds,
        )
        self._supports_responses_api = hasattr(self._client, "responses")

    def analyze_solution(
        self,
        solution_image_path: str,
        problem_image_path: str | None,
        subject: str,
        highlight_mode: str,
    ) -> dict[str, Any]:
        if self._supports_responses_api:
            messages = self._build_responses_input(
                solution_image_path, problem_image_path, subject, highlight_mode
            )
        else:
            messages = self._build_chat_messages(
                solution_image_path, problem_image_path, subject, highlight_mode
            )
        payload: dict[str, Any] | None = None
        try:
            payload = self._request(messages)
        except APITimeoutError:
            payload = self._request(messages)
        if payload is None:
            raise RuntimeError("Failed to parse model response.")
        return payload

    def _request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self._supports_responses_api:
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
        else:
            response = self._client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "analysis_result",
                        "schema": ANALYSIS_RESULT_JSON_SCHEMA,
                        "strict": True,
                    },
                },
            )
        parsed = self._extract_json(response)
        if parsed is None:
            raise RuntimeError("Model response did not contain valid JSON.")
        return parsed

    def _build_responses_input(
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
            self._responses_image_content(solution_image_path),
        ]
        if problem_image_path:
            content.append(self._responses_image_content(problem_image_path))

        return [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {"role": "user", "content": content},
        ]

    def _build_chat_messages(
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
            {"type": "text", "text": user_text},
            self._chat_image_content(solution_image_path),
        ]
        if problem_image_path:
            content.append(self._chat_image_content(problem_image_path))

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

    def _responses_image_content(self, image_path: str) -> dict[str, Any]:
        return {"type": "input_image", "image_url": self._image_data_url(image_path)}

    def _chat_image_content(self, image_path: str) -> dict[str, Any]:
        return {"type": "image_url", "image_url": {"url": self._image_data_url(image_path)}}

    def _image_data_url(self, image_path: str) -> str:
        path = Path(image_path)
        image_bytes = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any] | None:
        output_parsed = getattr(response, "output_parsed", None)
        if isinstance(output_parsed, dict):
            return output_parsed

        if hasattr(response, "output_text") and response.output_text:
            try:
                return json.loads(response.output_text)
            except json.JSONDecodeError:
                pass

        output = getattr(response, "output", None)
        if output:
            for item in output:
                content_items = getattr(item, "content", None)
                if not content_items:
                    continue
                for content in content_items:
                    parsed = getattr(content, "parsed", None)
                    if isinstance(parsed, dict):
                        return parsed
                    text = getattr(content, "text", None)
                    if not text:
                        continue
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        continue

        choices = getattr(response, "choices", None)
        if choices:
            for choice in choices:
                message = getattr(choice, "message", None)
                if message is None:
                    continue

                parsed = getattr(message, "parsed", None)
                if isinstance(parsed, dict):
                    return parsed

                content = getattr(message, "content", None)
                parsed_content = OpenAIService._parse_json_content(content)
                if parsed_content is not None:
                    return parsed_content
        return None

    @staticmethod
    def _parse_json_content(content: Any) -> dict[str, Any] | None:
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return None

        if not isinstance(content, list):
            return None

        for item in content:
            text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
            if not text:
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        return None
