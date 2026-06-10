from __future__ import annotations
from skills.base import SkillBase


class WebResearchSkill(SkillBase):
    """Skill importé depuis le standard agentskills.io."""

    @property  # type: ignore[override]
    def SYSTEM_PROMPT(self) -> str:
        return self.metadata.get("system_prompt", "")

    def get_system_prompt(self) -> str:  # noqa: D102
        return self.SYSTEM_PROMPT.strip()

    def is_active(self) -> bool:  # noqa: D102
        return bool(self.SYSTEM_PROMPT)
