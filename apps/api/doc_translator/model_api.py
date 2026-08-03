from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx


logger = logging.getLogger(__name__)

_ERROR_BODY_LIMIT = 600
_MAX_ATTEMPTS = 4
_INITIAL_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 8.0
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_JSON_WRAPPER_INSTRUCTION = (
    '\n\nReturn a JSON object with exactly one field named "result". '
    "The value of result must be the JSON value requested above."
)


class ModelApiFormat(StrEnum):
    ANTHROPIC_MESSAGES = "anthropic_messages"
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


class ModelApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelCompletion:
    text: str
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


class ModelApiClient:
    def __init__(
        self,
        *,
        api_format: ModelApiFormat,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_connections: int | None = 1,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        self.api_format = api_format
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_attempts = max_attempts
        self.client = httpx.Client(
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_connections,
            ),
            timeout=httpx.Timeout(
                timeout_seconds,
                connect=min(30.0, float(timeout_seconds)),
                read=timeout_seconds,
                write=min(30.0, float(timeout_seconds)),
                pool=10.0,
            ),
        )

    def close(self) -> None:
        self.client.close()

    def list_models(self) -> list[str]:
        if self.api_format == ModelApiFormat.ANTHROPIC_MESSAGES:
            endpoint = self._endpoint("/v1/models")
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
        else:
            endpoint = self._endpoint("/models")
            headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = self._request_json(endpoint, headers=headers, method="GET")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ModelApiError(f"{self.api_format.value} Models API returned an unexpected response")
        return list(
            dict.fromkeys(
                item["id"]
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
            )
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> ModelCompletion:
        request_messages = self._with_json_wrapper_instruction(messages) if json_mode else messages
        match self.api_format:
            case ModelApiFormat.ANTHROPIC_MESSAGES:
                return self._complete_anthropic(request_messages, max_tokens=max_tokens, json_mode=json_mode)
            case ModelApiFormat.CHAT_COMPLETIONS:
                return self._complete_chat(request_messages, max_tokens=max_tokens, json_mode=json_mode)
            case ModelApiFormat.RESPONSES:
                return self._complete_responses(request_messages, max_tokens=max_tokens, json_mode=json_mode)

    def _complete_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        json_mode: bool,
    ) -> ModelCompletion:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        body["thinking"] = {"type": "disabled"}
        payload = self._request_json(
            self._endpoint("/chat/completions"),
            headers={"Authorization": f"Bearer {self.api_key}"},
            body=body,
        )
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelApiError("Chat Completions API returned an unexpected response") from exc
        choice = payload["choices"][0]
        if (not isinstance(text, str) or not text.strip()) and choice.get("finish_reason") == "length":
            raise ModelApiError(
                "Chat Completions API used the entire output token limit before producing an answer; "
                "increase the output token limit or choose a model with less reasoning"
            )
        return self._completion(text, payload.get("usage"), json_mode=json_mode, usage_format="chat")

    def _complete_anthropic(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        json_mode: bool,
    ) -> ModelCompletion:
        system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [message for message in messages if message["role"] != "system"],
        }
        if system:
            body["system"] = system
        payload = self._request_json(
            self._endpoint("/v1/messages"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            body=body,
        )
        content = payload.get("content")
        if not isinstance(content, list):
            raise ModelApiError("Anthropic Messages API returned an unexpected response")
        text = "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        )
        return self._completion(text, payload.get("usage"), json_mode=json_mode, usage_format="anthropic")

    def _complete_responses(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        json_mode: bool,
    ) -> ModelCompletion:
        body: dict[str, Any] = {
            "model": self.model,
            "input": messages,
            "temperature": 0,
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": "none"},
        }
        if json_mode:
            body["text"] = {"format": {"type": "json_object"}}
        payload = self._request_json(
            self._endpoint("/responses"),
            headers={"Authorization": f"Bearer {self.api_key}"},
            body=body,
        )
        output = payload.get("output")
        if not isinstance(output, list):
            raise ModelApiError("Responses API returned an unexpected response")
        text_parts = [
            part["text"]
            for item in output
            if isinstance(item, dict) and item.get("type") == "message" and isinstance(item.get("content"), list)
            for part in item["content"]
            if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str)
        ]
        return self._completion("".join(text_parts), payload.get("usage"), json_mode=json_mode, usage_format="responses")

    def _completion(
        self,
        text: Any,
        usage: Any,
        *,
        json_mode: bool,
        usage_format: str,
    ) -> ModelCompletion:
        if not isinstance(text, str) or not text.strip():
            raise ModelApiError(f"{self.api_format.value} API returned empty model output")
        output_text = text.strip()
        if json_mode:
            try:
                value = json.loads(output_text)
            except json.JSONDecodeError as exc:
                raise ModelApiError(f"{self.api_format.value} API returned invalid JSON output") from exc
            return self._completion_from_json_value(value, usage, usage_format=usage_format)
        token_usage = self._token_usage(usage, usage_format)
        return ModelCompletion(text=output_text, **token_usage)

    def _completion_from_json_value(self, value: Any, usage: Any, *, usage_format: str) -> ModelCompletion:
        if not isinstance(value, dict) or "result" not in value:
            raise ModelApiError(f'{self.api_format.value} API JSON output must contain a "result" field')
        token_usage = self._token_usage(usage, usage_format)
        return ModelCompletion(text=json.dumps(value["result"], ensure_ascii=False), **token_usage)

    @staticmethod
    def _token_usage(usage: Any, usage_format: str) -> dict[str, int]:
        if not isinstance(usage, dict):
            return {}
        if usage_format == "chat":
            input_tokens = int(usage.get("prompt_tokens") or 0)
            output_tokens = int(usage.get("completion_tokens") or 0)
            details = usage.get("prompt_tokens_details") or {}
            cached_input_tokens = int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
        else:
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            details = usage.get("input_tokens_details") or {}
            cached_input_tokens = int(details.get("cached_tokens") or usage.get("cache_read_input_tokens") or 0)
        return {
            "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
        }

    def _request_json(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
        method: str = "POST",
    ) -> dict[str, Any]:
        request_headers = {"Content-Type": "application/json", **headers}
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                request_kwargs: dict[str, Any] = {"headers": request_headers}
                if body is not None:
                    request_kwargs["json"] = body
                response = self.client.request(method, endpoint, **request_kwargs)
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    raise httpx.HTTPStatusError(
                        f"Retryable status code {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ModelApiError("Model API returned a non-object JSON response")
                return payload
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code not in _RETRYABLE_STATUS_CODES or attempt + 1 >= self.max_attempts:
                    summary = re.sub(r"\s+", " ", exc.response.text.strip())[:_ERROR_BODY_LIMIT].strip()
                    reason = exc.response.reason_phrase or "HTTP error"
                    detail = f": {summary}" if summary else ""
                    raise ModelApiError(f"Model API request failed with {status_code} {reason}{detail}") from exc
                last_error = exc
            except httpx.RequestError as exc:
                if attempt + 1 >= self.max_attempts:
                    raise ModelApiError(f"Model API request failed after {self.max_attempts} attempts: {exc}") from exc
                last_error = exc
            except ValueError as exc:
                raise ModelApiError("Model API returned invalid JSON") from exc

            delay = min(_MAX_BACKOFF_SECONDS, _INITIAL_BACKOFF_SECONDS * (2**attempt))
            logger.warning(
                "Model API request failed, retrying",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": self.max_attempts,
                    "delay_seconds": delay,
                    "endpoint": endpoint,
                    "error": str(last_error),
                },
            )
            time.sleep(delay)
        raise ModelApiError("Model API request failed unexpectedly")

    def _endpoint(self, path: str) -> str:
        if self.base_url.endswith(path):
            return self.base_url
        if path.startswith("/v1/") and self.base_url.endswith("/v1"):
            return f"{self.base_url}{path[3:]}"
        return f"{self.base_url}{path}"

    @staticmethod
    def _with_json_wrapper_instruction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        wrapped = [message.copy() for message in messages]
        for message in reversed(wrapped):
            if message["role"] == "user":
                message["content"] += _JSON_WRAPPER_INSTRUCTION
                return wrapped
        raise ModelApiError("JSON mode requires a user message")
