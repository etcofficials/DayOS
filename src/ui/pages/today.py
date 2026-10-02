"""Today: the botanical dashboard — intention, a gentle plan, your day, study nook,
small rituals and what's coming up. Everything shown comes from the database."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from src.services.dates import (
    MONTH_NAMES,
    WEEKDAY_NAMES,
    countdown_text,
    format_date,
    format_duration,
    format_time,
    greeting,
    now,
    today,
    week_start,
)
from src.services.quickadd import parse_quick_task
from src.services.timer import FOCUS, LONG_BREAK, SHORT_BREAK
from src.ui import anim
from src.ui.bus import bus
from src.ui.dialogs import DailyReviewDialog, ManualStudyDialog, QuickNoteDialog, TaskDialog, subject_items
from src.ui.icons import bind_icon, pixmap
from src.ui.pages.base import Page
from src.ui.task_actions import TaskActions
from src.ui.theme import KIND_COLORS, serif, theme
from src.ui.widgets.art import Art
from src.ui.widgets.charts import ProgressRing
from src.modules.profiles import get_profile
from src.ui.widgets.dashboard import DashboardColumns
from src.ui.widgets.common import (
    AnimatedButton,
    FlowLayout,
    Card,
    EmptyState,
    IdCombo,
    RoundCheck,
    SegmentBar,
    ThinProgress,
    button,
    chip,
    clear_layout,
    guarded,
    label,
    scroll_wrap,
    separator,
    tool_button,
)

KIND_TONES = {"event": "blue", "class": "accent", "exam": "terracotta", "deadline": "amber", "task": ""}
KIND_NAMES = {"event": "Event", "class": "Class", "exam": "Exam", "deadline": "Deadline", "task": "Task"}

# Original gentle headlines, one per day (cycled deterministically by date).
HEADLINES = [
    "Make room for what matters.",
    "One gentle step at a time.",
    "Begin where you are.",
    "Let today be simple.",
    "Small steps still move you forward.",
    "Tend to what matters most.",
    "Slow and steady is still steady.",
]


def eyebrow_date(d: date, style: str) -> str:
    weekday = WEEKDAY_NAMES[d.weekday()]
    month = MONTH_NAMES[d.month - 1]
    if style == "mdy":
        return f"{weekday}, {month} {d.day}"
    if style == "iso":
        return f"{weekday}, {d.isoformat()}"
    return f"{weekday}, {d.day} {month}"


def short_countdown(when: date, ref: date) -> str:
    days = (when - ref).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return f"in {days} days" if days > 0 else f"{-days} days ago"


def round_button(icon_name: str, tooltip: str, on_click, text: str = "") -> AnimatedButton:
    btn = button(text, "", icon_name if not text else None, on_click, tooltip)
    btn.setFixedSize(44, 44)
    if text:
        btn.setProperty("serifSize", 15)
    btn.setProperty("round", True)
    return btn


class QuoteMark(QWidget):
    """A small, slightly tilted handwritten-style line of text."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(150, 96)
        theme.changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(18, 30)
        p.rotate(-10)
        font = serif(12.5)
        font.setItalic(True)
        p.setFont(font)
        p.setPen(theme.color("text2"))
        y = 0
        for line in self.text.split("\n"):
            p.drawText(QPointF(0, y), line)
            y += 19
        p.setPen(QPen(theme.color("text3"), 1))
        p.drawLine(QPointF(44, y), QPointF(96, y - 6))
        p.end()


