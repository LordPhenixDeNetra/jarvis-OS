"""
InitiativeStore — persistance des initiatives sur le disque.
Format : JSONL dans memory_data/initiatives/
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def _title_key(title: str) -> str:
    return re.sub(r"\W+", "", title.lower())


def _jaccard(a: str, b: str) -> float:
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)

from proactive.schemas import ExecutionMode, Initiative, InitiativeType, Priority

INITIATIVES_DIR = Path("memory_data/initiatives")


class InitiativeStore:

    def __init__(self) -> None:
        INITIATIVES_DIR.mkdir(parents=True, exist_ok=True)

    def save(self, initiative: Initiative) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = INITIATIVES_DIR / f"{today}.jsonl"

        # Dédup cross-cycle : exact match + Jaccard > 60% sur les pending du jour
        if log_file.exists():
            key = _title_key(initiative.title)
            for line in log_file.read_text().splitlines():
                if not line:
                    continue
                try:
                    existing = json.loads(line)
                    etitle = existing.get("title", "")
                    if _title_key(etitle) == key or _jaccard(initiative.title, etitle) > 0.60:
                        return
                except Exception:
                    pass

        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": initiative.id,
                "type": initiative.type,
                "title": initiative.title,
                "context": initiative.context,
                "reasoning": initiative.reasoning,
                "action": initiative.action,
                "priority": initiative.priority,
                "execution_mode": initiative.execution_mode,
                "draft_content": initiative.draft_content,
                "mission_description": initiative.mission_description,
                "status": initiative.status,
                "created_at": initiative.created_at.isoformat()
            }) + "\n")

    def load_pending(self) -> list[Initiative]:
        """Charge toutes les initiatives en attente du jour."""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = INITIATIVES_DIR / f"{today}.jsonl"

        if not log_file.exists():
            return []

        initiatives = []
        for line in log_file.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("status") == "pending":
                    initiatives.append(Initiative(
                        id=data["id"],
                        type=InitiativeType(data["type"]),
                        title=data["title"],
                        context=data["context"],
                        reasoning=data["reasoning"],
                        action=data["action"],
                        priority=Priority(data["priority"]),
                        execution_mode=ExecutionMode(data["execution_mode"]),
                        draft_content=data.get("draft_content"),
                        mission_description=data.get("mission_description"),
                        status=data["status"],
                        created_at=datetime.fromisoformat(data["created_at"])
                    ))
            except Exception:
                pass

        return initiatives

    def get_by_id(self, initiative_id: str) -> "Initiative | None":
        for i in self.load_pending():
            if i.id == initiative_id:
                return i
        return None

    def update_initiative(self, initiative_id: str, updates: dict) -> None:
        """Met à jour les champs d'une initiative existante."""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = INITIATIVES_DIR / f"{today}.jsonl"
        if not log_file.exists():
            return

        lines = log_file.read_text().strip().split("\n")
        updated = []
        for line in lines:
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("id") == initiative_id:
                    data.update(updates)
                line = json.dumps(data)
            except Exception:
                pass
            updated.append(line)

        log_file.write_text("\n".join(updated) + "\n")

    def update_status(self, initiative_id: str, status: str) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = INITIATIVES_DIR / f"{today}.jsonl"
        if not log_file.exists():
            return

        lines = log_file.read_text().strip().split("\n")
        updated = []
        for line in lines:
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("id") == initiative_id:
                    data["status"] = status
                line = json.dumps(data)
            except Exception:
                pass
            updated.append(line)

        log_file.write_text("\n".join(updated) + "\n")
