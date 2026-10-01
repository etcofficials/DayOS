"""Revision: today's queue with reasons, recall checks, rescheduling and flashcard sessions."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDateEdit, QFrame, QHBoxLayout, QMenu, QVBoxLayout, QWidget

from src.modules.studyforge import srs
from src.modules.studyforge.ui.common import MASTERY_TONES, sf, svc
from src.services.dates import format_date, today
from src.ui.bus import bus
from src.ui.widgets.common import (
    EmptyState,
    FadeDialog,
    button,
    chip,
    clear_layout,
    guarded,
    label,
    scroll_wrap,
    to_qdate,
)

RECALL_LEVELS = [(0.0, "Couldn't recall"), (0.4, "Shaky"), (0.7, "Mostly"), (1.0, "Confidently")]


class RecallDialog(FadeDialog):
    """Quick self-check for a topic: try to recall it, then rate honestly."""

    def __init__(self, page, node_id: int) -> None:
        super().__init__(page)
        self.page = page
        node = sf(page.ctx).courses.node(node_id)
        self.node_id = node_id
        self.setWindowTitle("Recall check")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label(node.title if node else "Topic", "title", wrap=True))
        lay.addWidget(label(sf(page.ctx).courses.path_text(node_id), "caption", wrap=True))
        lay.addWidget(label("Close your notes. Explain the key ideas, formulas or examples from memory — out loud or "
                            "on paper — then check your notes and rate how it went.", "muted", wrap=True))
        materials = [m for m in sf(page.ctx).materials.list(node.course_id) if m.node_id == node_id] if node else []
        if materials:
            lay.addWidget(label(f"Your notes for this topic: {', '.join(m.title for m in materials[:4])}", "caption",
                                wrap=True))
        row = QHBoxLayout()
        for score, text in RECALL_LEVELS:
            row.addWidget(button(text, "soft" if score < 1 else "primary", on_click=lambda s=score: self.rate(s)))
        lay.addLayout(row)
        lay.addWidget(label("Ratings count as practice for your revision schedule (they're your own judgement, so "
                            "be honest — it only helps you).", "caption", wrap=True))

    def rate(self, score: float) -> None:
        label_text = next(t for s, t in RECALL_LEVELS if s == score)
        if guarded(self, lambda: svc(self.page.ctx).record_practice(self.node_id, score, "recall", label_text)):
            bus.notify("studyforge")
            self.accept()
            st = sf(self.page.ctx).revision.state(self.node_id)
            self.page.toast(f"Next review {format_date(date.fromisoformat(st.due_date), self.page.date_style)}")


class CardSession(FadeDialog):
    """Flashcard review: show the front, reveal, grade (again / hard / good / easy)."""

    def __init__(self, page, cards) -> None:
        super().__init__(page)
        self.page = page
        self.cards = list(cards)
        self.reviewed = 0
        self.setWindowTitle("Flashcards")
        self.setMinimumSize(560, 380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 20, 26, 18)
        lay.setSpacing(12)
        self.progress = label("", "eyebrow")
        lay.addWidget(self.progress)
        self.front = label("", "intention", wrap=True, selectable=True)
        self.front.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.front, 1)
        self.back = label("", "", wrap=True, selectable=True)
        self.back.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.back, 1)
        self.reveal_btn = button("Show answer", "primary", on_click=self.reveal)
        lay.addWidget(self.reveal_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self.grades = QWidget()
        g = QHBoxLayout(self.grades)
        for key, text in (("again", "Again"), ("hard", "Hard"), ("good", "Good"), ("easy", "Easy")):
            g.addWidget(button(text, "primary" if key == "good" else "soft", on_click=lambda k=key: self.grade(k)))
        lay.addWidget(self.grades)
        self._show()

    def _show(self) -> None:
        if not self.cards:
            self.front.setText("All done for now.")
            self.back.setText(f"You reviewed {self.reviewed} card{"s" if self.reviewed != 1 else ""}.")
            self.back.show()
            self.reveal_btn.setText("Close")
            self.reveal_btn.clicked.disconnect()
            self.reveal_btn.clicked.connect(self.accept)
            self.reveal_btn.show()
            self.grades.hide()
            bus.notify("studyforge")
            return
        card = self.cards[0]
        self.progress.setText(f"{len(self.cards)} TO GO" + (f" · {card.node_title.upper()}" if card.node_title else ""))
        self.front.setText(card.front + ("\n\n(AI-generated — not checked yet)" if card.ai_generated and not card.reviewed
                                         else ""))
        self.back.setText(card.back)
        self.back.hide()
        self.reveal_btn.show()
        self.grades.hide()

    def reveal(self) -> None:
        self.back.show()
        self.reveal_btn.hide()
        self.grades.show()

    def grade(self, key: str) -> None:
        card = self.cards.pop(0)
        updated = svc(self.page.ctx).grade_card(card, key)
        if key == "again":
            self.cards.append(updated)  # see it again later in this session
        else:
            self.reviewed += 1
        self._show()


class RevisionTab(QWidget):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.summary = label("", "muted", wrap=True)
        top.addWidget(self.summary, 1)
        self.cards_btn = button("Review flashcards", "soft", "book", self.review_cards)
        top.addWidget(self.cards_btn)
        lay.addLayout(top)
        self.holder = QWidget()
        self.body = QVBoxLayout(self.holder)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(8)
        lay.addWidget(scroll_wrap(self.holder), 1)
        lay.addWidget(label("Topics come back sooner when you miss questions, later when you recall them well, and "
                            "more often as an exam approaches. A topic is never counted as mastered after one correct "
                            "answer.", "caption", wrap=True))

    def refresh(self) -> None:
        clear_layout(self.body)
        course = self.page.course_id
        queue = svc(self.ctx).queue(course)
        due_cards = sf(self.ctx).revision.cards(course, due_only=True)
        self.cards_btn.setText(f"Review flashcards ({len(due_cards)} due)" if due_cards else "Review flashcards")
        self.cards_btn.setEnabled(bool(due_cards))
        self.summary.setText(f"{len(queue)} topic{'s' if len(queue) != 1 else ''} to revise today."
                             if queue else "Nothing is due today.")
        if not queue:
            self.body.addWidget(EmptyState("book", "You're up to date",
                                           "Take a practice test or do a recall check; DayOS will schedule each topic's "
                                           "next review from your results.", compact=True))
        for item in queue:
            self.body.addWidget(self._row(item))
        self.body.addStretch(1)

    def _row(self, item) -> QWidget:
        frame = QFrame()
        frame.setProperty("card", True)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(16, 10, 10, 10)
        col = QVBoxLayout()
        col.setSpacing(2)
        head = QHBoxLayout()
        head.addWidget(label(item.node.title, "heading", wrap=True))
        head.addWidget(chip(srs.MASTERY_LABELS[item.mastery], MASTERY_TONES[item.mastery]))
        head.addStretch(1)
        col.addLayout(head)
        col.addWidget(label(sf(self.ctx).courses.path_text(item.node.parent_id) if item.node.parent_id else
                            item.course_name, "caption"))
        col.addWidget(label("Why now: " + "; ".join(item.reasons), "muted", wrap=True))
        lay.addLayout(col, 1)
        lay.addWidget(button("Practise", "primary", "exams", lambda n=item.node.id: self.page.create_test([n], "quick")))
        lay.addWidget(button("Recall check", "soft", on_click=lambda n=item.node.id: RecallDialog(self.page, n).exec()))
        more = button("", "ghost", "more", tooltip="More")
        more.clicked.connect(lambda _=False, n=item.node.id, b=more: self._menu(n, b))
        lay.addWidget(more)
        return frame

    def _menu(self, node_id: int, anchor) -> None:
        menu = QMenu(self)
        for days, text in ((1, "Tomorrow"), (3, "In 3 days"), (7, "Next week")):
            menu.addAction(f"Reschedule: {text}", lambda d=days: self._reschedule(node_id, today() + timedelta(days=d)))
        menu.addAction("Reschedule to a date…", lambda: self._pick_date(node_id))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _reschedule(self, node_id: int, day: date) -> None:
        if guarded(self, lambda: svc(self.ctx).reschedule(node_id, day)):
            bus.notify("studyforge")
            self.page.toast(f"Moved to {format_date(day, self.page.date_style)}")

    def _pick_date(self, node_id: int) -> None:
        dlg = FadeDialog(self)
        dlg.setWindowTitle("Reschedule")
        lay = QVBoxLayout(dlg)
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDate(to_qdate(today() + timedelta(days=1)))
        lay.addWidget(edit)
        lay.addWidget(button("Reschedule", "primary", on_click=dlg.accept))
        if dlg.exec():
            d = edit.date()
            self._reschedule(node_id, date(d.year(), d.month(), d.day()))

    def review_cards(self) -> None:
        cards = sf(self.ctx).revision.cards(self.page.course_id, due_only=True)
        if cards:
            CardSession(self.page, cards[:50]).exec()
