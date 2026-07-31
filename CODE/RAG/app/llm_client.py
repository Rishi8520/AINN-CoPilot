from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class LLMClientConfig:
    base_url: str
    provider: str
    model: str
    api_key: str = ""
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 30.0
    max_tokens: int = 512
    temperature: float = 0.0


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    response_model: str | None = None


class LLMClientError(Exception):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message

    def public_reason(self) -> str:
        return f"{self.category}: {self.message}"


def chat_completions_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise LLMClientError("configuration", "LLM_BASE_URL is required for OpenAI-compatible synthesis.")
    parts = urlsplit(normalized)
    path = parts.path.rstrip("/")
    if path.endswith("/v1/chat/completions"):
        final_path = path
    elif path.endswith("/v1"):
        final_path = f"{path}/chat/completions"
    else:
        final_path = f"{path}/v1/chat/completions"
    return urlunsplit((parts.scheme, parts.netloc, final_path, "", ""))


class OpenAICompatibleClient:
    def __init__(self, config: LLMClientConfig):
        self.config = config
        self.endpoint = chat_completions_endpoint(config.base_url)
        if not config.model.strip():
            raise LLMClientError("configuration", "LLM_MODEL is required for OpenAI-compatible synthesis.")

    def complete(self, messages: list[dict[str, str]]) -> LLMCompletion:
        payload = {
            "model": self.config.model.strip(),
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        timeout = httpx.Timeout(
            connect=self.config.connect_timeout_seconds,
            read=self.config.read_timeout_seconds,
            write=self.config.connect_timeout_seconds,
            pool=self.config.connect_timeout_seconds,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(self.endpoint, json=payload, headers=headers)
        except httpx.ConnectTimeout as exc:
            raise LLMClientError("connect_timeout", "connection to the LLM endpoint timed out") from exc
        except httpx.ReadTimeout as exc:
            raise LLMClientError("read_timeout", "LLM response timed out") from exc
        except httpx.ConnectError as exc:
            raise LLMClientError("connection_error", "LLM endpoint could not be reached") from exc
        except httpx.RequestError as exc:
            raise LLMClientError("request_error", "LLM request failed before a response was received") from exc

        if response.status_code in {401, 403}:
            raise LLMClientError("auth_error", f"LLM endpoint returned HTTP {response.status_code}")
        if response.status_code == 404:
            raise LLMClientError("not_found", "LLM endpoint returned HTTP 404")
        if response.status_code == 429:
            raise LLMClientError("rate_limited", "LLM endpoint returned HTTP 429")
        if 500 <= response.status_code:
            raise LLMClientError("server_error", f"LLM endpoint returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise LLMClientError("http_error", f"LLM endpoint returned HTTP {response.status_code}")

        content_type = response.headers.get("content-type", "").lower()
        if "json" not in content_type:
            raise LLMClientError("unexpected_content_type", "LLM endpoint did not return JSON")

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMClientError("malformed_json", "LLM endpoint returned malformed JSON") from exc

        return _parse_completion(body)


def _parse_completion(body: dict[str, Any]) -> LLMCompletion:
    if not isinstance(body, dict):
        raise LLMClientError("malformed_json", "LLM response JSON was not an object")
    choices = body.get("choices")
    if not isinstance(choices, list):
        raise LLMClientError("missing_choices", "LLM response did not include choices")
    if not choices:
        raise LLMClientError("empty_choices", "LLM response choices were empty")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMClientError("missing_message", "LLM response choice was not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMClientError("missing_message", "LLM response did not include a message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMClientError("empty_content", "LLM response content was empty")
    response_model = body.get("model")
    return LLMCompletion(
        content=content.strip(),
        response_model=response_model if isinstance(response_model, str) and response_model.strip() else None,
    )
