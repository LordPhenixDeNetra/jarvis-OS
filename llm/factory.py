from __future__ import annotations

from config.settings import settings
from llm.api import AnthropicProvider
from llm.base import LLMProvider
from llm.local import OllamaProvider


def get_llm_provider() -> LLMProvider:
    """Instancie le provider LLM selon LLM_PROVIDER dans .env."""
    if settings.llm_provider == "local":
        return OllamaProvider()
    return AnthropicProvider()


def create_background_llm() -> LLMProvider:
    """Provider léger et indépendant pour les tâches background (consolidation, auto_dream).

    Instance séparée = client HTTP distinct = aucune contention avec le provider principal.
    max_tokens=500 suffit largement pour les réponses de mémorisation.
    """
    if settings.llm_provider == "local":
        return OllamaProvider()
    return AnthropicProvider(max_tokens=500)
