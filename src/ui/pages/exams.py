from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QSplitter,
    QStackedLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.models import CHAPTER_STATUS_LABELS, CHAPTER_STATUSES, Chapter, Exam, Mistake, MockTest
from src.services.dates import countdown_text, format_date, format_time, relative_day, today
from src.services.revision import OUTCOME_LABELS
from src.ui.bus import bus
from src.ui.dialogs import subject_items
from src.ui.pages.base import Page
from src.ui.subjects_dialog import SubjectsDialog
from src.ui.widgets.charts import LineChart
from src.ui.widgets.common import (
    DateEdit,
    ElidedLabel,
    EmptyState,
    FormDialog,
    IdCombo,
    OptionalTime,
    PageHeader,
    ThinProgress,
    button,
    chip,
    clear_layout,
    confirm,
    fit_list_items,
    guarded,
    label,
    min_width_floor,
    scroll_wrap,
    separator,
    tool_button,
)

STATUS_TONES = {"not_started": "", "learning": "blue", "needs_revision": "amber", "revised": "accent", "mastered": "accent"}


# -- dialogs -------------------------------------------------------------------------

class ExamDialog(FormDialog):
    def __init__(self, ctx, parent=None, exam: Exam | None = None) -> None:
        super().__init__("Edit exam" if exam else "New exam", parent, width=520)
        self.ctx = ctx
        self.exam = exam
        self.title_edit = QLineEdit(exam.title if exam else "")
        self.title_edit.setPlaceholderText("e.g. Chemistry midterm")
        self.add_row("Exam", self.title_edit)
        row = QHBoxLayout()
        self.subject = IdCombo("No subject")
        self.subject.set_items(subject_items(ctx))
        self.subject.set_current_id(exam.subject_id if exam else None)
        row.addWidget(self.subject, 1)
        row.addWidget(button("Manage…", "link", on_click=self._manage))
        self.add_row("Subject", row)
        self.day = DateEdit(exam.day if exam else today())
        self.add_row("Date", self.day)
        self.time = OptionalTime("At", exam.exam_time if exam else None, bool(ctx.settings.get("clock_24h")))
        self.add_row("Time", self.time)
        self.syllabus = QPlainTextEdit(exam.syllabus if exam else "")
        self.syllabus.setPlaceholderText("What's covered (optional)")
        self.syllabus.setFixedHeight(60)
        self.add_row("Syllabus", self.syllabus)
        if not exam:
            self.chapters = QPlainTextEdit()
            self.chapters.setPlaceholderText("One chapter or topic per line (optional)")
            self.chapters.setFixedHeight(90)
            self.add_row("Chapters", self.chapters)
        self.notes = QPlainTextEdit(exam.notes if exam else "")
        self.notes.setPlaceholderText("Format, allowed materials, room… (optional)")
        self.notes.setFixedHeight(56)
        self.add_row("Notes", self.notes)
        self.title_edit.setFocus()

    def _manage(self) -> None:
        SubjectsDialog(self.ctx, self).exec()
        self.subject.set_items(subject_items(self.ctx))

    def save(self) -> None:
        data = dict(title=self.title_edit.text(), subject_id=self.subject.current_id(), exam_date=self.day.value(),
                    exam_time=self.time.value(), syllabus=self.syllabus.toPlainText(), notes=self.notes.toPlainText())
        with self.ctx.db.transaction():
            if self.exam:
                self.ctx.exams.update_exam(self.exam.id, **data)
            else:
                exam_id = self.ctx.exams.create_exam(**data)
                self.ctx.exams.add_chapters(exam_id, self.chapters.toPlainText().splitlines())
        bus.notify("exams")


class ChaptersDialog(FormDialog):
    def __init__(self, ctx, exam: Exam, parent=None) -> None:
        super().__init__("Add chapters", parent, save_text="Add")
        self.ctx = ctx
        self.exam = exam
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("One chapter or topic per line")
        self.text.setMinimumHeight(160)
        self.add_row("Chapters", self.text)
        self.text.setFocus()

    def save(self) -> None:
        names = [n for n in self.text.toPlainText().splitlines() if n.strip()]
        if not names:
            from src.services.dates import ValidationError

            raise ValidationError("Type at least one chapter name.")
        self.ctx.exams.add_chapters(self.exam.id, names)
        bus.notify("exams")


