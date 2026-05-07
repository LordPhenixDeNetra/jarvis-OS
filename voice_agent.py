"""
Jarvis Voice Agent — LiveKit Agents pipeline vocal.
Process indépendant de main.py FastAPI.
Lance avec : uv run python voice_agent.py dev
Test console (sans browser) : uv run python voice_agent.py console
"""
from __future__ import annotations
from livekit.plugins import google as lk_google
from livekit.plugins import deepgram, elevenlabs, silero
from livekit.agents import (
    Agent,
    AgentSession,
    WorkerOptions,
    cli,
)
from livekit.agents.voice.room_io import RoomOptions, AudioInputOptions

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


logger = logging.getLogger("jarvis-voice")

# ─── Prompt système vocal ──────────────────────────────────────────────────────

VOICE_SYSTEM_PROMPT = """
Tu es Jarvis, l'assistant IA personnel de Barth.

Règles absolues pour la voix :
- Réponses COURTES. Maximum 2-3 phrases sauf si l'utilisateur demande explicitement plus.
- Pas de listes à puces, pas de markdown, pas d'astérisques.
- Pas d'émojis.
- Parle naturellement, comme dans une conversation.
- Tu peux dire "mhm", "hmm", "ok", "allez" pour paraître naturel.
- Si tu dois faire quelque chose d'écran (code, liste longue), dis-le brièvement
  et propose de l'envoyer par écrit dans l'interface.
- Tu connais Barth : auto-entrepreneur à Lyon, YouTuber maker/électronique,
  projet Chimp NFC, Jarvis IA, communauté Le Labo.

Réponds en français sauf si Barth parle en anglais.
"""


# ─── Agent Jarvis ──────────────────────────────────────────────────────────────


class JarvisVoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=VOICE_SYSTEM_PROMPT,
            tools=[],
        )

    async def on_enter(self) -> None:
        await self.session.say(
            "Systèmes en ligne. Bonjour Barth.",
            allow_interruptions=True,
        )


# ─── Session et pipeline ───────────────────────────────────────────────────────


async def entrypoint(ctx: object) -> None:
    from dotenv import dotenv_values
    _env = dotenv_values(Path(__file__).parent / ".env")

    _quebec = _env.get("QUEBEC_MODE", "false").strip().lower() in ("true", "1", "yes")
    _voice_id = _env.get("QUEBEC_VOICE_ID") if _quebec else _env.get("ELEVENLABS_VOICE_ID", "")
    _tts_model = "eleven_multilingual_v2" if _quebec else _env.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")

    logger.info("TTS config — quebec=%s model=%s voice=%s", _quebec, _tts_model, _voice_id)

    session = AgentSession(
        # VAD — détection de voix
        vad=silero.VAD.load(
            min_speech_duration=0.05,
            min_silence_duration=0.3,
            activation_threshold=0.5,
        ),
        # STT — Deepgram Nova-2 streaming
        stt=deepgram.STT(
            model="nova-2",
            language="fr",
            smart_format=True,
            interim_results=True,
        ),
        # LLM — Gemini 2.5 Flash
        llm=lk_google.LLM(
            model="gemini-2.5-flash",
            temperature=0.7,
        ),
        # TTS — ElevenLabs
        tts=elevenlabs.TTS(
            model=_tts_model,
            voice_id=_voice_id,
            api_key=_env.get("ELEVENLABS_API_KEY", os.getenv("ELEVENLABS_API_KEY", "")),
            encoding="pcm_24000",
            streaming_latency=3,
        ),
    )

    agent = JarvisVoiceAgent()

    await session.start(
        room=ctx.room,
        agent=agent,
        room_options=RoomOptions(
            audio_input=AudioInputOptions(noise_cancellation=None),
        ),
    )


# ─── Lancement ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="jarvis",
        )
    )
