"""LLMService: the only way the rest of the OS calls a model.

Enforces input/output limits, a per-call timeout, bounded retries for transient failures,
and writes a CONTENT-FREE audit event per call (provider, model, token counts, latency,
outcome). Prompts and completions are never logged or stored here.
"""
import logging
import time
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.config import Settings
from app.kernel.audit import record_event
from app.llm.base import LLMProvider
from app.llm.errors import LLMError, LLMInputTooLargeError
from app.llm.types import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)
MAX_MESSAGES = 50
_BACKOFF_BASE_SECONDS = 0.5


class LLMService:
    def __init__(self, db: Session, provider: LLMProvider, settings: Settings, *,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.db, self.provider, self.settings = db, provider, settings
        self._sleep, self._clock = sleep, clock

    def complete(self, *, workspace_id: str, actor: Optional[str], purpose: str,
                 request: LLMRequest) -> LLMResponse:
        """`purpose` is a short machine label (e.g. "intent_classification"), never user text."""
        request = self._bounded(request)
        started, attempts = self._clock(), 0
        try:
            while True:
                attempts += 1
                try:
                    response = self.provider.complete(request, timeout=self.settings.llm_timeout_seconds)
                    break
                except LLMError as exc:
                    if not exc.retryable or attempts > self.settings.llm_max_retries:
                        raise
                    self._sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempts - 1))
        except LLMError as exc:
            self._audit(workspace_id, actor, "llm.failed", purpose, started, attempts,
                        {"code": exc.code})
            raise
        except Exception:                      # a provider bug must not leak content or crash callers
            logger.exception("Unexpected LLM provider failure")
            self._audit(workspace_id, actor, "llm.failed", purpose, started, attempts,
                        {"code": LLMError.code})
            raise LLMError("LLM call failed") from None
        self._audit(workspace_id, actor, "llm.completed", purpose, started, attempts,
                    # NOTE: not named "*_tokens": the audit redactor hides any key containing "token".
                    {"usage": {"input": response.usage.input_tokens, "output": response.usage.output_tokens},
                     "finish_reason": response.finish_reason})
        return response

    # ---------------------------------------------------------------- internals
    def _bounded(self, request: LLMRequest) -> LLMRequest:
        s = self.settings
        if len(request.messages) > MAX_MESSAGES:
            raise LLMInputTooLargeError("Too many messages")
        if sum(len(m.content) for m in request.messages) > s.llm_max_input_chars:
            raise LLMInputTooLargeError("Input exceeds the allowed size")
        cap = s.llm_max_output_tokens
        wanted = request.max_output_tokens or cap
        return request.model_copy(update={"max_output_tokens": min(wanted, cap)})

    def _audit(self, workspace_id, actor, event, purpose, started, attempts, extra) -> None:
        record_event(self.db, workspace_id=workspace_id, event_type=event, actor=actor,
                     payload={"purpose": purpose[:64], "provider": self.provider.name,
                              "model": self.provider.model, "attempts": attempts,
                              "latency_ms": int((self._clock() - started) * 1000), **extra})
        self.db.commit()