class MistakeDialog(FormDialog):
    def __init__(self, ctx, parent=None, mistake: Mistake | None = None) -> None:
        super().__init__("Edit mistake" if mistake else "Add to mistake notebook", parent, width=520)
        self.ctx = ctx
        self.mistake = mistake
        self.question = QPlainTextEdit(mistake.question if mistake else "")
        self.question.setPlaceholderText("The question, or what went wrong")
        self.question.setFixedHeight(80)
        self.add_row("Mistake", self.question)
        self.correction = QPlainTextEdit(mistake.correction if mistake else "")
        self.correction.setPlaceholderText("The right approach, and how to avoid it next time")
        self.correction.setFixedHeight(80)
        self.add_row("Correction", self.correction)
        self.subject = IdCombo("No subject")
        self.subject.set_items(subject_items(ctx))
        self.subject.set_current_id(mistake.subject_id if mistake else None)
        self.add_row("Subject", self.subject)
        self.chapter = IdCombo("No chapter")
        self.chapter.set_items([(c.id, f"{c.name} — {c.exam_title}") for c in ctx.exams.all_chapters()])
        self.chapter.set_current_id(mistake.chapter_id if mistake else None)
        self.add_row("Chapter", self.chapter)
        self.question.setFocus()

    def save(self) -> None:
        args = (self.question.toPlainText(), self.correction.toPlainText(), self.subject.current_id(),
                self.chapter.current_id())
        if self.mistake:
            self.ctx.exams.update_mistake(self.mistake.id, *args)
        else:
            self.ctx.exams.add_mistake(*args)
        bus.notify("exams")


class TestDialog(FormDialog):
    def __init__(self, ctx, parent=None, test: MockTest | None = None) -> None:
        super().__init__("Edit test result" if test else "Add test result", parent)
        self.ctx = ctx
        self.test = test
        self.title_edit = QLineEdit(test.title if test else "")
        self.title_edit.setPlaceholderText("e.g. Mock paper 2")
        self.add_row("Test", self.title_edit)
        self.subject = IdCombo("No subject")
        self.subject.set_items(subject_items(ctx))
        self.subject.set_current_id(test.subject_id if test else None)
        self.add_row("Subject", self.subject)
        self.exam = IdCombo("Not linked to an exam")
        self.exam.set_items([(e.id, e.title) for e in ctx.exams.exams()])
        self.exam.set_current_id(test.exam_id if test else None)
        self.add_row("For exam", self.exam)
        self.day = DateEdit(date.fromisoformat(test.date) if test else today())
        self.day.setMaximumDate(self.day.date().currentDate())
        self.add_row("Date", self.day)
        row = QHBoxLayout()
        self.marks = QDoubleSpinBox()
        self.marks.setRange(0, 100000)
        self.marks.setDecimals(1)
        self.marks.setValue(test.marks if test else 0)
        self.max_marks = QDoubleSpinBox()
        self.max_marks.setRange(0, 100000)
        self.max_marks.setDecimals(1)
        self.max_marks.setValue(test.max_marks if test else 100)
        row.addWidget(self.marks, 1)
        row.addWidget(label("out of", "muted"))
        row.addWidget(self.max_marks, 1)
        self.add_row("Score", row)
        self.notes = QLineEdit(test.notes if test else "")
        self.notes.setPlaceholderText("What to work on next (optional)")
        self.add_row("Notes", self.notes)

    def save(self) -> None:
        data = dict(title=self.title_edit.text(), subject_id=self.subject.current_id(), exam_id=self.exam.current_id(),
                    date=self.day.value(), marks=self.marks.value(), max_marks=self.max_marks.value(),
                    notes=self.notes.text())
        if self.test:
            self.ctx.exams.update_test(self.test.id, **data)
        else:
            self.ctx.exams.add_test(**data)
        bus.notify("exams")


# -- page ---------------------------------------------------------------------------

