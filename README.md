# Jarvis OS

Personal AI assistant — text & real-time voice, self-hosted, fully open stack.

---

## What is it?

Jarvis is a personal AI assistant running locally. It exposes a FastAPI server that handles both a text chat interface and a real-time voice pipeline (via LiveKit). It connects to the LLM of your choice, remembers conversations, uses tools (web search, Gmail, Google Calendar, Spotify, vision, code execution…) and runs background proactive tasks (weather alerts, news digests, etc.).

**Key features:**

- Real-time voice pipeline — STT (Whisper/Deepgram) + LLM + TTS (Piper/ElevenLabs), bridged via LiveKit
- Persistent memory — sessions, topics, auto-consolidation (nightly "dream" pass), vector search
- Tool use — browser, Gmail, Google Calendar, Notion, Spotify, CLI runner, filesystem, vision (YOLOv8), weather
- Skills system — pluggable autonomous modules (e.g. web researcher)
- Proactive engine — background agent that sends notifications on triggers (weather, news…)
- Multi-LLM — Anthropic Claude, Mistral, Google Gemini, or local Ollama models
- Admin UI — web dashboard, globe widget, control panel

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  FastAPI server (main.py)             │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ /api/ws  │  │ /api/http│  │  /admin (UI)     │   │
│  └────┬─────┘  └────┬─────┘  └──────────────────┘   │
│       │              │                                │
│  ┌────▼──────────────▼──────────────────────────┐   │
│  │              Gateway  (core/gateway.py)        │   │
│  │   session ──► Agent ──► LLM ──► Tool calls    │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  Memory          Background         Proactive        │
│  sessions/       scheduler/         engine/          │
│  topics/         worker/            collectors/      │
│  consolidation   notifications                       │
└──────────────────────────────────────────────────────┘

voice_agent.py  ──LiveKit──►  STT ──► Gateway ──► TTS
```

| Module | Role |
|---|---|
| `core/` | Agent, Gateway, SessionManager, Router |
| `llm/` | Provider abstraction (Anthropic, Mistral, Ollama, Gemini) |
| `memory/` | Sessions, topics, vector index, auto-consolidation |
| `tools/` | All callable tools (browser, Gmail, Calendar, vision…) |
| `skills/` | Higher-level pluggable modules |
| `audio/` | STT, TTS, VAD, wake word, audio chunker |
| `proactive/` | Background proactive engine + collectors |
| `background/` | Scheduler, worker, notification queue |
| `agent/` | Autonomous project/code agent (Docker executor) |
| `api/` | FastAPI routers (WS, HTTP, admin, voice, globe…) |
| `config/` | Settings (pydantic-settings), tools.yaml |
| `prompts/` | System prompt (static + dynamic context) |

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| [uv](https://docs.astral.sh/uv/) | latest | Package manager |
| [LiveKit](https://livekit.io/) | cloud or self-hosted | Voice pipeline only |
| Docker | optional | Required by the code-agent feature |

---

## Installation

```bash
git clone https://github.com/Grominet95/jarvis-OS.git
cd jarvis-OS
bash install.sh
```

The script:
1. Checks Python 3.11+
2. Installs/updates `uv`
3. Creates `.venv` and installs all Python dependencies (`pyproject.toml`)
4. Copies `.env.example` → `.env`
5. Downloads YOLOv8n model (~6 MB)
6. Downloads Piper TTS French model (~73 MB)
7. Creates `memory_data/` and `workspace/` directories

---

## Configuration

Edit `.env` — all keys are documented in `.env.example`:

```bash
# Minimum to start (text mode, Anthropic)
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=api

# Voice pipeline (LiveKit + Deepgram)
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxx
LIVEKIT_API_SECRET=xxx
DEEPGRAM_API_KEY=xxx
```

Optional services: ElevenLabs TTS, Mistral, Gemini, AISstream, Spotify.

**Google integrations (Gmail / Calendar):** place your OAuth `credentials.json` from Google Cloud Console at `config/google_credentials.json`, then start Jarvis — it will open a browser auth flow and save tokens locally (they are gitignored).

---

## Running

**Text + API server:**
```bash
uv run python main.py
# Server starts on http://localhost:8000
# Admin UI: http://localhost:8000/admin
```

**Voice agent (LiveKit):**
```bash
uv run python voice_agent.py dev
```

Both can run simultaneously — the voice agent delegates to the main server's gateway so they share the same session, memory, and tools.

---

## Available tools

| Tool | Description |
|---|---|
| `browser` | Web search + page scraping |
| `gmail` | List recent emails |
| `calendar` | List / create Google Calendar events |
| `spotify` | Playback control |
| `notion` | Search and read pages |
| `weather` | Current weather (Open-Meteo — no API key needed) |
| `vision` | Screen capture + YOLOv8 object detection |
| `filesystem` | Read files, find by pattern |
| `cli` | Run whitelisted shell commands (configured in `config/tools.yaml`) |
| `memory` | Write structured notes to topic store |

---

## Memory system

| Component | What it stores |
|---|---|
| `sessions/` | Full conversation history (jsonl per session) |
| `topics/` | Named long-term notes (written by the assistant) |
| `conso/` | Daily consumption logs (tokens, cost) |
| `initiatives/` | Proactive event log |

Each night (or on demand), **AutoDream** + **ConsolidationAgent** pass over recent sessions and merge relevant information into topics — similar to how sleep consolidates memory.

All memory files live in `memory_data/` which is gitignored and stays on your machine only.

---

## Proactive engine

The proactive engine runs in the background and pushes notifications to the connected client via WebSocket. Built-in collectors:

- **Weather** — morning briefing + severe weather alerts
- **News** — RSS digest on configured topics

Add a new collector in `proactive/collectors/` to extend it.

---

## Development

```bash
# Run tests
uv run pytest

# Lint + format
uv run ruff check .
uv run ruff format .

# Manual LLM smoke test
uv run python scripts/test_llm.py --stream
uv run python scripts/test_llm.py --provider mistral
```

---

## Tech stack

- **Python 3.11** — async / FastAPI / uvicorn
- **Anthropic Claude** (primary LLM) + Mistral / Gemini / Ollama fallbacks
- **LiveKit Agents** — real-time voice pipeline
- **Deepgram** — cloud STT / **faster-whisper** — local STT
- **Piper** — local TTS / **ElevenLabs** — cloud TTS
- **YOLOv8** (ultralytics) — object detection for vision tool
- **pydantic-settings** — typed configuration
- **loguru** — structured logging
- **uv** — dependency management

---

## License

MIT
