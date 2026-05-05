from __future__ import annotations

from config.settings import Settings


def test_settings_load() -> None:
    """Vérifie que les settings se chargent sans erreur."""
    s = Settings()
    assert s.llm_provider in ("api", "local")
    assert s.port > 0
    assert s.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")


def test_settings_defaults() -> None:
    """Vérifie les valeurs par défaut."""
    s = Settings()
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.anthropic_model == "claude-sonnet-4-6"
