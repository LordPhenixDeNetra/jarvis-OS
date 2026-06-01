from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config.settings import settings

router = APIRouter(prefix="/api/music")


async def _get_state() -> dict:
    provider = settings.music_provider or ""
    if provider == "spotify":
        from api.spotify import _get_player_state

        state = await _get_player_state()
    elif provider == "deezer":
        from api.deezer import _get_player_state

        state = await _get_player_state()
    elif provider == "local":
        from api.local_music import _get_player_state

        state = await _get_player_state()
    else:
        return {"provider": None, "connected": False}
    state["provider"] = provider
    return state


async def _action(action: str) -> JSONResponse:
    provider = settings.music_provider or ""
    if not provider:
        return JSONResponse({"ok": False, "error": "no_provider"}, status_code=400)

    if provider == "spotify":
        from api.spotify import next_track as sp_next
        from api.spotify import pause as sp_pause
        from api.spotify import play as sp_play
        from api.spotify import previous_track as sp_prev

        mapping = {"play": sp_play, "pause": sp_pause, "next": sp_next, "prev": sp_prev}
    elif provider == "deezer":
        from api.deezer import next_track as dz_next
        from api.deezer import pause as dz_pause
        from api.deezer import play as dz_play
        from api.deezer import previous_track as dz_prev

        mapping = {"play": dz_play, "pause": dz_pause, "next": dz_next, "prev": dz_prev}
    elif provider == "local":
        from api.local_music import next_track as lm_next
        from api.local_music import pause as lm_pause
        from api.local_music import play as lm_play
        from api.local_music import previous_track as lm_prev

        mapping = {"play": lm_play, "pause": lm_pause, "next": lm_next, "prev": lm_prev}
    else:
        return JSONResponse({"ok": False, "error": "unknown_provider"}, status_code=400)

    fn = mapping.get(action)
    if fn is None:
        return JSONResponse({"ok": False, "error": "unknown_action"}, status_code=400)
    return await fn()


@router.get("/status")
async def get_music_status() -> JSONResponse:
    return JSONResponse(await _get_state())


@router.get("/provider-status")
async def get_provider_status() -> JSONResponse:
    provider = settings.music_provider or ""
    if not provider:
        return JSONResponse({"provider": None, "connected": False})
    state = await _get_state()
    return JSONResponse({"provider": provider, "connected": state.get("connected", False)})


@router.post("/play")
async def music_play() -> JSONResponse:
    return await _action("play")


@router.post("/pause")
async def music_pause() -> JSONResponse:
    return await _action("pause")


@router.post("/next")
async def music_next() -> JSONResponse:
    return await _action("next")


@router.post("/prev")
async def music_prev() -> JSONResponse:
    return await _action("prev")
