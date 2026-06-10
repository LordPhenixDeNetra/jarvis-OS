"""Ré-export de kernel.settings — CDC §A.1.3.

Le foyer canonique de Settings est `kernel/settings.py` depuis la Phase A.
Ce fichier reste pour préserver les imports existants (`from config.settings
import settings`) jusqu'à la Phase B (§B.1 table de migration).
"""

from __future__ import annotations

from kernel.settings import Settings, _VALID_WHISPER, settings  # noqa: F401
