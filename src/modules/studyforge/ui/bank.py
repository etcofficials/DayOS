"""Question bank: browse, filter, write, verify, import and export questions."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.modules.studyforge.models import ASSERTION_OPTIONS, ORIGINS, QTYPES, SHORT_TYPES, Question
from src.modules.studyforge.repository import DuplicateQuestion
from src.modules.studyforge.ui.common import NodeCombo, sf
from src.ui.bus import bus
from src.ui.widgets.common import (
    EmptyState,
    FormDialog,
    SearchField,
    button,
    clear_layout,
    confirm,
    guarded,
    label,
    show_error,
    show_info,
    tool_button,
)


class RubricEditor(QWidget):
    """Marking points with marks each (for written answers)."""

    def __init__(self, points: list[dict]) -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)
        self.rows: list[tuple[QWidget, QLineEdit, QDoubleSpinBox]] = []
        self.lay.addWidget(button("Add marking point", "link", "plus", lambda: self.add_row("", 1.0, True)), 0,
                           Qt.AlignmentFlag.AlignLeft)
        for p in points:
            self.add_row(str(p.get("text", "")), float(p.get("marks", 1)))

    def add_row(self, text: str, marks: float, focus: bool = False) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(text)
        edit.setPlaceholderText("What a good answer must include")
        spin = QDoubleSpinBox()
        spin.setRange(0, 50)
        spin.setSingleStep(0.5)
        spin.setValue(marks)
        spin.setSuffix(" mk")
        rm = tool_button("close", "Remove point", size=14)
        h.addWidget(edit, 1)
        h.addWidget(spin)
        h.addWidget(rm)
        entry = (row, edit, spin)
        self.rows.append(entry)
        rm.clicked.connect(lambda: (self.rows.remove(entry), row.deleteLater()))
        self.lay.insertWidget(self.lay.count() - 1, row)
        if focus:
            edit.setFocus()

    def points(self) -> list[dict]:
        return [{"text": e.text().strip(), "marks": s.value()} for _, e, s in self.rows if e.text().strip()]


class QuestionDialog(FormDialog):
    def __init__(self, ctx, course_id: int, parent=None, question: Question | None = None,
                 default_node: int | None = None) -> None:
        super().__init__("Edit question" if question else "New question", parent, width=640)
        self.ctx = ctx
        self.course_id = course_id
        self.q = question
        self.saved_id: int | None = question.id if question else None
        self.qtype = QComboBox()
        for key, text in QTYPES.items():
            self.qtype.addItem(text, key)
        self.qtype.setCurrentIndex(max(0, self.qtype.findData(question.qtype if question else "mcq")))
        self.add_row("Type", self.qtype)
        self.node = NodeCombo("No topic")
        self.node.load(sf(ctx).courses.tree(course_id), question.node_id if question else default_node)
        self.add_row("Topic", self.node)
        self.text = QPlainTextEdit(question.text if question else "")
        self.text.setPlaceholderText("Question text. For assertion–reason, write “Assertion (A): …” and “Reason (R): …”.")
        self.text.setMinimumHeight(90)
        self.add_row("Question", self.text)
        row = QHBoxLayout()
        self.marks = QDoubleSpinBox()
        self.marks.setRange(0.5, 100)
        self.marks.setSingleStep(0.5)
        self.marks.setValue(question.marks if question else 1)
        self.marks.setSuffix(" marks")
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.difficulty.setPrefix("Difficulty ")
        self.difficulty.setValue(question.difficulty if question else 2)
        row.addWidget(self.marks)
        row.addWidget(self.difficulty)
        row.addStretch(1)
        self.add_row("Marks", row)

        # answer editors per type
        self.answer_stack = QStackedWidget()
        self.add_row("Answer", self.answer_stack)
        # choice (mcq / multi / assertion)
        self.choice_page = QWidget()
        cl = QVBoxLayout(self.choice_page)
        cl.setContentsMargins(0, 0, 0, 0)
        self.options_edit = QPlainTextEdit()
        self.options_edit.setPlaceholderText("One option per line")
        self.options_edit.setFixedHeight(96)
        self.options_edit.textChanged.connect(self._rebuild_choices)
        cl.addWidget(self.options_edit)
        cl.addWidget(label("Correct answer:", "caption"))
        self.choices_box = QVBoxLayout()
        cl.addLayout(self.choices_box)
        self.answer_stack.addWidget(self.choice_page)
        # true/false
        self.tf = QComboBox()
        self.tf.addItem("True", "true")
        self.tf.addItem("False", "false")
        self.answer_stack.addWidget(self.tf)
        # fill
        self.fill = QLineEdit()
        self.fill.setPlaceholderText("Accepted answer(s), separated by |")
        self.answer_stack.addWidget(self.fill)
        # numerical
        num = QWidget()
        nl = QHBoxLayout(num)
        nl.setContentsMargins(0, 0, 0, 0)
        self.num_value = QLineEdit()
        self.num_value.setPlaceholderText("Value")
        self.num_tol = QLineEdit()
        self.num_tol.setPlaceholderText("± tolerance (optional)")
        self.num_unit = QLineEdit()
        self.num_unit.setPlaceholderText("Unit (optional)")
        for w in (self.num_value, self.num_tol, self.num_unit):
            nl.addWidget(w)
        self.answer_stack.addWidget(num)
        # match
        self.match = QPlainTextEdit()
        self.match.setPlaceholderText("One pair per line:  left => right")
        self.match.setFixedHeight(96)
        self.answer_stack.addWidget(self.match)
        # written
        written = QWidget()
        wl = QVBoxLayout(written)
        wl.setContentsMargins(0, 0, 0, 0)
        self.model = QPlainTextEdit()
        self.model.setPlaceholderText("Model answer")
        self.model.setFixedHeight(90)
        wl.addWidget(self.model)
        wl.addWidget(label("Marking points (used for marking and partial credit):", "caption"))
        self.rubric = RubricEditor(question.rubric_points if question else [])
        wl.addWidget(self.rubric)
        self.answer_stack.addWidget(written)

        self.explanation = QPlainTextEdit(question.explanation if question else "")
        self.explanation.setPlaceholderText("Why the answer is right (shown after the test)")
        self.explanation.setFixedHeight(64)
        self.add_row("Explanation", self.explanation)
        self.tags = QLineEdit(question.tags if question else "")
        self.tags.setPlaceholderText("Optional tags")
        self.add_row("Tags", self.tags)
        self.verified = QCheckBox("I've checked this question and its answer")
        self.verified.setChecked(bool(question.verified) if question else True)
        self.add_row("", self.verified)
        if question:
            self.form.addRow(label(f"Source: {question.provenance}" + (f" · {question.source_ref}" if question.source_ref
                                                                        and question.origin != "official" else ""),
                                   "caption", wrap=True))
        self.choice_buttons: list = []
        self.choice_group = QButtonGroup(self)
        self.qtype.currentIndexChanged.connect(self._type_changed)
        self._load_answer()
        self._type_changed()

    def _load_answer(self) -> None:
        q = self.q
        if q is None:
            return
        if q.qtype in ("mcq", "multi"):
            self.options_edit.setPlainText("\n".join(q.option_list))
        if q.qtype == "tf":
            self.tf.setCurrentIndex(0 if q.answer == "true" else 1)
        elif q.qtype == "fill":
            self.fill.setText(q.answer)
        elif q.qtype == "numerical" and q.answer:
            key = json.loads(q.answer)
            self.num_value.setText(f"{key['value']:g}")
            self.num_tol.setText(f"{key.get('tolerance', 0):g}" if key.get("tolerance") else "")
            self.num_unit.setText(key.get("unit", ""))
        elif q.qtype == "match":
            self.match.setPlainText("\n".join(q.option_list))
        elif q.qtype not in ("mcq", "multi", "assertion"):
            self.model.setPlainText(q.answer)

    def _type_changed(self) -> None:
        t = self.qtype.currentData()
        index = {"mcq": 0, "multi": 0, "assertion": 0, "tf": 1, "fill": 2, "numerical": 3, "match": 4}.get(t, 5)
        self.answer_stack.setCurrentIndex(index)
        self.options_edit.setVisible(t != "assertion")
        self._rebuild_choices()

    def _options(self) -> list[str]:
        if self.qtype.currentData() == "assertion":
            return list(ASSERTION_OPTIONS)
        return [o.strip() for o in self.options_edit.toPlainText().splitlines() if o.strip()]

    def _rebuild_choices(self) -> None:
        t = self.qtype.currentData()
        if t not in ("mcq", "multi", "assertion"):
            return
        previous = self._choice_value()
        if previous is None and self.q is not None and self.q.qtype == t and self.q.answer:
            previous = json.loads(self.q.answer) if t == "multi" else int(self.q.answer)
        clear_layout(self.choices_box)
        for b in self.choice_group.buttons():
            self.choice_group.removeButton(b)
        self.choice_buttons = []
        multi = t == "multi"
        self.choice_group.setExclusive(not multi)
        for i, opt in enumerate(self._options()):
            b = QCheckBox(f"{chr(65 + i)}. {opt}") if multi else QRadioButton(f"{chr(65 + i)}. {opt}")
            if multi and isinstance(previous, list) and i in previous:
                b.setChecked(True)
            elif not multi and previous == i:
                b.setChecked(True)
            self.choice_group.addButton(b, i)
            self.choice_buttons.append(b)
            self.choices_box.addWidget(b)

    def _choice_value(self):
        if not self.choice_buttons:
            return None
        if self.qtype.currentData() == "multi":
            return [i for i, b in enumerate(self.choice_buttons) if b.isChecked()]
        for i, b in enumerate(self.choice_buttons):
            if b.isChecked():
                return i
        return None

    def save(self) -> None:
        t = self.qtype.currentData()
        options: list[str] = []
        rubric: list[dict] = []
        if t in ("mcq", "multi", "assertion"):
            options = self._options()
            value = self._choice_value()
            answer = value if value is not None else ""
        elif t == "tf":
            answer = self.tf.currentData()
        elif t == "fill":
            answer = self.fill.text()
        elif t == "numerical":
            answer = {"value": self.num_value.text(), "tolerance": self.num_tol.text() or 0, "unit": self.num_unit.text()}
        elif t == "match":
            options = [l for l in self.match.toPlainText().splitlines() if l.strip()]
            answer = ""
        else:
            answer = self.model.toPlainText()
            rubric = self.rubric.points()
        fields = dict(qtype=t, text=self.text.toPlainText(), options=options, answer=answer, marks=self.marks.value(),
                      difficulty=self.difficulty.value(), explanation=self.explanation.toPlainText(), rubric=rubric,
                      node_id=self.node.current_id(), tags=self.tags.text(), verified=self.verified.isChecked())
        bank = sf(self.ctx).bank
        try:
            if self.q:
                bank.update(self.q.id, **fields)
            else:
                verified = fields.pop("verified")
                self.saved_id = bank.add(self.course_id, fields.pop("qtype"), fields.pop("text"), verified=verified,
                                         **fields)
        except DuplicateQuestion as exc:
            from src.services.dates import ValidationError

            raise ValidationError(f"{exc} (question #{exc.existing_id}).") from None
        bus.notify("studyforge")


class BankTab(QWidget):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        self.search = SearchField("Search questions")
        self.search.textChanged.connect(lambda _: self.refresh())
        self.node = NodeCombo("All topics")
        self.node.currentIndexChanged.connect(lambda _: self.refresh())
        self.type = QComboBox()
        self.type.addItem("All types", None)
        for key, text in QTYPES.items():
            self.type.addItem(text, key)
        self.type.currentIndexChanged.connect(lambda _: self.refresh())
        self.origin = QComboBox()
        self.origin.addItem("All sources", None)
        for key, text in ORIGINS.items():
            self.origin.addItem(text, key)
        self.origin.addItem("Not verified yet", "unverified")
        self.origin.currentIndexChanged.connect(lambda _: self.refresh())
        for w in (self.search, self.node, self.type, self.origin):
            bar.addWidget(w)
        bar.addStretch(1)
        lay.addLayout(bar)
        actions = QHBoxLayout()
        actions.addWidget(button("New question", "primary", "plus", self.new_question))
        actions.addWidget(button("Edit", "", "edit", self.edit_selected))
        actions.addWidget(button("Mark verified", "ghost", "check", self.verify_selected))
        actions.addWidget(button("Delete", "ghost", "trash", self.delete_selected))
        actions.addStretch(1)
        actions.addWidget(button("Import…", "ghost", "upload", self.import_file))
        actions.addWidget(button("Export…", "ghost", "download", self.export_file))
        lay.addLayout(actions)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Question", "Type", "Marks", "Topic", "Source", "Your results"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 6):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda _: self.edit_selected())
        self.table.setAccessibleName("Questions")
        lay.addWidget(self.table, 1)
        self.empty = QWidget()
        self.empty_lay = QVBoxLayout(self.empty)
        lay.addWidget(self.empty)
        self.footer = label("", "caption", wrap=True)
        lay.addWidget(self.footer)
        self._questions: list[Question] = []

    def refresh(self) -> None:
        course = self.page.course_id
        if course is None:
            return
        tree = sf(self.ctx).courses.tree(course)
        current = self.node.current_id()
        self.node.load(tree, current)
        node_ids = sf(self.ctx).courses.descendants([current]) if current else None
        origin = self.origin.currentData()
        self._questions = sf(self.ctx).bank.list(
            course, node_ids, {self.type.currentData()} if self.type.currentData() else None,
            origin if origin not in (None, "unverified") else None, False if origin == "unverified" else None,
            self.search.text())
        self.table.setRowCount(len(self._questions))
        for row, q in enumerate(self._questions):
            values = [q.text.replace("\n", " ")[:160], SHORT_TYPES.get(q.qtype, q.qtype), f"{q.marks:g}",
                      q.node_title or "–", ("AI · " if q.origin == "ai" else "") + (
                          "Verified" if q.verified else "Not verified" if q.origin in ("ai", "imported") else
                          "Official" if q.origin == "official" else "Yours"),
                      f"{round(100 * q.times_correct / q.times_used)}% of {q.times_used}" if q.times_used else "Not used yet"]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setToolTip(q.text[:1000] + f"\n\n{q.provenance}")
                    item.setData(Qt.ItemDataRole.UserRole, q.id)
                self.table.setItem(row, col, item)
        clear_layout(self.empty_lay)
        has = bool(self._questions)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            self.empty_lay.addWidget(EmptyState(
                "exams", "No questions here yet",
                "Write your own questions, import them from a sample paper (Documents tab), or import a question "
                "bank file. Tests are only ever built from questions in your bank.",
                [("New question", self.new_question)]))
        total = len(sf(self.ctx).bank.list(course))
        self.footer.setText(f"{len(self._questions)} shown · {total} in this course. Official questions keep their "
                            "source reference; AI-generated ones stay labelled until you verify them.")

    def _selected(self) -> list[Question]:
        rows = {i.row() for i in self.table.selectedIndexes()}
        return [self._questions[r] for r in sorted(rows) if r < len(self._questions)]

    def new_question(self) -> None:
        if self.page.course_id is None:
            return
        QuestionDialog(self.ctx, self.page.course_id, self, default_node=self.node.current_id()).exec()

    def edit_selected(self) -> None:
        sel = self._selected()
        if sel:
            QuestionDialog(self.ctx, self.page.course_id, self, sf(self.ctx).bank.get(sel[0].id)).exec()

    def verify_selected(self) -> None:
        sel = self._selected()
        if sel and guarded(self, lambda: [sf(self.ctx).bank.set_verified(q.id, True) for q in sel]):
            bus.notify("studyforge")
            self.page.toast(f"{len(sel)} question(s) marked as checked")

    def delete_selected(self) -> None:
        sel = self._selected()
        if sel and confirm(self, "Delete questions?", f"{len(sel)} question(s) will be removed from the bank. "
                                                     "Past tests keep their own copy."):
            if guarded(self, lambda: [sf(self.ctx).bank.delete(q.id) for q in sel]):
                bus.notify("studyforge")

    def export_file(self) -> None:
        course = sf(self.ctx).courses.get(self.page.course_id)
        default = self.ctx.paths.exports_dir / f"{course.name} questions.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export question bank", str(default), "JSON (*.json)")
        if not path:
            return
        data = {"format": "dayos-question-bank", "version": 1, "course": course.name,
                "questions": sf(self.ctx).bank.export(course.id)}
        try:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            show_error(self, "Export failed", str(exc))
            return
        self.page.toast(f"Exported {len(data['questions'])} questions")

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import a question bank", str(self.ctx.paths.exports_dir),
                                              "DayOS question bank (*.json)")
        if not path:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8")
            if len(raw) > 30_000_000:
                raise ValueError("The file is too large.")
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("format") != "dayos-question-bank":
                raise ValueError("This isn't a DayOS question bank file.")
            items = data.get("questions")
            if not isinstance(items, list):
                raise ValueError("The file has no questions.")
        except (OSError, ValueError) as exc:
            show_error(self, "Can't import this file", str(exc))
            return
        lookup = {n.title: n.id for n in sf(self.ctx).courses.nodes(self.page.course_id)}
        added, dupes, problems = sf(self.ctx).bank.import_items(self.page.course_id, items, lookup)
        bus.notify("studyforge")
        show_info(self, "Import finished", f"Added {added} question(s); skipped {dupes} already in the bank.",
                  ("Problems:\n" + "\n".join(problems[:12])) if problems else
                  "Imported questions are marked “imported, not verified” until you check them.")
