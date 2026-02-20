from __future__ import annotations

import base64
import json
import mimetypes
import re
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

        if settings.openai_api_key:
            self._provider = "openai"
            self._model = settings.openai_model
            self._client = OpenAI(
                api_key=settings.openai_api_key,
                organization=settings.openai_organization or None,
                project=settings.openai_project or None,
                timeout=settings.openai_timeout_seconds,
            )
            self._supports_responses_api = hasattr(self._client, "responses")
            return

        if settings.groq_api_key:
            self._provider = "groq"
            configured_model = (settings.groq_model or "").strip()
            self._model = configured_model or "llama-3.1-8b-instant"
            self._client = OpenAI(
                api_key=settings.groq_api_key,
                base_url=settings.groq_base_url,
                timeout=settings.openai_timeout_seconds,
            )
            # Groq uses the OpenAI-compatible Chat API, not Responses API.
            self._supports_responses_api = False
            return

        raise RuntimeError("Neither OPENAI_API_KEY nor GROQ_API_KEY is configured.")

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

    @staticmethod
    def _build_user_text(subject: str, highlight_mode: str) -> str:
        return (
            f"subject={subject}\n"
            f"highlight_mode={highlight_mode}\n"
            "Grade the student solution with the provided rubric.\n"
            "Return Korean feedback for deductions, minimal patch, and checklist.\n"
            "Do not output full tutoring unless required for minimal correction.\n"
            "Use concise evidence-based mistakes and conservative confidence."
        )

    def _request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self._supports_responses_api:
            response = self._client.responses.create(
                model=self._model,
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
            if self._provider == "groq":
                response = self._request_with_groq(messages)
            else:
                response = self._client.chat.completions.create(
                    model=self._model,
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

    def _request_with_groq(self, messages: list[dict[str, Any]]) -> Any:
        # Prefer JSON-mode for Groq. If the model requires string-only content,
        # convert multimodal message arrays to a text-compatible fallback and retry.
        try:
            return self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        except Exception as exc:
            if not self._should_retry_with_text_messages(exc):
                return self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0.1,
                )

        compatible_messages = self._to_text_only_messages(messages)
        try:
            return self._client.chat.completions.create(
                model=self._model,
                messages=compatible_messages,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        except Exception:
            return self._client.chat.completions.create(
                model=self._model,
                messages=compatible_messages,
                temperature=0.1,
            )

    @staticmethod
    def _should_retry_with_text_messages(exc: Exception) -> bool:
        message = str(exc).lower()
        retry_hints = (
            "content must be a string",
            "messages[1].content",
            "invalid image",
            "image_url",
            "unsupported content",
        )
        return any(hint in message for hint in retry_hints)

    @staticmethod
    def _to_text_only_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = message.get("content")
            if isinstance(content, str):
                normalized.append({"role": role, "content": content})
                continue

            if not isinstance(content, list):
                normalized.append({"role": role, "content": ""})
                continue

            parts: list[str] = []
            image_count = 0
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type in {"text", "input_text"}:
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
                    continue
                if item_type in {"image_url", "input_image"}:
                    image_count += 1

            if image_count > 0:
                parts.append(
                    f"[첨부 이미지 {image_count}개: 현재 Groq 호환 모드에서 직접 시각 입력이 제한되어 텍스트 컨텍스트 기반으로 처리]"
                )

            normalized.append({"role": role, "content": "\n".join(parts).strip()})
        return normalized

    def _build_responses_input(
        self,
        solution_image_path: str,
        problem_image_path: str | None,
        subject: str,
        highlight_mode: str,
    ) -> list[dict[str, Any]]:
        user_text = self._build_user_text(subject=subject, highlight_mode=highlight_mode)
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
        user_text = self._build_user_text(subject=subject, highlight_mode=highlight_mode)
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
            parsed_output_text = OpenAIService._parse_json_text(response.output_text)
            if parsed_output_text is not None:
                return parsed_output_text

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
                    parsed_text = OpenAIService._parse_json_text(text)
                    if parsed_text is not None:
                        return parsed_text

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
            return OpenAIService._parse_json_text(content)

        if not isinstance(content, list):
            return None

        for item in content:
            text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
            if not text:
                continue
            parsed_text = OpenAIService._parse_json_text(text)
            if parsed_text is not None:
                return parsed_text
        return None

    @staticmethod
    def _parse_json_text(text: str) -> dict[str, Any] | None:
        raw = text.strip()
        if not raw:
            return None

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw, flags=re.IGNORECASE)
        if fenced:
            block = fenced.group(1)
            try:
                parsed = json.loads(block)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                pass

        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            snippet = raw[start : end + 1]
            try:
                parsed = json.loads(snippet)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None
