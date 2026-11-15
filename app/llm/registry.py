"""Provider registry. Adding a provider = one entry in PROVIDERS."""
from typing import Callable, Dict

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.errors import LLMConfigError
from app.llm.fake import FakeProvider
from app.llm.openai_compatible import OpenAICompatibleProvider

ProviderFactory = Callable[..., LLMProvider]      # (settings, **kw) -> provider


def _openai_compatible(settings: Settings, **kw) -> LLMProvider:
    if not settings.llm_base_url or settings.llm_api_key is None:
        raise LLMConfigError("LLM_BASE_URL and LLM_API_KEY are required")
    return OpenAICompatibleProvider(settings.llm_base_url, settings.llm_api_key, settings.llm_model,
                                    require_https=settings.is_production,
                                    allow_private_host=settings.allow_private_connector_hosts, **kw)


PROVIDERS: Dict[str, ProviderFactory] = {
    "fake": lambda s, **kw: FakeProvider(model=s.llm_model),
    "openai_compatible": _openai_compatible,
}


def build_provider(settings: Settings, **kw) -> LLMProvider:
    factory = PROVIDERS.get(settings.llm_provider)
    if factory is None:
        raise LLMConfigError("Unsupported LLM provider")
    return factory(settings, **kw)
