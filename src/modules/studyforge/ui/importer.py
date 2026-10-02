"""Document import (syllabus, chapter list, sample paper, marking scheme) and the CBSE starter dialog."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.modules.studyforge import extract as extractor
from src.modules.studyforge.models import DOC_KINDS, NODE_KINDS, NODE_LABELS, QTYPES
from src.modules.studyforge.paperparse import apply_answer_key, parse_answer_key, parse_paper
from src.modules.studyforge.repository import DuplicateQuestion
from src.modules.studyforge.syllabus import parse
from src.modules.studyforge.templates import CBSE10_SUBJECTS, MATHS_VARIANTS, create_cbse10
from src.modules.studyforge.ui.common import NodeCombo, sf
from src.services.dates import ValidationError
from src.ui.bus import bus
from src.ui.widgets.common import FadeDialog, FormDialog, OptionalDate, button, clear_layout, guarded, label, show_error
from src.ui.worker import run_in_background


class ImportWizard(FadeDialog):
    """1. choose file → 2. describe it → 3. review what was found → save."""

    def __init__(self, page) -> None:
        super().__init__(page)
        self.page = page
        self.ctx = page.ctx
        self.cancel = threading.Event()
        self.result: extractor.Extracted | None = None
        self.path: Path | None = None
        self.setWindowTitle("Import a document")
        self.resize(900, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 16)
        lay.setSpacing(10)
        lay.addWidget(label("Import a document", "title"))
        lay.addWidget(label("Everything is read on this computer. Nothing is uploaded, and nothing is saved until you "
                            "review it.", "muted", wrap=True))
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        # step 1
        s1 = QWidget()
        l1 = QVBoxLayout(s1)
        l1.addWidget(label("Choose a syllabus, chapter list, sample paper or marking scheme (PDF, Word .docx or text).",
                           "", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Choose file…", "primary", "folder", self.choose))
        row.addStretch(1)
        l1.addLayout(row)
        self.status = label("", "muted", wrap=True)
        l1.addWidget(self.status)
        l1.addWidget(label("Scanned PDFs (images of pages) can't be read without OCR, which DayOS doesn't include; "
                           "DayOS will tell you which pages it couldn't read.", "caption", wrap=True))
        l1.addStretch(1)
        self.stack.addWidget(s1)
        # step 2
        s2 = QWidget()
        self.l2 = QVBoxLayout(s2)
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        self.kind = QComboBox()
        for k, t in DOC_KINDS.items():
            self.kind.addItem(t, k)
        self.title = QLineEdit()
        self.session = QLineEdit()
        self.session.setPlaceholderText("e.g. 2026–27")
        self.authority = QLineEdit()
        self.authority.setPlaceholderText("e.g. CBSE")
        self.version = QLineEdit()
        self.version.setPlaceholderText("Version / release date shown on the document")
        self.official = QCheckBox("This is an official document from that authority (e.g. their sample paper)")
        for r, (text, w) in enumerate((("What is it?", self.kind), ("Title", self.title), ("Session", self.session),
                                       ("Board / authority", self.authority), ("Version", self.version))):
            form.addWidget(label(text, "muted"), r, 0)
            form.addWidget(w, r, 1)
        form.addWidget(self.official, 5, 1)
        self.l2.addLayout(form)
        self.problems = label("", "warning", wrap=True)
        self.l2.addWidget(self.problems)
        self.l2.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Analyse", "primary", "chev-right", self.analyse))
        self.l2.addLayout(row)
        self.stack.addWidget(s2)
        # step 3a: course map review
        s3 = QWidget()
        l3 = QVBoxLayout(s3)
        self.map_info = label("", "muted", wrap=True)
        l3.addWidget(self.map_info)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item (untick to skip, double-click to rename)", "Level", "Confidence", "Notes"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        l3.addWidget(self.tree, 1)
        dest = QHBoxLayout()
        dest.addWidget(label("Add to", "muted"))
        self.target = QComboBox()
        dest.addWidget(self.target, 1)
        self.parent_node = NodeCombo("Top level")
        dest.addWidget(self.parent_node, 1)
        self.target.currentIndexChanged.connect(self._target_changed)
        l3.addLayout(dest)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Add to course map", "primary", "check", self.save_map))
        l3.addLayout(row)
        self.stack.addWidget(s3)
        # step 3b: paper review
        s4 = QWidget()
        l4 = QVBoxLayout(s4)
        self.paper_info = label("", "muted", wrap=True)
        l4.addWidget(self.paper_info)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Include", "Question", "Type", "Marks", "Answer key"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        l4.addWidget(self.table, 1)
        prow = QHBoxLayout()
        prow.addWidget(label("Topic for these questions", "muted"))
        self.q_node = NodeCombo("No topic (assign later)")
        prow.addWidget(self.q_node, 1)
        self.make_blueprint = QCheckBox("Also save the paper's structure as a provisional blueprint")
        prow.addWidget(self.make_blueprint)
        l4.addLayout(prow)
        row = QHBoxLayout()
        row.addWidget(button("Apply a marking scheme…", "ghost", "upload", self.load_key))
        row.addStretch(1)
        row.addWidget(button("Save questions", "primary", "check", self.save_paper))
        l4.addLayout(row)
        self.stack.addWidget(s4)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(button("Cancel", "ghost", on_click=self.reject))
        lay.addLayout(bottom)

    def reject(self) -> None:
        self.cancel.set()
        super().reject()

    # -- step 1 ---------------------------------------------------------------------
    def choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a document", str(Path.home()),
                                              "Documents (*.pdf *.docx *.txt *.md *.csv);;All files (*)")
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        self.path = path
        self.status.setText(f"Reading {path.name}…")
        cancel = self.cancel

        def done(result: extractor.Extracted) -> None:
            self.result = result
            self._describe()

        def failed(exc: Exception) -> None:
            if isinstance(exc, extractor.Cancelled):
                return
            self.status.setText("")
            show_error(self, "Couldn't read the file", str(exc))

        run_in_background(lambda: extractor.extract(path, cancel), done, failed)

    def _describe(self) -> None:
        r = self.result
        text = r.text[:20000].lower()
        guess = "sample_paper" if ("maximum marks" in text or "section a" in text) else (
            "marking_scheme" if "marking scheme" in text else "syllabus")
        self.kind.setCurrentIndex(self.kind.findData(guess))
        self.title.setText(self.path.stem.replace("_", " ")[:120])
        proposal = parse(r.pages)
        self.session.setText(proposal.session)
        self.authority.setText(proposal.authority)
        notes = [f"Read {len(r.pages)} page(s): {r.status}."] + r.problems
        self.problems.setText("\n".join(notes))
        self.problems.setProperty("role", "warning" if r.problems else "muted")
        self.stack.setCurrentIndex(1)

    # -- step 2 → 3 ---------------------------------------------------------------------
    def _existing_doc(self) -> int | None:
        course = self.page.course_id
        doc = sf(self.ctx).courses.find_document_by_hash(self.result.sha256, course)
        return doc.id if doc else None

    def _save_document(self, course_id: int | None) -> int:
        existing = sf(self.ctx).courses.find_document_by_hash(self.result.sha256, course_id)
        if existing:
            return existing.id
        return sf(self.ctx).courses.add_document(
            course_id, self.title.text() or self.path.name, self.result.pages, filename=self.path.name,
            path=str(self.path), kind=self.kind.currentData(), official=self.official.isChecked(),
            sha256=self.result.sha256, session=self.session.text(), authority=self.authority.text(),
            version=self.version.text(), status=self.result.status, problems=self.result.problems)

    def analyse(self) -> None:
        if self.result is None or self.result.status == "unreadable":
            show_error(self, "Nothing to analyse", "No readable text was found in this document.")
            return
        kind = self.kind.currentData()
        if kind in ("sample_paper", "marking_scheme"):
            self._show_paper()
        else:
            self._show_map()

    def _show_map(self) -> None:
        proposal = parse(self.result.pages)
        self.proposal = proposal
        self.tree.clear()

        def add(parent, nodes) -> None:
            for n in nodes:
                item = QTreeWidgetItem([n.title, NODE_LABELS[n.kind], f"{round(n.confidence * 100)}%",
                                        "; ".join(n.flags)])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
                item.setCheckState(0, Qt.CheckState.Unchecked if n.skip else Qt.CheckState.Checked)
                item.setData(0, Qt.ItemDataRole.UserRole, n.kind)
                item.setData(1, Qt.ItemDataRole.UserRole, n.source_ref)
                item.setData(2, Qt.ItemDataRole.UserRole, n.confidence)
                (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(item)
                add(item, n.children)

        add(self.tree, proposal.nodes)
        self.tree.expandAll()
        info = [f"Found {proposal.count()} item(s)."]
        if proposal.level:
            info.append(f"Level: {proposal.level}.")
        info += proposal.flags
        if proposal.dates:
            info.append("Dates mentioned near exam words (not added automatically): " + "; ".join(proposal.dates[:4]))
        self.map_info.setText(" ".join(info))
        self.target.clear()
        self.target.addItem("A new course", None)
        for c in sf(self.ctx).courses.list():
            self.target.addItem(c.name, c.id)
        if self.page.course_id:
            self.target.setCurrentIndex(max(0, self.target.findData(self.page.course_id)))
        self._target_changed()
        self.stack.setCurrentIndex(2)

    def _target_changed(self) -> None:
        cid = self.target.currentData()
        self.parent_node.setEnabled(cid is not None)
        if cid is not None:
            self.parent_node.load(sf(self.ctx).courses.tree(cid), None, {"subject", "unit", "chapter"})

    def _tree_items(self, parent) -> list[dict]:
        out = []
        count = parent.childCount() if isinstance(parent, QTreeWidgetItem) else parent.topLevelItemCount()
        for i in range(count):
            it = parent.child(i) if isinstance(parent, QTreeWidgetItem) else parent.topLevelItem(i)
            out.append({"title": it.text(0), "kind": it.data(0, Qt.ItemDataRole.UserRole),
                        "source_ref": f"{self.title.text()} {it.data(1, Qt.ItemDataRole.UserRole)}".strip(),
                        "confidence": it.data(2, Qt.ItemDataRole.UserRole),
                        "skip": it.checkState(0) != Qt.CheckState.Checked, "children": self._tree_items(it)})
        return out

    def save_map(self) -> None:
        items = self._tree_items(self.tree)
        if not any(not i["skip"] for i in items):
            show_error(self, "Nothing selected", "Tick at least one item to add.")
            return
        cid = self.target.currentData()
        added = 0

        def run() -> None:
            nonlocal cid, added
            if cid is None:
                cid = sf(self.ctx).courses.create(self.title.text() or "Imported course", "custom",
                                                  self.session.text(), self.authority.text(), self.proposal.level)
            doc = self._save_document(cid)
            added = sf(self.ctx).courses.import_map(cid, items, self.parent_node.current_id() if self.target.currentData()
                                                    else None, doc)

        if guarded(self, run, "Couldn't import"):
            bus.notify("studyforge")
            self.page.select_course(cid)
            self.page.toast(f"Added {added} item(s). Review them on the Course map tab.")
            self.accept()

    # -- papers ---------------------------------------------------------------------------
    def _show_paper(self) -> None:
        if self.page.course_id is None:
            show_error(self, "Choose a course first", "Questions belong to a course. Create or select one, then import.")
            return
        self.paper = parse_paper(self.result.pages)
        self.q_node.load(sf(self.ctx).courses.tree(self.page.course_id), None)
        self._fill_paper()
        self.make_blueprint.setChecked(bool(self.paper.sections and self.paper.duration_min))
        self.make_blueprint.setEnabled(bool(self.paper.sections and self.paper.duration_min and self.paper.max_marks))
        self.stack.setCurrentIndex(3)

    def _fill_paper(self) -> None:
        p = self.paper
        self.table.setRowCount(len(p.questions))
        for r, q in enumerate(p.questions):
            inc = QTableWidgetItem()
            inc.setFlags(inc.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            inc.setCheckState(Qt.CheckState.Checked if q.include else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, inc)
            self.table.setItem(r, 1, QTableWidgetItem(q.text.replace("\n", " ")[:300]))
            combo = QComboBox()
            for k, t in QTYPES.items():
                combo.addItem(t, k)
            combo.setCurrentIndex(max(0, combo.findData(q.qtype)))
            self.table.setCellWidget(r, 2, combo)
            spin = QDoubleSpinBox()
            spin.setRange(0, 100)
            spin.setSingleStep(0.5)
            spin.setValue(q.marks or 0)
            self.table.setCellWidget(r, 3, spin)
            key = f"({chr(97 + int(q.answer))})" if q.answer else ("—" if q.qtype in ("mcq", "assertion") else "manual")
            self.table.setItem(r, 4, QTableWidgetItem(key))
        info = [f"Found {len(p.questions)} question(s)."]
        if p.max_marks:
            info.append(f"Maximum marks {p.max_marks:g}.")
        if p.duration_min:
            info.append(f"Time {p.duration_min} min.")
        if p.sections:
            info.append("Sections: " + ", ".join(f"{s.name} {s.count}×{s.marks_each:g}" for s in p.sections) + ".")
        info += p.flags
        origin = "official" if self.official.isChecked() else "imported (not verified)"
        info.append(f"Questions will be saved as {origin}, with page references. Choice questions without an answer "
                    "key are marked by hand.")
        self.paper_info.setText(" ".join(info))

    def load_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the marking scheme / answer key", str(self.path.parent),
                                              "Documents (*.pdf *.docx *.txt);;All files (*)")
        if not path:
            return
        try:
            key = parse_answer_key(extractor.extract(Path(path)).pages)
        except (ValueError, OSError) as exc:
            show_error(self, "Couldn't read the marking scheme", str(exc))
            return
        matched = apply_answer_key(self.paper, key)
        self._fill_paper()
        self.page.toast(f"Matched {matched} answer(s) from the marking scheme")

    def save_paper(self) -> None:
        course = self.page.course_id
        official = self.official.isChecked()
        added = dupes = 0
        problems: list[str] = []

        def run() -> None:
            nonlocal added, dupes
            doc = self._save_document(course)
            for r, q in enumerate(self.paper.questions):
                if self.table.item(r, 0).checkState() != Qt.CheckState.Checked:
                    continue
                qtype = self.table.cellWidget(r, 2).currentData()
                marks = self.table.cellWidget(r, 3).value()
                if marks <= 0:
                    problems.append(f"Q{q.number}: set its marks.")
                    continue
                try:
                    sf(self.ctx).bank.add(course, qtype, q.text, node_id=self.q_node.current_id(), options=q.options,
                                          answer=q.answer, marks=marks, origin="official" if official else "imported",
                                          verified=False, source_doc_id=doc,
                                          source_ref=f"{self.title.text()}, Q{q.number}, p. {q.page}",
                                          allow_missing_key=True)
                    added += 1
                except DuplicateQuestion:
                    dupes += 1
                except ValidationError as exc:
                    problems.append(f"Q{q.number}: {exc}")
            if self.make_blueprint.isChecked() and self.paper.max_marks and self.paper.duration_min:
                try:
                    sf(self.ctx).tests.save_blueprint(
                        course, f"{self.title.text()} (structure)", self.paper.max_marks, self.paper.duration_min,
                        self.paper.sections, session=self.session.text(), status="provisional", source_doc_id=doc,
                        source_note=f"Read from {self.path.name}", version=self.version.text())
                except ValidationError as exc:
                    problems.append(f"Blueprint not saved: {exc}")

        if guarded(self, run, "Couldn't save the questions"):
            bus.notify("studyforge")
            msg = f"Saved {added} question(s)" + (f", skipped {dupes} already in the bank" if dupes else "")
            if problems:
                show_error(self, msg, "Some items need attention:", "\n".join(problems[:15]))
            self.page.toast(msg)
            self.accept()


class CbseSetupDialog(FormDialog):
    def __init__(self, page) -> None:
        super().__init__("Set up CBSE Class 10", page, save_text="Create course", width=620)
        self.page = page
        self.session = QLineEdit()
        self.session.setPlaceholderText("Your academic session, e.g. 2026–27")
        self.add_row("Session", self.session)
        # A widget (not a bare layout) in the form row, so the rows grow once styling sets their height.
        subjects_box = QWidget()
        grid = QGridLayout(subjects_box)
        grid.setContentsMargins(0, 0, 0, 0)
        self.subjects: dict[str, QCheckBox] = {}
        self.dates: dict[str, OptionalDate] = {}
        for r, name in enumerate(CBSE10_SUBJECTS):
            cb = QCheckBox(name)
            cb.setChecked(name in ("Mathematics", "Science", "Social Science", "English"))
            od = OptionalDate("Exam on")
            self.subjects[name] = cb
            self.dates[name] = od
            grid.addWidget(cb, r, 0)
            grid.addWidget(od, r, 1)
        self.add_row("Subjects", subjects_box)
        self.maths = QComboBox()
        self.maths.addItems(MATHS_VARIANTS)
        self.add_row("Mathematics", self.maths)
        self.chapters = QCheckBox("Add starter chapter lists for Mathematics, Science and Social Science")
        self.chapters.setChecked(True)
        self.add_row("", self.chapters)
        self.form.addRow(label("Starter chapter lists follow the NCERT textbook contents and are marked provisional. "
                               "Syllabi change between sessions, so compare them with the official CBSE curriculum for "
                               "your session (or import that document from the Documents tab). Exam patterns are never "
                               "assumed: import the official sample paper to create a blueprint.", "caption", wrap=True))

    def save(self) -> None:
        chosen = [n for n, cb in self.subjects.items() if cb.isChecked()]
        if not chosen:
            raise ValidationError("Choose at least one subject.")
        ctx = self.page.ctx
        cid = create_cbse10(sf(ctx), self.session.text().strip(), chosen,
                            {n: self.dates[n].value() for n in chosen}, self.chapters.isChecked(),
                            self.maths.currentText(), ctx.subjects)
        self.course_id = cid
        bus.notify("studyforge", "subjects")
