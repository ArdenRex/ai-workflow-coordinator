"""Provider for any OpenAI-compatible Chat Completions API (OpenAI, Groq, Together, vLLM, ...).

Hardened like the connectors: fixed endpoint path, no redirects (the key is never forwarded to
another host), response size cap, SSRF host guard, generic errors that never include request or
response bodies, and the API key lives only in a SecretStr and the Authorization header.
"""
import json
import logging
from typing import Any, Optional

import httpx
from pydantic import SecretStr

from app.connectors import netguard
from app.connectors.base import ConnectorConfig
from app.connectors.errors import ConnectorConfigError
from app.llm.base import LLMProvider
from app.llm.errors import (LLMAuthError, LLMBadResponseError, LLMConfigError, LLMInputError,
                            LLMRateLimitedError, LLMTimeoutError, LLMUnavailableError)
from app.llm.types import LLMRequest, LLMResponse, Usage

logger = logging.getLogger(__name__)
ENDPOINT = "/chat/completions"
MAX_RESPONSE_BYTES = 1_000_000
_FINISH = {"stop": "stop", "length": "length"}


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: SecretStr, model: str, *, require_https: bool = False,
                 allow_private_host: bool = False, transport: Optional[httpx.BaseTransport] = None,
                 max_response_bytes: int = MAX_RESPONSE_BYTES):
        if not model or len(model) > 100 or any(ord(c) < 33 for c in model):
            raise LLMConfigError("Invalid model name")
        if not api_key.get_secret_value().strip():
            raise LLMConfigError("API key is required")
        try:
            ConnectorConfig(base_url=base_url, require_https=require_https)       # URL shape + https rule
            netguard.assert_public_host(base_url, allow_private=allow_private_host)
        except ConnectorConfigError as exc:
            raise LLMConfigError(f"Invalid LLM endpoint: {exc}") from None
        self.model, self._base_url, self._key, self._max = model, base_url.rstrip("/"), api_key, max_response_bytes
        self._client = httpx.Client(base_url=self._base_url, follow_redirects=False, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __repr__(self) -> str:                        # never reveals the key
        return f"<OpenAICompatibleProvider base_url={self._base_url} model={self.model}>"

    # ------------------------------------------------------------------ call
    def complete(self, request: LLMRequest, *, timeout: float) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
        }
        if request.max_output_tokens:
            body["max_tokens"] = request.max_output_tokens
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._key.get_secret_value()}", "Accept": "application/json"}
        try:
            with self._client.stream("POST", ENDPOINT, json=body, headers=headers,
                                     timeout=httpx.Timeout(timeout)) as resp:
                status = resp.status_code
                raw = self._read_capped(resp) if status == 200 else b""
        except httpx.TimeoutException:
            raise LLMTimeoutError("LLM provider timed out") from None
        except httpx.TransportError:
            raise LLMUnavailableError("LLM provider unreachable") from None
        self._raise_for_status(status)
        return self._parse(raw)

    # --------------------------------------------------------------- helpers
    def _read_capped(self, resp: httpx.Response) -> bytes:
        declared = resp.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max:
            raise LLMBadResponseError("LLM response too large")
        buf = bytearray()
        for chunk in resp.iter_bytes():
            buf.extend(chunk)
            if len(buf) > self._max:
                raise LLMBadResponseError("LLM response too large")
        return bytes(buf)

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status == 200:
            return
        if 300 <= status < 400:
            raise LLMBadResponseError("Unexpected redirect from LLM provider")
        if status in (401, 403):
            raise LLMAuthError("LLM provider rejected the credentials")
        if status == 429:
            raise LLMRateLimitedError("LLM provider rate limited the request")
        if status in (408, 409) or status >= 500:
            raise LLMUnavailableError("LLM provider error")
        if 400 <= status < 500:
            raise LLMInputError("LLM provider rejected the request")
        raise LLMBadResponseError("Unexpected response from LLM provider")

    def _parse(self, raw: bytes) -> LLMResponse:
        try:
            data = json.loads(raw)
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMBadResponseError("LLM provider returned an unusable response") from None
        if not isinstance(text, str):
            raise LLMBadResponseError("LLM provider returned an unusable response")
        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        return LLMResponse(
            text=text, provider=self.name, model=self.model,
            finish_reason=_FINISH.get(choice.get("finish_reason"), "other"),
            usage=Usage(input_tokens=_count(usage.get("prompt_tokens")),
                        output_tokens=_count(usage.get("completion_tokens"))))


def _count(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
