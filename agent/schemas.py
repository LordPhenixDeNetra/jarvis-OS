from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"
    SKIPPED = "skipped"


class ProjectStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class Step:
    id: str
    title: str
    description: str
    status: StepStatus = StepStatus.PENDING
    requires_approval: bool = False
    output: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class Project:
    id: str
    title: str
    mission: str
    status: ProjectStatus = ProjectStatus.PLANNING
    steps: list[Step] = field(default_factory=list)
    workspace_path: str = ""
    timeout_minutes: int = 30
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    llm_calls: int = 0
    files_created: list[str] = field(default_factory=list)
    requires_network: bool = False


@dataclass
class LogEntry:
    timestamp: datetime
    level: str  # "info" | "tool" | "error" | "approval"
    message: str
    step_id: str | None = None
    data: Any = None
