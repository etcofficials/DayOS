"""Skills: roadmaps with milestones, prerequisites, resources, practice and evidence of progress."""

from __future__ import annotations

from src.modules import registry
from src.modules.registry import ModuleSpec

registry.register(ModuleSpec(
    "skills", "Skills", "skill", "create", "src.modules.skills.ui.page:SkillsPage",
    "Skill roadmaps: milestones, resources, practice tasks, evidence and a weekly look back."))


def install(window) -> None:
    from src.repositories.links import register_kind
    from src.ui.shell.commands import Command

    register_kind("skill", "skills", "name")

    def page():
        window.navigate("skills")
        return window.page("skills")

    window.openers.register("skill", lambda sid: page().open_skill(sid))
    window.commands.add(Command("skills.new", "New skill", "Plan something you want to get better at", "", "skill",
                                lambda: page().new_item(), ("learn", "skill", "roadmap", "growth")))
    window.commands.add(Command("skills.week", "Skills this week", "What you practised and made this week", "",
                                "chart", lambda: page().view.set_current("week") or page().refresh(),
                                ("review", "skills", "progress")))
