from __future__ import annotations

import pytest

from core.router import RouteEnum, SpeedRouter

# ── heuristic ────────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("Quelle heure est-il ?", RouteEnum.INSTANT),
    ("Qu'est-ce que tu penses de ça ?", RouteEnum.INSTANT),
    ("Allume la lumière du salon.", RouteEnum.CONFIRM_FIRE),
    ("Éteins le thermostat.", RouteEnum.CONFIRM_FIRE),
    ("Lance un minuteur de 10 minutes.", RouteEnum.CONFIRM_FIRE),
    ("Mémorise que j'ai rendez-vous demain.", RouteEnum.CONFIRM_FIRE),
    ("Ouvre le volet de la chambre.", RouteEnum.CONFIRM_FIRE),
])
def test_heuristic(message: str, expected: RouteEnum) -> None:
    assert SpeedRouter.heuristic(message) == expected


# ── strip_tag ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("[I] Réponse directe.", "Réponse directe."),
    ("[CF] Je confirme.", "Je confirme."),
    ("[BG] Ok je lance.", "Ok je lance."),
    ("Pas de tag.", "Pas de tag."),
])
def test_strip_tag(raw: str, expected: str) -> None:
    assert SpeedRouter.strip_tag(raw) == expected


# ── extract_route ─────────────────────────────────────────────

async def _extract(chunks: list[str]) -> tuple[RouteEnum, str]:
    async def _gen() -> RouteEnum:  # type: ignore[valid-type]
        for c in chunks:
            yield c
    route, stream = await SpeedRouter.extract_route(_gen())
    return route, "".join([c async for c in stream])


async def test_extract_route_instant_single() -> None:
    route, text = await _extract(["[I] Il est 14h23."])
    assert route == RouteEnum.INSTANT
    assert text == "Il est 14h23."


async def test_extract_route_cf_single() -> None:
    route, text = await _extract(["[CF] Lumière allumée."])
    assert route == RouteEnum.CONFIRM_FIRE
    assert text == "Lumière allumée."


async def test_extract_route_bg_single() -> None:
    route, text = await _extract(["[BG] Je lance la recherche."])
    assert route == RouteEnum.BACKGROUND
    assert text == "Je lance la recherche."


async def test_extract_route_tag_split() -> None:
    route, text = await _extract(["[CF", "] Mode nuit activé."])
    assert route == RouteEnum.CONFIRM_FIRE
    assert text == "Mode nuit activé."


async def test_extract_route_tag_and_space_split() -> None:
    route, text = await _extract(["[BG]", " Tâche soumise."])
    assert route == RouteEnum.BACKGROUND
    assert text == "Tâche soumise."


async def test_extract_route_no_tag() -> None:
    route, text = await _extract(["Bonjour", " chef."])
    assert route == RouteEnum.INSTANT
    assert text == "Bonjour chef."


async def test_extract_route_multi_chunks() -> None:
    route, text = await _extract(["[I] ", "Il est ", "14h."])
    assert route == RouteEnum.INSTANT
    assert text == "Il est 14h."
