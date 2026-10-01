"""Flashcards and study material (notes, summaries, formula sheets, definitions, key terms)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.modules.studyforge.repository import MaterialRepository
from src.modules.studyforge.ui.common import NodeCombo, sf
from src.ui.bus import bus
from src.ui.widgets.common import (
    EmptyState,
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

CARD_KINDS = {"card": "Question / answer", "formula": "Formula", "definition": "Definition", "keyterm": "Key term",
              "qa": "Q&A"}


class CardDialog(FormDialog):
    def __init__(self, page, card=None, node_id: int | None = None) -> None:
        super().__init__("Edit flashcard" if card else "New flashcard", page, width=540)
        self.page = page
        self.card = card
        self.kind = QComboBox()
        for k, t in CARD_KINDS.items():
            self.kind.addItem(t, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(card.kind if card else "card")))
        self.add_row("Type", self.kind)
        self.front = QPlainTextEdit(card.front if card else "")
        self.front.setPlaceholderText("Front: a question, term or formula name")
        self.front.setFixedHeight(70)
        self.add_row("Front", self.front)
        self.back = QPlainTextEdit(card.back if card else "")
        self.back.setPlaceholderText("Back: the answer")
        self.back.setFixedHeight(90)
        self.add_row("Back", self.back)
        self.node = NodeCombo("No topic")
        self.node.load(sf(page.ctx).courses.tree(page.course_id), card.node_id if card else node_id)
        self.add_row("Topic", self.node)
        self.reviewed = QCheckBox("I've checked this card")
        self.reviewed.setChecked(bool(card.reviewed) if card else True)
        if card and card.ai_generated:
            self.add_row("", self.reviewed)
        self.front.setFocus()

    def save(self) -> None:
        repo = sf(self.page.ctx).revision
        if self.card:
            repo.update_card(self.card.id, self.front.toPlainText(), self.back.toPlainText(), self.node.current_id(),
                             self.kind.currentData(), self.reviewed.isChecked() if self.card.ai_generated else None)
        else:
            repo.add_card(self.page.course_id, self.front.toPlainText(), self.back.toPlainText(),
                          node_id=self.node.current_id(), kind=self.kind.currentData())
        bus.notify("studyforge")


class MaterialDialog(FormDialog):
    def __init__(self, page, material=None, node_id: int | None = None) -> None:
        super().__init__("Edit study material" if material else "New study material", page, width=680)
        self.page = page
        self.m = material
        self.title_edit = QLineEdit(material.title if material else "")
        self.add_row("Title", self.title_edit)
        self.kind = QComboBox()
        for k, t in MaterialRepository.KINDS.items():
            self.kind.addItem(t, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(material.kind if material else "notes")))
        self.add_row("Type", self.kind)
        self.node = NodeCombo("No topic")
        self.node.load(sf(page.ctx).courses.tree(page.course_id), material.node_id if material else node_id)
        self.add_row("Topic", self.node)
        self.body = QPlainTextEdit(material.body if material else "")
        self.body.setProperty("editor", True)
        self.body.setMinimumHeight(260)
        self.body.setPlaceholderText("Write in your own words. For formula sheets and definitions, one per line "
                                     "(“term: meaning”) also lets you turn them into flashcards.")
        self.add_row("Content", self.body)
        self.reviewed = QCheckBox("I've checked this against my sources")
        self.reviewed.setChecked(bool(material.reviewed) if material else True)
        if material and material.ai_generated:
            self.form.addRow(label("AI-generated summary — it may contain mistakes. Compare it with your textbook "
                                   "or notes.", "warning", wrap=True))
            self.add_row("", self.reviewed)
        self.title_edit.setFocus()

    def save(self) -> None:
        repo = sf(self.page.ctx).materials
        if self.m:
            repo.update(self.m.id, self.title_edit.text(), self.body.toPlainText(), self.kind.currentData(),
                        self.node.current_id(), self.reviewed.isChecked() if self.m.ai_generated else None)
        else:
            repo.add(self.page.course_id, self.title_edit.text(), self.body.toPlainText(), kind=self.kind.currentData(),
                     node_id=self.node.current_id())
        bus.notify("studyforge")


class MaterialsTab(QWidget):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        self.view = SegmentBar([("cards", "Flashcards"), ("material", "Notes & formula sheets")], "cards")
        self.view.changed.connect(lambda _: self.refresh())
        bar.addWidget(self.view)
        self.search = SearchField("Search")
        self.search.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.search)
        bar.addStretch(1)
        bar.addWidget(button("New flashcard", "", "plus", lambda: CardDialog(self.page).exec()))
        bar.addWidget(button("New notes", "primary", "plus", lambda: MaterialDialog(self.page).exec()))
        lay.addLayout(bar)
        self.holder = QWidget()
        self.body = QVBoxLayout(self.holder)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(8)
        lay.addWidget(scroll_wrap(self.holder), 1)

    def refresh(self) -> None:
        clear_layout(self.body)
        text = self.search.text().strip().lower()
        if self.view.current() == "cards":
            cards = [c for c in sf(self.ctx).revision.cards(self.page.course_id)
                     if not text or text in (c.front + " " + c.back).lower()]
            if not cards:
                self.body.addWidget(EmptyState("book", "No flashcards yet",
                                               "Make cards for formulas, definitions and key facts; DayOS spaces their "
                                               "reviews for you.", [("New flashcard", lambda: CardDialog(self.page).exec())],
                                               compact=True))
            for c in cards[:300]:
                row = QFrame()
                row.setProperty("inset", True)
                r = QHBoxLayout(row)
                r.setContentsMargins(12, 8, 8, 8)
                col = QVBoxLayout()
                col.addWidget(label(c.front[:200], "heading", wrap=True))
                col.addWidget(label(c.back[:300], "muted", wrap=True))
                r.addLayout(col, 1)
                r.addWidget(chip(CARD_KINDS.get(c.kind, c.kind), ""))
                if c.ai_generated and not c.reviewed:
                    r.addWidget(chip("AI · unchecked", "amber"))
                if c.node_title:
                    r.addWidget(chip(c.node_title, "blue"))
                r.addWidget(label(f"next {c.due_date}" if c.due_date else "new", "caption"))
                r.addWidget(button("Edit", "link", on_click=lambda cc=c: CardDialog(self.page, cc).exec()))
                r.addWidget(button("Delete", "link", on_click=lambda cid=c.id: self._delete_card(cid)))
                self.body.addWidget(row)
        else:
            items = sf(self.ctx).materials.list(self.page.course_id, search=text)
            if not items:
                self.body.addWidget(EmptyState("notes", "No study material yet",
                                               "Chapter summaries, revision notes, formula sheets and definitions live "
                                               "here, linked to topics.", [("New notes", lambda: MaterialDialog(self.page).exec())],
                                               compact=True))
            for m in items:
                row = QFrame()
                row.setProperty("card", True)
                r = QVBoxLayout(row)
                r.setContentsMargins(16, 10, 12, 10)
                head = QHBoxLayout()
                head.addWidget(label(m.title, "heading"), 1)
                head.addWidget(chip(MaterialRepository.KINDS[m.kind], "accent"))
                if m.ai_generated:
                    head.addWidget(chip("AI summary" + ("" if m.reviewed else " · unchecked"), "amber"))
                if m.node_title:
                    head.addWidget(chip(m.node_title, "blue"))
                r.addLayout(head)
                r.addWidget(label(m.body[:400] + ("…" if len(m.body) > 400 else ""), "muted", wrap=True))
                actions = QHBoxLayout()
                actions.addWidget(button("Open", "link", on_click=lambda mm=m: MaterialDialog(self.page, mm).exec()))
                if m.kind in ("formula_sheet", "definitions", "keyterms"):
                    actions.addWidget(button("Make flashcards", "link", on_click=lambda mm=m: self._to_cards(mm)))
                actions.addStretch(1)
                actions.addWidget(button("Delete", "link", on_click=lambda mid=m.id: self._delete_material(mid)))
                r.addLayout(actions)
                self.body.addWidget(row)
        self.body.addStretch(1)

    def _to_cards(self, m) -> None:
        lines = [l for l in m.body.splitlines() if ":" in l or "=" in l]
        kind = {"formula_sheet": "formula", "definitions": "definition", "keyterms": "keyterm"}[m.kind]
        made = 0
        for line in lines:
            sep = ":" if ":" in line else "="
            front, back = line.split(sep, 1)
            if front.strip() and back.strip():
                sf(self.ctx).revision.add_card(self.page.course_id, front.strip(), back.strip(), node_id=m.node_id,
                                               kind=kind, source_ref=f"From “{m.title}”")
                made += 1
        bus.notify("studyforge")
        self.page.toast(f"Made {made} flashcard(s)" if made else "No “term: meaning” lines found")

    def _delete_card(self, card_id: int) -> None:
        if confirm(self, "Delete flashcard?", "This card and its review schedule will be deleted."):
            if guarded(self, lambda: sf(self.ctx).revision.delete_card(card_id)):
                bus.notify("studyforge")

    def _delete_material(self, material_id: int) -> None:
        if confirm(self, "Delete study material?", "This item will be deleted."):
            if guarded(self, lambda: sf(self.ctx).materials.delete(material_id)):
                bus.notify("studyforge")
