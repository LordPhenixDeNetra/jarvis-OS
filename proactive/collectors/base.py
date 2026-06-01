from __future__ import annotations

from abc import ABC, abstractmethod

from loguru import logger

from proactive.schemas import ContextItem


class CollectorBase(ABC):
    name: str = "base"

    async def collect(self) -> list[ContextItem]:
        """Point d'entrée principal. Gère les erreurs proprement."""
        try:
            items = await self._collect()
            logger.debug(f"Collector {self.name}: {len(items)} items")
            return items
        except Exception as e:
            logger.error(f"Collector {self.name} failed: {e}")
            return []

    @abstractmethod
    async def _collect(self) -> list[ContextItem]:
        """Implémenter dans chaque sous-classe."""
