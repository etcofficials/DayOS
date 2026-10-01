"""StudyForge: courses, question bank, test generation and marking, adaptive revision, mistakes, flashcards."""

from __future__ import annotations

from src.modules import registry
from src.modules.registry import ModuleSpec

registry.register(ModuleSpec(
    "studyforge", "StudyForge", "book", "learn", "src.modules.studyforge.ui.page:StudyForgePage",
    "Courses and syllabi, a question bank, practice tests with marking, revision and a mistake notebook."),
    after="study")


def services(ctx) -> None:
    from src.modules.studyforge.repository import StudyForge
    from src.modules.studyforge.service import StudyForgeService

    sf = StudyForge(ctx.db)
    ctx.services["studyforge"] = sf
    ctx.services["studyforge.service"] = StudyForgeService(sf)


def install(window) -> None:
    from src.modules.studyforge.ui import hooks

    hooks.install(window)
