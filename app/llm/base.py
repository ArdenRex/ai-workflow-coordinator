"""Provider contract. A provider turns an LLMRequest into an LLMResponse, nothing more."""
from abc import ABC, abstractmethod

from app.llm.types import LLMRequest, LLMResponse


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def complete(self, request: LLMRequest, *, timeout: float) -> LLMResponse:
        """Must raise only LLMError subclasses, with generic messages."""

    def close(self) -> None:  # pragma: no cover - optional
        pass
