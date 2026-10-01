"""Tests: create practice tests (quick or from a blueprint), blueprints, history, printing."""

from __future__ import annotations

import random
from datetime import datetime

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.modules.studyforge.assembler import quick_sections
from src.modules.studyforge.models import BLUEPRINT_STATUS, QTYPES, Section
from src.modules.studyforge.printable import paper_html
from src.modules.studyforge.service import GenerateRequest
from src.modules.studyforge.templates import GENERIC_PRESETS
from src.modules.studyforge.ui.common import NodeCombo, ScopeTree, sf, svc
from src.services.dates import ValidationError, format_date
from src.ui.bus import bus
from src.ui.widgets.common import (
    EmptyState,
    FormDialog,
    SegmentBar,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    show_error,
    tool_button,
)


class CreateTestDialog(FormDialog):
    def __init__(self, page, preset_nodes: list[int] | None = None, preset: str = "quick") -> None:
        super().__init__("Create a practice test", page, save_text="Create test", width=720)
        self.page = page
        self.ctx = page.ctx
        self.course_id = page.course_id
        self.test_id: int | None = None
        self.title_edit = QLineEdit(f"Practice test {datetime.now():%d %b}")
        self.add_row("Title", self.title_edit)
        self.scope = ScopeTree()
        self.scope.load(sf(self.ctx).courses.tree(self.course_id), set(preset_nodes or []),
                        sf(self.ctx).bank.counts_by_node(self.course_id))
        scope_box = QVBoxLayout()
        scope_box.addWidget(self.scope)
        row = QHBoxLayout()
        row.addWidget(button("Everything", "link", on_click=lambda: self.scope.check_all(True)))
        row.addWidget(button("Clear", "link", on_click=lambda: self.scope.check_all(False)))
        row.addStretch(1)
        scope_box.addLayout(row)
        self.add_row("Covering", scope_box)
        self.structure = SegmentBar([("quick", "Quick quiz"), ("medium", "Medium test"), ("full", "Long practice"),
                                     ("custom", "Custom"), ("blueprint", "Blueprint")], preset)
        self.structure.changed.connect(self._structure_changed)
        self.add_row("Structure", self.structure)
        self.types_box = QWidget()
        tg = QGridLayout(self.types_box)
        tg.setContentsMargins(0, 0, 0, 0)
        self.type_checks: dict[str, QCheckBox] = {}
        for i, (key, text) in enumerate(QTYPES.items()):
            cb = QCheckBox(text)
            self.type_checks[key] = cb
            tg.addWidget(cb, i // 3, i % 3)
        self.add_row("Question types", self.types_box)
        self.count = QSpinBox()
        self.count.setRange(1, 200)
        self.count.setSuffix(" questions")
        self.add_row("Length", self.count)
        self.blueprint = QComboBox()
        for bp in sf(self.ctx).tests.blueprints(self.course_id):
            self.blueprint.addItem(f"{bp.name} — {bp.max_marks:g} marks, {bp.duration_min} min "
                                   f"({BLUEPRINT_STATUS[bp.status].split(' —')[0].lower()})", bp.id)
        self.add_row("Blueprint", self.blueprint)
        diff = QHBoxLayout()
        self.diff_lo = QSpinBox()
        self.diff_lo.setRange(1, 5)
        self.diff_hi = QSpinBox()
        self.diff_hi.setRange(1, 5)
        self.diff_hi.setValue(5)
        diff.addWidget(self.diff_lo)
        diff.addWidget(label("to", "muted"))
        diff.addWidget(self.diff_hi)
        diff.addStretch(1)
        self.add_row("Difficulty", diff)
        self.focus = QComboBox()
        self.focus.addItem("Balanced across the topics", "balanced")
        self.focus.addItem("More from weak topics and mistakes", "weak")
        self.focus.addItem("Topics due for revision", "due")
        self.add_row("Focus", self.focus)
        mode_row = QHBoxLayout()
        self.timed = QCheckBox("Timed")
        self.duration = QSpinBox()
        self.duration.setRange(1, 600)
        self.duration.setSuffix(" min")
        self.timed.toggled.connect(self.duration.setEnabled)
        mode_row.addWidget(self.timed)
        mode_row.addWidget(self.duration)
        mode_row.addStretch(1)
        self.add_row("Mode", mode_row)
        self.sources = QComboBox()
        self.sources.addItem("Any question in my bank", None)
        self.sources.addItem("Only verified / official questions", "verified")
        self.sources.addItem("Leave out AI-generated questions", "no_ai")
        self.add_row("Sources", self.sources)
        self.preview = label("", "caption", wrap=True)
        self.extra.addWidget(self.preview)
        prev = button("Check what's possible", "ghost", "check", self.check)
        self.left_buttons.addWidget(prev)
        self._structure_changed(preset)

    def _structure_changed(self, key: str) -> None:
        bp = key == "blueprint"
        self.blueprint.setEnabled(bp)
        self.types_box.setEnabled(not bp)
        self.count.setEnabled(not bp)
        if key in GENERIC_PRESETS:
            p = GENERIC_PRESETS[key]
            for t, cb in self.type_checks.items():
                cb.setChecked(t in p["types"])
            self.count.setValue(p["count"])
            self.duration.setValue(p["minutes"])
        if bp and self.blueprint.count() == 0:
            self.preview.setText("This course has no blueprints yet. Create one on the Tests tab (or import one "
                                 "from an official sample paper), then come back.")
        self.timed.setChecked(key in ("full", "blueprint"))
        self.duration.setEnabled(self.timed.isChecked())

    def _request(self) -> GenerateRequest:
        nodes = self.scope.checked_ids()
        if not nodes:
            raise ValidationError("Tick the chapters or topics the test should cover.")
        structure = self.structure.current()
        blueprint_id = None
        sections: list[Section] = []
        if structure == "blueprint":
            blueprint_id = self.blueprint.currentData()
            if blueprint_id is None:
                raise ValidationError("Choose a blueprint, or pick another structure.")
        else:
            types = [t for t, cb in self.type_checks.items() if cb.isChecked()]
            if not types:
                raise ValidationError("Tick at least one question type.")
            sections = quick_sections(types, self.count.value())
        lo, hi = sorted((self.diff_lo.value(), self.diff_hi.value()))
        source = self.sources.currentData()
        origins = {"official", "imported", "user"} if source == "no_ai" else None
        return GenerateRequest(self.course_id, self.title_edit.text(), nodes, sections, blueprint_id,
                               "timed" if self.timed.isChecked() else "practice",
                               self.duration.value() if self.timed.isChecked() else None, (lo, hi),
                               self.focus.currentData(), origins, source == "verified")

    def check(self) -> None:
        try:
            result = svc(self.ctx).generate(self._request(), save=False)
        except ValidationError as exc:
            self.show_error(str(exc))
            return
        n = len(result.assembly.items)
        text = f"Possible: {n} question(s), {result.assembly.total_marks:g} marks."
        if result.issues:
            text += "\n• " + "\n• ".join(result.issues)
        else:
            text += " Everything checks out."
        self.preview.setText(text)

    def save(self) -> None:
        req = self._request()
        req.seed = random.randint(1, 10**9)  # the same seed gives the same paper when it's saved below
        result = svc(self.ctx).generate(req, save=False)
        if not result.assembly.items:
            raise ValidationError("No questions match. " + (result.issues[0] if result.issues else
                                                             "Add questions to the bank for these topics."))
        if result.issues and not confirm(self, "Create the test anyway?",
                                         "• " + "\n• ".join(result.issues[:8]), "Create anyway", danger=False):
            raise ValidationError("Not created — adjust the settings or add questions.")
        final = svc(self.ctx).generate(req, save=True)
        self.test_id = final.test_id
        bus.notify("studyforge")


class BlueprintDialog(FormDialog):
    def __init__(self, page, blueprint=None) -> None:
        super().__init__("Edit blueprint" if blueprint else "New blueprint", page, width=720)
        self.page = page
        self.ctx = page.ctx
        self.bp = blueprint
        self.name = QLineEdit(blueprint.name if blueprint else "")
        self.name.setPlaceholderText("e.g. Term 1 paper (from the official sample paper)")
        self.add_row("Name", self.name)
        self.subject = NodeCombo("Whole course")
        self.subject.load(sf(self.ctx).courses.tree(page.course_id), blueprint.subject_node_id if blueprint else None,
                          {"subject", "unit"})
        self.add_row("Subject", self.subject)
        row = QHBoxLayout()
        self.max_marks = QDoubleSpinBox()
        self.max_marks.setRange(1, 1000)
        self.max_marks.setValue(blueprint.max_marks if blueprint else 20)
        self.max_marks.setSuffix(" marks")
        self.duration = QSpinBox()
        self.duration.setRange(1, 600)
        self.duration.setValue(blueprint.duration_min if blueprint else 30)
        self.duration.setSuffix(" min")
        row.addWidget(self.max_marks)
        row.addWidget(self.duration)
        row.addStretch(1)
        self.add_row("Total", row)
        self.sections = QTableWidget(0, 5)
        self.sections.setHorizontalHeaderLabels(["Section", "Question type", "Questions", "Marks each", "Extra choices"])
        self.sections.verticalHeader().setVisible(False)
        self.sections.setMinimumHeight(180)
        self.add_row("Sections", self.sections)
        srow = QHBoxLayout()
        srow.addWidget(button("Add section", "link", "plus", lambda: self._add_section(None)))
        srow.addWidget(button("Remove section", "link", "trash", self._remove_section))
        srow.addStretch(1)
        self.sum_label = label("", "caption")
        srow.addWidget(self.sum_label)
        self.add_row("", srow)
        self.instructions = QPlainTextEdit(blueprint.instructions if blueprint else "")
        self.instructions.setFixedHeight(70)
        self.instructions.setPlaceholderText("General instructions printed on the paper (optional)")
        self.add_row("Instructions", self.instructions)
        self.session = QLineEdit(blueprint.session if blueprint else "")
        self.session.setPlaceholderText("e.g. 2026–27")
        self.add_row("Session", self.session)
        self.status = QComboBox()
        for key, text in BLUEPRINT_STATUS.items():
            self.status.addItem(text, key)
        self.status.setCurrentIndex(max(0, self.status.findData(blueprint.status if blueprint else "user")))
        self.add_row("Status", self.status)
        self.source = QLineEdit(blueprint.source_note if blueprint else "")
        self.source.setPlaceholderText("Official document this structure comes from (required for “verified”)")
        self.add_row("Source", self.source)
        self.version = QLineEdit(blueprint.version if blueprint else "")
        self.version.setPlaceholderText("Version or date of that document")
        self.add_row("Version", self.version)
        self.form.addRow(label("DayOS never assumes an exam pattern. Copy the structure from the official document "
                               "for your session; when the pattern changes, edit this blueprint.", "caption", wrap=True))
        for s in (blueprint.section_list if blueprint else [Section("Section A", "mcq", 10, 1),
                                                             Section("Section B", "sa", 5, 2)]):
            self._add_section(s)
        self.sections.itemChanged.connect(lambda _i: self._update_sum())
        self._update_sum()

    def _add_section(self, s: Section | None) -> None:
        s = s or Section(f"Section {chr(65 + self.sections.rowCount())}", "sa", 1, 1)
        r = self.sections.rowCount()
        self.sections.insertRow(r)
        self.sections.setItem(r, 0, QTableWidgetItem(s.name))
        combo = QComboBox()
        for key, text in QTYPES.items():
            combo.addItem(text, key)
        combo.setCurrentIndex(max(0, combo.findData(s.qtype)))
        self.sections.setCellWidget(r, 1, combo)
        for col, (value, lo, hi, step) in enumerate(((s.count, 1, 200, 1), (s.marks_each, 0.5, 100, 0.5),
                                                     (s.choice, 0, 5, 1)), start=2):
            spin = QDoubleSpinBox() if col == 3 else QSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setValue(value)
            spin.valueChanged.connect(lambda _v: self._update_sum())
            self.sections.setCellWidget(r, col, spin)
        self._update_sum()

    def _remove_section(self) -> None:
        r = self.sections.currentRow()
        if r >= 0:
            self.sections.removeRow(r)
            self._update_sum()

    def _section_list(self) -> list[Section]:
        out = []
        for r in range(self.sections.rowCount()):
            name = self.sections.item(r, 0).text() if self.sections.item(r, 0) else ""
            out.append(Section(name.strip(), self.sections.cellWidget(r, 1).currentData(),
                               int(self.sections.cellWidget(r, 2).value()), float(self.sections.cellWidget(r, 3).value()),
                               int(self.sections.cellWidget(r, 4).value())))
        return out

    def _update_sum(self) -> None:
        if not hasattr(self, "sum_label"):
            return
        total = sum(s.total for s in self._section_list())
        ok = abs(total - self.max_marks.value()) < 1e-6
        self.sum_label.setText(f"Sections add up to {total:g} marks" + ("" if ok else f" (total is {self.max_marks.value():g})"))
        self.sum_label.setProperty("role", "success" if ok else "warning")
        self.sum_label.style().unpolish(self.sum_label)
        self.sum_label.style().polish(self.sum_label)

    def save(self) -> None:
        sf(self.ctx).tests.save_blueprint(
            self.page.course_id, self.name.text(), self.max_marks.value(), self.duration.value(), self._section_list(),
            blueprint_id=self.bp.id if self.bp else None, subject_node_id=self.subject.current_id(),
            session=self.session.text(), instructions=self.instructions.toPlainText(), status=self.status.currentData(),
            source_doc_id=self.bp.source_doc_id if self.bp else None, source_note=self.source.text(),
            version=self.version.text())
        bus.notify("studyforge")


class TestsTab(QWidget):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(12)
        bar = QHBoxLayout()
        for key, p in (("quick", GENERIC_PRESETS["quick"]), ("medium", GENERIC_PRESETS["medium"])):
            bar.addWidget(button(f"{p['label']} (~{p['minutes']} min)", "soft", "exams",
                                 lambda k=key: self.page.create_test(preset=k)))
        bar.addWidget(button("Custom test…", "primary", "plus", lambda: self.page.create_test(preset="custom")))
        bar.addStretch(1)
        bar.addWidget(button("New blueprint", "ghost", "grid", lambda: BlueprintDialog(self.page).exec()))
        lay.addLayout(bar)
        self.holder = QWidget()
        self.body = QVBoxLayout(self.holder)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(10)
        lay.addWidget(scroll_wrap(self.holder), 1)

    def refresh(self) -> None:
        clear_layout(self.body)
        course = self.page.course_id
        unfinished = [a for a in svc(self.ctx).unfinished() if sf(self.ctx).tests.test(a.test_id)
                      and sf(self.ctx).tests.test(a.test_id).course_id == course]
        for a in unfinished:
            box = QFrame()
            box.setObjectName("Banner")
            box.setProperty("tone", "warning")
            r = QHBoxLayout(box)
            r.setContentsMargins(14, 8, 10, 8)
            r.addWidget(label(f"Unfinished: “{a.test_title}” started {a.started_at[:16]}. Your answers are saved.",
                              "warning", wrap=True), 1)
            r.addWidget(button("Resume", "primary", on_click=lambda t=a.test_id: self.page.take_test(t)))
            self.body.addWidget(box)
        tests = sf(self.ctx).tests.tests(course)
        self.body.addWidget(label("Your tests", "section"))
        if not tests:
            self.body.addWidget(EmptyState("exams", "No tests yet",
                                           "Create a quick quiz from the chapters you choose. Questions come only from "
                                           "your question bank, and results feed your revision plan.",
                                           [("Create a test", lambda: self.page.create_test())], compact=True))
        for t in tests[:60]:
            row = QFrame()
            row.setProperty("inset", True)
            r = QHBoxLayout(row)
            r.setContentsMargins(12, 8, 8, 8)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(t.title, "heading"))
            meta = [format_date(datetime.fromisoformat(t.created_at).date(), self.page.date_style),
                    f"{t.total_marks:g} marks", "timed" if t.mode == "timed" else "practice"]
            if t.duration_min:
                meta.append(f"{t.duration_min} min")
            col.addWidget(label(" · ".join(meta), "caption"))
            r.addLayout(col, 1)
            if t.best is not None:
                r.addWidget(chip(f"Best {t.best:.0f}%", "accent"))
            if t.attempts:
                r.addWidget(label(f"{t.attempts} attempt{'s' if t.attempts != 1 else ''}", "caption"))
                r.addWidget(button("Results", "link", on_click=lambda tid=t.id: self.page.show_results(tid)))
            r.addWidget(button("Take", "soft", "play", lambda tid=t.id: self.page.take_test(tid)))
            r.addWidget(tool_button("download", "Print or save the paper", lambda tid=t.id: self.print_test(tid, False), 16))
            r.addWidget(tool_button("check", "Print the answer key", lambda tid=t.id: self.print_test(tid, True), 16))
            r.addWidget(tool_button("trash", "Delete test", lambda tid=t.id: self.delete_test(tid), 16))
            self.body.addWidget(row)
        blueprints = sf(self.ctx).tests.blueprints(course)
        self.body.addWidget(label("Blueprints", "section"))
        if not blueprints:
            self.body.addWidget(label("A blueprint describes a paper's structure (sections, question types, marks). "
                                      "Import one from an official sample paper on the Documents tab, or create your own.",
                                      "muted", wrap=True))
        for bp in blueprints:
            row = QFrame()
            row.setProperty("inset", True)
            r = QHBoxLayout(row)
            r.setContentsMargins(12, 8, 8, 8)
            col = QVBoxLayout()
            col.addWidget(label(bp.name, "heading"))
            col.addWidget(label(" · ".join(f"{s.name}: {s.count}×{s.marks_each:g}" for s in bp.section_list)
                                + f" = {bp.max_marks:g} marks, {bp.duration_min} min", "caption", wrap=True))
            if bp.source_note:
                col.addWidget(label(f"Source: {bp.source_note}" + (f" ({bp.version})" if bp.version else ""), "caption"))
            r.addLayout(col, 1)
            r.addWidget(chip({"verified": "Verified", "provisional": "Provisional", "user": "User-defined"}[bp.status],
                             {"verified": "accent", "provisional": "amber", "user": ""}[bp.status]))
            r.addWidget(button("Edit", "link", on_click=lambda b=bp: BlueprintDialog(self.page, b).exec()))
            r.addWidget(tool_button("trash", "Delete blueprint", lambda b=bp: self.delete_blueprint(b), 16))
            self.body.addWidget(row)
        self.body.addStretch(1)

    def print_test(self, test_id: int, key: bool) -> None:
        test = sf(self.ctx).tests.test(test_id)
        course = sf(self.ctx).courses.get(test.course_id) if test.course_id else None
        html = paper_html(test, sf(self.ctx).tests.items(test_id), key, course.name if course else "")
        folder = self.ctx.paths.exports_dir / "papers"
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in test.title if c.isalnum() or c in " -_")[:60].strip() or "test"
        path = folder / f"{safe}{' - answer key' if key else ''}.html"
        try:
            path.write_text(html, encoding="utf-8")
        except OSError as exc:
            show_error(self, "Couldn't save the paper", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self.page.toast("Opened in your browser — print it or save it as PDF from there")

    def delete_test(self, test_id: int) -> None:
        if confirm(self, "Delete test?", "The test and its attempts are deleted. Questions stay in the bank, and "
                                        "your revision history is kept."):
            if guarded(self, lambda: sf(self.ctx).tests.delete_test(test_id)):
                bus.notify("studyforge")

    def delete_blueprint(self, bp) -> None:
        if confirm(self, "Delete blueprint?", f"“{bp.name}” will be deleted. Tests made from it are kept."):
            if guarded(self, lambda: sf(self.ctx).tests.delete_blueprint(bp.id)):
                bus.notify("studyforge")
