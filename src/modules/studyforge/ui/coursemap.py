"""Course map: the editable hierarchy of subjects, units, chapters, topics and learning objectives."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.modules.studyforge import srs
from src.modules.studyforge.models import NODE_KINDS, NODE_LABELS
from src.modules.studyforge.ui.common import percent, sf, svc
from src.services.dates import format_date
from src.ui.bus import bus
from src.ui.widgets.common import EmptyState, FormDialog, OptionalDate, button, clear_layout, confirm, guarded, label

CHILD_KIND = {None: "subject", "subject": "chapter", "unit": "chapter", "chapter": "topic", "topic": "objective",
              "objective": "objective"}


class NodeDialog(FormDialog):
    def __init__(self, ctx, course_id: int, parent=None, node=None, parent_id: int | None = None,
                 kind: str = "chapter") -> None:
        super().__init__("Edit item" if node else "Add to course map", parent)
        self.ctx = ctx
        self.course_id = course_id
        self.node = node
        self.parent_id = parent_id
        self.title_edit = QLineEdit(node.title if node else "")
        self.title_edit.setPlaceholderText("Title")
        self.add_row("Title", self.title_edit)
        self.kind = QComboBox()
        for k in NODE_KINDS:
            self.kind.addItem(NODE_LABELS[k], k)
        self.kind.setCurrentIndex(self.kind.findData(node.kind if node else kind))
        self.add_row("Level", self.kind)
        self.exam = OptionalDate("Exam on", node.exam_day if node else None)
        self.add_row("Exam date", self.exam)
        self.notes = QPlainTextEdit(node.notes if node else "")
        self.notes.setFixedHeight(70)
        self.notes.setPlaceholderText("Notes (optional)")
        self.add_row("Notes", self.notes)
        if node and node.source_ref:
            self.form.addRow(label(f"Source: {node.source_ref}", "caption", wrap=True))
        self.form.addRow(label("Exam dates set on a subject apply to everything inside it and make revision "
                               "come round more often as the date approaches.", "caption", wrap=True))
        self.title_edit.setFocus()

    def save(self) -> None:
        courses = sf(self.ctx).courses
        if self.node:
            courses.update_node(self.node.id, title=self.title_edit.text(), kind=self.kind.currentData(),
                                notes=self.notes.toPlainText(), exam_date=self.exam.value())
        else:
            nid = courses.add_node(self.course_id, self.kind.currentData(), self.title_edit.text(), self.parent_id)
            courses.update_node(nid, notes=self.notes.toPlainText(), exam_date=self.exam.value())
        bus.notify("studyforge")


class CourseMapTab(QWidget):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(button("Add subject", "", "plus", lambda: self.add(None)))
        bar.addWidget(button("Add inside selected", "primary", "plus", self.add_child))
        bar.addWidget(button("Edit", "ghost", "edit", self.edit))
        bar.addWidget(button("Move up", "ghost", "chev-up", lambda: self.move(-1)))
        bar.addWidget(button("Move down", "ghost", "chev-down", lambda: self.move(1)))
        bar.addWidget(button("Delete", "ghost", "trash", self.delete))
        bar.addStretch(1)
        bar.addWidget(button("Paste a list…", "ghost", "list", self.paste_list))
        lay.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["Course map", "Level", "Questions", "Accuracy", "Mastery (estimate)", "Next review"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 6):
            self.tree.header().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.setAccessibleName("Course map")
        lay.addWidget(self.tree, 1)
        self.empty_holder = QWidget()
        self.empty_lay = QVBoxLayout(self.empty_holder)
        lay.addWidget(self.empty_holder)
        lay.addWidget(label("Mastery is an estimate from your practice: it needs several correct, spaced-out attempts "
                            "before a topic counts as strong.", "caption", wrap=True))

    def refresh(self) -> None:
        course = self.page.course_id
        if course is None:
            return
        selected = self.selected_id()
        overview = svc(self.ctx).topic_overview(course)
        roots = sf(self.ctx).courses.tree(course)
        self.tree.clear()
        style = self.page.date_style

        def add(parent, nodes) -> None:
            for n in nodes:
                info = overview.get(n.id, {})
                due = info.get("due")
                cols = [n.title + (f"   · exam {format_date(n.exam_day, style)}" if n.exam_day else ""),
                        NODE_LABELS.get(n.kind, n.kind), str(info.get("questions") or "–"),
                        percent(info.get("accuracy")), srs.MASTERY_LABELS.get(info.get("mastery", "new"), ""),
                        format_date(date.fromisoformat(due), style) if due else "–"]
                item = QTreeWidgetItem(cols)
                item.setData(0, Qt.ItemDataRole.UserRole, n.id)
                if n.confidence is not None and n.confidence < 0.6:
                    item.setToolTip(0, "Imported with low confidence — check the title")
                elif n.source_ref:
                    item.setToolTip(0, f"Source: {n.source_ref}")
                (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(item)
                add(item, n.children)
                if n.id == selected:
                    self.tree.setCurrentItem(item)

        add(self.tree, roots)
        self.tree.expandToDepth(1)
        clear_layout(self.empty_lay)
        self.tree.setVisible(bool(roots))
        self.empty_holder.setVisible(not roots)
        if not roots:
            self.empty_lay.addWidget(EmptyState(
                "book", "An empty course map",
                "Add subjects, chapters and topics yourself, paste a chapter list, or import an official syllabus "
                "from the Documents tab and review what DayOS found.",
                [("Add subject", lambda: self.add(None)), ("Paste a list", self.paste_list)]))

    def selected_id(self) -> int | None:
        item = self.tree.currentItem()
        return int(item.data(0, Qt.ItemDataRole.UserRole)) if item else None

    def add(self, parent_id: int | None, kind: str | None = None) -> None:
        parent = sf(self.ctx).courses.node(parent_id) if parent_id else None
        NodeDialog(self.ctx, self.page.course_id, self, parent_id=parent_id,
                   kind=kind or CHILD_KIND[parent.kind if parent else None]).exec()

    def add_child(self) -> None:
        self.add(self.selected_id())

    def edit(self) -> None:
        nid = self.selected_id()
        if nid:
            NodeDialog(self.ctx, self.page.course_id, self, sf(self.ctx).courses.node(nid)).exec()

    def move(self, delta: int) -> None:
        nid = self.selected_id()
        if nid and guarded(self, lambda: sf(self.ctx).courses.move_node(nid, delta)):
            bus.notify("studyforge")

    def delete(self) -> None:
        nid = self.selected_id()
        if not nid:
            return
        node = sf(self.ctx).courses.node(nid)
        inside = len(sf(self.ctx).courses.descendants([nid])) - 1
        if confirm(self, "Delete from the course map?",
                   f"“{node.title}”" + (f" and the {inside} item(s) inside it" if inside else "") +
                   " will be removed. Questions, flashcards and notes linked to them are kept (unlinked)."):
            if guarded(self, lambda: sf(self.ctx).courses.delete_node(nid)):
                bus.notify("studyforge")

    def paste_list(self) -> None:
        from src.modules.studyforge.syllabus import from_lines

        parent_id = self.selected_id()
        text, ok = QInputDialog.getMultiLineText(
            self, "Paste a list", "One chapter per line. Indent a line (or start it with '-') to make it a topic of "
                                  "the line above." + (" Items go inside the selected item." if parent_id else ""))
        if not ok or not text.strip():
            return
        nodes = [n.to_dict() for n in from_lines(text)]
        added = 0

        def run() -> None:
            nonlocal added
            added = sf(self.ctx).courses.import_map(self.page.course_id, nodes, parent_id)

        if guarded(self, run):
            bus.notify("studyforge")
            self.page.toast(f"Added {added} item(s)")

    def _menu(self, pos) -> None:
        nid = self.selected_id()
        if not nid:
            return
        menu = QMenu(self)
        menu.addAction("Practise this (quick quiz)…", lambda: self.page.create_test([nid], "quick"))
        menu.addAction("Add a question here…", lambda: self.page.new_question(nid))
        menu.addAction("Add a flashcard here…", lambda: self.page.new_card(nid))
        menu.addAction("Revise today", lambda: self._revise_today(nid))
        menu.addSeparator()
        menu.addAction("Add inside…", self.add_child)
        menu.addAction("Edit…", self.edit)
        menu.addAction("Delete…", self.delete)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _revise_today(self, nid: int) -> None:
        from src.services.dates import today

        if guarded(self, lambda: svc(self.ctx).reschedule(nid, today())):
            bus.notify("studyforge")
            self.page.toast("Added to today's revision")
