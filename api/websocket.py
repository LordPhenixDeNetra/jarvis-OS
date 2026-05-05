from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from background.notifications import NotificationQueue, ProactiveQueue
from background.worker import BackgroundTask, BackgroundWorker
from core.gateway import _FALLBACK, Gateway
from core.router import RouteEnum
from memory.auto_dream import AutoDream
from memory.consolidation import ConsolidationAgent
from tools.spotify import SpotifyTool
from vision.objects_queue import get_vision_objects_queue

router = APIRouter()

_spotify_tool = SpotifyTool()

_GESTURE_DIRECT_ACTIONS: dict[str, str] = {
    "Open_Palm": "toggle",
    "Victory":   "next",
}

_GESTURE_LLM_COMMANDS: dict[str, str] = {
    "Thumb_Up":    "Oui, confirme",
    "Thumb_Down":  "Non, annule",
    "Pointing_Up": "Hey Jarvis",
}

_PRESENCE_MSGS: dict[bool, str] = {
    True:  "L'utilisateur est revenu devant l'ordinateur.",
    False: "L'utilisateur s'est éloigné de l'ordinateur.",
}


async def _handle_vision_event(
    data: dict,
    websocket: WebSocket,
    gateway: Gateway,
    notifications: NotificationQueue,
) -> None:
    """Traite un événement MediaPipe reçu depuis le navigateur."""
    event = data.get("event")

    if event == "presence":
        active: bool = bool(data.get("active", True))
        notifications.add(_PRESENCE_MSGS[active])
        logger.debug("Vision presence", active=active)
        return

    if event == "gesture_direct":
        gesture = data.get("gesture", "")
        action = _GESTURE_DIRECT_ACTIONS.get(gesture)
        if action:
            result = await _spotify_tool.execute(action=action)
            logger.info("Vision gesture direct", gesture=gesture, action=action, ok=not result.is_error)
        return

    if event == "gesture_volume":
        delta = int(data.get("delta", 0))
        if delta:
            result = await _spotify_tool.execute(action="volume_delta", delta=delta)
            logger.debug("Vision gesture volume", delta=delta, ok=not result.is_error)
        return

    if event == "gesture":
        gesture = data.get("gesture", "")
        message = _GESTURE_LLM_COMMANDS.get(gesture)
        if not message:
            return
        logger.info("Vision gesture LLM", gesture=gesture, message=message)
        session_id: str | None = data.get("session_id")
        session, route, response = await gateway.handle(
            message=message, session_id=session_id, stream=True
        )
        await websocket.send_json(
            {"type": "start", "session_id": str(session.id), "route": route.value}
        )
        full = ""
        if isinstance(response, str):
            full = response
            await websocket.send_json({"type": "chunk", "content": response})
        else:
            try:
                async for chunk in response:
                    full += chunk
                    await websocket.send_json({"type": "chunk", "content": chunk})
            except Exception as e:
                logger.error("Vision gesture stream error", error=str(e))
                full = _FALLBACK
                await websocket.send_json({"type": "chunk", "content": _FALLBACK})
        session.add_message("assistant", full)
        await websocket.send_json({"type": "done"})


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket de chat texte. Protocole JSON :

    Client → Server : {"message": "...", "session_id": "uuid|null"}
    Server → Client :
      {"type": "start",  "session_id": "...", "route": "I|CF|BG"}
      {"type": "chunk",  "content": "..."}
      {"type": "done"}
      {"type": "error",  "content": "..."}

    Pour la route BG : l'ack est streamé token par token, "done" est envoyé dès que
    l'ack est terminé, et la tâche background est soumise APRÈS — elle ne bloque jamais
    le client.
    """
    await websocket.accept()
    logger.info("WebSocket connection opened")

    gateway: Gateway = websocket.app.state.gateway
    worker: BackgroundWorker = websocket.app.state.worker
    consolidation: ConsolidationAgent = websocket.app.state.consolidation
    auto_dream: AutoDream = websocket.app.state.auto_dream
    proactive: ProactiveQueue = websocket.app.state.proactive_queue
    notifications: NotificationQueue = websocket.app.state.notifications

    sub_q = proactive.subscribe()
    objects_q = get_vision_objects_queue().subscribe()

    async def _push_proactive() -> None:
        while True:
            item = await sub_q.get()
            try:
                if isinstance(item, dict):
                    await websocket.send_json(item)
                else:
                    await websocket.send_json({"type": "notification", "content": item})
            except Exception as e:
                logger.warning("Proactive push failed", error=str(e))

    async def _push_vision_objects() -> None:
        while True:
            objects = await objects_q.get()
            try:
                await websocket.send_json({"type": "vision_objects", "objects": objects})
            except Exception:
                pass

    pusher_task = asyncio.create_task(_push_proactive(), name="ws-proactive-pusher")
    vision_pusher_task = asyncio.create_task(_push_vision_objects(), name="ws-vision-pusher")

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "JSON invalide."})
                continue

            # ── Vision events (MediaPipe) ─────────────────────────────────────
            if data.get("type") == "vision_event":
                await _handle_vision_event(data, websocket, gateway, notifications)
                continue

            message: str = data.get("message", "").strip()
            session_id: str | None = data.get("session_id")

            if not message:
                await websocket.send_json({"type": "error", "content": "Message vide."})
                continue

            # Signaler l'activité — le ProactiveEngine attendra avant son prochain appel LLM
            proactive_engine = getattr(websocket.app.state, "proactive_engine", None)
            if proactive_engine is not None:
                proactive_engine.signal_user_activity()

            session, route, response = await gateway.handle(
                message=message,
                session_id=session_id,
                stream=True,
            )

            logger.debug("Route", route=route.value, session_id=str(session.id))
            await websocket.send_json(
                {"type": "start", "session_id": str(session.id), "route": route.value}
            )

            full = ""
            if isinstance(response, str):
                full = response
                await websocket.send_json({"type": "chunk", "content": response})
            else:
                try:
                    async for chunk in response:
                        full += chunk
                        await websocket.send_json({"type": "chunk", "content": chunk})
                except Exception as e:
                    logger.error("Stream error", error=str(e))
                    full = _FALLBACK
                    await websocket.send_json({"type": "chunk", "content": _FALLBACK})

            session.add_message("assistant", full)

            # ── "done" envoyé en premier — client débloqué ────────────────────
            await websocket.send_json({"type": "done"})

            # ── BG : soumission APRÈS "done" (gateway ne soumet plus) ─────────
            if route is RouteEnum.BACKGROUND:
                worker.submit(BackgroundTask(session_id=str(session.id), instruction=message))
                logger.info("BackgroundTask submitted", session_id=str(session.id))

            # ── PROJECT : lancement orchestrateur APRÈS "done" ────────────────
            elif route is RouteEnum.PROJECT:
                orchestrator = getattr(websocket.app.state, "orchestrator", None)
                if orchestrator:
                    async def _run_project(msg: str = message) -> None:
                        try:
                            await orchestrator.create_and_run(msg)
                        except Exception as exc:
                            logger.error("Project creation failed", error=str(exc))
                            proactive.broadcast_event({
                                "type": "notification",
                                "content": f"Erreur création projet : {exc}",
                            })
                    asyncio.create_task(_run_project(), name=f"project-{str(session.id)[:8]}")
                    logger.info("Project task launched", session_id=str(session.id))

            # ── mémoire post-done, hors chemin critique ───────────────────────
            # sleep(2) laisse la connexion HTTP principale se libérer avant que
            # le background_llm parte — évite la contention sur le client Anthropic.
            await asyncio.sleep(2)
            asyncio.create_task(
                consolidation._run_safe(user_message=message, assistant_message=full),
                name="consolidation",
            )
            asyncio.create_task(
                auto_dream._run_micro_safe(user_message=message, assistant_message=full),
                name="autodream-micro",
            )

    except WebSocketDisconnect:
        logger.info("WebSocket connection closed")
    except Exception as e:
        logger.error("WebSocket fatal error", error=str(e))
        try:
            await websocket.send_json({"type": "error", "content": "Erreur serveur."})
        except Exception:
            pass
    finally:
        pusher_task.cancel()
        vision_pusher_task.cancel()
        proactive.unsubscribe(sub_q)
        get_vision_objects_queue().unsubscribe(objects_q)
