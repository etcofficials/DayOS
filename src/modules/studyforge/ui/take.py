"""Taking a test (autosaved, resumable) and reviewing / marking the results."""

from __future__ import annotations

import json
import random
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.modules.studyforge import marking
from src.modules.studyforge.models import ASSERTION_OPTIONS, QTYPES
from src.modules.studyforge.ui.common import sf, svc
from src.ui.bus import bus
from src.ui.widgets.common import (
    AnimatedButton,
    FadeDialog,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    show_info,
)


def _fmt_clock(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class TakeTestDialog(FadeDialog):
    def __init__(self, page, test_id: int) -> None:
        super().__init__(page)
        self.page = page
        self.ctx = page.ctx
        self.store = sf(self.ctx).tests
        self.test = self.store.test(test_id)
        self.items = self.store.items(test_id)
        existing = self.store.open_attempt(test_id)
        self.attempt_id = existing.id if existing else self.store.start_attempt(test_id)
        self.base_elapsed = existing.elapsed_s if existing else 0
        self.opened = time.monotonic()
        self.answers = {k: v for k, v in self.store.answers(self.attempt_id).items()}
        self.index = 0
        self.q_started = time.monotonic()
        self.submitted = False
        self._value: str | None = None
        self._match_rights: dict[int, list[str]] = {}
        self.setWindowTitle(self.test.title)
        self.setModal(True)
        self.resize(1040, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(12)
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label(self.test.title, "title"))
        col.addWidget(label(f"{self.test.total_marks:g} marks · {len(self.items)} questions · "
                            + ("timed" if self.test.mode == "timed" else "practice — take your time"), "muted"))
        top.addLayout(col, 1)
        self.clock = label("", "metric")
        self.clock.setAccessibleName("Time")
        top.addWidget(self.clock)
        lay.addLayout(top)
        body = QHBoxLayout()
        body.setSpacing(18)
        nav_box = QFrame()
        nav_box.setProperty("panel", True)
        nv = QVBoxLayout(nav_box)
        nv.setContentsMargins(12, 12, 12, 12)
        nv.addWidget(label("Questions", "heading"))
        self.nav = QGridLayout()
        self.nav.setSpacing(6)
        self.nav_buttons: list[AnimatedButton] = []
        for i, _it in enumerate(self.items):
            b = AnimatedButton(str(i + 1), "")
            b.setFixedSize(40, 34)
            b.clicked.connect(lambda _=False, n=i: self.go(n))
            self.nav.addWidget(b, i // 5, i % 5)
            self.nav_buttons.append(b)
        nv.addLayout(self.nav)
        nv.addWidget(label("✓ answered · ⚑ marked for review", "caption"))
        nv.addStretch(1)
        nav_box.setFixedWidth(250)
        body.addWidget(nav_box)
        q_box = QVBoxLayout()
        self.q_header = label("", "eyebrow")
        q_box.addWidget(self.q_header)
        self.q_area = QWidget()
        self.q_lay = QVBoxLayout(self.q_area)
        self.q_lay.setContentsMargins(0, 0, 8, 0)
        q_box.addWidget(scroll_wrap(self.q_area), 1)
        body.addLayout(q_box, 1)
        lay.addLayout(body, 1)
        bottom = QHBoxLayout()
        self.prev_btn = button("Previous", "ghost", "chev-left", lambda: self.go(self.index - 1))
        self.flag_btn = button("Mark for review", "ghost", "flag", self.toggle_flag)
        self.next_btn = button("Next", "", "chev-right", lambda: self.go(self.index + 1))
        bottom.addWidget(self.prev_btn)
        bottom.addWidget(self.flag_btn)
        bottom.addStretch(1)
        self.saved_note = label("Answers save automatically.", "caption")
        bottom.addWidget(self.saved_note)
        bottom.addWidget(self.next_btn)
        bottom.addWidget(button("Submit", "primary", "check", self.submit))
        lay.addLayout(bottom)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self.save_current)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._last_persist = time.monotonic()
        self.go(0)
        self._on_tick()

    # -- timing ---------------------------------------------------------------------
    def elapsed(self) -> int:
        return int(self.base_elapsed + (time.monotonic() - self.opened))

    def _on_tick(self) -> None:
        if self.test.mode == "timed" and self.test.duration_min:
            remaining = self.test.duration_min * 60 - self.elapsed()
            self.clock.setText(_fmt_clock(remaining))
            self.clock.setProperty("role", "metric" if remaining > 300 else "warning")
            if remaining <= 0 and not self.submitted:
                self._tick.stop()
                self.save_current()
                show_info(self, "Time's up", "Your answers have been submitted.")
                self._do_submit()
                return
        else:
            self.clock.setText(_fmt_clock(self.elapsed()))
        if time.monotonic() - self._last_persist > 15:
            self._last_persist = time.monotonic()
            self.store.set_elapsed(self.attempt_id, self.elapsed())

    # -- navigation & rendering -------------------------------------------------------
    def go(self, index: int) -> None:
        if not 0 <= index < len(self.items):
            return
        self.save_current()
        self.index = index
        self.q_started = time.monotonic()
        self._render()

    def _response(self, item_id: int) -> str:
        a = self.answers.get(item_id)
        return a.response if a else ""

    def _flagged(self, item_id: int) -> bool:
        a = self.answers.get(item_id)
        return bool(a and a.flagged)

    def _render(self) -> None:
        clear_layout(self.q_lay)
        item = self.items[self.index]
        q = item.question
        group_note = ""
        if item.choice_group is not None:
            mates = [i + 1 for i, it in enumerate(self.items) if it.choice_group == item.choice_group]
            group_note = f" · internal choice: answer one of questions {', '.join(map(str, mates))}"
        self.q_header.setText(f"{(item.section + ' · ') if item.section else ''}QUESTION {self.index + 1} OF "
                              f"{len(self.items)} · {item.marks:g} MARK{'S' if item.marks != 1 else ''}"
                              f" · {QTYPES.get(q.get('qtype', ''), '').upper()}{group_note.upper()}")
        text = label(q.get("text", ""), "intention", wrap=True, selectable=True)
        self.q_lay.addWidget(text)
        if q.get("origin") == "ai":
            self.q_lay.addWidget(label("AI-generated practice question" + ("" if q.get("verified") else
                                                                          " (not checked yet)"), "caption"))
        self.q_lay.addSpacing(8)
        self.editor = self._answer_widget(item)
        self.q_lay.addWidget(self.editor)
        self.q_lay.addStretch(1)
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.items) - 1)
        self.flag_btn.setText("Unmark review" if self._flagged(item.id) else "Mark for review")
        self._update_nav()

    def _answer_widget(self, item) -> QWidget:
        q = item.question
        qtype = q.get("qtype", "")
        response = self._response(item.id)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._value = None
        if qtype in ("mcq", "assertion", "tf"):
            options = ASSERTION_OPTIONS if qtype == "assertion" else (
                ["True", "False"] if qtype == "tf" else marking.question_options(q))
            group = QButtonGroup(box)
            for i, opt in enumerate(options):
                rb = QRadioButton(f"{chr(65 + i)}.  {opt}" if qtype != "tf" else opt)
                value = (["true", "false"][i] if qtype == "tf" else str(i))
                rb.setChecked(response == value)
                rb.toggled.connect(lambda on, v=value: on and self._changed(v))
                group.addButton(rb)
                lay.addWidget(rb)
        elif qtype == "multi":
            chosen = set(json.loads(response)) if response else set()
            checks = []
            for i, opt in enumerate(marking.question_options(q)):
                cb = QCheckBox(f"{chr(65 + i)}.  {opt}")
                cb.setChecked(i in chosen)
                checks.append(cb)
                lay.addWidget(cb)
            for cb in checks:
                cb.toggled.connect(lambda _on: self._changed(json.dumps([i for i, c in enumerate(checks) if c.isChecked()])))
            lay.addWidget(label("Select every correct option.", "caption"))
        elif qtype in ("fill", "numerical"):
            edit = QLineEdit(response)
            edit.setPlaceholderText("Your answer" + (" (a number)" if qtype == "numerical" else ""))
            edit.textChanged.connect(self._changed)
            lay.addWidget(edit)
        elif qtype == "match":
            pairs = marking.match_pairs(marking.question_options(q))
            rights = self._match_rights.setdefault(item.id, random.sample([r for _, r in pairs], len(pairs)))
            given = json.loads(response) if response else {}
            combos = []
            for left, _ in pairs:
                row = QHBoxLayout()
                row.addWidget(label(left), 1)
                combo = QComboBox()
                combo.addItem("—", "")
                for r in rights:
                    combo.addItem(r, r)
                combo.setCurrentIndex(max(0, combo.findData(given.get(left, ""))))
                combos.append((left, combo))
                row.addWidget(combo, 1)
                lay.addLayout(row)
            for _, combo in combos:
                combo.currentIndexChanged.connect(
                    lambda _i: self._changed(json.dumps({l: c.currentData() for l, c in combos if c.currentData()})))
        else:
            edit = QPlainTextEdit(response)
            edit.setPlaceholderText("Write your answer here")
            edit.setMinimumHeight(220)
            edit.textChanged.connect(lambda: self._changed(edit.toPlainText()))
            lay.addWidget(edit)
        return box

    def _changed(self, value: str) -> None:
        self._value = value
        self._save_timer.start()

    def save_current(self) -> None:
        if not self.items:
            return
        item = self.items[self.index]
        spent = int(time.monotonic() - self.q_started)
        self.q_started = time.monotonic()
        if self._value is None and item.id not in self.answers:
            return  # only looked at it: nothing to save yet
        value = self._value if self._value is not None else self._response(item.id)
        flagged = self._flagged(item.id)
        self.store.save_answer(self.attempt_id, item.id, value, flagged, spent)
        self.answers = self.store.answers(self.attempt_id)
        self._value = None
        self._update_nav()

    def toggle_flag(self) -> None:
        item = self.items[self.index]
        self.save_current()
        self.store.save_answer(self.attempt_id, item.id, self._response(item.id), not self._flagged(item.id), 0)
        self.answers = self.store.answers(self.attempt_id)
        self._render()

    def _update_nav(self) -> None:
        for i, (b, it) in enumerate(zip(self.nav_buttons, self.items)):
            answered = bool(self._response(it.id).strip()) and self._response(it.id) not in ("[]", "{}")
            mark = "⚑" if self._flagged(it.id) else ("✓" if answered else "")
            b.setText(f"{i + 1}{mark}")
            b.setProperty("variant", "primary" if i == self.index else ("soft" if answered else ""))
            b.update()

    # -- finishing ------------------------------------------------------------------------
    def submit(self) -> None:
        self.save_current()
        unanswered = sum(1 for it in self.items if it.choice_group is None and not self._response(it.id).strip())
        flagged = sum(1 for it in self.items if self._flagged(it.id))
        notes = []
        if unanswered:
            notes.append(f"{unanswered} question(s) are unanswered.")
        if flagged:
            notes.append(f"{flagged} question(s) are marked for review.")
        if not confirm(self, "Submit your answers?", " ".join(notes) + ("\n\n" if notes else "")
                       + "Objective questions are marked straight away; you'll mark written answers next.",
                       "Submit", danger=False):
            return
        self._do_submit()

    def _do_submit(self) -> None:
        self.submitted = True
        self._tick.stop()
        summary = None

        def run() -> None:
            nonlocal summary
            summary = svc(self.ctx).submit(self.attempt_id, self.elapsed())

        if guarded(self, run, "Couldn't submit the test"):
            bus.notify("studyforge")
            self.accept()
            self.page.show_attempt(self.attempt_id, summary)

    def reject(self) -> None:
        if self.submitted:
            super().reject()
            return
        self.save_current()
        self.store.set_elapsed(self.attempt_id, self.elapsed())
        if confirm(self, "Leave the test for now?", "Your answers are saved. You can resume this test later from "
                                                     "the Tests tab.", "Leave", danger=False):
            self._tick.stop()
            bus.notify("studyforge")
            super().reject()


