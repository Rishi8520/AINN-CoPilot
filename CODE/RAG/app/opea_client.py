"""Strict adapter for OPEA's GeneratedDoc response, not OpenAI's choices schema."""

import json
from urllib.parse import urlsplit

import httpx

from app.llm_client import LLMClientError, LLMCompletion


def complete_opea(base_url, prompt, timeout_seconds=120):
    if len(prompt) > 24000:
        raise LLMClientError("opea_input_limit", "Evidence request exceeds the OPEA input limit.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LLMClientError("configuration", "OPEA_AGENT_URL must be a credential-free HTTP(S) base URL.")
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=5), trust_env=False) as client:
            response = client.post(base_url.rstrip("/") + "/v1/chat/completions",
                                   json={"messages": prompt, "stream": False})
            response.raise_for_status()
            envelope = response.json()
            text = envelope.get("text") if isinstance(envelope, dict) else None
            if not isinstance(text, str) or len(text) > 32000:
                raise ValueError("Invalid envelope")
            result = json.loads(text)
            if not isinstance(result, dict) or result.get("status") != "ok":
                raise ValueError("Missing success envelope")
            answer = result.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("Missing answer")
            return LLMCompletion(content=answer.strip())
    except httpx.TimeoutException as error:
        raise LLMClientError("opea_timeout", "OPEA reasoning timed out.") from error
    except httpx.HTTPStatusError as error:
        raise LLMClientError("opea_http_error", f"OPEA returned HTTP {error.response.status_code}.") from error
    except httpx.RequestError as error:
        raise LLMClientError("opea_connection", "OPEA reasoning service is unavailable.") from error
    except (ValueError, TypeError) as error:
        # OPEA can return exception strings inside successful HTTP responses.
        raise LLMClientError("opea_invalid_response", "OPEA did not return a valid structured answer.") from error
