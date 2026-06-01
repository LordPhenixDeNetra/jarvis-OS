"""
CalendarCollector — récupère les événements des prochaines 48h.
Réutilise le tool calendar existant.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from proactive.collectors.base import CollectorBase
from proactive.schemas import ContextItem, ItemType, Priority


class CalendarCollector(CollectorBase):
    name = "calendar"

    async def _collect(self) -> list[ContextItem]:
        from config.settings import settings
        from tools.calendar import CalendarListTool

        tool = CalendarListTool(
            credentials_path=Path(settings.google_credentials_path),
            token_path=Path(settings.google_token_path),
        )
        result = await tool.execute(days_ahead=2)

        if result.is_error:
            return []

        items = []
        now = datetime.now()

        lines = result.content.split("\n") if result.content else []
        for line in lines:
            if not line.strip():
                continue

            priority = Priority.MEDIUM
            if "aujourd'hui" in line.lower() or "dans" in line.lower():
                priority = Priority.HIGH

            items.append(
                ContextItem(
                    type=ItemType.EVENT,
                    title=line.strip(),
                    summary=line.strip(),
                    raw=line.strip(),
                    source="google_calendar",
                    timestamp=now,
                    priority=priority,
                )
            )

        return items