class ExamsPage(Page):
    domains = ("exams", "subjects", "settings")
    title = "Exams"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.selected_id: int | None = None
        header = PageHeader("Exams & revision", "Countdowns, chapter progress, revision and results.", eyebrow="Prepare calmly")
        header.add_action(button("Subjects", "ghost", "subject", lambda: SubjectsDialog(self.ctx, self).exec()))
        header.add_action(button("New exam", "primary", "plus", self.new_item, "New exam (Ctrl+N)"))
        self.root.addWidget(header)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.root.addWidget(self.tabs, 1)

        # exams tab
        exams_tab = QWidget()
        el = QVBoxLayout(exams_tab)
        el.setContentsMargins(0, 12, 0, 0)
        self.show_past = QCheckBox("Show past exams")
        self.show_past.toggled.connect(lambda _: self.refresh())
        el.addWidget(self.show_past)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(14)
        split.setChildrenCollapsible(False)
        left = QFrame()
        left.setProperty("panel", True)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 10, 10, 10)
        self.exam_list = QListWidget()
        self.exam_list.setAccessibleName("Exams")
        self.exam_list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.exam_list)
        min_width_floor(left, 260)
        split.addWidget(left)
        right = QFrame()
        right.setProperty("panel", True)
        self.detail_stack = QStackedLayout(right)
        self.detail = QWidget()
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(22, 18, 22, 18)
        self.detail_layout.setSpacing(8)
        self.detail_stack.addWidget(scroll_wrap(self.detail))
        self.empty = QWidget()
        self.empty_layout = QVBoxLayout(self.empty)
        self.detail_stack.addWidget(self.empty)
        split.addWidget(right)
        split.setSizes([320, 700])
        split.setStretchFactor(1, 1)
        el.addWidget(split, 1)
        self.tabs.addTab(exams_tab, "Exams")

        # revision tab
        self.rev_widget = QWidget()
        self.rev_layout = QVBoxLayout(self.rev_widget)
        self.rev_layout.setContentsMargins(0, 12, 0, 0)
        self.rev_layout.setSpacing(8)
        self.tabs.addTab(scroll_wrap(self.rev_widget), "Revision queue")

        # mistakes tab
        mistakes_tab = QWidget()
        ml = QVBoxLayout(mistakes_tab)
        ml.setContentsMargins(0, 12, 0, 0)
        bar = QHBoxLayout()
        self.mistake_subject = IdCombo("All subjects")
        self.mistake_subject.currentIndexChanged.connect(lambda _: self._fill_mistakes())
        bar.addWidget(self.mistake_subject)
        self.show_resolved = QCheckBox("Show resolved")
        self.show_resolved.toggled.connect(lambda _: self._fill_mistakes())
        bar.addWidget(self.show_resolved)
        bar.addStretch(1)
        bar.addWidget(button("Add mistake", "", "plus", lambda: MistakeDialog(self.ctx, self).exec()))
        ml.addLayout(bar)
        self.mistake_widget = QWidget()
        self.mistake_layout = QVBoxLayout(self.mistake_widget)
        self.mistake_layout.setContentsMargins(0, 0, 0, 0)
        self.mistake_layout.setSpacing(10)
        ml.addWidget(scroll_wrap(self.mistake_widget), 1)
        self.tabs.addTab(mistakes_tab, "Mistake notebook")

        # tests tab
        tests_tab = QWidget()
        tl = QVBoxLayout(tests_tab)
        tl.setContentsMargins(0, 12, 0, 0)
        bar = QHBoxLayout()
        self.test_subject = IdCombo("All subjects")
        self.test_subject.currentIndexChanged.connect(lambda _: self._fill_tests())
        bar.addWidget(self.test_subject)
        bar.addStretch(1)
        bar.addWidget(button("Add result", "", "plus", lambda: TestDialog(self.ctx, self).exec()))
        tl.addLayout(bar)
        self.test_widget = QWidget()
        self.test_layout = QVBoxLayout(self.test_widget)
        self.test_layout.setContentsMargins(0, 0, 0, 0)
        self.test_layout.setSpacing(8)
        tl.addWidget(scroll_wrap(self.test_widget), 1)
        self.tabs.addTab(tests_tab, "Test results")
        self.tabs.currentChanged.connect(lambda _: self.refresh())

    def show_revision(self) -> None:
        self.tabs.setCurrentIndex(1)

    def open_exam(self, exam_id: int) -> None:
        self.tabs.setCurrentIndex(0)
        if not self.show_past.isChecked():
            exam = self.ctx.exams.get_exam(exam_id)
            if exam is not None and exam.day < today():
                self.show_past.setChecked(True)
        self.refresh()
        for i in range(self.exam_list.count()):
            item = self.exam_list.item(i)
            if int(item.data(Qt.ItemDataRole.UserRole)) == exam_id:
                self.exam_list.setCurrentItem(item)
                break
        self._show_exam(exam_id)

    def show_mistakes(self) -> None:
        self.tabs.setCurrentIndex(2)

    # -- refresh ------------------------------------------------------------------
    def refresh(self) -> None:
        subjects = subject_items(self.ctx)
        self.mistake_subject.set_items(subjects)
        self.test_subject.set_items(subjects)
        queue_n = len(self.ctx.exams.revision_queue())
        self.tabs.setTabText(1, f"Revision queue ({queue_n})" if queue_n else "Revision queue")
        index = self.tabs.currentIndex()
        if index == 0:
            self._fill_exams()
        elif index == 1:
            self._fill_revision()
        elif index == 2:
            self._fill_mistakes()
        else:
            self._fill_tests()

    def _fill_exams(self) -> None:
        exams = self.ctx.exams.exams(include_past=self.show_past.isChecked())
        self.exam_list.blockSignals(True)
        self.exam_list.clear()
        target = None
        ref = today()
        for exam in exams:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, exam.id)
            w = QWidget()
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay = QVBoxLayout(w)
            lay.setContentsMargins(8, 8, 8, 8)
            lay.setSpacing(3)
            top = QHBoxLayout()
            t = ElidedLabel(exam.title)
            t.setStyleSheet("font-weight: 600;")
            top.addWidget(t, 1)
            past = exam.day < ref
            top.addWidget(chip(countdown_text(exam.day, ref), "" if past else ("terracotta" if (exam.day - ref).days <= 7 else "blue")))
            lay.addLayout(top)
            meta = [format_date(exam.day, self.date_style, with_weekday=True)]
            if exam.subject_name:
                meta.insert(0, exam.subject_name)
            lay.addWidget(ElidedLabel(" · ".join(meta), "caption"))
            if exam.chapter_total:
                lay.addWidget(ThinProgress(exam.chapter_ready / exam.chapter_total, "accent", 4))
            item.setSizeHint(w.sizeHint())
            self.exam_list.addItem(item)
            self.exam_list.setItemWidget(item, w)
            if exam.id == self.selected_id:
                target = item
        self.exam_list.blockSignals(False)
        fit_list_items(self.exam_list)
        if target is None and self.exam_list.count():
            target = self.exam_list.item(0)
        if target is not None:
            self.exam_list.setCurrentItem(target)
            self._show_exam(int(target.data(Qt.ItemDataRole.UserRole)))
        else:
            clear_layout(self.empty_layout)
            self.empty_layout.addWidget(EmptyState(
                "exams", "No upcoming exams" if not self.show_past.isChecked() else "No exams yet",
                "Add an exam with its chapters. DayOS counts down the days, tracks each chapter and "
                "suggests what to revise.", [("New exam", self.new_item)]))
            self.detail_stack.setCurrentIndex(1)

    def _on_select(self, current, _prev) -> None:
        if current is not None:
            self._show_exam(int(current.data(Qt.ItemDataRole.UserRole)))

    def _show_exam(self, exam_id: int) -> None:
        exam = self.ctx.exams.get_exam(exam_id)
        if exam is None:
            return
        self.selected_id = exam_id
        lay = self.detail_layout
        clear_layout(lay)
        ref = today()
        top = QHBoxLayout()
        top.addWidget(label(exam.title, "title", wrap=True), 1)
        top.addWidget(button("Edit", "ghost", "edit", lambda: ExamDialog(self.ctx, self, exam).exec()))
        top.addWidget(button("Delete", "ghost", "trash", lambda: self._delete_exam(exam)))
        lay.addLayout(top)
        when = format_date(exam.day, self.date_style, with_weekday=True)
        if exam.exam_time:
            when += f" at {format_time(exam.exam_time, self.clock24)}"
        meta = [x for x in (exam.subject_name, when, countdown_text(exam.day, ref)) if x]
        lay.addWidget(label(" · ".join(meta), "subtitle", wrap=True))
        if exam.syllabus:
            lay.addWidget(label("Syllabus", "caption"))
            lay.addWidget(label(exam.syllabus, "", wrap=True, selectable=True))
        if exam.notes:
            lay.addWidget(label("Notes", "caption"))
            lay.addWidget(label(exam.notes, "muted", wrap=True, selectable=True))
        lay.addWidget(separator())
        chapters = self.ctx.exams.chapters(exam.id)
        head = QHBoxLayout()
        ready = sum(1 for c in chapters if c.status in ("revised", "mastered"))
        head.addWidget(label(f"Chapters · {ready} of {len(chapters)} revised" if chapters else "Chapters", "section"), 1)
        head.addWidget(button("Add chapters", "link", "plus", lambda: ChaptersDialog(self.ctx, exam, self).exec()))
        lay.addLayout(head)
        if chapters:
            lay.addWidget(ThinProgress(ready / len(chapters)))
        else:
            lay.addWidget(label("Add the chapters or topics this exam covers to track them one by one.", "muted", wrap=True))
        for chapter in chapters:
            lay.addWidget(self._chapter_row(chapter, ref))
        tests = [t for t in self.ctx.exams.tests() if t.exam_id == exam.id]
        if tests:
            lay.addWidget(separator())
            lay.addWidget(label("Test results for this exam", "section"))
            for t in tests[:10]:
                lay.addWidget(label(f"{format_date(date.fromisoformat(t.date), self.date_style)} · {t.title} · "
                                    f"{t.marks:g}/{t.max_marks:g} ({t.percent:.0f}%)", "muted"))
        lay.addStretch(1)
        self.detail_stack.setCurrentIndex(0)

    def _chapter_row(self, chapter: Chapter, ref: date, show_exam: bool = False) -> QWidget:
        w = QWidget()
        w.setObjectName("Row")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(w)
        row.setContentsMargins(8, 5, 6, 5)
        row.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(chapter.name, wrap=True))
        info = []
        if show_exam:
            info.append(" · ".join(x for x in (chapter.subject_name, chapter.exam_title) if x))
            if chapter.exam_date:
                info.append(f"exam {countdown_text(date.fromisoformat(chapter.exam_date), ref).lower()}")
        if chapter.last_reviewed:
            info.append(f"last revised {relative_day(date.fromisoformat(chapter.last_reviewed), ref).lower()}")
        if chapter.next_review:
            nr = date.fromisoformat(chapter.next_review)
            info.append(("review overdue since " if nr < ref else "next review ") + relative_day(nr, ref).lower()
                        if nr != ref else "review due today")
        if info:
            col.addWidget(label(" · ".join(i for i in info if i), "caption", wrap=True))
        row.addLayout(col, 1)
        status = QComboBox()
        for key in CHAPTER_STATUSES:
            status.addItem(CHAPTER_STATUS_LABELS[key], key)
        status.setCurrentIndex(CHAPTER_STATUSES.index(chapter.status))
        status.setAccessibleName(f"Status of {chapter.name}")
        status.currentIndexChanged.connect(lambda _i, c=chapter, s=status: self._set_status(c, s.currentData()))
        row.addWidget(status)
        rev = button("Log revision", "", "check", tooltip="Log a revision session and schedule the next review")
        menu = QMenu(rev)
        for outcome, text in OUTCOME_LABELS.items():
            hint = {"hard": "review tomorrow", "okay": "review in a few days", "easy": "review much later"}[outcome]
            menu.addAction(f"{text} — {hint}", lambda o=outcome, c=chapter: self._log_revision(c, o))
        rev.setMenu(menu)
        row.addWidget(rev)
        more = tool_button("more", f"More actions for {chapter.name}", size=16)
        more.clicked.connect(lambda: self._chapter_menu(chapter, more))
        row.addWidget(more)
        return w

    def _chapter_menu(self, chapter: Chapter, anchor: QWidget) -> None:
        menu = QMenu(self)
        menu.addAction("Add a mistake for this chapter…", lambda: self._add_mistake_for(chapter))
        menu.addAction("Clear scheduled review", lambda: self._clear_review(chapter))
        menu.addSeparator()
        menu.addAction("Delete chapter…", lambda: self._delete_chapter(chapter))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _add_mistake_for(self, chapter: Chapter) -> None:
        dlg = MistakeDialog(self.ctx, self)
        dlg.chapter.set_current_id(chapter.id)
        exam = self.ctx.exams.get_exam(chapter.exam_id)
        if exam:
            dlg.subject.set_current_id(exam.subject_id)
        dlg.exec()

    def _clear_review(self, chapter: Chapter) -> None:
        if guarded(self, lambda: self.ctx.exams.set_next_review(chapter.id, None)):
            bus.notify("exams")

    def _set_status(self, chapter: Chapter, status: str) -> None:
        if guarded(self, lambda: self.ctx.exams.set_chapter_status(chapter.id, status)):
            bus.notify("exams")

    def _log_revision(self, chapter: Chapter, outcome: str) -> None:
        result = None

        def run() -> None:
            nonlocal result
            result = self.ctx.exams.log_revision(chapter.id, outcome)

        if guarded(self, run, "Couldn't log the revision") and result is not None:
            bus.notify("exams")
            self.toast(f"Logged. Next review {relative_day(result.next_review).lower()} "
                       f"({format_date(result.next_review, self.date_style)}).")

    def _delete_chapter(self, chapter: Chapter) -> None:
        if confirm(self, "Delete chapter?", f"“{chapter.name}” and its revision history will be deleted. "
                                            "Mistakes linked to it are kept."):
            if guarded(self, lambda: self.ctx.exams.delete_chapter(chapter.id)):
                bus.notify("exams")

    def _delete_exam(self, exam: Exam) -> None:
        if confirm(self, "Delete exam?",
                   f"“{exam.title}”, its {exam.chapter_total} chapter(s) and their revision history will be deleted. "
                   "Test results and mistakes are kept."):
            if guarded(self, lambda: self.ctx.exams.delete_exam(exam.id)):
                self.selected_id = None
                bus.notify("exams", "schedule")
                self.toast("Exam deleted")

    # -- revision queue ---------------------------------------------------------------
    def _fill_revision(self) -> None:
        lay = self.rev_layout
        clear_layout(lay)
        lay.addWidget(label(
            "How this works: after revising a chapter, rate it Hard, Okay or Easy. Hard brings it back tomorrow; "
            "Okay doubles the gap (2–30 days); Easy triples it (4–60 days) and marks it mastered at 21+ days. "
            "Reviews are pulled before the exam date. It's a simple, predictable rule — not an AI prediction.",
            "caption", wrap=True))
        queue = self.ctx.exams.revision_queue()
        if not queue:
            lay.addWidget(EmptyState(
                "check", "Nothing to revise right now",
                "Chapters appear here when their review date arrives, or when they're marked Learning / "
                "Needs revision for an upcoming exam.", [("Go to exams", lambda: self.tabs.setCurrentIndex(0))]))
            lay.addStretch(1)
            return
        ref = today()
        for chapter in queue:
            lay.addWidget(self._chapter_row(chapter, ref, show_exam=True))
        lay.addStretch(1)

    # -- mistakes ---------------------------------------------------------------------
    def _fill_mistakes(self) -> None:
        lay = self.mistake_layout
        clear_layout(lay)
        mistakes = self.ctx.exams.mistakes(self.mistake_subject.current_id(), self.show_resolved.isChecked())
        if not mistakes:
            lay.addWidget(EmptyState(
                "mistake", "Your mistake notebook is empty",
                "Write down errors from homework and tests with the correct approach. Reviewing them is one of "
                "the quickest ways to improve.", [("Add mistake", lambda: MistakeDialog(self.ctx, self).exec())]))
            lay.addStretch(1)
            return
        for m in mistakes:
            card = QFrame()
            card.setProperty("card", True)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(4)
            head = QHBoxLayout()
            tags = [x for x in (m.subject_name, m.chapter_name) if x]
            for t in tags:
                head.addWidget(chip(t, "blue"))
            if m.resolved:
                head.addWidget(chip("Resolved", "accent"))
            head.addStretch(1)
            head.addWidget(label(m.created_at[:10], "caption"))
            resolve = tool_button("check", "Mark unresolved" if m.resolved else "Mark resolved",
                                  lambda m=m: self._resolve(m), 16)
            head.addWidget(resolve)
            head.addWidget(tool_button("edit", "Edit", lambda m=m: MistakeDialog(self.ctx, self, m).exec(), 16))
            head.addWidget(tool_button("trash", "Delete", lambda m=m: self._delete_mistake(m), 16))
            cl.addLayout(head)
            cl.addWidget(label(m.question, "", wrap=True, selectable=True))
            if m.correction:
                cl.addWidget(label("Correction", "caption"))
                cl.addWidget(label(m.correction, "muted", wrap=True, selectable=True))
            lay.addWidget(card)
        lay.addStretch(1)

    def _resolve(self, m: Mistake) -> None:
        if guarded(self, lambda: self.ctx.exams.set_mistake_resolved(m.id, not m.resolved)):
            bus.notify("exams")

    def _delete_mistake(self, m: Mistake) -> None:
        if confirm(self, "Delete mistake?", "This entry will be removed from your notebook."):
            if guarded(self, lambda: self.ctx.exams.delete_mistake(m.id)):
                bus.notify("exams")

    # -- tests --------------------------------------------------------------------------
    def _fill_tests(self) -> None:
        lay = self.test_layout
        clear_layout(lay)
        tests = self.ctx.exams.tests(subject_id=self.test_subject.current_id())
        if not tests:
            lay.addWidget(EmptyState(
                "chart", "No test results yet",
                "Record mock tests and quizzes to see how your scores move over time.",
                [("Add result", lambda: TestDialog(self.ctx, self).exec())]))
            lay.addStretch(1)
            return
        chronological = list(reversed(tests))
        chart_card = QFrame()
        chart_card.setProperty("card", True)
        cc = QVBoxLayout(chart_card)
        cc.setContentsMargins(16, 12, 16, 12)
        avg = sum(t.percent for t in tests) / len(tests)
        cc.addWidget(label(f"Scores over time · average {avg:.0f}% across {len(tests)} test(s)", "section"))
        chart = LineChart("blue")
        chart.set_points([(f"{date.fromisoformat(t.date).day}/{date.fromisoformat(t.date).month}", t.percent,
                           f"{t.title}: {t.marks:g}/{t.max_marks:g} ({t.percent:.1f}%)") for t in chronological[-30:]])
        cc.addWidget(chart)
        lay.addWidget(chart_card)
        for t in tests:
            w = QWidget()
            w.setObjectName("Row")
            w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row = QHBoxLayout(w)
            row.setContentsMargins(8, 6, 6, 6)
            row.addWidget(label(format_date(date.fromisoformat(t.date), self.date_style), "muted"))
            row.addWidget(label(t.title), 1)
            if t.subject_name:
                row.addWidget(chip(t.subject_name, "blue"))
            row.addWidget(label(f"{t.marks:g} / {t.max_marks:g}"))
            row.addWidget(label(f"{t.percent:.0f}%", "section"))
            row.addWidget(tool_button("edit", "Edit result", lambda t=t: TestDialog(self.ctx, self, t).exec(), 16))
            row.addWidget(tool_button("trash", "Delete result", lambda t=t: self._delete_test(t), 16))
            lay.addWidget(w)
            if t.notes:
                lay.addWidget(label("    " + t.notes, "caption", wrap=True))
        lay.addStretch(1)

    def _delete_test(self, t: MockTest) -> None:
        if confirm(self, "Delete test result?", f"“{t.title}” ({t.marks:g}/{t.max_marks:g}) will be deleted."):
            if guarded(self, lambda: self.ctx.exams.delete_test(t.id)):
                bus.notify("exams")

    def new_item(self) -> None:
        dlg = ExamDialog(self.ctx, self)
        if dlg.exec():
            self.tabs.setCurrentIndex(0)
