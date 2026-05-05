from __future__ import annotations

import re
from collections.abc import AsyncIterator
from enum import StrEnum

from loguru import logger


class RouteEnum(StrEnum):
    INSTANT      = "I"
    CONFIRM_FIRE = "CF"
    BACKGROUND   = "BG"
    PROJECT      = "BG:PROJECT"


# BG:PROJECT doit être testé AVANT BG pour éviter le match partiel.
_TAG_RE = re.compile(r"^\[(I|CF|BG:PROJECT|BG)\]\s?")

# Filtre les tags routing inconnus courts (ex: [C], [A], [X]…)
# Ne pas matcher [MINDMAP], [/MINDMAP] ou tout tag > 3 lettres
_ANY_TAG_RE = re.compile(r"^\[[A-Z]{1,3}(?::[A-Z]+)?\]\s?")

# Mots-clés domotiques / actions → pré-route CONFIRM_FIRE.
_CF_PATTERNS = re.compile(
    r"\b(allume|éteins|lumière|lampe|thermostat|minuteur|timer|rappel|note|"
    r"souviens|mémorise|programme|règle|lance|démarre|arrête|ouvre|ferme)\b",
    re.IGNORECASE,
)


class SpeedRouter:
    """Heuristique de pré-routing + extraction du tag LLM depuis un stream."""

    @staticmethod
    def heuristic(message: str) -> RouteEnum:
        """Pré-classe la requête avant l'appel LLM. INSTANT par défaut."""
        if _CF_PATTERNS.search(message):
            return RouteEnum.CONFIRM_FIRE
        return RouteEnum.INSTANT

    @staticmethod
    def strip_tag(text: str) -> str:
        """Retire le tag de routing d'une réponse complète (non-stream)."""
        return _TAG_RE.sub("", text)

    @staticmethod
    async def extract_route(
        stream: AsyncIterator[str],
    ) -> tuple[RouteEnum, AsyncIterator[str]]:
        """Lit le tag du début du stream et retourne (route, stream nettoyé).

        Bufferise les premiers chunks jusqu'à voir ']' ou 20 caractères,
        détecte le tag, puis relâche le reste proprement.
        """
        buffer = ""
        async for chunk in stream:
            buffer += chunk
            if "]" in buffer or len(buffer) >= 20:
                break

        match = _TAG_RE.match(buffer)
        if match:
            tag = match.group(1)
            try:
                route = RouteEnum(tag)
            except ValueError:
                route = RouteEnum.INSTANT
            stripped = _TAG_RE.sub("", buffer)
            tag_consumed_all = not stripped
        else:
            route = RouteEnum.INSTANT
            # Strip any unrecognized [TAG] the model might have invented
            stripped = _ANY_TAG_RE.sub("", buffer)
            tag_consumed_all = not stripped

        logger.debug("SpeedRouter", route=route.value)

        async def _tail() -> AsyncIterator[str]:
            lstrip_next = tag_consumed_all
            if stripped:
                yield stripped
            async for chunk in stream:
                if lstrip_next:
                    chunk = chunk.lstrip(" ")
                    lstrip_next = not chunk
                if chunk:
                    yield chunk

        return route, _tail()
