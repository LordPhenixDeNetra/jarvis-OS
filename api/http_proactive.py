from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class RectifyBody(BaseModel):
    correction: str


# ── Initiatives API ───────────────────────────────────────────────────────────

@router.get("/api/initiatives")
async def get_initiatives() -> list[dict]:
    """Initiatives en attente (mode VALIDATE)."""
    from proactive.store import InitiativeStore
    store = InitiativeStore()
    initiatives = store.load_pending()
    return [
        {
            "id":               i.id,
            "type":             i.type,
            "title":            i.title,
            "context":          i.context,
            "reasoning":        i.reasoning,
            "action":           i.action,
            "priority":         i.priority,
            "execution_mode":   i.execution_mode,
            "draft_content":    i.draft_content,
            "created_at":       i.created_at.isoformat(),
        }
        for i in initiatives
    ]


@router.post("/api/initiatives/{initiative_id}/approve")
async def approve_initiative(initiative_id: str, request: Request) -> dict:
    import asyncio

    from loguru import logger as _log

    from proactive.schemas import InitiativeType
    from proactive.store import InitiativeStore

    store = InitiativeStore()
    init  = store.get_by_id(initiative_id)
    if not init:
        raise HTTPException(404, "Initiative introuvable")

    result: dict = {"status": "approved", "type": str(init.type)}

    try:
        if init.type == InitiativeType.DRAFT_RESPONSE:
            from config.settings import settings as _s
            from tools.gmail import send_gmail_draft
            msg_id = await send_gmail_draft(
                draft_content=init.draft_content or "",
                credentials_path=Path(_s.google_credentials_path),
                token_path=Path(_s.google_token_path).parent / "google_gmail_token.json",
            )
            result["message_id"] = msg_id
            _to = init.draft_content[:40] if init.draft_content else ""
            _log.info(f"Initiative {initiative_id}: email envoyé", to=_to)

        elif init.type == InitiativeType.AUTO_TASK:
            orchestrator = getattr(request.app.state, "orchestrator", None)
            if orchestrator:
                mission = init.mission_description or init.action
                asyncio.create_task(
                    orchestrator.create_and_run(mission),
                    name=f"initiative-{initiative_id[:8]}",
                )
                result["mission_launched"] = True
                _log.info(f"Initiative {initiative_id}: mission lancée", mission=mission[:60])
            else:
                result["warning"] = "Orchestrateur non disponible"

        else:
            _log.info(f"Initiative {initiative_id} approuvée", type=init.type, title=init.title)

    except Exception as e:
        _log.error(f"Initiative approve error ({init.type}): {e}")
        result["error"] = str(e)

    store.update_status(initiative_id, "approved")
    return result


@router.post("/api/initiatives/{initiative_id}/reject")
async def reject_initiative(initiative_id: str) -> dict:
    from proactive.store import InitiativeStore
    InitiativeStore().update_status(initiative_id, "rejected")
    return {"status": "rejected"}


@router.post("/api/initiatives/{initiative_id}/rectify")
async def rectify_initiative(initiative_id: str, body: RectifyBody) -> dict:
    from proactive.initiative_generator import InitiativeGenerator
    from proactive.store import InitiativeStore

    store    = InitiativeStore()
    init     = store.get_by_id(initiative_id)
    if not init:
        raise HTTPException(404, "Initiative introuvable")

    generator = InitiativeGenerator()
    new_init  = await generator.rectify(init, body.correction)
    if not new_init:
        raise HTTPException(500, "Régénération échouée")

    store.update_initiative(initiative_id, {
        "title":               new_init.title,
        "context":             new_init.context,
        "reasoning":           new_init.reasoning,
        "action":              new_init.action,
        "priority":            new_init.priority,
        "execution_mode":      new_init.execution_mode,
        "draft_content":       new_init.draft_content,
        "mission_description": new_init.mission_description,
    })

    return {
        "id":                  initiative_id,
        "type":                new_init.type,
        "title":               new_init.title,
        "context":             new_init.context,
        "reasoning":           new_init.reasoning,
        "action":              new_init.action,
        "priority":            new_init.priority,
        "execution_mode":      new_init.execution_mode,
        "draft_content":       new_init.draft_content,
        "mission_description": new_init.mission_description,
        "created_at":          init.created_at.isoformat(),
    }


# ── Proactive engine API ──────────────────────────────────────────────────────

@router.post("/api/proactive/run")
async def run_proactive_now(request: Request) -> dict:
    """Force un cycle proactif immédiat."""
    import asyncio
    engine = getattr(request.app.state, "proactive_engine", None)
    if not engine:
        raise HTTPException(503, "ProactiveEngine non disponible")
    asyncio.create_task(engine.run_now(), name="proactive-manual")
    return {"triggered": True}


@router.get("/api/proactive/status")
async def proactive_status(request: Request) -> dict:
    """Statut du moteur proactif (dernière exécution, prochaine)."""
    engine = getattr(request.app.state, "proactive_engine", None)
    if not engine:
        return {"running": False}
    last_run = engine._last_run.isoformat() if engine._last_run else None
    return {
        "running":    engine._running,
        "interval_s": engine._interval,
        "last_run":   last_run,
    }
