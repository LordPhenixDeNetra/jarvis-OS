"""
Jarvis Voice Agent — LiveKit Agents pipeline vocal.
Architecture bridge : STT/TTS LiveKit → Claude via gateway Jarvis.
Le LLM Gemini est remplacé par JarvisGatewayLLM qui délègue à core/gateway.py
(Claude + outils + mémoire complète, même session que le chat texte).
Lance avec : uv run python voice_agent.py dev
"""
from __future__ import annotations

import logging
import os
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

from livekit.agents import (
    Agent,
    AgentSession,
    WorkerOptions,
    cli,
)
from livekit.agents import llm as lk_llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions
from livekit.agents.voice.room_io import RoomOptions
from livekit.plugins import deepgram, elevenlabs, silero
from livekit.plugins.elevenlabs import VoiceSettings

logger = logging.getLogger("jarvis-voice")

JARVIS_API = "http://localhost:8000"

# Instructions minimales — le vrai prompt système est géré par core/agent.py via le gateway
_AGENT_INSTRUCTIONS = (
    "Tu es Jarvis, assistant personnel de Barth. "
    "Réponds oralement : sans markdown, réponses courtes 2-3 phrases max."
)


# ─── LLM bridge → gateway Jarvis ──────────────────────────────────────────────


class JarvisGatewayLLM(lk_llm.LLM):
    """Délègue les appels LLM au gateway Jarvis (Claude + outils + mémoire complète)."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self._session_id = session_id

    def chat(
        self,
        *,
        chat_ctx: lk_llm.ChatContext,
        tools=None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        **kwargs,
    ) -> "JarvisGatewayStream":
        # Extraire le dernier message utilisateur du chat_ctx LiveKit
        user_msg = ""
        for item in reversed(chat_ctx.items):
            if isinstance(item, lk_llm.ChatMessage) and item.role == "user":
                user_msg = item.text_content or ""
                break
        return JarvisGatewayStream(
            llm=self,
            session_id=self._session_id,
            user_msg=user_msg,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class JarvisGatewayStream(lk_llm.LLMStream):
    def __init__(
        self,
        *,
        llm: lk_llm.LLM,
        session_id: str,
        user_msg: str,
        **kwargs,
    ) -> None:
        super().__init__(llm=llm, **kwargs)
        self._session_id = session_id
        self._user_msg = user_msg

    async def _run(self) -> None:
        if not self._user_msg.strip():
            return
        chunk_id = str(uuid.uuid4())
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{JARVIS_API}/api/voice/generate",
                    json={
                        "message": self._user_msg,
                        "session_id": self._session_id,
                    },
                ) as resp:
                    async for text in resp.aiter_text():
                        if text:
                            self._event_ch.send_nowait(
                                lk_llm.ChatChunk(
                                    id=chunk_id,
                                    delta=lk_llm.ChoiceDelta(
                                        role="assistant",
                                        content=text,
                                    ),
                                )
                            )
        except Exception as e:
            logger.error("JarvisGatewayStream error: %s", e)
            self._event_ch.send_nowait(
                lk_llm.ChatChunk(
                    id=chunk_id,
                    delta=lk_llm.ChoiceDelta(
                        role="assistant",
                        content="Désolé, j'ai eu un souci.",
                    ),
                )
            )


# ─── Agent Jarvis ──────────────────────────────────────────────────────────────


class JarvisVoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=_AGENT_INSTRUCTIONS,
            # Délai avant de finaliser un tour — évite de couper les pauses naturelles
            min_endpointing_delay=0.8,
            max_endpointing_delay=6.0,
        )

    async def on_enter(self) -> None:
        await self.session.say(
            "Systèmes en ligne. Bonjour Barth.",
            allow_interruptions=True,
        )


# ─── Session et pipeline ───────────────────────────────────────────────────────


async def entrypoint(ctx: object) -> None:
    # Lire le session_id depuis le nom de la room (format: "jarvis-<session_id>")
    # Fiable car ctx.room.name est disponible immédiatement, sans race condition participant
    session_id = None
    room_name = ctx.room.name
    if room_name and room_name.startswith("jarvis-"):
        candidate = room_name[len("jarvis-"):]
        # Vérifie que c'est un vrai UUID (pas un hex court généré faute de session)
        if len(candidate) > 16:
            session_id = candidate

    if not session_id:
        session_id = str(uuid.uuid4())
        logger.info("Voice: nouvelle session %s", session_id[:8])
    else:
        logger.info("Voice: session partagée %s", session_id[:8])

    gateway_llm = JarvisGatewayLLM(session_id=session_id)

    session = AgentSession(
        vad=silero.VAD.load(
            min_speech_duration=0.1,
            min_silence_duration=0.8,
            activation_threshold=0.5,
        ),
        stt=deepgram.STT(
            model="nova-2",
            language="fr",
            smart_format=True,
            interim_results=True,
        ),
        llm=gateway_llm,
        tts=elevenlabs.TTS(
            model="eleven_multilingual_v2",
            voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
            api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            voice_settings=VoiceSettings(
                stability=0.4,
                similarity_boost=0.8,
                style=0.3,
                speed=1.0,
            ),
        ),
    )

    agent = JarvisVoiceAgent()

    await session.start(
        room=ctx.room,
        agent=agent,
        room_options=RoomOptions(delete_room_on_close=True),
    )


# ─── Lancement ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="jarvis",
        )
    )
