"""Outils LLM pour la gestion des skills Jarvis (création, amélioration, liste)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from skills.synthesizer import SkillSynthesizer


class SkillCreateTool(Tool):
    """Crée un nouveau skill depuis la tâche courante."""

    name = "skill_create"
    description = (
        "Synthétise un nouveau skill Jarvis depuis une tâche complexe accomplie. "
        "Appeler après avoir réussi une tâche non-triviale et répétable pour "
        "persister le savoir-faire en tant que skill réutilisable. "
        "Fournir un résumé de la tâche, les outils utilisés et le résultat."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Description concise de la tâche accomplie (1-3 phrases).",
            },
            "messages": {
                "type": "array",
                "description": (
                    "Extrait de l'historique de conversation (liste de {role, content})."
                ),
                "items": {"type": "object"},
            },
            "tool_calls": {
                "type": "array",
                "description": "Outils utilisés pendant la tâche (liste de {name, result}).",
                "items": {"type": "object"},
            },
            "result": {
                "type": "string",
                "description": "Résultat ou livrable final de la tâche.",
            },
        },
        "required": ["task_description"],
    }

    def __init__(self, synthesizer: SkillSynthesizer | None = None) -> None:
        if synthesizer is None:
            from skills.synthesizer import SkillSynthesizer

            synthesizer = SkillSynthesizer()
        self._synthesizer = synthesizer

    async def execute(  # type: ignore[override]
        self,
        task_description: str,
        messages: list[dict] | None = None,
        tool_calls: list[dict] | None = None,
        result: str = "",
    ) -> ToolResult:
        trajectory: dict = {
            "task_description": task_description,
            "messages": messages or [],
            "tool_calls": tool_calls or [],
            "result": result,
        }
        try:
            skill_name = await self._synthesizer.propose_skill(trajectory)
            return ToolResult(
                content=f"Skill '{skill_name}' créé dans skills/installed/{skill_name}/."
            )
        except ValueError as exc:
            return ToolResult(content=f"Génération échouée : {exc}", is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=f"Erreur inattendue : {exc}", is_error=True)


class SkillImproveTool(Tool):
    """Améliore un skill existant à partir d'une nouvelle expérience."""

    name = "skill_improve"
    description = (
        "Affine et améliore un skill Jarvis existant avec une nouvelle expérience. "
        "Appeler quand une tâche déjà couverte par un skill a révélé des cas "
        "non gérés, des meilleures pratiques ou des corrections utiles."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Nom kebab-case du skill à améliorer (ex: 'web-research').",
            },
            "new_experience": {
                "type": "string",
                "description": (
                    "Description de la nouvelle expérience à intégrer : "
                    "ce qui a changé, ce qui a mieux fonctionné, les cas limites découverts."
                ),
            },
        },
        "required": ["skill_name", "new_experience"],
    }

    def __init__(self, synthesizer: SkillSynthesizer | None = None) -> None:
        if synthesizer is None:
            from skills.synthesizer import SkillSynthesizer

            synthesizer = SkillSynthesizer()
        self._synthesizer = synthesizer

    async def execute(  # type: ignore[override]
        self,
        skill_name: str,
        new_experience: str,
    ) -> ToolResult:
        try:
            await self._synthesizer.improve_skill(skill_name, new_experience)
            return ToolResult(content=f"Skill '{skill_name}' amélioré avec la nouvelle expérience.")
        except FileNotFoundError as exc:
            return ToolResult(content=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(content=f"Erreur amélioration : {exc}", is_error=True)


class SkillListTool(Tool):
    """Liste les skills installés dans Jarvis."""

    name = "skill_list"
    description = (
        "Liste tous les skills installés dans Jarvis avec leur nom, version, "
        "description et tags. Utiliser pour savoir quels skills sont disponibles "
        "avant d'en créer un nouveau similaire."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "filter_tag": {
                "type": "string",
                "description": "Filtrer par tag (optionnel). Ex: 'research', 'coding'.",
            },
        },
        "required": [],
    }

    async def execute(self, filter_tag: str = "") -> ToolResult:  # type: ignore[override]
        from skills.registry import skill_registry

        skills = skill_registry.list_installed()
        if filter_tag:
            skills = [
                s for s in skills if filter_tag.lower() in [t.lower() for t in s.get("tags", [])]
            ]

        if not skills:
            msg = "Aucun skill installé" + (f" avec le tag '{filter_tag}'" if filter_tag else "")
            return ToolResult(content=msg)

        lines = [f"## Skills installés ({len(skills)})\n"]
        for s in skills:
            tags_str = ", ".join(s.get("tags", [])) or "—"
            lines.append(
                f"**{s['name']}** v{s['version']} — {s['description']}\n"
                f"  Tags : {tags_str} | Type : {s.get('type', 'conversational')}"
            )

        return ToolResult(content="\n\n".join(lines))
