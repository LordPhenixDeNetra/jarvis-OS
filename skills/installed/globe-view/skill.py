from __future__ import annotations

from skills.base import SkillBase


class GlobeViewSkill(SkillBase):
    SYSTEM_PROMPT = ""  # La description du tool suffit au routing

    def get_tools(self) -> list:
        from background.notifications import get_broadcast_fn
        from tools.show_view import ShowViewTool

        return [ShowViewTool(broadcast_event=get_broadcast_fn())]
