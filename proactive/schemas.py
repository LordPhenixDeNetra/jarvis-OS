from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ItemType(StrEnum):
    EMAIL = "email"
    EVENT = "event"
    TASK = "task"
    NEWS = "news"
    MISSION = "mission"
    MEMORY = "memory"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ContextItem:
    """Un élément d'information collecté depuis une source."""

    type: ItemType
    title: str
    summary: str
    raw: str
    source: str
    timestamp: datetime
    priority: Priority = Priority.MEDIUM
    metadata: dict = field(default_factory=dict)


@dataclass
class CollectionResult:
    """Résultat d'une collecte complète (toutes sources)."""

    items: list[ContextItem]
    collected_at: datetime
    errors: dict[str, str] = field(default_factory=dict)

    def by_type(self, item_type: ItemType) -> list[ContextItem]:
        return [i for i in self.items if i.type == item_type]

    def high_priority(self) -> list[ContextItem]:
        return [i for i in self.items if i.priority == Priority.HIGH]


class InitiativeType(StrEnum):
    DRAFT_RESPONSE = "draft_response"
    REMINDER = "reminder"
    SUGGESTION = "suggestion"
    ALERT = "alert"
    AUTO_TASK = "auto_task"
    INFO = "info"


class ExecutionMode(StrEnum):
    AUTO = "auto"
    NOTIFY = "notify"
    VALIDATE = "validate"


@dataclass
class Initiative:
    id: str
    type: InitiativeType
    title: str
    context: str
    reasoning: str
    action: str
    priority: Priority
    execution_mode: ExecutionMode
    created_at: datetime = field(default_factory=datetime.now)
    draft_content: str | None = None
    mission_description: str | None = None
    status: str = "pending"
