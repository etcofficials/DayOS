"""StudyForge page: courses, map, question bank, tests, revision, mistakes, cards & notes, analytics, documents."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from src.modules.studyforge import srs
from src.modules.studyforge.models import DOC_KINDS
from src.modules.studyforge.repository import COURSE_KINDS
from src.modules.studyforge.ui.analytics import AnalyticsTab
from src.modules.studyforge.ui.bank import BankTab, QuestionDialog
from src.modules.studyforge.ui.common import MASTERY_TONES, sf, svc
from src.modules.studyforge.ui.coursemap import CourseMapTab
from src.modules.studyforge.ui.materials import CardDialog, MaterialsTab
from src.modules.studyforge.ui.mistakes import MistakesTab
from src.modules.studyforge.ui.revision import RevisionTab
from src.modules.studyforge.ui.tests_tab import CreateTestDialog, TestsTab
from src.services.dates import countdown_text, format_date, today
from src.ui.bus import bus
from src.ui.pages.base import Page
from src.ui.widgets.common import (
    Card,
    EmptyState,
    FormDialog,
    PageHeader,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    tool_button,
)


class CourseDialog(FormDialog):
    def __init__(self, page, course=None) -> None:
        super().__init__("Edit course" if course else "New course", page)
        self.page = page
        self.course = course
        self.name = QLineEdit(course.name if course else "")
        self.name.setPlaceholderText("e.g. Class 10, First-year Chemistry, Python fundamentals")
        self.add_row("Name", self.name)
        self.kind = QComboBox()
        for k, t in COURSE_KINDS.items():
            self.kind.addItem(t, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(course.kind if course else "custom")))
        self.add_row("Type", self.kind)
        self.session = QLineEdit(course.session if course else "")
        self.session.setPlaceholderText("Academic session or term (optional)")
        self.add_row("Session", self.session)
        self.authority = QLineEdit(course.authority if course else "")
        self.authority.setPlaceholderText("Board, university or exam body (optional)")
        self.add_row("Authority", self.authority)
        self.level = QLineEdit(course.level if course else "")
        self.level.setPlaceholderText("e.g. Class 10, Year 1, Beginner (optional)")
        self.add_row("Level", self.level)
        self.name.setFocus()
        self.saved_id = course.id if course else None

    def save(self) -> None:
        repo = sf(self.page.ctx).courses
        data = dict(name=self.name.text(), kind=self.kind.currentData(), session=self.session.text(),
                    authority=self.authority.text(), level=self.level.text())
        if self.course:
            repo.update(self.course.id, **data)
        else:
            self.saved_id = repo.create(**data)
        bus.notify("studyforge")


class StudyForgePage(Page):
    domains = ("studyforge", "settings", "subjects", "exams")
    title = "StudyForge"

    TABS = ["Overview", "Course map", "Question bank", "Tests", "Revision", "Mistakes", "Cards & notes", "Analytics",
            "Documents"]

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.course_id: int | None = None
        self.header = PageHeader("StudyForge", "", eyebrow="Learn, practise, remember")
        self.course_combo = QComboBox()
        self.course_combo.setMinimumWidth(240)
        self.course_combo.setAccessibleName("Course")
        self.course_combo.currentIndexChanged.connect(self._course_changed)
        self.header.add_action(self.course_combo)
        self.header.add_action(tool_button("edit", "Edit course", self.edit_course))
        self.header.add_action(button("New course", "ghost", "plus", self.new_course))
        self.header.add_action(button("Import…", "", "upload", self.import_document, "Import a syllabus or sample paper"))
        self.header.add_action(button("Create test", "primary", "exams", lambda: self.create_test()))
        self.root.addWidget(self.header)
        self.empty_holder = QWidget()
        self.empty_lay = QVBoxLayout(self.empty_holder)
        self.root.addWidget(self.empty_holder, 1)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.overview = QWidget()
        self.ov = QVBoxLayout(self.overview)
        self.ov.setContentsMargins(0, 12, 6, 0)
        self.tab_widgets = [scroll_wrap(self.overview), CourseMapTab(self), BankTab(self), TestsTab(self),
                            RevisionTab(self), MistakesTab(self), MaterialsTab(self), AnalyticsTab(self),
                            self._documents_tab()]
        for title, w in zip(self.TABS, self.tab_widgets):
            self.tabs.addTab(w, title)
        self.tabs.currentChanged.connect(lambda _i: self._refresh_tab())
        self.root.addWidget(self.tabs, 1)

    # -- courses ---------------------------------------------------------------------
    def refresh(self) -> None:
        courses = sf(self.ctx).courses.list()
        current = self.course_id
        self.course_combo.blockSignals(True)
        self.course_combo.clear()
        for c in courses:
            self.course_combo.addItem(c.name, c.id)
        if courses:
            index = self.course_combo.findData(current) if current else 0
            self.course_combo.setCurrentIndex(max(0, index))
            self.course_id = self.course_combo.currentData()
        else:
            self.course_id = None
        self.course_combo.blockSignals(False)
        has = bool(courses)
        self.tabs.setVisible(has)
        self.course_combo.setVisible(has)
        self.empty_holder.setVisible(not has)
        clear_layout(self.empty_lay)
        if not has:
            self.header.set_subtitle("Courses, practice tests and revision that adapt to your results.")
            self.empty_lay.addWidget(EmptyState(
                "book", "Start with a course",
                "Create a course for anything you're learning, import an official syllabus to build its chapters, or "
                "use the CBSE Class 10 starter. Then add questions, take practice tests, and revise what needs it.",
                [("Set up CBSE Class 10", self.cbse_setup), ("Create a course", self.new_course),
                 ("Import a syllabus", self.import_document)]))
            return
        course = sf(self.ctx).courses.get(self.course_id)
        bits = [COURSE_KINDS.get(course.kind, "")] + [x for x in (course.level, course.session, course.authority) if x]
        self.header.set_subtitle(" · ".join(b for b in bits if b))
        self._refresh_tab()

    def _course_changed(self) -> None:
        self.course_id = self.course_combo.currentData()
        self.refresh()

    def select_course(self, course_id: int) -> None:
        self.course_id = course_id
        self.refresh()

    def _refresh_tab(self) -> None:
        if self.course_id is None:
            return
        i = self.tabs.currentIndex()
        if i == 0:
            self._fill_overview()
        elif i == 8:
            self._fill_documents()
        else:
            self.tab_widgets[i].refresh()

    def new_course(self) -> None:
        dlg = CourseDialog(self)
        if dlg.exec() and dlg.saved_id:
            self.select_course(dlg.saved_id)
            self.tabs.setCurrentIndex(1)

    def edit_course(self) -> None:
        course = sf(self.ctx).courses.get(self.course_id) if self.course_id else None
        if course:
            dlg = CourseDialog(self, course)
            dlg.left_buttons.addWidget(button("Archive", "ghost", on_click=lambda: (dlg.reject(), self._archive(course))))
            dlg.left_buttons.addWidget(button("Delete…", "danger", on_click=lambda: (dlg.reject(), self._delete(course))))
            dlg.exec()

    def _archive(self, course) -> None:
        if guarded(self, lambda: sf(self.ctx).courses.update(course.id, status="archived")):
            self.course_id = None
            bus.notify("studyforge")
            self.toast("Course archived — its data is kept")

    def _delete(self, course) -> None:
        n_q = len(sf(self.ctx).bank.list(course.id))
        if confirm(self, "Delete course?", f"“{course.name}”, its course map, {n_q} question(s), tests, results, "
                                          "flashcards and notes will be permanently deleted. Archive it instead to keep "
                                          "everything."):
            if guarded(self, lambda: sf(self.ctx).courses.delete(course.id)):
                self.course_id = None
                bus.notify("studyforge")

    def cbse_setup(self) -> None:
        from src.modules.studyforge.ui.importer import CbseSetupDialog

        dlg = CbseSetupDialog(self)
        if dlg.exec():
            self.select_course(dlg.course_id)
            self.tabs.setCurrentIndex(1)
            self.toast("Course created. Check the chapter lists against your official syllabus.")

    def import_document(self) -> None:
        from src.modules.studyforge.ui.importer import ImportWizard

        ImportWizard(self).exec()

    # -- actions used by the tabs ---------------------------------------------------------
    def create_test(self, nodes: list[int] | None = None, preset: str = "quick") -> None:
        if self.course_id is None:
            self.toast("Create a course first")
            return
        dlg = CreateTestDialog(self, nodes, preset)
        if dlg.exec() and dlg.test_id:
            if confirm(self, "Test ready", "Start it now?", "Start now", danger=False):
                self.take_test(dlg.test_id)
            else:
                self.tabs.setCurrentIndex(3)

    def take_test(self, test_id: int) -> None:
        from src.modules.studyforge.ui.take import TakeTestDialog

        TakeTestDialog(self, test_id).exec()

    def show_attempt(self, attempt_id: int, summary=None) -> None:
        from src.modules.studyforge.ui.take import ResultsDialog

        ResultsDialog(self, attempt_id, summary).exec()

    def show_results(self, test_id: int) -> None:
        attempts = [a for a in sf(self.ctx).tests.attempts(None) if a.test_id == test_id]
        if attempts:
            self.show_attempt(attempts[0].id)

    def new_question(self, node_id: int | None = None) -> None:
        QuestionDialog(self.ctx, self.course_id, self, default_node=node_id).exec()

    def new_card(self, node_id: int | None = None) -> None:
        CardDialog(self, node_id=node_id).exec()

    def ai_feedback(self, attempt_id, item, dialog) -> None:
        hook = self.ctx.services.get("studyforge.ai_feedback")
        if hook is not None:
            hook(self, attempt_id, item, dialog)

    def new_item(self) -> None:
        self.create_test()

    # -- overview ---------------------------------------------------------------------------
    def _fill_overview(self) -> None:
        clear_layout(self.ov)
        cid = self.course_id
        grid = QGridLayout()
        grid.setSpacing(14)
        queue = svc(self.ctx).queue(cid, limit=6)
        rev = Card("Revise today", "book")
        if queue:
            for q in queue[:5]:
                r = QHBoxLayout()
                col = QVBoxLayout()
                col.addWidget(label(q.node.title, "heading", wrap=True))
                col.addWidget(label("; ".join(q.reasons[:2]), "caption", wrap=True))
                r.addLayout(col, 1)
                r.addWidget(chip(srs.MASTERY_LABELS[q.mastery], MASTERY_TONES[q.mastery]))
                rev.body.addLayout(r)
            rev.body.addWidget(button("Open revision", "soft", "chev-right", lambda: self.tabs.setCurrentIndex(4)))
        else:
            rev.body.addWidget(label("Nothing due. Practise anything to start building your revision schedule.",
                                     "muted", wrap=True))
        grid.addWidget(rev, 0, 0)
        exams = Card("Exam dates", "calendar")
        dated = [n for n in sf(self.ctx).courses.nodes(cid) if n.exam_date]
        dated.sort(key=lambda n: n.exam_date)
        for n in dated[:6]:
            r = QHBoxLayout()
            r.addWidget(label(n.title), 1)
            r.addWidget(label(f"{format_date(n.exam_day, self.date_style)} · {countdown_text(n.exam_day)}", "caption"))
            exams.body.addLayout(r)
        if not dated:
            exams.body.addWidget(label("Set exam dates on subjects (Course map → Edit) so revision speeds up before "
                                       "each exam.", "muted", wrap=True))
        grid.addWidget(exams, 0, 1)
        overview = svc(self.ctx).topic_overview(cid)
        topics = sf(self.ctx).courses.topic_nodes(cid)
        progress = Card("Progress (estimates)", "chart")
        counts = {"new": 0, "learning": 0, "developing": 0, "strong": 0}
        for t in topics:
            counts[overview.get(t.id, {}).get("mastery", "new")] += 1
        if topics:
            for key, n in counts.items():
                r = QHBoxLayout()
                r.addWidget(label(srs.MASTERY_LABELS[key]), 1)
                r.addWidget(label(f"{n} of {len(topics)}", "muted"))
                progress.body.addLayout(r)
            progress.body.addWidget(label("Based only on your marked practice and recall checks.", "caption", wrap=True))
        else:
            progress.body.addWidget(label("Add chapters or topics to the course map first.", "muted", wrap=True))
        grid.addWidget(progress, 1, 0)
        tests = Card("Recent results", "exams")
        attempts = sf(self.ctx).tests.attempts(cid, limit=5)
        for a in attempts:
            pct = f"{round(100 * (a.score or 0) / a.max_score)}%" if a.max_score else "–"
            r = QHBoxLayout()
            r.addWidget(label(a.test_title or "Test", "", wrap=True), 1)
            r.addWidget(label(pct + ("" if a.status == "marked" else " (unmarked answers)"), "muted"))
            r.addWidget(button("View", "link", on_click=lambda aid=a.id: self.show_attempt(aid)))
            tests.body.addLayout(r)
        if not attempts:
            tests.body.addWidget(label("No tests taken yet.", "muted"))
        tests.body.addWidget(button("Create a test", "soft", "plus", lambda: self.create_test()))
        grid.addWidget(tests, 1, 1)
        bank = Card("Question bank", "grid")
        qs = sf(self.ctx).bank.list(cid)
        by_origin: dict[str, int] = {}
        for q in qs:
            by_origin[q.origin] = by_origin.get(q.origin, 0) + 1
        bank.body.addWidget(label(f"{len(qs)} question(s)", "metric"))
        from src.modules.studyforge.models import ORIGINS

        for k, n in by_origin.items():
            bank.body.addWidget(label(f"{ORIGINS[k]}: {n}", "caption"))
        unverified = sum(1 for q in qs if q.origin in ("ai", "imported") and not q.verified)
        if unverified:
            bank.body.addWidget(label(f"{unverified} still need checking", "warning"))
        grid.addWidget(bank, 2, 0)
        cards = Card("Flashcards", "book")
        due = sf(self.ctx).revision.cards(cid, due_only=True)
        total = sf(self.ctx).revision.cards(cid)
        cards.body.addWidget(label(f"{len(due)} due · {len(total)} total", "muted"))
        if due:
            cards.body.addWidget(button("Review now", "soft", "play", lambda: self.tab_widgets[4].review_cards()))
        grid.addWidget(cards, 2, 1)
        for c in range(2):
            grid.setColumnStretch(c, 1)
        self.ov.addLayout(grid)
        self.ov.addStretch(1)

    # -- documents ---------------------------------------------------------------------------
    def _documents_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        row = QHBoxLayout()
        row.addWidget(label("Documents you imported for this course. The extracted text stays in your DayOS data so "
                            "questions keep their page references.", "muted", wrap=True), 1)
        row.addWidget(button("Import…", "primary", "upload", self.import_document))
        lay.addLayout(row)
        self.docs_holder = QWidget()
        self.docs = QVBoxLayout(self.docs_holder)
        self.docs.setContentsMargins(0, 0, 6, 0)
        lay.addWidget(scroll_wrap(self.docs_holder), 1)
        w.refresh = self._fill_documents  # type: ignore[attr-defined]
        return w

    def _fill_documents(self) -> None:
        clear_layout(self.docs)
        docs = sf(self.ctx).courses.documents(self.course_id)
        if not docs:
            self.docs.addWidget(EmptyState("folder", "No documents yet",
                                           "Import an official syllabus to build the course map, or a sample paper to "
                                           "add its questions and structure.", compact=True))
        for d in docs:
            frame = QFrame()
            frame.setProperty("card", True)
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(16, 10, 12, 10)
            top = QHBoxLayout()
            top.addWidget(label(d.title, "heading"), 1)
            top.addWidget(chip(DOC_KINDS.get(d.kind, d.kind), "blue"))
            if d.official:
                top.addWidget(chip("Official", "accent"))
            top.addWidget(chip({"parsed": "Read fully", "partial": "Partly readable", "unreadable": "Unreadable"}[d.status],
                               {"parsed": "", "partial": "amber", "unreadable": "danger"}[d.status]))
            top.addWidget(tool_button("trash", "Remove document", lambda did=d.id: self._delete_doc(did), 16))
            lay.addLayout(top)
            meta = [f"{d.pages} page(s)", d.filename] + [x for x in (d.authority, d.session, d.syllabus_version) if x]
            lay.addWidget(label(" · ".join(m for m in meta if m) + f" · imported {d.imported_at[:10]}", "caption",
                                wrap=True))
            for p in d.problem_list:
                lay.addWidget(label(p, "warning", wrap=True))
            self.docs.addWidget(frame)
        self.docs.addStretch(1)

    def _delete_doc(self, doc_id: int) -> None:
        if confirm(self, "Remove document?", "The stored text is removed. Questions and course-map items imported from "
                                            "it are kept (they lose their link to the document)."):
            if guarded(self, lambda: sf(self.ctx).courses.delete_document(doc_id)):
                bus.notify("studyforge")
