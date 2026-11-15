"""FAKE / TEST ONLY provider: deterministic, offline, free. Never selectable in production."""
from collections import deque
from typing import Callable, Iterable, Optional, Union

from app.llm.base import LLMProvider
from app.llm.errors import LLMBadResponseError, LLMError
from app.llm.types import LLMRequest, LLMResponse, MessageRole, Usage

Scripted = Union[str, LLMError, Callable[[LLMRequest], str]]


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, script: Optional[Iterable[Scripted]] = None, *, model: str = "fake-model"):
        self.model = model
        self._script = deque(script or [])
        self.requests: list[LLMRequest] = []      # inspect what the service actually sent

    def push(self, item: Scripted) -> None:
        self._script.append(item)

    def complete(self, request: LLMRequest, *, timeout: float) -> LLMResponse:
        self.requests.append(request)
        if self._script:
            item = self._script.popleft()
            if isinstance(item, LLMError):
                raise item
            text = item(request) if callable(item) else item
        else:                                      # default: echo the last user message
            last = next((m for m in reversed(request.messages) if m.role == MessageRole.USER), None)
            if last is None:
                raise LLMBadResponseError("No user message to answer")
            text = f"[FAKE] {last.content}"
        used_in = sum(_tokens(m.content) for m in request.messages)
        return LLMResponse(text=text, provider=self.name, model=self.model,
                           usage=Usage(input_tokens=used_in, output_tokens=_tokens(text)))
