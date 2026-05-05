from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

from background.notifications import NotificationQueue
from llm.base import LLMProvider

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

_BG_SYSTEM = (
    "Tu es Jarvis. Exécute la tâche demandée avec les outils disponibles. "
    "Donne un résumé concis et factuel du résultat en français."
)
_BG_SYSTEM_NOTOOL = "Tu es Jarvis. Exécute la tâche et confirme en une phrase courte."

_HISTORY_MAX = 50


@dataclass
class BackgroundTask:
    session_id: str
    instruction: str


@dataclass
class TaskRecord:
    session_id: str
    instruction: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    result: str | None = None
    error: str | None = None


class BackgroundWorker:
    """Consommateur asyncio d'une queue de tâches longues."""

    def __init__(
        self,
        llm: LLMProvider,
        notifications: NotificationQueue,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._llm = llm
        self._notifications = notifications
        self._tool_registry = tool_registry
        self._queue: asyncio.Queue[BackgroundTask] = asyncio.Queue()
        self._history: deque[TaskRecord] = deque(maxlen=_HISTORY_MAX)

    def submit(self, task: BackgroundTask) -> None:
        self._queue.put_nowait(task)

    def history(self) -> list[TaskRecord]:
        return list(reversed(self._history))

    async def run_loop(self) -> None:
        logger.info("BackgroundWorker started")
        while True:
            task = await self._queue.get()
            record = TaskRecord(session_id=task.session_id, instruction=task.instruction)
            try:
                await self._execute(task, record)
            except Exception as e:
                record.error = str(e)
                record.completed_at = datetime.now(UTC).isoformat()
                logger.error("BackgroundTask failed", session_id=task.session_id, error=str(e))
                self._notifications.add(f"Tâche échouée : {e}")
            finally:
                self._history.append(record)
                self._queue.task_done()

    async def _execute(self, task: BackgroundTask, record: TaskRecord) -> None:
        logger.info("BackgroundTask executing", session_id=task.session_id)
        messages = [{"role": "user", "content": task.instruction}]

        if (
            self._tool_registry is not None
            and self._tool_registry.has_tools()
            and self._llm.supports_tools
        ):
            result = await self._llm.tool_loop(
                messages=messages,
                system=_BG_SYSTEM,
                tools=self._tool_registry.schemas(),
                tool_executor=self._tool_registry.call_str,
            )
        else:
            result = str(
                await self._llm.complete(
                    messages=messages,
                    system=_BG_SYSTEM_NOTOOL,
                    stream=False,
                )
            )

        record.result = result.strip()
        record.completed_at = datetime.now(UTC).isoformat()
        self._notifications.add(result.strip())
        logger.info("BackgroundTask done", session_id=task.session_id)
