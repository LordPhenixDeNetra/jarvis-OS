"""API REST pour les projets agent worker."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


def _orch(request: Request):
    return request.app.state.orchestrator


# ── Schemas ───────────────────────────────────────────────────────────────────

class ApprovalBody(BaseModel):
    step_id: str
    approved: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/projects")
async def list_projects(request: Request) -> list[dict]:
    orch = _orch(request)
    projects = orch.list_projects()
    return [
        {
            "id":          p.id,
            "title":       p.title,
            "status":      p.status,
            "steps_done":  sum(1 for s in p.steps if s.status == "done"),
            "steps_total": len(p.steps),
            "created_at":  p.created_at.isoformat(),
            "completed_at": p.completed_at.isoformat() if p.completed_at else None,
            "files_created": len(p.files_created),
        }
        for p in projects
    ]


@router.get("/api/projects/{project_id}")
async def get_project(project_id: str, request: Request) -> dict:
    orch = _orch(request)
    project = orch.get_project(project_id)
    if not project:
        raise HTTPException(404, f"Projet non trouvé : {project_id}")
    return orch._project_summary(project)


@router.get("/api/projects/{project_id}/logs")
async def get_logs(project_id: str, request: Request) -> list[dict]:
    orch = _orch(request)
    logs = orch.get_logs(project_id)
    return [
        {
            "ts":      e.timestamp.isoformat(),
            "level":   e.level,
            "msg":     e.message,
            "step_id": e.step_id,
            "data":    e.data,
        }
        for e in logs
    ]


@router.post("/api/projects/{project_id}/kill")
async def kill_project(project_id: str, request: Request) -> dict:
    orch = _orch(request)
    ok = orch.kill(project_id)
    if not ok:
        raise HTTPException(404, f"Worker actif non trouvé : {project_id}")
    return {"killed": True}


@router.post("/api/projects/{project_id}/approve")
async def approve_step(project_id: str, body: ApprovalBody, request: Request) -> dict:
    orch = _orch(request)
    ok = orch.resolve_approval(project_id, body.step_id, body.approved)
    return {"resolved": ok, "approved": body.approved}


@router.get("/api/projects/{project_id}/files")
async def list_files(project_id: str, request: Request) -> list[str]:
    orch = _orch(request)
    return orch.get_workspace_files(project_id)


@router.get("/api/projects/{project_id}/files/{path:path}")
async def read_file(project_id: str, path: str, request: Request) -> dict:
    orch = _orch(request)
    try:
        content = orch.read_workspace_file(project_id, path)
        return {"path": path, "content": content}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(403, str(e))


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, request: Request) -> dict:
    import shutil
    from pathlib import Path
    orch = _orch(request)
    project = orch.get_project(project_id)
    if not project:
        raise HTTPException(404, f"Projet non trouvé : {project_id}")
    orch.kill(project_id)
    workspace = Path(project.workspace_path)
    if workspace.exists():
        shutil.rmtree(workspace)
    return {"deleted": True}
