"""How StudyForge plugs into the rest of DayOS: palette commands, openers, Today, links."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout

from src.repositories.links import register_kind
from src.ui.shell.commands import Command
from src.ui.widgets.common import button, label


def install(window) -> None:
    ctx = window.ctx
    register_kind("question", "sf_questions", "text")
    register_kind("course", "sf_nodes", "title")
    register_kind("flashcard", "sf_flashcards", "front")
    register_kind("material", "sf_materials", "title")

    def page():
        window.navigate("studyforge")
        return window.page("studyforge")

    def course_of(table: str, ref_id: int) -> int | None:
        value = ctx.db.scalar(f"SELECT course_id FROM {table} WHERE id = ?", (ref_id,))
        return int(value) if value else None

    def open_question(qid: int) -> None:
        from src.modules.studyforge.ui.bank import QuestionDialog

        q = ctx.services["studyforge"].bank.get(qid)
        if q and q.course_id:
            p = page()
            p.select_course(q.course_id)
            QuestionDialog(ctx, q.course_id, p, q).exec()

    def open_node(nid: int) -> None:
        cid = course_of("sf_nodes", nid)
        if cid:
            p = page()
            p.select_course(cid)
            p.tabs.setCurrentIndex(1)

    def open_card(cid_: int) -> None:
        cid = course_of("sf_flashcards", cid_)
        if cid:
            p = page()
            p.select_course(cid)
            p.tabs.setCurrentIndex(6)

    def open_material(mid: int) -> None:
        from src.modules.studyforge.ui.materials import MaterialDialog

        cid = course_of("sf_materials", mid)
        if cid:
            p = page()
            p.select_course(cid)
            p.tabs.setCurrentIndex(6)
            MaterialDialog(p, ctx.services["studyforge"].materials.get(mid)).exec()

    for kind, fn in (("question", open_question), ("course", open_node), ("flashcard", open_card),
                     ("material", open_material)):
        window.openers.register(kind, fn)

    add = window.commands.add
    add(Command("studyforge.test", "Create practice test", "Build a test from your question bank", "", "exams",
                lambda: page().create_test(), ("quiz", "exam", "mock", "paper", "practice")))
    add(Command("studyforge.import", "Import syllabus or sample paper", "Read a PDF, Word or text document locally", "",
                "upload", lambda: page().import_document(), ("pdf", "syllabus", "chapters", "paper")))
    add(Command("studyforge.revise", "Revise due topics", "Open today's revision queue", "", "book",
                lambda: page().tabs.setCurrentIndex(4), ("revision", "spaced", "review")))
    add(Command("studyforge.cards", "Review flashcards", "Spaced flashcard review", "", "book",
                lambda: page().tab_widgets[4].review_cards(), ("flashcards", "cards", "recall")))
    add(Command("studyforge.mistakes", "Open mistake notebook", "Retry questions you got wrong", "", "mistake",
                lambda: page().tabs.setCurrentIndex(5), ("mistakes", "errors", "retry")))
    add(Command("studyforge.cbse", "Set up CBSE Class 10", "Create a CBSE Class 10 course", "", "subject",
                lambda: page().cbse_setup(), ("cbse", "class 10", "board")))

    def revision_provider(layout, day) -> bool:
        queue = ctx.services["studyforge.service"].queue(None, day, limit=4)
        if not queue:
            return False
        layout.addWidget(label(f"{len(queue)} StudyForge topic{'s' if len(queue) != 1 else ''} due", "caption"))
        for item in queue[:3]:
            layout.addWidget(label(f"• {item.node.title} — {item.reasons[0] if item.reasons else ''}", "", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Open revision", "soft", "book", lambda: page().tabs.setCurrentIndex(4)))
        row.addStretch(1)
        layout.addLayout(row)
        return True

    window.revision_providers.append(revision_provider)
