from __future__ import annotations

import httpx
from loguru import logger

from api.spotify import _get_access_token
from tools.base import Tool, ToolResult

_API_BASE = "https://api.spotify.com/v1"


class SpotifyTool(Tool):
    name = "spotify_control"
    description = (
        "Contrôle la lecture Spotify. Actions disponibles : "
        "'play' (reprendre), 'pause', 'next' (piste suivante), 'previous' (piste précédente), "
        "'search_track' (chercher et jouer un morceau par nom/artiste), "
        "'search_playlist' (chercher et jouer une playlist par nom). "
        "Pour search_track et search_playlist, fournir 'query' avec le nom recherché."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play", "pause", "toggle", "next", "previous", "search_track", "search_playlist", "volume_delta"],
                "description": "Action à effectuer.",
            },
            "query": {
                "type": "string",
                "description": "Terme de recherche (requis pour search_track et search_playlist).",
            },
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: object) -> ToolResult:
        action = str(kwargs.get("action", ""))
        query = str(kwargs.get("query", ""))

        token = await _get_access_token()
        if not token:
            return ToolResult(
                content="Spotify non connecté. Va sur /api/spotify/auth pour autoriser.",
                is_error=True,
            )

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                headers = {"Authorization": f"Bearer {token}"}

                if action == "toggle":
                    r = await client.get(f"{_API_BASE}/me/player", headers=headers)
                    is_playing = r.status_code == 200 and r.json().get("is_playing", False)
                    endpoint = f"{_API_BASE}/me/player/{'pause' if is_playing else 'play'}"
                    method = client.put
                    r2 = await method(endpoint, headers=headers)
                    label = "Pause." if is_playing else "Lecture reprise."
                    return ToolResult(content=label if r2.status_code in (200, 204) else f"Erreur Spotify ({r2.status_code})")

                if action == "play":
                    r = await client.put(f"{_API_BASE}/me/player/play", headers=headers)
                    return ToolResult(content="Lecture reprise." if r.status_code in (200, 204) else f"Erreur Spotify ({r.status_code})")

                if action == "pause":
                    r = await client.put(f"{_API_BASE}/me/player/pause", headers=headers)
                    return ToolResult(content="Lecture mise en pause." if r.status_code in (200, 204) else f"Erreur Spotify ({r.status_code})")

                if action == "next":
                    r = await client.post(f"{_API_BASE}/me/player/next", headers=headers)
                    return ToolResult(content="Piste suivante." if r.status_code in (200, 204) else f"Erreur Spotify ({r.status_code})")

                if action == "previous":
                    r = await client.post(f"{_API_BASE}/me/player/previous", headers=headers)
                    return ToolResult(content="Piste précédente." if r.status_code in (200, 204) else f"Erreur Spotify ({r.status_code})")

                if action == "search_track":
                    if not query:
                        return ToolResult(content="'query' requis pour search_track.", is_error=True)
                    r = await client.get(
                        f"{_API_BASE}/search",
                        headers=headers,
                        params={"q": query, "type": "track", "limit": 5},
                    )
                    r.raise_for_status()
                    # Spotify peut retourner des items null — on filtre
                    items = [i for i in r.json().get("tracks", {}).get("items", []) if i]
                    if not items:
                        return ToolResult(content=f"Aucun morceau trouvé pour « {query} ».", is_error=True)
                    track = items[0]
                    uri = track["uri"]
                    name = track["name"]
                    artist = ", ".join(a["name"] for a in track.get("artists", []))
                    play_r = await client.put(
                        f"{_API_BASE}/me/player/play",
                        headers=headers,
                        json={"uris": [uri]},
                    )
                    if play_r.status_code in (200, 204):
                        return ToolResult(content=f"Lecture de « {name} » par {artist}.")
                    return ToolResult(content=f"Morceau trouvé ({name}) mais impossible de lancer ({play_r.status_code}).", is_error=True)

                if action == "volume_delta":
                    delta = int(kwargs.get("delta", 0))
                    r = await client.get(f"{_API_BASE}/me/player", headers=headers)
                    if r.status_code != 200 or not r.content:
                        return ToolResult(content="Impossible de récupérer l'état du lecteur.", is_error=True)
                    current = r.json().get("device", {}).get("volume_percent", 50)
                    new_vol = max(0, min(100, current + delta))
                    r2 = await client.put(
                        f"{_API_BASE}/me/player/volume",
                        headers=headers,
                        params={"volume_percent": new_vol},
                    )
                    if r2.status_code in (200, 204):
                        return ToolResult(content=f"Volume : {new_vol}%.")
                    return ToolResult(content=f"Erreur volume ({r2.status_code})", is_error=True)

                if action == "search_playlist":
                    if not query:
                        return ToolResult(content="'query' requis pour search_playlist.", is_error=True)
                    r = await client.get(
                        f"{_API_BASE}/search",
                        headers=headers,
                        params={"q": query, "type": "playlist", "limit": 5},
                    )
                    r.raise_for_status()
                    # Spotify peut retourner des items null — on filtre
                    items = [i for i in r.json().get("playlists", {}).get("items", []) if i]
                    if not items:
                        return ToolResult(content=f"Aucune playlist trouvée pour « {query} ».", is_error=True)
                    playlist = items[0]
                    uri = playlist.get("uri", "")
                    name = playlist.get("name", query)
                    if not uri:
                        return ToolResult(content=f"Playlist « {name} » trouvée mais URI manquant.", is_error=True)
                    play_r = await client.put(
                        f"{_API_BASE}/me/player/play",
                        headers=headers,
                        json={"context_uri": uri},
                    )
                    if play_r.status_code in (200, 204):
                        return ToolResult(content=f"Lecture de la playlist « {name} ».")
                    return ToolResult(content=f"Playlist trouvée ({name}) mais impossible de lancer ({play_r.status_code}).", is_error=True)

                return ToolResult(content=f"Action inconnue : {action}", is_error=True)

        except httpx.TimeoutException:
            logger.warning("SpotifyTool timeout", action=action)
            return ToolResult(content="Timeout Spotify. Réessaie dans un instant.", is_error=True)
        except httpx.RequestError as e:
            logger.error("SpotifyTool request error", error=str(e))
            return ToolResult(content=f"Erreur réseau Spotify : {e}", is_error=True)
