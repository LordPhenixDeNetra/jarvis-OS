from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from core.vocab import AutonomyLevel


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
    """Initiative proactive — étendue PHASE 6 §10.1.

    Champs historiques (PHASE 2 proactive existante) conservés :
    type, title, context, reasoning, action, priority, execution_mode,
    draft_content, mission_description, status.

    Nouveaux champs §10.1 — défauts pour compat ascendante des JSONL legacy :
    - autonomy_level : 0-5 (cf. core.vocab.AutonomyLevel). Défaut SUGGEST (1).
    - permission_required : catégorie ApprovalConfig (ex. "agent_mission",
      "email_send"). Lue par le gate composite à l'exécution.
    - cost_max_usd : plafond budgétaire de l'initiative. None = pas de plafond
      explicite ; le BudgetGuard global s'applique de toute façon.
    - risk : tag humain libre ("low" | "medium" | "high"). Indicatif.
    - deadline : datetime au-delà de laquelle l'initiative expire/annule.
    - next_action : prochaine étape concrète (texte court, humain-lisible).
    - requires_validation : override explicite. Si True, ignore autonomy_level
      et force passage par validation humaine. CDC §10 : niveau 5 toujours True.
    """

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
    # PHASE 6 — champs gouvernance §10.1 (defaults pour compat JSONL legacy).
    autonomy_level: AutonomyLevel = AutonomyLevel.SUGGEST
    permission_required: str = "agent_mission"
    cost_max_usd: float | None = None
    risk: str = "low"
    deadline: datetime | None = None
    next_action: str = ""
    requires_validation: bool = False


def needs_human_validation(initiative: Initiative) -> bool:
    """Renvoie True si l'initiative DOIT passer par validation humaine.

    Règle CDC §10 : niveau 5 (EXTERNAL_ACTION = publier/payer/contacter/
    supprimer) exige TOUJOURS validation, même si requires_validation=False.
    Le flag requires_validation peut forcer plus bas en niveau si besoin.
    """
    if initiative.autonomy_level == AutonomyLevel.EXTERNAL_ACTION:
        return True
    return initiative.requires_validation
