from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from config.settings import settings

router = APIRouter(prefix="/api")

_NOTION_VERSION = "2022-06-28"
_NOTION_BASE = "https://api.notion.com/v1"


# ── Models ────────────────────────────────────────────────────

class Task(BaseModel):
    text: str
    done: bool


class TasksResponse(BaseModel):
    tasks: list[Task]


class CalEvent(BaseModel):
    time: str
    name: str
    subtitle: str


class EventsResponse(BaseModel):
    events: list[CalEvent]


# ── Notion tasks ──────────────────────────────────────────────

@router.get("/tasks", response_model=TasksResponse)
async def get_tasks() -> TasksResponse:
    token = settings.notion_token
    page_id = settings.notion_page_id
    if not token or not page_id:
        return TasksResponse(tasks=[])

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_NOTION_BASE}/blocks/{page_id}/children",
                headers=headers,
            )
            resp.raise_for_status()
    except Exception as e:
        logger.error("Notion widget error", error=str(e))
        return TasksResponse(tasks=[])

    blocks = resp.json().get("results", [])
    tasks: list[Task] = []
    in_section = False

    for block in blocks:
        btype = block.get("type", "")

        if btype.startswith("heading_"):
            text = "".join(
                rt.get("plain_text", "")
                for rt in block.get(btype, {}).get("rich_text", [])
            )
            if "Tâches du jour" in text or "tâches du jour" in text.lower():
                in_section = True
            elif in_section:
                break
            continue

        if in_section and btype == "to_do":
            todo = block.get("to_do", {})
            text = "".join(
                rt.get("plain_text", "") for rt in todo.get("rich_text", [])
            ).strip()
            if text:
                tasks.append(Task(text=text, done=bool(todo.get("checked", False))))

    return TasksResponse(tasks=tasks)


# ── Google Calendar events ────────────────────────────────────

_cal_cache: list[CalEvent] = []
_cal_cache_ts: datetime | None = None
_cal_lock = asyncio.Lock()
_CAL_TTL = 300  # secondes


def _load_calendar_creds(token_path: Path):  # noqa: ANN202
    """Charge et rafraîchit les credentials Calendar OAuth2 (bloquant)."""
    from google.auth.transport.requests import Request as GRequest
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(
        str(token_path),
        ["https://www.googleapis.com/auth/calendar.readonly"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
    return creds


async def _fetch_today_events() -> list[CalEvent]:
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
    except ImportError:
        logger.warning("google-api-python-client non installé")
        return []

    token_path = Path(settings.google_token_path)
    if not token_path.exists():
        return []

    try:
        creds = await asyncio.to_thread(_load_calendar_creds, token_path)
    except Exception as e:
        logger.error("Calendar widget creds error", error=str(e))
        return []

    now = datetime.now(UTC)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    params = {
        "timeMin": start_of_day.isoformat(),
        "timeMax": end_of_day.isoformat(),
        "maxResults": 15,
        "singleEvents": "true",
        "orderBy": "startTime",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {creds.token}"},
            params=params,
        )
        resp.raise_for_status()

    events: list[CalEvent] = []
    for item in resp.json().get("items", []):
        start = item["start"].get("dateTime", item["start"].get("date", ""))
        if "T" in start:
            dt = datetime.fromisoformat(start)
            time_str = dt.strftime("%H:%M")
        else:
            time_str = "Journée"

        name = item.get("summary", "(sans titre)")
        subtitle = (item.get("location") or "").strip()
        if not subtitle:
            desc = (item.get("description") or "").strip()
            subtitle = desc.split("\n")[0][:40] if desc else ""

        events.append(CalEvent(time=time_str, name=name, subtitle=subtitle))

    return events


@router.get("/events", response_model=EventsResponse)
async def get_events() -> EventsResponse:
    global _cal_cache, _cal_cache_ts

    # Servir le cache si < TTL — évite les appels concurrents à Google API
    now = datetime.now(UTC)
    if _cal_cache_ts and (now - _cal_cache_ts).total_seconds() < _CAL_TTL:
        return EventsResponse(events=_cal_cache)

    # Un seul appel API à la fois — les autres attendent et réutilisent le résultat
    async with _cal_lock:
        # Re-check après avoir acquis le lock (un autre a peut-être déjà rafraîchi)
        if _cal_cache_ts and (now - _cal_cache_ts).total_seconds() < _CAL_TTL:
            return EventsResponse(events=_cal_cache)
        try:
            events = await _fetch_today_events()
            _cal_cache = events
            _cal_cache_ts = datetime.now(UTC)
            return EventsResponse(events=events)
        except Exception as e:
            logger.error("Calendar widget error", error=str(e))
            return EventsResponse(events=_cal_cache)  # retourne le cache périmé si erreur
