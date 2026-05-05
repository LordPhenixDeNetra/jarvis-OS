"""Analytics — stats Jarvis locales + YouTube Data API v3."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ── Jarvis stats ──────────────────────────────────────────────────────────────

async def get_jarvis_stats(days: int = 30) -> dict:
    """Stats d'usage Jarvis depuis les fichiers locaux."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Sessions
    sessions_dir = Path("memory_data/sessions")
    session_count = 0
    if sessions_dir.exists():
        for f in sessions_dir.iterdir():
            if f.suffix == ".jsonl":
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                    if mtime >= cutoff:
                        session_count += 1
                except OSError:
                    pass

    # Projects / Missions
    mission_count = 0
    try:
        from agent.project_store import ProjectStore
        store = ProjectStore()
        projects = store.list_all() if hasattr(store, "list_all") else []
        for p in projects:
            created = getattr(p, "created_at", None)
            if created:
                if isinstance(created, str):
                    try:
                        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    except ValueError:
                        created = None
                if created and created >= cutoff:
                    mission_count += 1
    except Exception:
        pass

    # Tokens + coût depuis les fichiers JSONL conso
    conso_dir = Path("memory_data/conso")
    total_tokens = 0
    total_cost = 0.0
    tool_calls: dict[str, int] = {}

    if conso_dir.exists():
        for f in sorted(conso_dir.glob("*.jsonl")):
            try:
                file_date = datetime.strptime(f.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if file_date < cutoff:
                    continue
            except ValueError:
                continue
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    total_tokens += entry.get("input_tokens", 0) + entry.get("output_tokens", 0)
                    total_cost += entry.get("cost_usd", 0.0)
                    tool = entry.get("model", "")
                    if tool:
                        tool_calls[tool] = tool_calls.get(tool, 0) + 1
            except Exception:
                continue

    top_model = max(tool_calls, key=tool_calls.get) if tool_calls else "—"

    return {
        "period_days": days,
        "sessions": session_count,
        "missions": mission_count,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "top_model": top_model,
    }


# ── YouTube stats ─────────────────────────────────────────────────────────────

async def get_youtube_stats(days: int = 7) -> dict:
    """Stats YouTube via Data API v3 (YOUTUBE_API_KEY requis dans .env)."""
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")

    if not api_key or not channel_id:
        return {"configured": False, "error": "YOUTUBE_API_KEY ou YOUTUBE_CHANNEL_ID manquant"}

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            # Abonnés + vues totales
            ch_resp = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={
                    "part": "statistics",
                    "id": channel_id,
                    "key": api_key,
                },
            )
            ch_data = ch_resp.json()
            stats = ch_data.get("items", [{}])[0].get("statistics", {})
            subscribers = int(stats.get("subscriberCount", 0))
            total_views = int(stats.get("viewCount", 0))

            # Dernières vidéos (vues récentes)
            vid_resp = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "channelId": channel_id,
                    "maxResults": 5,
                    "order": "date",
                    "type": "video",
                    "key": api_key,
                },
            )
            vid_data = vid_resp.json()
            videos = []
            for item in vid_data.get("items", []):
                videos.append({
                    "id": item.get("id", {}).get("videoId", ""),
                    "title": item.get("snippet", {}).get("title", ""),
                    "published": item.get("snippet", {}).get("publishedAt", ""),
                })

            # Stats individuelles des vidéos récentes
            if videos:
                ids = ",".join(v["id"] for v in videos if v["id"])
                vstats_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={"part": "statistics", "id": ids, "key": api_key},
                )
                vstats = {
                    i["id"]: int(i.get("statistics", {}).get("viewCount", 0))
                    for i in vstats_resp.json().get("items", [])
                }
                for v in videos:
                    v["views"] = vstats.get(v["id"], 0)

            top = max(videos, key=lambda v: v.get("views", 0)) if videos else None

        return {
            "configured": True,
            "channel_id": channel_id,
            "subscribers": subscribers,
            "total_views": total_views,
            "recent_videos": videos,
            "top_video": top,
            "period_days": days,
        }

    except Exception as exc:
        return {"configured": False, "error": str(exc)}


async def get_analytics_summary() -> dict:
    import asyncio
    jarvis_task = asyncio.create_task(get_jarvis_stats(30))
    yt_task = asyncio.create_task(get_youtube_stats(7))
    jarvis, youtube = await asyncio.gather(jarvis_task, yt_task, return_exceptions=True)
    return {
        "jarvis": jarvis if not isinstance(jarvis, Exception) else None,
        "youtube": youtube if not isinstance(youtube, Exception) else None,
    }
