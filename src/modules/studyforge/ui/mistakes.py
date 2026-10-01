"""Mistake notebook: what went wrong, why, and a retry queue (shared with the Exams page notebook)."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QInputDialog, QPlainTextEdit, QVBoxLayout, QWidget

from src.modules.studyforge.ui.common import NodeCombo, sf
from src.ui.bus import bus
from src.ui.widgets.common import (
    EmptyState,
    FadeDialog,
    FormDialog,
    SearchField,
    SegmentBar,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
)


class MistakeDialog(FormDialog):
    def __init__(self, page, node_id: int | None = None) -> None:
        super().__init__("Add a mistake", page, width=560)
        self.page = page
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("The question (or a short description)")
        self.question.setFixedHeight(70)
        self.add_row("Question", self.question)
        self.yours = QPlainTextEdit()
        self.yours.setFixedHeight(50)
        self.yours.setPlaceholderText("What you answered")
        self.add_row("Your answer", self.yours)
        self.expected = QPlainTextEdit()
        self.expected.setFixedHeight(50)
        self.add_row("Correct answer", self.expected)
        self.explanation = QPlainTextEdit()
        self.explanation.setFixedHeight(60)
        self.explanation.setPlaceholderText("Why — in your own words")
        self.add_row("Explanation", self.explanation)
        self.node = NodeCombo("No topic")
        self.node.load(sf(page.ctx).courses.tree(page.course_id), node_id)
        self.add_row("Topic", self.node)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems([""] + sf(page.ctx).mistakes.categories())
        self.add_row("Category", self.category)

    def save(self) -> None:
        cat = self.category.currentText().strip()
        repo = sf(self.page.ctx).mistakes
        if cat and cat not in repo.categories():
            repo.add_category(cat)
        repo.add(self.question.toPlainText(), node_id=self.node.current_id(), user_answer=self.yours.toPlainText(),
                 expected_answer=self.expected.toPlainText(), explanation=self.explanation.toPlainText(), category=cat)
        bus.notify("studyforge", "exams")


class RetryDialog(FadeDialog):
    def __init__(self, page, mistake: dict) -> None:
        super().__init__(page)
        self.page = page
        self.m = mistake
        self.setWindowTitle("Retry")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Try it again before looking", "section"))
        lay.addWidget(label(mistake["question"], "", wrap=True, selectable=True))
        self.answer_box = QWidget()
        al = QVBoxLayout(self.answer_box)
        al.setContentsMargins(0, 0, 0, 0)
        if mistake.get("expected_answer"):
            al.addWidget(label(f"Correct answer: {mistake['expected_answer']}", "success", wrap=True, selectable=True))
        if mistake.get("explanation"):
            al.addWidget(label(mistake["explanation"], "muted", wrap=True, selectable=True))
        if mistake.get("user_answer"):
            al.addWidget(label(f"Last time you wrote: {mistake['user_answer']}", "caption", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("I got it right", "primary", "check", lambda: self.result(True)))
        row.addWidget(button("Still wrong", "soft", on_click=lambda: self.result(False)))
        al.addLayout(row)
        self.answer_box.hide()
        self.reveal = button("Show the answer", "primary", on_click=lambda: (self.answer_box.show(), self.reveal.hide()))
        lay.addWidget(self.reveal)
        lay.addWidget(self.answer_box)

    def result(self, ok: bool) -> None:
        if guarded(self, lambda: sf(self.page.ctx).mistakes.retried(self.m["id"], ok)):
            bus.notify("studyforge", "exams")
            self.accept()
            self.page.toast("Three right in a row resolves a mistake" if ok else "It'll come back tomorrow")


class MistakesTab(QWidget):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        self.status = SegmentBar([("due", "Retry today"), ("open", "Open"), ("resolved", "Resolved"), ("all", "All")],
                                 "open")
        self.status.changed.connect(lambda _: self.refresh())
        bar.addWidget(self.status)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.category)
        self.search = SearchField("Search mistakes")
        self.search.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.search)
        bar.addStretch(1)
        bar.addWidget(button("Add mistake", "primary", "plus", lambda: MistakeDialog(self.page).exec()))
        bar.addWidget(button("New category", "ghost", "tag", self.new_category))
        lay.addLayout(bar)
        self.holder = QWidget()
        self.body = QVBoxLayout(self.holder)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(8)
        lay.addWidget(scroll_wrap(self.holder), 1)
        lay.addWidget(label("Wrong test answers are added here automatically. Patterns in your categories can guide "
                            "practice; they say nothing fixed about your ability.", "caption", wrap=True))

    def refresh(self) -> None:
        repo = sf(self.ctx).mistakes
        current = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", "")
        for c in repo.categories():
            self.category.addItem(c, c)
        self.category.setCurrentIndex(max(0, self.category.findData(current)))
        self.category.blockSignals(False)
        clear_layout(self.body)
        nodes = {n.id for n in sf(self.ctx).courses.nodes(self.page.course_id)}
        status = self.status.current()
        items = repo.list(course_node_ids=nodes, category=self.category.currentData() or "",
                          status="open" if status == "due" else status, search=self.search.text(), due_only=status == "due")
        if not items:
            self.body.addWidget(EmptyState("mistake", "No mistakes here",
                                           "Mistakes from tests land here with the right answer, so you can retry them "
                                           "until they stick.", compact=True))
        for m in items[:200]:
            self.body.addWidget(self._card(m))
        self.body.addStretch(1)

    def _card(self, m: dict) -> QWidget:
        frame = QFrame()
        frame.setProperty("card", True)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(4)
        top = QHBoxLayout()
        if m.get("node_title"):
            top.addWidget(chip(m["node_title"], "blue"))
        if m.get("resolved"):
            top.addWidget(chip("Resolved", "accent"))
        top.addWidget(label(f"added {m['created_at'][:10]}" + (f" · retry from {m['next_review']}"
                                                              if m.get("next_review") and not m.get("resolved") else ""),
                            "caption"), 1)
        cat = QComboBox()
        cat.addItem("Uncategorised", "")
        for c in sf(self.ctx).mistakes.categories():
            cat.addItem(c, c)
        cat.setCurrentIndex(max(0, cat.findData(m.get("category") or "")))
        cat.currentIndexChanged.connect(lambda _i, mid=m["id"], c=cat: self._set_category(mid, c.currentData()))
        top.addWidget(cat)
        lay.addLayout(top)
        lay.addWidget(label(m["question"][:600], "", wrap=True, selectable=True))
        if m.get("user_answer"):
            lay.addWidget(label(f"You: {m['user_answer'][:300]}", "danger", wrap=True))
        expected = m.get("expected_answer") or m.get("correction")
        if expected:
            lay.addWidget(label(f"Correct: {expected[:400]}", "success", wrap=True))
        row = QHBoxLayout()
        if not m.get("resolved"):
            row.addWidget(button("Retry", "soft", "refresh", lambda mm=m: RetryDialog(self.page, mm).exec()))
            row.addWidget(button("Mark resolved", "ghost", "check", lambda mid=m["id"]: self._resolve(mid, True)))
        else:
            row.addWidget(button("Reopen", "ghost", on_click=lambda mid=m["id"]: self._resolve(mid, False)))
        row.addStretch(1)
        row.addWidget(button("Delete", "ghost", "trash", lambda mid=m["id"]: self._delete(mid)))
        lay.addLayout(row)
        return frame

    def _set_category(self, mistake_id: int, category: str) -> None:
        if guarded(self, lambda: sf(self.ctx).mistakes.update(mistake_id, category=category)):
            bus.notify("exams")

    def _resolve(self, mistake_id: int, resolved: bool) -> None:
        if guarded(self, lambda: self.ctx.exams.set_mistake_resolved(mistake_id, resolved)):
            bus.notify("studyforge", "exams")

    def _delete(self, mistake_id: int) -> None:
        if confirm(self, "Delete mistake?", "This entry will be removed from your notebook."):
            if guarded(self, lambda: self.ctx.exams.delete_mistake(mistake_id)):
                bus.notify("studyforge", "exams")

    def new_category(self) -> None:
        name, ok = QInputDialog.getText(self, "New category", "Category name")
        if ok and name.strip() and guarded(self, lambda: sf(self.ctx).mistakes.add_category(name)):
            self.refresh()
