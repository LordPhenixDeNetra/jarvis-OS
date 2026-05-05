"""CLI sandboxé pour le WorkerAgent — whitelist stricte + exécution dans le workspace."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from loguru import logger

WORKER_CLI_WHITELIST: list[str] = [
    "python", "python3",
    "node", "npm", "npx",
    "git clone", "git init", "git add", "git status", "git log", "git diff",
    "pip install", "pip3 install",
    "mkdir", "touch", "cp", "mv",
    "ls", "cat", "head", "tail", "grep", "find", "wc",
    "echo", "printf",
    "curl -s", "curl --silent",
    "wget",
    "ffmpeg", "convert",
    "zip", "unzip", "tar",
    "uv", "uv run", "uv add",
    "pandoc", "pdftotext",
    "stat", "diff", "du", "sort", "uniq", "cut", "tr", "sed", "awk",
    "test", "true", "false",
    "sh -c", "bash -c",
]

# Ces patterns sont bloqués quoi qu'il arrive
_BLOCKED_RE = re.compile(
    r"rm\s+-[a-z]*r|rm\s+-[a-z]*f|"
    r">\s*/dev/|"
    r"\bsudo\b|"
    r"chmod\s+777|"
    r"curl\s+-X\s+POST|"
    r"curl\s+-X\s+DELETE|"
    r"git\s+push|"
    r"git\s+commit|"
    r":\(\)\s*\{",      # fork bomb
    re.IGNORECASE,
)


class WorkerCLITool:

    def __init__(self, workspace_path: str, docker_executor=None) -> None:
        self._workspace = Path(workspace_path).resolve()
        self._docker    = docker_executor  # None = V1 direct, DockerExecutor = V2

    def _check(self, command: str) -> dict | None:
        """Retourne un dict d'erreur si la commande est bloquée, None sinon."""
        if _BLOCKED_RE.search(command):
            logger.error("WorkerCLI blocked", command=command[:80])
            return {
                "success": False, "stdout": "",
                "stderr": f"Commande bloquée par la politique de sécurité : {command[:60]}",
                "returncode": -1,
            }
        stripped = command.strip()
        if not any(stripped.startswith(w) for w in WORKER_CLI_WHITELIST):
            logger.warning("WorkerCLI not whitelisted", command=command[:80])
            return {
                "success": False, "stdout": "",
                "stderr": (
                    f"Commande non autorisée. Commandes permises : "
                    f"{', '.join(WORKER_CLI_WHITELIST[:8])}..."
                ),
                "returncode": -1,
            }
        return None

    async def execute(self, command: str, timeout: int = 60) -> dict:
        """Exécute une commande. Route vers Docker (V2) ou direct (V1)."""
        err = self._check(command)
        if err:
            return err

        from config.settings import settings
        if self._docker and settings.docker_enabled:
            return await self._docker.execute(command, timeout)
        return await self._run_direct(command, timeout)

    async def _run_direct(self, command: str, timeout: int) -> dict:
        """Exécution directe V1 — dans le workspace sur l'hôte."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            logger.debug("WorkerCLI exec", cmd=command[:60], rc=proc.returncode)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode("utf-8", errors="replace")[:8000],
                "stderr": stderr.decode("utf-8", errors="replace")[:2000],
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            return {
                "success": False, "stdout": "",
                "stderr": f"Timeout après {timeout}s",
                "returncode": -1,
            }
        except Exception as e:
            return {
                "success": False, "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }
