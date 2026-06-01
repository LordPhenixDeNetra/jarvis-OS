"""
Jarvis Voice Agent — LiveKit Agents pipeline vocal.
Process indépendant de main.py FastAPI.
Lance avec : uv run python voice_agent.py dev
Test console (sans browser) : uv run python voice_agent.py console
"""

from __future__ import annotations

import logging
import os
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    WorkerOptions,
    cli,
)
from livekit.agents import (
    llm as lk_llm,
)
from livekit.agents.voice.room_io import AudioInputOptions, RoomOptions
from livekit.plugins import deepgram, elevenlabs, silero
from livekit.plugins import google as lk_google

load_dotenv(Path(__file__).parent / ".env")

# Réduit le bruit du terminal : warnings Python + format loguru aligné sur main.py.
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
try:
    from loguru import logger as _loguru

    _loguru.remove()
    _loguru.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level>"
            " | <cyan>{name}</cyan> — {message}"
        ),
        colorize=True,
    )
except Exception:
    pass


logger = logging.getLogger("jarvis-voice")

# ─── Prompt système vocal (base) ───────────────────────────────────────────────

_VOICE_SYSTEM_BASE = """
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
- Quand tu utilises un outil, annonce-le en 1 phrase courte avant (ex: "Je vérifie l'imprimante…").

Réponds en français sauf si Barth parle en anglais.
"""


# ─── Chargement des skills ─────────────────────────────────────────────────────


def _build_voice_instructions() -> str:
    """Prompt système = base + SYSTEM_PROMPT de chaque skill actif."""
    try:
        from skills.registry import SkillRegistry

        reg = SkillRegistry.get_instance()
        skill_prompt = reg.get_combined_system_prompt()
        if skill_prompt:
            return _VOICE_SYSTEM_BASE + "\n\n# SKILLS ACTIFS\n\n" + skill_prompt
    except Exception as e:
        logger.warning("Skills non chargés pour les instructions vocales: %s", e)
    return _VOICE_SYSTEM_BASE


def _make_livekit_tool(jarvis_tool: object) -> lk_llm.RawFunctionTool:
    """Wraps un Jarvis Tool comme LiveKit RawFunctionTool."""
    schema = jarvis_tool.to_claude_schema()  # type: ignore[attr-defined]
    raw_schema = {
        "name": schema["name"],
        "description": schema["description"],
        "parameters": schema["input_schema"],
    }

    async def _execute(raw_arguments: dict[str, object]) -> str:
        result = await jarvis_tool.execute(**raw_arguments)  # type: ignore[attr-defined]
        return f"[ERREUR] {result.content}" if result.is_error else result.content

    return lk_llm.function_tool(_execute, raw_schema=raw_schema)


def _voice_broadcast(event: dict) -> None:
    """Envoie un événement UI via HTTP au serveur FastAPI (localhost)."""
    import json as _json
    import threading
    import urllib.request

    def _post() -> None:
        from config.settings import settings

        url = f"http://localhost:{settings.port}/internal/broadcast"
        data = _json.dumps(event).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=2)
        except Exception as e:
            logger.debug("Voice broadcast HTTP fail: %s", e)

    threading.Thread(target=_post, daemon=True).start()


def _build_voice_tools() -> list:
    """Retourne les LiveKit tools en miroir du mode texte (main.py)."""
    from pathlib import Path

    from config.settings import settings

    _root = Path(__file__).parent
    _google_creds = (_root / settings.google_credentials_path).resolve()
    _gmail_token = (_root / "config/google_gmail_token.json").resolve()
    _calendar_token = (_root / settings.google_token_path).resolve()
    _allowed_roots = [Path(r).expanduser().resolve() for r in settings.file_search_roots]

    jarvis_tools = []

    _tool_factories = [
        ("weather", lambda: __import__("tools.weather", fromlist=["WeatherTool"]).WeatherTool()),
        ("browser", lambda: __import__("tools.browser", fromlist=["BrowserTool"]).BrowserTool()),
        ("vision", lambda: __import__("tools.vision", fromlist=["VisionTool"]).VisionTool()),
        (
            "filesystem",
            lambda: [
                __import__("tools.filesystem", fromlist=["ReadFileTool"]).ReadFileTool(
                    allowed_roots=_allowed_roots
                ),
                __import__("tools.filesystem", fromlist=["FindFilesTool"]).FindFilesTool(
                    allowed_roots=_allowed_roots
                ),
            ],
        ),
        (
            "cli",
            lambda: [
                __import__("tools.cli", fromlist=["CLIRunnerTool"]).CLIRunnerTool(
                    whitelist_path=Path(settings.cli_whitelist_path)
                ),
                __import__("tools.cli", fromlist=["ExecuteCLITool"]).ExecuteCLITool(),
            ],
        ),
        (
            "calendar",
            lambda: [
                __import__("tools.calendar", fromlist=["CalendarListTool"]).CalendarListTool(
                    credentials_path=_google_creds, token_path=_calendar_token
                ),
                __import__("tools.calendar", fromlist=["CalendarCreateTool"]).CalendarCreateTool(
                    credentials_path=_google_creds, token_path=_calendar_token
                ),
            ],
        ),
        (
            "notion",
            lambda: __import__("tools.notion", fromlist=["NotionTasksTool"]).NotionTasksTool(),
        ),
        (
            "memory",
            lambda: __import__(
                "tools.memory", fromlist=["MemoryTopicWriteTool"]
            ).MemoryTopicWriteTool(),
        ),
        ("spotify", lambda: __import__("tools.spotify", fromlist=["SpotifyTool"]).SpotifyTool()),
        (
            "gmail",
            lambda: __import__("tools.gmail", fromlist=["GmailListTool"]).GmailListTool(
                credentials_path=_google_creds, token_path=_gmail_token
            ),
        ),
        # show_view fourni par le skill globe-view
        (
            "preset",
            lambda: __import__("tools.preset", fromlist=["ExecutePresetTool"]).ExecutePresetTool(),
        ),
    ]

    for name, factory in _tool_factories:
        try:
            result = factory()
            if isinstance(result, list):
                jarvis_tools += result
            else:
                jarvis_tools.append(result)
        except Exception as e:
            logger.warning("Outil '%s' non chargé: %s", name, e)

    # Outils des skills installés (BambuLab, Fusion360…)
    try:
        from skills.registry import SkillRegistry

        reg = SkillRegistry.get_instance()
        jarvis_tools += reg.get_all_tools()
    except Exception as e:
        logger.warning("Skill tools non chargés: %s", e)

    tools = [_make_livekit_tool(t) for t in jarvis_tools]
    logger.info("Voice tools chargés: %s", [t._info.name for t in tools])
    return tools