class TodayHeader(QWidget):
    """Date, headline and greeting, with a window-and-plants vignette on the right."""

    def __init__(self, page: "TodayPage") -> None:
        super().__init__()
        self.page = page
        self.setMinimumHeight(170)
        self.art = Art("window", 360, 190, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.art.setParent(self)
        self.quote = QuoteMark("Good things take\ntime.")
        self.quote.setParent(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 6)
        lay.setSpacing(4)
        self.eyebrow = label("", "eyebrow")
        self.headline = label("", "display", wrap=True)
        self.greeting = label("", "subtitle", wrap=True)
        lay.addWidget(self.eyebrow)
        lay.addWidget(self.headline)
        lay.addWidget(self.greeting)
        lay.addStretch(1)
        self.buttons = QWidget(self)
        row = QHBoxLayout(self.buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.theme_btn = round_button("sun", "Theme", lambda: page.theme_menu(self.theme_btn))
        self.avatar = round_button("", "Your settings", lambda: page.main.navigate("settings"), text="·")
        row.addWidget(self.theme_btn)
        row.addWidget(self.avatar)
        self.buttons.adjustSize()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        w = self.width()
        wide = w > 900
        self.art.setVisible(wide)
        self.quote.setVisible(w > 1180)
        art_w = min(380, int(w * 0.34))
        self.buttons.adjustSize()
        self.buttons.move(w - self.buttons.width(), 0)
        # The vignette sits left of the quote (wide) or of the round buttons, never underneath them.
        clear = 0 if w > 1180 else self.buttons.width() + 16
        self.art.setGeometry(w - art_w - (150 if w > 1180 else clear), -26, art_w, self.height() + 26)
        self.art.lower()
        self.quote.move(w - 150, 44)
        self.layout().setContentsMargins(0, 4, (art_w + 60 + clear) if wide else self.buttons.width() + 16, 6)


class IntentionBanner(QFrame):
    """Soft sage banner holding today's intention; editable in place."""

    def __init__(self, page: "TodayPage") -> None:
        super().__init__()
        self.page = page
        self.setObjectName("Banner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 14, 10)
        lay.setSpacing(14)
        sprig = Art("sprig", 40, 40, Qt.AlignmentFlag.AlignCenter)
        sprig.setFixedSize(40, 40)
        lay.addWidget(sprig)
        self.stack = QStackedLayout()
        self.text = label("", "intention", wrap=True)
        self.text.setAccessibleName("Today's intention")
        holder = QWidget()
        holder.setLayout(self.stack)
        self.stack.addWidget(self.text)
        self.edit = QLineEdit()
        self.edit.setProperty("intention", True)
        self.edit.setMaxLength(300)
        self.edit.setPlaceholderText("Today, I want to focus on…")
        self.edit.setAccessibleName("Edit today's intention")
        self.edit.returnPressed.connect(self.finish)
        self.edit.editingFinished.connect(self.finish)
        self.stack.addWidget(self.edit)
        lay.addWidget(holder, 1)
        self.edit_btn = button("Edit", "ghost", "edit", self.start_edit, "Edit today's intention")
        lay.addWidget(self.edit_btn)
        self.value = ""

    def set_value(self, text: str) -> None:
        self.value = text
        if self.stack.currentWidget() is self.edit and self.edit.hasFocus():
            return
        self.text.setText(text if text else "Today, I want to focus on… (set a gentle intention for the day)")
        self.text.setProperty("role", "intention" if text else "muted")
        self.text.style().unpolish(self.text)
        self.text.style().polish(self.text)
        self.edit_btn.setText("Edit" if text else "Set intention")
        self.edit_btn.updateGeometry()

    def start_edit(self) -> None:
        self.edit.setText(self.value)
        self.stack.setCurrentWidget(self.edit)
        anim.fade_in(self.edit, anim.FAST)
        self.edit.setFocus()
        self.edit.selectAll()

    def finish(self) -> None:
        if self.stack.currentWidget() is not self.edit:
            return
        text = self.edit.text().strip()
        self.stack.setCurrentWidget(self.text)
        if text != self.value:
            self.page.save_intention(text)
        self.set_value(text)


class PlanRow(QWidget):
    """A task line in 'A gentle plan'."""

    def __init__(self, page: "TodayPage", task, day: date, overdue: bool) -> None:
        super().__init__()
        self.setObjectName("Row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.task = task
        self.page = page
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 8, 2, 8)
        lay.setSpacing(12)
        check = RoundCheck(task.done, 22, f"Complete task: {task.title}")
        check.toggled.connect(lambda on: page.actions.toggle(task.id, on))
        lay.addWidget(check)
        title = QLabel(task.title)
        title.setWordWrap(True)
        title.setProperty("role", "rowtitle")
        if task.done:
            title.setProperty("strike", "true")
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        lay.addWidget(title, 1)
        if overdue:
            lay.addWidget(chip("Overdue", "danger"))
        if task.subject_name:
            lay.addWidget(chip(task.subject_name, "blue"))
        elif task.category:
            lay.addWidget(chip(task.category, "terracotta"))
        if task.priority == 2 and not task.done:
            lay.addWidget(chip("High", "amber"))
        if task.due_time:
            when = QLabel()
            when.setPixmap(pixmap("calendar", theme.tokens["text3"], 16))
            lay.addWidget(when)
            lay.addWidget(label(format_time(task.due_time, page.clock24), "muted"))
        elif overdue and task.due:
            lay.addWidget(label(format_date(task.due, page.date_style), "caption"))
        more = tool_button("more", f"More for {task.title}", size=16)
        more.clicked.connect(lambda: page.task_menu(task, more))
        lay.addWidget(more)
        self.setToolTip(task.description[:300] if task.description else "")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.page.actions.edit(self.task.id)


class TimelineRow(QWidget):
    """One entry of 'Your day': a dot on a vertical line, the time, title and a chip."""

    def __init__(self, item, clock24: bool, first: bool, last: bool, past: bool) -> None:
        super().__init__()
        self.kind, self.first, self.last, self.past = item.kind, first, last, past
        lay = QHBoxLayout(self)
        lay.setContentsMargins(34, 6, 0, 10)
        lay.setSpacing(14)
        if item.start_time:
            when = format_time(item.start_time, clock24)
        else:
            when = "All day"
        t = label(when, "muted" if not past else "caption")
        t.setFixedWidth(84 if clock24 else 96)
        t.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        lay.addWidget(t, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(item.title)
        title.setWordWrap(True)
        title.setProperty("role", "rowtitle")
        if past:
            title.setProperty("past", "true")
        col.addWidget(title)
        detail = item.detail
        if item.end_time:
            detail = (f"until {format_time(item.end_time, clock24)}" + (f" · {detail}" if detail else ""))
        if detail:
            col.addWidget(label(detail, "muted", wrap=True))
        lay.addLayout(col, 1)
        lay.addWidget(chip(KIND_NAMES[item.kind], KIND_TONES[item.kind]), 0, Qt.AlignmentFlag.AlignTop)
        self.setAccessibleName(f"{when}: {item.title}, {KIND_NAMES[item.kind]}" + (" (finished)" if past else ""))
        theme.changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y = 11.0, 17.0
        line = theme.color("divider")
        p.setPen(QPen(line, 1.6))
        p.drawLine(QPointF(x, 0 if not self.first else y), QPointF(x, self.height() if not self.last else y))
        color = theme.color(KIND_COLORS.get(self.kind, "accent"))
        p.setPen(QPen(theme.color("surface"), 3))
        p.setBrush(color if not self.past else theme.color("surface"))
        if self.past:
            p.setPen(QPen(color, 1.6))
        p.drawEllipse(QPointF(x, y), 6, 6)
        p.end()


class StudyNook(Card):
    """The dashboard's view of the one real focus timer (owned by the Study page)."""

    def __init__(self, page: "TodayPage") -> None:
        super().__init__("Study nook", "clock")
        self.page = page
        self.add_action(button("History", "link", "chev-right", lambda: page.main.navigate("study")))
        self.set_art(Art("corner", 130, 110, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, 0.85),
                     Qt.Corner.BottomLeftCorner)
        row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        row.setSpacing(18)
        self.row = row
        ring_box = QWidget()
        ring_box.setFixedSize(178, 178)
        grid = QGridLayout(ring_box)
        grid.setContentsMargins(0, 0, 0, 0)
        self.ring = ProgressRing(170, thickness=7)
        grid.addWidget(self.ring, 0, 0)
        center = QVBoxLayout()
        center.setSpacing(0)
        center.addStretch(1)
        self.time = QLabel("25:00")
        self.time.setProperty("role", "nooktime")
        self.time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time.setAccessibleName("Focus time remaining")
        self.state = label("Focus time", "caption")
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.addWidget(self.time)
        center.addWidget(self.state)
        center.addStretch(1)
        overlay = QWidget()
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setLayout(center)
        grid.addWidget(overlay, 0, 0)
        row.addWidget(ring_box, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        side = QVBoxLayout()
        side.setSpacing(6)
        side.addWidget(label("Subject", "muted"))
        self.subject = IdCombo("No subject")
        self.subject.setAccessibleName("Study subject")
        self.subject.currentIndexChanged.connect(lambda _: page.study().choose_subject(self.subject.current_id()))
        side.addWidget(self.subject)
        side.addSpacing(4)
        side.addWidget(label("Session type", "muted"))
        self.mode = SegmentBar([(FOCUS, "Focus"), (SHORT_BREAK, "Short break"), (LONG_BREAK, "Long break")],
                               style="accent")
        self.mode.changed.connect(lambda m: page.study().choose_mode(m))
        side.addWidget(self.mode)
        side.addSpacing(6)
        actions = QHBoxLayout()
        self.start = button("Start focus", "primary", "play", self._start, "Start or pause the timer (Ctrl+Enter on Study)")
        self.start.setMinimumHeight(44)
        self.start.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        actions.addWidget(self.start, 1)
        actions.addWidget(tool_button("study", "Log a session you did without the timer",
                                      lambda: ManualStudyDialog(page.ctx, page).exec(), 18))
        side.addLayout(actions)
        side.addStretch(1)
        row.addLayout(side, 1)
        self.body.addLayout(row)
        self.summary = label("", "caption", wrap=True)
        self.summary.setContentsMargins(120, 0, 0, 0)
        self.body.addWidget(self.summary)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        narrow = self.width() < 500
        direction = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        if self.row.direction() != direction:
            self.row.setDirection(direction)
            self.summary.setContentsMargins(0 if narrow else 120, 0, 0, 0)
            self.summary.setAlignment(Qt.AlignmentFlag.AlignHCenter if narrow else Qt.AlignmentFlag.AlignLeft)

    def _start(self) -> None:
        study = self.page.study()
        if not study.timer.is_active:
            study.choose_subject(self.subject.current_id())
            study.choose_mode(self.mode.current())
        study.start_pause()

    def reload_subjects(self) -> None:
        self.subject.blockSignals(True)
        self.subject.set_items(subject_items(self.page.ctx))
        self.subject.set_current_id(self.page.study().subject.current_id())
        self.subject.blockSignals(False)

    def sync(self) -> None:
        st = self.page.study().dashboard_state()
        if self.time.text() != st["text"]:
            self.time.setText(st["text"])
        self.ring.set_fraction(st["fraction"], "accent" if st["mode"] == FOCUS else "blue")
        states = {"idle": f"{st['mode_label']} time", "running": st["mode_label"], "paused": "Paused",
                  "finished": "Done"}
        self.state.setText(states.get(st["state"], ""))
        self.mode.set_current(st["mode"])
        self.subject.setEnabled(not st["active"])
        self.mode.setEnabled(not st["active"])
        text = {"running": "Pause", "paused": "Resume"}.get(st["state"], "Start focus" if st["mode"] == FOCUS else "Start break")
        if self.start.text() != text:
            self.start.setText(text)
            bind_icon(self.start, "pause" if st["state"] == "running" else "play", "on_primary", 16)
        if st["subject_id"] != self.subject.current_id() and not st["active"]:
            self.subject.blockSignals(True)
            self.subject.set_current_id(st["subject_id"])
            self.subject.blockSignals(False)


class TodayPage(Page):
    domains = ("tasks", "habits", "goals", "journal", "schedule", "study", "exams", "settings", "subjects")
    title = "Today"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.actions = TaskActions(ctx, self, lambda t, a, c: self.toast(t, a, c))
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(38, 26, 38, 30)
        outer.setSpacing(16)
        self.root.addWidget(scroll_wrap(content))

        self.header = TodayHeader(self)
        outer.addWidget(self.header)
        self.intention = IntentionBanner(self)

        self.quick_box = QWidget()
        self.quick_row = FlowLayout(self.quick_box, spacing=4)
        self.quick_box.setContentsMargins(0, 6, 0, 0)
        self._quick_profile = None
        self.review_btn = button("End-of-day review", "ghost", "moon", self._review)
        self.header.layout().insertWidget(3, self.quick_box)
        self.welcome = self._welcome_banner()
        outer.addWidget(self.welcome)
        outer.addWidget(self.intention)

        # row 1: plan + your day
        self.plan_card = Card("A gentle plan", "list")
        self.plan_count = label("", "muted")
        self.plan_progress = ThinProgress(0.0, "progress", 6)
        self.plan_progress.setFixedWidth(170)
        prog = QVBoxLayout()
        prog.setSpacing(6)
        prog.addWidget(self.plan_count, 0, Qt.AlignmentFlag.AlignRight)
        prog.addWidget(self.plan_progress)
        self.plan_card.header.addLayout(prog)
        self.plan_list = QVBoxLayout()
        self.plan_list.setSpacing(0)
        self.plan_card.body.addLayout(self.plan_list)
        self.plan_card.body.addLayout(self._quick_add())

        self.day_card = Card("Your day", "calendar")
        self.day_card.add_action(button("Open calendar", "link", "chev-right", lambda: self.main.navigate("calendar")))
        self.day_list = QVBoxLayout()
        self.day_list.setSpacing(0)
        self.day_card.body.addLayout(self.day_list)
        add_event = button("Add event", "ghost", "plus", self._add_event, "Add an event for today")
        self.day_card.body.addWidget(add_event, 0, Qt.AlignmentFlag.AlignLeft)


        # row 2: study nook, rituals, coming up
        self.nook = StudyNook(self)
        self.rituals_card = Card("Small rituals", "leaf")
        self.rituals_count = label("", "muted")
        self.rituals_card.add_action(self.rituals_count)
        self.rituals_list = QVBoxLayout()
        self.rituals_list.setSpacing(0)
        self.rituals_card.body.addLayout(self.rituals_list)
        add_habit = button("Add a habit", "soft", "plus", self._add_habit)
        add_habit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.rituals_card.body.addSpacing(4)
        self.rituals_card.body.addWidget(add_habit)

        self.coming_card = Card("Coming up", "flag")
        self.coming_card.add_action(button("View all", "link", "chev-right", lambda: self.main.navigate("exams")))
        self.coming_card.set_art(Art("landscape", 900, 120, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                                     0.95, fill_width=True, clip_radius=15), Qt.Corner.BottomRightCorner)
        self.coming_list = QVBoxLayout()
        self.coming_list.setSpacing(8)
        self.coming_card.body.addLayout(self.coming_list)
        self.coming_card.body.addSpacing(96)

        self.board = DashboardColumns()
        outer.addWidget(self.board)
        outer.addStretch(1)
        self.workload_card = Card("Workload check", "clock")
        self.workload_body = QVBoxLayout()
        self.workload_body.setSpacing(6)
        self.workload_card.body.addLayout(self.workload_body)
        self.inbox_card = Card("Capture inbox", "inbox")
        self.inbox_card.add_action(button("Sort", "link", "chev-right", lambda: self.main.navigate("inbox")))
        self.inbox_body = QVBoxLayout()
        self.inbox_body.setSpacing(6)
        self.inbox_card.body.addLayout(self.inbox_body)
        self.revision_card = Card("Revision due", "book")
        self.revision_body = QVBoxLayout()
        self.revision_body.setSpacing(6)
        self.revision_card.body.addLayout(self.revision_body)
        self.review_card = Card("End of the day", "moon")
        self.review_body = QVBoxLayout()
        self.review_body.setSpacing(6)
        self.review_card.body.addLayout(self.review_body)
        self.cards: dict[str, QWidget] = {
            "plan": self.plan_card, "day": self.day_card, "focus": self.nook,
            "rituals": self.rituals_card, "coming": self.coming_card, "workload": self.workload_card,
            "inbox": self.inbox_card, "revision": self.revision_card, "review": self.review_card,
        }
        # Feature modules add dashboard widgets here: key -> (card factory, fill callback).
        self.extra_widgets: dict[str, tuple] = {}
        self._apply_widgets()

        self._clock_timer = QTimer(self)
        self._clock_timer.setSingleShot(True)
        self._clock_timer.timeout.connect(self._tick_clock)
        QTimer.singleShot(0, self._connect_study)
        theme.changed.connect(self._theme_changed)

    # -- helpers -------------------------------------------------------------
    def study(self):
        return self.main.pages["study"]

    def _connect_study(self) -> None:
        study = self.main.pages.get("study")
        if study is not None:
            study.timer_changed.connect(self.nook.sync)
            self.nook.reload_subjects()
            self.nook.sync()

    def _theme_changed(self) -> None:
        bind_icon(self.header.theme_btn, "moon" if theme.mode == "light" else "sun", "text2", 18)

    def _quick_add(self) -> QHBoxLayout:
        frame = QFrame()
        frame.setProperty("inset", True)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(10)
        plus = button("", "soft", "plus", lambda: self.quick_edit.setFocus(), "Add a new task")
        plus.setFixedSize(34, 34)
        lay.addWidget(plus)
        self.quick_edit = QLineEdit()
        self.quick_edit.setProperty("quickadd", True)
        self.quick_edit.setPlaceholderText("Add a new task…  (try “Read chapter 3 !high #English”)")
        self.quick_edit.setAccessibleName("Add a task for today")
        self.quick_edit.returnPressed.connect(self._quick_task)
        lay.addWidget(self.quick_edit, 1)
        enter = button("", "primary", "check", self._quick_task, "Add task")
        enter.setFixedSize(34, 34)
        lay.addWidget(enter)
        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        row.addWidget(frame)
        return row

    # -- dashboard widgets ---------------------------------------------------------
    def widget_keys(self) -> list[str]:
        """The dashboard widgets to show, in order (user choice, else the profile's defaults)."""
        chosen = self.ctx.settings.get("dashboard.widgets")
        if chosen is None:
            chosen = list(get_profile(self.ctx.settings.get("profile")).widgets)
        return [k for k in chosen if k in self.cards]

    def register_widget(self, key: str, card: QWidget, fill) -> None:
        """Let a feature module add a dashboard widget (shown when chosen in Settings → Profile & layout)."""
        self.cards[key] = card
        self.extra_widgets[key] = (card, fill)
        card.hide()
        self._apply_widgets()
        self.mark_dirty()

    def _apply_widgets(self) -> None:
        keys = self.widget_keys()
        for key, card in self.cards.items():
            if key not in keys:
                card.hide()
        self.board.set_widgets([self.cards[k] for k in keys])

    # -- header extras -----------------------------------------------------------------
    def _welcome_banner(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Banner")
        frame.setProperty("tone", "info")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(18, 12, 12, 12)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label("Welcome to DayOS 2", "heading"))
        col.addWidget(label("Choose a profile and one of five themes to shape your sidebar and this dashboard. "
                            "You can change both at any time.", "muted", wrap=True))
        lay.addLayout(col, 1)
        lay.addWidget(button("Personalise", "primary", "sparkle", self._personalise))
        lay.addWidget(button("Not now", "ghost", on_click=self._dismiss_welcome))
        frame.hide()
        return frame

    def _personalise(self) -> None:
        self._dismiss_welcome()
        self.main.navigate("settings")
        self.main.page("settings").show_section("profile")

    def _dismiss_welcome(self) -> None:
        self.ctx.settings.set("onboarded", True)
        self.welcome.hide()

    def _fill_quick_actions(self) -> None:
        profile = get_profile(self.ctx.settings.get("profile"))
        if self._quick_profile == profile.id:
            return
        self._quick_profile = profile.id
        while self.quick_row.count():
            widget = self.quick_row.takeAt(0).widget()
            if widget is not None and widget is not self.review_btn:
                widget.deleteLater()
        ctx = self.ctx
        actions = {
            "task": ("New task", "plus", lambda: TaskDialog(ctx, self, default_due=today()).exec(), "Add a task due today (Ctrl+N)"),
            "note": ("Quick note", "notes", self._quick_note, "Capture a note (Ctrl+Shift+N)"),
            "capture": ("Capture", "inbox", self.main.quick_capture, "Quick capture to your Inbox (Ctrl+Shift+Space)"),
            "event": ("New event", "calendar", self._add_event, "Add an event for today"),
            "focus": ("Log study", "clock", lambda: ManualStudyDialog(ctx, self).exec(),
                      "Record a session you did without the timer"),
            "test": ("Practice test", "exams", lambda: self.main.commands.run("studyforge.test") or self.main.navigate("exams"),
                     "Create a practice test"),
            "project": ("New project", "project", lambda: self.main.commands.run("project.new"), "Start a project"),
            "expense": ("Add expense", "money", lambda: self.main.commands.run("money.expense") or self.main.navigate("money"),
                        "Record an expense"),
            "review": ("Weekly review", "goals", lambda: self.main.commands.run("review.weekly"), "Look back at the week"),
        }
        for key in profile.quick_actions:
            if key in actions:
                text, icon_name, fn, tip = actions[key]
                self.quick_row.addWidget(button(text, "ghost", icon_name, fn, tip))
        self.quick_row.addWidget(self.review_btn)

    def theme_menu(self, anchor: QWidget) -> None:
        from src.ui.themes import THEMES

        menu = QMenu(self)
        current = theme.id
        for tid, t in THEMES.items():
            act = menu.addAction(t.name, lambda tid=tid: (self.ctx.settings.set("theme", tid), bus.notify("settings")))
            act.setCheckable(True)
            act.setChecked(tid == current)
        menu.addSeparator()
        menu.addAction("Appearance settings…", lambda: (self.main.navigate("settings"),
                                                        self.main.page("settings").show_section("appearance")))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    # -- extra widgets ----------------------------------------------------------------------
    def _fill_workload(self, day: date) -> None:
        from src.services.workload import day_workload

        clear_layout(self.workload_body)
        load = day_workload(self.ctx, day)
        if load.available_minutes is None:
            self.workload_body.addWidget(label(
                "Tell DayOS how much time you usually have, and it will check whether today's plan fits.",
                "muted", wrap=True))
            self.workload_body.addWidget(button("Set my available hours", "soft", "clock", self._open_workload_settings))
            if load.planned_minutes:
                self.workload_body.addWidget(label(f"Planned today: {format_duration(load.planned_minutes * 60)}",
                                                   "caption"))
            return
        planned, avail = load.planned_minutes, load.available_minutes
        top = QHBoxLayout()
        top.addWidget(label(f"{format_duration(planned * 60) if planned else '0 min'}", "metric"))
        top.addWidget(label(f"of {format_duration(avail * 60)} available", "muted"), 1)
        self.workload_body.addLayout(top)
        bar = ThinProgress(min(1.0, planned / avail) if avail else 0, "danger" if load.over_by else "progress", 6)
        self.workload_body.addWidget(bar)
        parts = []
        if load.scheduled_minutes:
            parts.append(f"{format_duration(load.scheduled_minutes * 60)} scheduled")
        if load.task_minutes:
            parts.append(f"{format_duration(load.task_minutes * 60)} of task estimates")
        if load.unestimated_tasks:
            parts.append(f"{load.unestimated_tasks} task{'s' if load.unestimated_tasks != 1 else ''} without an estimate")
        if parts:
            self.workload_body.addWidget(label(" · ".join(parts), "caption", wrap=True))
        if load.over_by:
            self.workload_body.addWidget(label(
                f"Today looks about {format_duration(load.over_by * 60)} fuller than your time. It's fine to move "
                "something; these would free enough:", "warning", wrap=True))
            for task in load.suggestions:
                r = QHBoxLayout()
                r.addWidget(label(f"{task.title} (~{format_duration((task.estimate_minutes or 0) * 60)})", "", wrap=True), 1)
                r.addWidget(button("Move to tomorrow", "link", on_click=lambda t=task.id: self._move_tomorrow(t)))
                self.workload_body.addLayout(r)
        elif planned:
            self.workload_body.addWidget(label("Today's plan fits the time you have.", "success"))

    def _open_workload_settings(self) -> None:
        self.main.navigate("settings")
        self.main.page("settings").show_section("focus")

    def _fill_inbox(self) -> None:
        clear_layout(self.inbox_body)
        items = self.ctx.inbox.open_items(4)
        count = self.ctx.inbox.count_open()
        self.main.set_badge("inbox", str(count) if count else "")
        if not items:
            self.inbox_body.addWidget(label("Nothing waiting. Press Ctrl+Shift+Space to capture a thought.", "muted",
                                            wrap=True))
            self.inbox_body.addWidget(button("Capture", "soft", "plus", self.main.quick_capture))
            return
        self.inbox_body.addWidget(label(f"{count} item{'s' if count != 1 else ''} to sort", "caption"))
        for item in items[:3]:
            self.inbox_body.addWidget(label("• " + item.text.splitlines()[0][:90], "", wrap=True))

    def _fill_revision(self, day: date) -> None:
        clear_layout(self.revision_body)
        chapters = self.ctx.exams.revision_queue(day, limit=5)
        provided = False
        for provider in getattr(self.main, "revision_providers", []):
            try:
                provided = provider(self.revision_body, day) or provided
            except Exception:
                import logging

                logging.getLogger(__name__).warning("Revision provider failed", exc_info=True)
        if chapters:
            self.revision_body.addWidget(label(f"{len(chapters)} chapter{'s' if len(chapters) != 1 else ''} from "
                                               "your exams are due for revision", "caption"))
            for ch in chapters[:4]:
                self.revision_body.addWidget(label(f"• {ch.name}" + (f" · {ch.exam_title}" if getattr(ch, 'exam_title', '') else ""),
                                                   "", wrap=True))
            self.revision_body.addWidget(button("Revise now", "soft", "book", self._open_revision))
        elif not provided:
            self.revision_body.addWidget(label("Nothing is due for revision today.", "muted", wrap=True))

    def _fill_review(self, day: date, entry) -> None:
        clear_layout(self.review_body)
        if entry.went_well or entry.reflection or entry.improve:
            if entry.went_well:
                self.review_body.addWidget(label(f"Went well: {entry.went_well}", "", wrap=True))
            if entry.improve:
                self.review_body.addWidget(label(f"Tomorrow: {entry.improve}", "muted", wrap=True))
            self.review_body.addWidget(button("Edit today's review", "link", "edit", self._review))
        else:
            self.review_body.addWidget(label("A two-minute look back: what went well, and one thing for tomorrow.",
                                             "muted", wrap=True))
            self.review_body.addWidget(button("Write today's review", "soft", "moon", self._review))
        if day.weekday() >= 4:
            self.review_body.addWidget(button("Weekly review", "link", "goals",
                                              lambda: self.main.commands.run("review.weekly")))

    # -- clock -------------------------------------------------------------------
    def _tick_clock(self) -> None:
        current = now()
        text = eyebrow_date(current.date(), self.date_style)
        if self.ctx.settings.get("show_clock"):
            text += f"  ·  {format_time(current.time(), self.clock24)}"
        self.header.eyebrow.setText(text.upper())
        self.header.greeting.setText(self._greeting_text(current))
        ms = (60 - current.second) * 1000 - current.microsecond // 1000 + 50
        if self.isVisible():
            self._clock_timer.start(max(1000, ms))

    def _greeting_text(self, current: datetime) -> str:
        name = str(self.ctx.settings.get("user_name") or "").strip()
        hello = f"{greeting(current)}, {name}." if name else f"{greeting(current)}."
        return f"{hello} A little progress is still progress."

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._tick_clock()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._clock_timer.stop()
        super().hideEvent(event)

    # -- refresh -------------------------------------------------------------------
    def refresh(self) -> None:
        day = today()
        self._apply_widgets()
        self._tick_clock()
        self.header.headline.setText(HEADLINES[day.toordinal() % len(HEADLINES)])
        name = str(self.ctx.settings.get("user_name") or "").strip()
        self.header.avatar.setText(name[:1].upper() if name else "")
        if name:
            self.header.avatar.setIcon(QIcon())
        else:
            bind_icon(self.header.avatar, "leaf", "accent_text", 18)
        self.header.avatar.setToolTip("Settings" if name else "Add your name in Settings for a personal greeting")
        self._theme_changed()
        entry = self.ctx.journal.get(day)
        self.intention.set_value(entry.intention)
        self.review_btn.setText("Edit today's review" if (entry.reflection or entry.went_well) else "End-of-day review")
        self.welcome.setVisible(not self.ctx.settings.get("onboarded"))
        self._fill_quick_actions()
        visible = set(self.widget_keys())
        self._fill_plan(day)
        self._fill_day(day)
        self._fill_rituals(day)
        self._fill_coming(day)
        if "workload" in visible:
            self._fill_workload(day)
        if "inbox" in visible:
            self._fill_inbox()
        if "revision" in visible:
            self._fill_revision(day)
        if "review" in visible:
            self._fill_review(day, entry)
        for key, (card, fill) in self.extra_widgets.items():
            if key in visible:
                try:
                    fill(card, day)
                except Exception:  # an optional widget must never break the dashboard
                    import logging

                    logging.getLogger(__name__).warning("Dashboard widget %s failed", key, exc_info=True)
        self.nook.reload_subjects()
        self.nook.sync()
        week = self.ctx.study.seconds_between(week_start(day, self.week_start), day)
        today_secs = self.ctx.study.seconds_on(day)
        self.nook.summary.setText(
            f"Studied {format_duration(today_secs)} today · {format_duration(week)} this week" if week else
            "No study time recorded yet this week."
        )

    def _fill_plan(self, day: date) -> None:
        clear_layout(self.plan_list)
        overdue, due = self.ctx.tasks.for_day(day)
        done = sum(1 for t in due if t.done)
        self.plan_count.setText(f"{done} of {len(due)} done" if due else "Nothing due today")
        self.plan_progress.set_value(done / len(due) if due else 0.0)
        rows = [(t, True) for t in overdue[:4]] + [(t, False) for t in due[:8]]
        if not rows:
            self.plan_list.addWidget(EmptyState(
                "tasks", "A clear page",
                "Nothing is due today. Add a task below, or pick something from your list.",
                [("Open tasks", lambda: self.main.navigate("tasks"))], compact=True))
            return
        for i, (task, is_overdue) in enumerate(rows):
            if i:
                self.plan_list.addWidget(separator())
            self.plan_list.addWidget(PlanRow(self, task, day, is_overdue))
        hidden = max(0, len(overdue) - 4) + max(0, len(due) - 8)
        if hidden:
            self.plan_list.addWidget(button(f"{hidden} more in Tasks", "link",
                                            on_click=lambda: self._open_tasks("today")))

    def task_menu(self, task, anchor: QWidget) -> None:
        menu = QMenu(self)
        menu.addAction("Edit…", lambda: self.actions.edit(task.id))
        menu.addAction("Reopen" if task.done else "Mark complete", lambda: self.actions.toggle(task.id, not task.done))
        if not task.done:
            menu.addAction("Move to tomorrow", lambda: self._move_tomorrow(task.id))
        menu.addSeparator()
        menu.addAction("Delete…", lambda: self.actions.delete(task.id))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _move_tomorrow(self, task_id: int) -> None:
        if guarded(self, lambda: self.ctx.tasks.update(task_id, due_date=today() + timedelta(days=1))):
            bus.notify("tasks")
            self.toast("Moved to tomorrow")

    def _open_tasks(self, filter_name: str) -> None:
        page = self.main.page("tasks")
        page.filters.set_current(filter_name)  # type: ignore[attr-defined]
        page.mark_dirty()
        self.main.navigate("tasks")

    def _quick_task(self) -> None:
        text = self.quick_edit.text().strip()
        if not text:
            return
        parsed = parse_quick_task(text, today())

        def run() -> None:
            self.ctx.tasks.create(parsed.title, due_date=parsed.due_date or today(), priority=parsed.priority,
                                  category=parsed.category)
            bus.notify("tasks")

        if guarded(self, run, "Couldn't add the task"):
            self.quick_edit.clear()
            self.toast(f"Added “{parsed.title}”")

    def _fill_day(self, day: date) -> None:
        clear_layout(self.day_list)
        items = [i for i in self.ctx.schedule.day_agenda(day) if i.kind != "task"]
        if not items:
            self.day_list.addWidget(EmptyState(
                "calendar", "An open day",
                "Classes, events and exams scheduled for today will appear on this timeline.",
                [("Open calendar", lambda: self.main.navigate("calendar"))], compact=True))
            return
        current = now().strftime("%H:%M")
        shown = items[:6]
        for i, item in enumerate(shown):
            past = item.end_time is not None and item.end_time <= current
            self.day_list.addWidget(TimelineRow(item, self.clock24, i == 0, i == len(shown) - 1, past))
        if len(items) > 6:
            self.day_list.addWidget(label(f"+{len(items) - 6} more in the calendar", "caption"))

    def _add_event(self) -> None:
        from src.ui.pages.calendar import EventDialog

        EventDialog(self.ctx, self, day=today()).exec()

    def _fill_rituals(self, day: date) -> None:
        clear_layout(self.rituals_list)
        habits = self.ctx.habits.scheduled_on(day)
        done_ids = self.ctx.habits.done_on(day)
        done_n = sum(1 for h in habits if h.id in done_ids)
        self.rituals_count.setText(f"{done_n} of {len(habits)} rituals" if habits else "")
        if not habits:
            has_any = bool(self.ctx.habits.list())
            self.rituals_list.addWidget(EmptyState(
                "leaf", "Nothing scheduled today" if has_any else "No rituals yet",
                "None of your habits are planned for today." if has_any else
                "Small daily habits — reading, stretching, water — live here.", compact=True))
            return
        for i, habit in enumerate(habits[:6]):
            if i:
                self.rituals_list.addWidget(separator())
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 7, 0, 7)
            lay.setSpacing(12)
            check = RoundCheck(habit.id in done_ids, 22, f"Done today: {habit.name}")
            check.toggled.connect(lambda on, hid=habit.id: self._toggle_habit(hid, on))
            lay.addWidget(check)
            col = QVBoxLayout()
            col.setSpacing(1)
            name = QLabel(habit.name)
            name.setProperty("role", "rowtitle")
            col.addWidget(name)
            streak = self.ctx.habits.streak_info(habit, day).current
            sub = habit.description or ""
            if streak:
                sub = f"{streak}-day streak" + (f" · {sub}" if sub else "")
            if sub:
                col.addWidget(label(sub, "caption"))
            lay.addLayout(col, 1)
            more = tool_button("more", f"More for {habit.name}", size=16)
            more.clicked.connect(lambda _=False, h=habit, b=more: self._habit_menu(h, b))
            lay.addWidget(more)
            self.rituals_list.addWidget(row)
        if len(habits) > 6:
            self.rituals_list.addWidget(button(f"{len(habits) - 6} more in Habits", "link",
                                               on_click=lambda: self.main.navigate("habits")))

    def _habit_menu(self, habit, anchor: QWidget) -> None:
        from src.ui.pages.habits import HabitDialog

        menu = QMenu(self)
        menu.addAction("Edit…", lambda: HabitDialog(self.ctx, self, habit).exec())
        menu.addAction("Open habits", lambda: self.main.navigate("habits"))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _toggle_habit(self, habit_id: int, done: bool) -> None:
        def run() -> None:
            self.ctx.habits.set_done(habit_id, today(), done)
            QTimer.singleShot(260, lambda: bus.notify("habits"))

        guarded(self, run, "Couldn't update the habit")

    def _add_habit(self) -> None:
        from src.ui.pages.habits import HabitDialog

        HabitDialog(self.ctx, self).exec()

    def _fill_coming(self, day: date) -> None:
        clear_layout(self.coming_list)
        horizon = day + timedelta(days=30)
        entries: list[tuple] = []
        for e in self.ctx.exams.upcoming(day, horizon):
            title = (f"{e.subject_name} • {e.title}"
                     if e.subject_name and e.subject_name.lower() not in e.title.lower() else e.title)
            detail = f"{e.chapter_ready} of {e.chapter_total} chapters revised" if e.chapter_total else "Exam"
            entries.append((e.day, "exam", title, detail))
        for d in self.ctx.schedule.upcoming_deadlines(day, horizon):
            entries.append((date.fromisoformat(d.date), "deadline", d.title, d.subject_name or d.category or "Deadline"))
        entries.sort(key=lambda x: x[0])
        revision_due = self.ctx.exams.revision_queue(day)
        if revision_due:
            r = QHBoxLayout()
            r.addWidget(label(f"{len(revision_due)} chapter{'s' if len(revision_due) != 1 else ''} ready to revise today",
                              "warning"), 1)
            r.addWidget(button("Revise", "link", on_click=self._open_revision))
            self.coming_list.addLayout(r)
        for when, kind, title, detail in entries[:2 if revision_due else 3]:
            self.coming_list.addWidget(self._coming_item(when, kind, title, detail, day))
        goals = self.ctx.goals.list("active")[:1 if entries else 3]
        for g in goals:
            gl = QVBoxLayout()
            gl.setSpacing(4)
            top = QHBoxLayout()
            top.addWidget(label(g.title), 1)
            if g.fraction is not None:
                top.addWidget(label(f"{round(g.fraction * 100)}%", "caption"))
            elif g.linked_tasks:
                top.addWidget(label(f"{g.linked_done}/{g.linked_tasks} tasks", "caption"))
            gl.addLayout(top)
            if g.fraction is not None:
                gl.addWidget(ThinProgress(g.fraction, "blue", 5))
            self.coming_list.addLayout(gl)
        if not entries and not revision_due and not goals:
            self.coming_list.addWidget(EmptyState(
                "flag", "Nothing on the horizon",
                "Exams, deadlines and goals you add will gather here with gentle countdowns.",
                [("Add an exam", lambda: self._go_new("exams"))], compact=True))

    def _coming_item(self, when: date, kind: str, title: str, detail: str, ref: date) -> QWidget:
        frame = QFrame()
        frame.setProperty("inset", True)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 9, 12, 9)
        lay.setSpacing(12)
        tile = QLabel()
        tile.setFixedSize(40, 40)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tone = "terracotta" if kind == "exam" else "amber"
        tile.setStyleSheet(f"background: {theme.tokens[tone + '_soft']}; border-radius: 10px;")
        tile.setPixmap(pixmap("calendar", theme.tokens[tone + "_text"], 20))
        lay.addWidget(tile)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setWordWrap(True)
        t.setStyleSheet("font-weight: 600;")
        col.addWidget(t)
        col.addWidget(label(detail, "caption", wrap=True))
        lay.addLayout(col, 1)
        right = QVBoxLayout()
        right.setSpacing(1)
        count = label(short_countdown(when, ref), "")
        count.setStyleSheet(f"color: {theme.tokens[tone + '_text']};")
        count.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(count)
        d = label(format_date(when, self.date_style), "caption")
        d.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(d)
        lay.addLayout(right)
        frame.setAccessibleName(f"{KIND_NAMES[kind]}: {title}, {countdown_text(when, ref)}")
        return frame

    def _open_revision(self) -> None:
        page = self.main.page("exams")
        if hasattr(page, "show_revision"):
            page.show_revision()  # type: ignore[attr-defined]
        self.main.navigate("exams")

    def _go_new(self, key: str) -> None:
        self.main.navigate(key)
        self.main.page(key).new_item()

    # -- actions ----------------------------------------------------------------
    def save_intention(self, text: str) -> None:
        if text == self.ctx.journal.get(today()).intention:
            return
        if guarded(self, lambda: self.ctx.journal.save(today(), intention=text), "Couldn't save your intention"):
            if text:
                self.toast("Intention saved")

    def toggle_theme(self) -> None:
        """Switch between the current theme and its light/dark counterpart."""
        self.ctx.settings.set("theme", theme.theme.counterpart or ("midnight" if theme.mode == "light" else "paper"))
        bus.notify("settings")

    def _quick_note(self) -> None:
        if QuickNoteDialog(self.ctx, self).exec():
            self.toast("Note saved", "Open notes", lambda: self.main.navigate("notes"))

    def _review(self) -> None:
        self.intention.finish()
        if DailyReviewDialog(self.ctx, self).exec():
            self.toast("Review saved. Rest well.")

    def new_item(self) -> None:
        TaskDialog(self.ctx, self, default_due=today()).exec()

    def can_leave(self) -> bool:
        self.intention.finish()
        return True

