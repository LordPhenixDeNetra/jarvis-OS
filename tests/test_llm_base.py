from __future__ import annotations

from llm.base import LLMProvider
from llm.factory import get_llm_provider


def test_factory_returns_provider() -> None:
    """Vérifie que la factory instancie un LLMProvider."""
    provider = get_llm_provider()
    assert isinstance(provider, LLMProvider)


def test_provider_has_required_methods() -> None:
    """Vérifie que le provider implémente l'interface."""
    provider = get_llm_provider()
    assert callable(provider.complete)
    assert callable(provider.health_check)
