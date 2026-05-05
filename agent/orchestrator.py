"""ProjectOrchestrator — point d'entrée central pour créer, suivre et tuer les projets."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from loguru import logger

from agent.project_manager import ProjectManager
from agent.project_store import ProjectStore
from agent.schemas import LogEntry, Project
from agent.worker_agent import WorkerAgent


class ProjectOrchestrator:
    """Gère le cycle de vie complet des projets agents."""

    def __init__(self, broadcast_event: Callable[[dict], None]) -> None:
        self._broadcast         = broadcast_event
        self._store             = ProjectStore()
        self._manager           = ProjectManager()
        self._workers: dict[str, WorkerAgent] = {}
        self._pending_approvals: dict[str, asyncio.Future[bool]] = {}

    # ── Création & lancement ──────────────────────────────────────────────────

    async def create_and_run(self, mission: str, timeout_minutes: int = 30) -> Project:
        """Crée le projet (appel LLM de planification) et lance le worker en background."""
        project = await self._manager.create_project(mission, timeout_minutes)

        worker = WorkerAgent(
            project=project,
            store=self._store,
            broadcast_event=self._broadcast,
            approval_callback=self._request_approval,
        )
        self._workers[project.id] = worker

        # Push initial vers le dashboard
        self._broadcast({
            "type":    "project_created",
            "project": self._project_summary(project),
        })

        asyncio.create_task(
            asyncio.wait_for(worker.run(), timeout=project.timeout_minutes * 60),
            name=f"worker-{project.id}",
        )

        logger.info("Project launched", id=project.id, steps=len(project.steps))
        return project

    # ── Kill switch ───────────────────────────────────────────────────────────

    def kill(self, project_id: str) -> bool:
        worker = self._workers.get(project_id)
        if not worker:
            return False
        worker.kill()
        return True

    # ── Approval system ───────────────────────────────────────────────────────

    async def _request_approval(
        self, project_id: str, step_id: str, description: str
    ) -> bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        key = f"{project_id}:{step_id}"
        self._pending_approvals[key] = future

        self._broadcast({
            "type":         "approval_request",
            "project_id":   project_id,
            "step_id":      step_id,
            "description":  description,
            "approval_key": key,
        })

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=600)
        except asyncio.TimeoutError:
            self._pending_approvals.pop(key, None)
            logger.warning("Approval timeout", key=key)
            return False

    def resolve_approval(self, project_id: str, step_id: str, approved: bool) -> bool:
        key = f"{project_id}:{step_id}"
        future = self._pending_approvals.pop(key, None)
        if future and not future.done():
            future.set_result(approved)
            return True
        return False

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_project(self, project_id: str) -> Project | None:
        return self._store.load_project(project_id)

    def list_projects(self) -> list[Project]:
        return self._store.list_projects()

    def get_logs(self, project_id: str, last_n: int = 200) -> list[LogEntry]:
        project = self._store.load_project(project_id)
        if not project:
            return []
        return self._store.get_logs(project, last_n)

    def get_workspace_files(self, project_id: str) -> list[str]:
        from agent.file_tool import SandboxedFileTool
        project = self._store.load_project(project_id)
        if not project:
            return []
        return SandboxedFileTool(project.workspace_path).list_files()

    def read_workspace_file(self, project_id: str, path: str) -> str:
        from agent.file_tool import SandboxedFileTool
        project = self._store.load_project(project_id)
        if not project:
            raise FileNotFoundError(f"Projet non trouvé : {project_id}")
        return SandboxedFileTool(project.workspace_path).read_file(path)

    # ── Serialization helpers ─────────────────────────────────────────────────

    @staticmethod
    def _project_summary(project: Project) -> dict:
        done  = sum(1 for s in project.steps if s.status == "done")
        total = len(project.steps)
        return {
            "id":              project.id,
            "title":           project.title,
            "status":          project.status,
            "steps_done":      done,
            "steps_total":     total,
            "progress":        round(done / total * 100) if total else 0,
            "timeout_minutes": project.timeout_minutes,
            "created_at":      project.created_at.isoformat(),
            "steps": [
                {
                    "id":               s.id,
                    "title":            s.title,
                    "status":           s.status,
                    "requires_approval": s.requires_approval,
                    "output":           s.output,
                    "error":            s.error,
                }
                for s in project.steps
            ],
        }