# ─── Agent Jarvis ──────────────────────────────────────────────────────────────


class JarvisVoiceAgent(Agent):
    def __init__(self, instructions: str, tools: list) -> None:
        super().__init__(instructions=instructions, tools=tools)

    async def on_enter(self) -> None:
        await self.session.say(
            "Systèmes en ligne. Bonjour Barth.",
            allow_interruptions=True,
        )


# ─── Prewarm — chargé une fois au démarrage du process ─────────────────────────


def prewarm(proc: object) -> None:
    """Pré-charge les skills, outils et le modèle VAD avant l'arrivée d'un job."""
    proc.userdata["instructions"] = _build_voice_instructions()  # type: ignore[attr-defined]
    proc.userdata["tools"] = _build_voice_tools()  # type: ignore[attr-defined]
    # Le modèle ONNX silero met ~300-800ms à charger ; le faire ici évite de payer
    # ce coût au premier clic micro.
    proc.userdata["vad"] = silero.VAD.load(  # type: ignore[attr-defined]
        min_speech_duration=0.05,
        min_silence_duration=0.2,
        activation_threshold=0.5,
    )
    logger.info("=" * 40)
    logger.info("✓ Jarvis vocal prêt — clique sur le micro")
    logger.info("=" * 40)


# ─── Session et pipeline ───────────────────────────────────────────────────────


async def entrypoint(ctx: object) -> None:
    from dotenv import dotenv_values
    from livekit import rtc as lk_rtc

    _env = dotenv_values(Path(__file__).parent / ".env")

    _quebec = _env.get("QUEBEC_MODE", "false").strip().lower() in ("true", "1", "yes")
    _voice_id = _env.get("QUEBEC_VOICE_ID") if _quebec else _env.get("ELEVENLABS_VOICE_ID", "")
    _tts_model = (
        "eleven_multilingual_v2" if _quebec else _env.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
    )

    logger.info("TTS config — quebec=%s model=%s voice=%s", _quebec, _tts_model, _voice_id)

    # Pré-connecte la room avec un connect_timeout étendu pour éviter les retries v0/v1 de 5s.
    # livekit-agents utilise rtc.RoomOptions() sans connect_timeout (défaut Rust ~5s),
    # ce qui cause des timeouts systématiques sur le v0 path. On se connecte nous-mêmes d'abord.
    _info = getattr(ctx, "_info", None)
    if _info and not getattr(ctx, "_connected", False):
        try:
            await ctx.room.connect(
                _info.url,
                _info.token,
                options=lk_rtc.RoomOptions(auto_subscribe=True, connect_timeout=15.0),
            )
            ctx._connected = True  # empêche la double connexion dans session.start()
            logger.info("Room pre-connected: %s", ctx.room.name)
        except Exception as e:
            logger.warning("Pre-connect failed (%s), session.start() va réessayer", e)

    # Récupère les données pré-chargées par prewarm (fallback si prewarm non exécuté)
    userdata = getattr(ctx, "proc", None)
    userdata = getattr(userdata, "userdata", {}) if userdata else {}
    instructions = userdata.get("instructions") or _build_voice_instructions()
    tools = userdata.get("tools") or _build_voice_tools()
    vad = userdata.get("vad") or silero.VAD.load(
        min_speech_duration=0.05,
        min_silence_duration=0.2,
        activation_threshold=0.5,
    )

    session = AgentSession(
        # VAD — détection de voix (pré-chargé dans prewarm)
        vad=vad,
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
        # TTS — ElevenLabs : chunk_length_schedule courts → 1er chunk audio plus rapide.
        # streaming_latency est deprecated, on le retire.
        tts=elevenlabs.TTS(
            model=_tts_model,
            voice_id=_voice_id,
            api_key=_env.get("ELEVENLABS_API_KEY", os.getenv("ELEVENLABS_API_KEY", "")),
            encoding="pcm_24000",
            chunk_length_schedule=[50, 90, 160, 250],
        ),
        # Désactive l'adaptive interruption (agent-gateway.livekit.cloud) — local dev only
        turn_handling={"interruption": {"mode": "vad"}},
    )

    agent = JarvisVoiceAgent(instructions=instructions, tools=tools)

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
            prewarm_fnc=prewarm,
            agent_name="jarvis",
            initialize_process_timeout=30.0,  # 10s par défaut, trop court si réseau lent
            max_retry=32,
            # Garde 1 process Python pré-chauffé (skills/tools/VAD déjà chargés)
            # pour que le clic micro ne paie pas un cold start de 5-7s.
            num_idle_processes=1,
        )
    )
