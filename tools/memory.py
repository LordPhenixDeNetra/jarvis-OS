from __future__ import annotations

from pathlib import Path

from config.settings import settings
from tools.base import Tool, ToolResult


class MemoryTopicWriteTool(Tool):
    """Écrit ou met à jour un fichier de mémoire thématique existant."""

    name = "memory_write"
    description = (
        "Écrire ou mettre à jour le contenu d'un fichier mémoire thématique (topics). "
        "Utiliser pour sauvegarder des préférences utilisateur, informations personnelles, "
        "contexte projet, etc. La mise à jour REMPLACE le contenu du fichier. "
        "Fichiers disponibles : user_prefs.md, user_profile.md, spotify.md, notion.md, "
        "home_assistant.md, visual_memory.md. "
        "IMPORTANT : lire le fichier d'abord (read_file tool) pour préserver l'existant."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Nom exact du fichier topic (ex: user_prefs.md). Doit exister.",
            },
            "content": {
                "type": "string",
                "description": "Nouveau contenu complet du fichier (Markdown).",
            },
        },
        "required": ["filename", "content"],
    }

    def __init__(self, topics_dir: Path | None = None) -> None:
        self._dir = topics_dir or (Path(settings.memory_dir) / "topics")

    async def execute(self, filename: str, content: str) -> ToolResult:
        if "/" in filename or "\\" in filename or ".." in filename or not filename.endswith(".md"):
            return ToolResult(content="Nom de fichier invalide.", is_error=True)
        path = self._dir / filename
        if not path.exists():
            existing = [p.name for p in self._dir.glob("*.md")]
            return ToolResult(
                content=f"Fichier '{filename}' introuvable. Fichiers disponibles : {', '.join(existing)}",
                is_error=True,
            )
        path.write_text(content, encoding="utf-8")
        return ToolResult(content=f"Mémoire '{filename}' mise à jour ({len(content)} caractères).")
