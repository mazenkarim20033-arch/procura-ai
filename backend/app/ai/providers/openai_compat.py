"""OpenAI-compatible chat-completions provider (Groq, OpenAI, Ollama, LM Studio...).

Behaviour: temperature 0, JSON-object output validated against a Pydantic schema; invalid output is
retried with the validation error fed back (up to `max_format_retries`); transient HTTP failures
(429/5xx/timeouts) are retried with exponential backoff. Token usage and latency are returned.
"""
import json
import time
from collections.abc import Callable

import httpx
from pydantic import ValidationError

from app.ai.providers.base import LLMError, LLMResult, T

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class OpenAICompatProvider:
    is_mock = False

    def __init__(
        self, *, base_url: str, api_key: str, model: str, name: str = "openai_compat", timeout: float = 60.0,
        max_http_retries: int = 3, max_format_retries: int = 2, sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ):
        self.name, self.model = name, model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self._max_http, self._max_format, self._sleep = max_http_retries, max_format_retries, sleep

    def _post(self, payload: dict) -> tuple[dict, int]:
        """POST with backoff. Returns (json, retries_used)."""
        last = "unknown error"
        for attempt in range(self._max_http + 1):
            try:
                r = self._client.post(self._url, headers=self._headers, json=payload)
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}"
            else:
                if r.status_code == 200:
                    return r.json(), attempt
                last = f"HTTP {r.status_code}"
                if r.status_code not in RETRYABLE_STATUS:
                    raise LLMError(f"{self.name}: {last} (not retryable): {r.text[:200]}")
            if attempt < self._max_http:
                self._sleep(min(2 ** attempt, 20))
        raise LLMError(f"{self.name}: gave up after {self._max_http + 1} attempts ({last})")

    def generate(self, *, system: str, user: str, schema: type[T], prompt_name: str, prompt_version: str) -> LLMResult[T]:
        schema_hint = json.dumps(schema.model_json_schema())
        messages = [
            {"role": "system", "content": f"{system}\n\nRespond with a single JSON object matching this JSON "
                                          f"schema, and nothing else:\n{schema_hint}"},
            {"role": "user", "content": user},
        ]
        start = time.perf_counter()
        in_tok = out_tok = 0
        retries = 0
        for format_attempt in range(self._max_format + 1):
            data, http_retries = self._post({
                "model": self.model, "messages": messages, "temperature": 0,
                "response_format": {"type": "json_object"},
            })
            retries += http_retries
            usage = data.get("usage") or {}
            in_tok += usage.get("prompt_tokens") or 0
            out_tok += usage.get("completion_tokens") or 0
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"{self.name}: malformed response envelope") from exc
            try:
                parsed = schema.model_validate_json(content)
            except (ValidationError, ValueError) as exc:
                if format_attempt == self._max_format:
                    raise LLMError(f"{self.name}: output failed schema validation after "
                                   f"{format_attempt + 1} attempts: {str(exc)[:200]}") from exc
                retries += 1
                messages = [*messages, {"role": "assistant", "content": content},
                            {"role": "user", "content": f"Your previous reply was invalid: {str(exc)[:500]}. "
                                                        "Reply again with only a valid JSON object."}]
                continue
            return LLMResult(parsed, self.name, self.model, in_tok or None, out_tok or None,
                             int((time.perf_counter() - start) * 1000), retries, False, content)
        raise LLMError("unreachable")