class ResultsDialog(FadeDialog):
    """Score, answers and explanations; written answers are marked here against the marking points."""

    def __init__(self, page, attempt_id: int, summary=None) -> None:
        super().__init__(page)
        self.page = page
        self.ctx = page.ctx
        self.attempt_id = attempt_id
        self.setWindowTitle("Test results")
        self.resize(900, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(10)
        self.head = QVBoxLayout()
        lay.addLayout(self.head)
        self.holder = QWidget()
        self.body = QVBoxLayout(self.holder)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(10)
        lay.addWidget(scroll_wrap(self.holder), 1)
        row = QHBoxLayout()
        row.addWidget(label("Marks you give yourself feed your revision plan. AI feedback, if you use it, is only an "
                            "estimate and is never treated as official marking.", "caption", wrap=True), 1)
        row.addWidget(button("Close", "primary", on_click=self.accept))
        lay.addLayout(row)
        self.summary = summary
        self.fill()

    def fill(self) -> None:
        store = sf(self.ctx).tests
        attempt = store.attempt(self.attempt_id)
        items = store.items(attempt.test_id)
        answers = store.answers(self.attempt_id)
        clear_layout(self.head)
        clear_layout(self.body)
        pending = [it for it in items if answers.get(it.id) and answers[it.id].marks is None
                   and answers[it.id].response.strip()]
        self.head.addWidget(label(attempt.test_title or "Test", "title"))
        pct = f" ({round(100 * (attempt.score or 0) / attempt.max_score)}%)" if attempt.max_score else ""
        line = f"{attempt.score or 0:g} of {attempt.max_score or 0:g} marks{pct}"
        if pending:
            line += f" so far — {len(pending)} written answer{'s' if len(pending) != 1 else ''} to mark below"
        self.head.addWidget(label(line, "section"))
        extra = [f"Time: {_fmt_clock(attempt.elapsed_s)}"]
        if self.summary and self.summary.mistakes_added:
            extra.append(f"{self.summary.mistakes_added} mistake(s) added to your notebook for later retry")
        if attempt.has_estimates:
            extra.append("includes AI estimates — check them")
        self.head.addWidget(label(" · ".join(extra), "muted", wrap=True))
        for n, it in enumerate(items, start=1):
            self.body.addWidget(self._item_card(n, it, answers.get(it.id)))
        self.body.addStretch(1)

    def _item_card(self, n: int, item, ans) -> QWidget:
        q = item.question
        card = QFrame()
        card.setProperty("card", True)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(5)
        top = QHBoxLayout()
        top.addWidget(label(f"{n}. {QTYPES.get(q.get('qtype', ''), '')}", "eyebrow"), 1)
        if ans is None or not ans.response.strip():
            top.addWidget(chip("Not answered", ""))
        if ans is not None and ans.marks is not None:
            tone = "accent" if ans.marks >= item.marks else ("danger" if ans.marks == 0 else "amber")
            top.addWidget(chip(f"{ans.marks:g} / {item.marks:g}" + (" · AI estimate" if ans.marker == "ai" else ""), tone))
        lay.addLayout(top)
        lay.addWidget(label(q.get("text", ""), "", wrap=True, selectable=True))
        response = ans.response if ans else ""
        lay.addWidget(label(f"Your answer: {marking.response_text(q, response)}", "muted", wrap=True, selectable=True))
        expected = marking.expected_answer_text(q)
        if expected:
            lay.addWidget(label(f"Answer: {expected}", "success", wrap=True, selectable=True))
        if q.get("explanation"):
            lay.addWidget(label(q["explanation"], "caption", wrap=True, selectable=True))
        if ans is not None and ans.feedback:
            lay.addWidget(label(f"Note: {ans.feedback}", "caption", wrap=True))
        if q.get("qtype") not in ("mcq", "multi", "assertion", "tf", "fill", "numerical", "match") or \
                (ans is not None and ans.marks is None and response.strip()):
            if response.strip():
                lay.addWidget(self._marker(item, ans))
        return card

    def _marker(self, item, ans) -> QWidget:
        box = QFrame()
        box.setProperty("inset", True)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 8, 12, 8)
        points = marking.rubric_points(item.question)
        checks = []
        spin = QDoubleSpinBox()
        spin.setRange(0, item.marks)
        spin.setSingleStep(0.5)
        spin.setValue(ans.marks if ans and ans.marks is not None else 0)
        spin.setSuffix(f" / {item.marks:g}")
        if points:
            lay.addWidget(label("Tick the marking points your answer covers:", "caption"))
            for p in points:
                cb = QCheckBox(f"{p['text']}  ({float(p.get('marks', 1)):g})")
                checks.append(cb)
                lay.addWidget(cb)
            for cb in checks:
                cb.toggled.connect(lambda _on: spin.setValue(
                    marking.rubric_score(points, [c.isChecked() for c in checks], item.marks)))
        else:
            model = item.question.get("answer", "")
            lay.addWidget(label("Compare with the model answer above and give yourself marks.", "caption", wrap=True)
                          if model else label("No model answer was recorded; mark it as fairly as you can.", "caption"))
        row = QHBoxLayout()
        row.addWidget(label("Marks", "muted"))
        row.addWidget(spin)
        feedback = QLineEdit(ans.feedback if ans and ans.marker == "self" else "")
        feedback.setPlaceholderText("What was missing? (optional)")
        row.addWidget(feedback, 1)
        save = button("Save marks", "soft", "check",
                      lambda: self._save_mark(item.id, spin.value(), feedback.text()))
        row.addWidget(save)
        lay.addLayout(row)
        ai = self.ctx.services.get("ai")
        if ai is not None and getattr(ai, "configured", lambda: False)():
            lay.addWidget(button("Ask AI for feedback (estimate)…", "link", "sparkle",
                                 lambda: self.page.ai_feedback(self.attempt_id, item, self)))
        return box

    def _save_mark(self, item_id: int, marks: float, feedback: str) -> None:
        if guarded(self, lambda: svc(self.ctx).mark_written(self.attempt_id, item_id, marks, feedback),
                   "Couldn't save the marks"):
            bus.notify("studyforge")
            self.fill()
