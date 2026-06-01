from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

import httpx
from loguru import logger

from config.settings import settings
from llm.base import LLMProvider

# Strip <think>...</think> au cas où Ollama les laisse passer (fallback)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text).lstrip()


class OllamaProvider(LLMProvider):
    """Provider Ollama pour les modèles locaux (Qwen3, Mistral…).

    Chat-only : supports_tools retourne False (valeur de base).
    Le function calling Ollama dépend du modèle sous-jacent et n'est pas
    activé ici car l'API /api/chat native ne garantit pas le format
    OpenAI tool_calls pour tous les modèles configurés.
    """

    def __init__(self) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model

    def _payload(self, messages: list[dict], system: str, stream: bool) -> dict:
        return {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": stream,
            "think": False,  # désactive le mode reasoning Qwen3 côté Ollama
            "options": {"temperature": 0.7},
        }

    async def complete(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict] | None = None,
        stream: bool = False,
        context: str = "",
    ) -> str | AsyncIterator[str]:
        payload = self._payload(messages, system, stream)

        if stream:
            return self._stream(payload)

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self._base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            text: str = data["message"]["content"]
            logger.debug("Ollama complete", model=self._model, chars=len(text))
            return _strip_think(text)

    async def _stream(self, payload: dict) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{self._base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                in_think = False
                think_buf = ""

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    delta: str = data.get("message", {}).get("content", "")

                    if delta:
                        # Filtre <think>...</think> token par token (sécurité)
                        think_buf += delta
                        output = ""
                        while think_buf:
                            if in_think:
                                end = think_buf.find("</think>")
                                if end == -1:
                                    think_buf = ""
                                    break
                                think_buf = think_buf[end + len("</think>") :]
                                in_think = False
                            else:
                                start = think_buf.find("<think>")
                                if start == -1:
                                    output += think_buf
                                    think_buf = ""
                                    break
                                output += think_buf[:start]
                                think_buf = think_buf[start + len("<think>") :]
                                in_think = True
                        if output:
                            yield output

                    if data.get("done"):
                        break

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                return response.status_code == 200
        except Exception as e:
            logger.error("Ollama health check failed", error=str(e))
            return False
