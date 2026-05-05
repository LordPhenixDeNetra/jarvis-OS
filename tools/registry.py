from __future__ import annotations

from loguru import logger

from tools.base import Tool, ToolResult


class ToolRegistry:
    """Registre central de tous les outils disponibles pour Jarvis."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, *tools: Tool) -> None:
        for tool in tools:
            self._tools[tool.name] = tool
            logger.debug("Tool registered", name=tool.name)

    def has_tools(self) -> bool:
        return bool(self._tools)

    def schemas(self) -> list[dict]:
        """Retourne les schémas Claude de tous les outils enregistrés."""
        return [t.to_claude_schema() for t in self._tools.values()]

    async def call(self, name: str, inputs: dict) -> ToolResult:
        """Exécute un outil par nom. Retourne une ToolResult d'erreur si inconnu."""
        tool = self._tools.get(name)
        if tool is None:
            logger.warning("Unknown tool called", name=name)
            return ToolResult(content=f"Outil inconnu: {name}", is_error=True)
        try:
            result = await tool.execute(**inputs)
            logger.info("Tool executed", name=name, is_error=result.is_error)
            return result
        except Exception as e:
            logger.error("Tool execution error", name=name, error=str(e))
            return ToolResult(content=f"Erreur outil {name}: {e}", is_error=True)

    async def call_str(self, name: str, inputs: dict) -> str:
        """Wrapper call() → str pour le tool_loop du LLM provider."""
        result = await self.call(name, inputs)
        if result.is_error:
            return f"[ERREUR] {result.content}"
        return result.content
