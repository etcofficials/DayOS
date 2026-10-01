from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from src.models import AgendaItem, Event, TimetableEntry
from src.services.dates import (
    MONTH_NAMES,
    WEEKDAY_NAMES,
    WEEKDAY_SHORT,
    ValidationError,
    add_months,
    format_date,
    format_long_date,
    format_time,
    month_grid_start,
    relative_day,
    today,
    week_start,
)
from src.services import recurrence
from src.ui.bus import bus
from src.ui.dialogs import subject_items
from src.ui.pages.base import Page
from src.ui.theme import KIND_COLORS, theme
from src.ui.widgets.day_timeline import DayTimeline
from src.ui.widgets.common import (
    DateEdit,
    FadeDialog,
    EmptyState,
    FormDialog,
    IdCombo,
    OptionalDate,
    PageHeader,
    SegmentBar,
    TimeEdit,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    tool_button,
)

KIND_TONES = {"event": "blue", "class": "accent", "exam": "terracotta", "deadline": "amber", "task": ""}
KIND_NAMES = {"event": "Event", "class": "Class", "exam": "Exam", "deadline": "Deadline", "task": "Task"}


# -- dialogs --------------------------------------------------------------------

REMINDER_CHOICES = [(None, "No reminder"), (0, "At start time"), (5, "5 minutes before"), (10, "10 minutes before"),
                    (15, "15 minutes before"), (30, "30 minutes before"), (60, "1 hour before"),
                    (120, "2 hours before"), (1440, "1 day before")]


class EventDialog(FormDialog):
    def __init__(self, ctx, parent=None, event: Event | None = None, day: date | None = None,
                 kind: str = "event", start_time: str | None = None) -> None:
        super().__init__("Edit entry" if event else ("New deadline" if kind == "deadline" else "New event"), parent, width=520)
        self.ctx = ctx
        if event is not None and event.recurrence:
            event = ctx.schedule.get_event(event.id) or event  # edit the series, not one expanded occurrence
        self.event = event
        clock24 = bool(ctx.settings.get("clock_24h"))
        self.title_edit = QLineEdit(event.title if event else "")
        self.title_edit.setPlaceholderText("Title")
        self.add_row("Title", self.title_edit)
        self.kind = QComboBox()
        self.kind.addItem("Event", "event")
        self.kind.addItem("Deadline", "deadline")
        self.kind.setCurrentIndex(self.kind.findData(event.kind if event else kind))
        self.add_row("Type", self.kind)
        self.day = DateEdit(date.fromisoformat(event.date) if event else (day or today()))
        self.day.set_first_weekday(int(ctx.settings.get("week_start")))
        self.add_row("Date", self.day)
        self.all_day = QCheckBox("All day / no specific time")
        self.all_day.setChecked(bool(event) and not event.start_time)
        self.add_row("", self.all_day)
        times = QHBoxLayout()
        self.start = TimeEdit(clock24=clock24)
        self.start.set_value(event.start_time if event and event.start_time else (start_time or "09:00"))
        self.has_end = QCheckBox("until")
        self.has_end.setChecked(bool(event and event.end_time) or not event)
        self.end = TimeEdit(clock24=clock24)
        default_end = "10:00"
        if start_time and not event:
            h, m = (int(x) for x in start_time.split(":"))
            default_end = f"{min(23, h + 1):02d}:{m:02d}"
        self.end.set_value(event.end_time if event and event.end_time else default_end)
        times.addWidget(self.start)
        times.addWidget(self.has_end)
        times.addWidget(self.end)
        times.addStretch(1)
        self.add_row("Time", times)
        self.location = QLineEdit(event.location if event else "")
        self.location.setPlaceholderText("Optional, e.g. Library, Room 4")
        self.add_row("Location", self.location)
        rep_row = QHBoxLayout()
        self.repeat = QComboBox()
        for key, text in recurrence.RULES.items():
            self.repeat.addItem(text, key)
        self.repeat.setCurrentIndex(max(0, self.repeat.findData(event.recurrence if event else "")))
        self.until = OptionalDate("until", date.fromisoformat(event.recur_until) if event and event.recur_until else None)
        rep_row.addWidget(self.repeat, 1)
        rep_row.addWidget(self.until, 1)
        self.repeat.currentIndexChanged.connect(lambda _: self.until.setEnabled(bool(self.repeat.currentData())))
        self.until.setEnabled(bool(self.repeat.currentData()))
        self.add_row("Repeat", rep_row)
        if event is not None and event.recurrence:
            self.form.addRow(label("This is a repeating event: changes here apply to every occurrence. To change a "
                                   "single day, skip it from the calendar and add a one-off event.", "caption", wrap=True))
        self.remind = QComboBox()
        for minutes, text in REMINDER_CHOICES:
            self.remind.addItem(text, minutes)
        self.remind.setCurrentIndex(max(0, self.remind.findData(event.remind_minutes if event else None)))
        self.add_row("Reminder", self.remind)
        self.subject = IdCombo("No subject")
        self.subject.set_items(subject_items(ctx))
        self.subject.set_current_id(event.subject_id if event else None)
        self.add_row("Subject", self.subject)
        self.category = QLineEdit(event.category if event else "")
        self.category.setPlaceholderText("Optional, e.g. Club, Family")
        self.add_row("Category", self.category)
        self.desc = QPlainTextEdit(event.description if event else "")
        self.desc.setFixedHeight(64)
        self.add_row("Details", self.desc)
        self.form.addRow(label("Events can't cross midnight — split late-night plans into two entries.", "caption", wrap=True))
        self.all_day.toggled.connect(self._toggle)
        self.has_end.toggled.connect(lambda on: self.end.setEnabled(on and not self.all_day.isChecked()))
        self._toggle(self.all_day.isChecked())
        self.title_edit.setFocus()

    def _toggle(self, all_day: bool) -> None:
        self.start.setEnabled(not all_day)
        self.has_end.setEnabled(not all_day)
        self.end.setEnabled(not all_day and self.has_end.isChecked())

    def save(self) -> None:
        start = None if self.all_day.isChecked() else self.start.value()
        end = self.end.value() if start and self.has_end.isChecked() else None
        data = dict(title=self.title_edit.text(), kind=self.kind.currentData(), date=self.day.value(),
                    start_time=start, end_time=end, subject_id=self.subject.current_id(),
                    category=self.category.text(), description=self.desc.toPlainText(),
                    location=self.location.text(), recurrence=self.repeat.currentData(),
                    recur_until=self.until.value() if self.repeat.currentData() else None,
                    remind_minutes=self.remind.currentData() if start else None,
                    task_id=self.event.task_id if self.event else None)
        if self.remind.currentData() is not None and not start:
            raise ValidationError("Reminders need a start time. Untick “All day” or choose “No reminder”.")
        if start and end and end <= start:
            raise ValidationError("The end time must be after the start time. Events can't cross midnight.")
        conflicts = self.ctx.schedule.event_conflicts(self.day.value(), start, end, self.event.id if self.event else None)
        if conflicts and not confirm(self, "Overlapping time",
                                     "This overlaps with:\n• " + "\n• ".join(conflicts[:5]) + "\n\nSave anyway?",
                                     "Save anyway", danger=False):
            raise ValidationError("Not saved — adjust the time or save anyway.")
        if self.event:
            self.ctx.schedule.update_event(self.event.id, **data)
        else:
            self.ctx.schedule.create_event(**data)
        bus.notify("schedule", "reminders")


class TimetableDialog(FormDialog):
    def __init__(self, ctx, parent=None, entry: TimetableEntry | None = None, weekday: int | None = None) -> None:
        super().__init__("Edit weekly class" if entry else "Add weekly class", parent, width=500)
        self.ctx = ctx
        self.entry = entry
        clock24 = bool(ctx.settings.get("clock_24h"))
        self.title_edit = QLineEdit(entry.title if entry else "")
        self.title_edit.setPlaceholderText("e.g. Chemistry lecture")
        self.add_row("Title", self.title_edit)
        self.subject = IdCombo("No subject")
        self.subject.set_items(subject_items(ctx))
        self.subject.set_current_id(entry.subject_id if entry else None)
        self.add_row("Subject", self.subject)
        self.weekday = QComboBox()
        self.weekday.addItems(WEEKDAY_NAMES)
        self.weekday.setCurrentIndex(entry.weekday if entry else (weekday if weekday is not None else today().weekday()))
        self.add_row("Every", self.weekday)
        times = QHBoxLayout()
        self.start = TimeEdit(clock24=clock24)
        self.start.set_value(entry.start_time if entry else "09:00")
        self.end = TimeEdit(clock24=clock24)
        self.end.set_value(entry.end_time if entry else "10:00")
        times.addWidget(self.start)
        times.addWidget(label("to", "muted"))
        times.addWidget(self.end)
        times.addStretch(1)
        self.add_row("Time", times)
        self.location = QLineEdit(entry.location if entry else "")
        self.location.setPlaceholderText("Room or place (optional)")
        self.add_row("Location", self.location)
        self.valid_from = OptionalDate("Starts", date.fromisoformat(entry.valid_from) if entry and entry.valid_from else None)
        self.valid_until = OptionalDate("Ends", date.fromisoformat(entry.valid_until) if entry and entry.valid_until else None)
        self.add_row("From", self.valid_from)
        self.add_row("Until", self.valid_until)
        note = ("Changes apply to every week of this class. To change a single day, skip it from the calendar "
                "and add a one-off event instead." if entry else "Repeats weekly. Leave the dates empty to repeat indefinitely.")
        self.form.addRow(label(note, "caption", wrap=True))

    def save(self) -> None:
        data = dict(title=self.title_edit.text(), subject_id=self.subject.current_id(),
                    weekday=self.weekday.currentIndex(), start_time=self.start.value(), end_time=self.end.value(),
                    location=self.location.text(), valid_from=self.valid_from.value(),
                    valid_until=self.valid_until.value())
        if data["end_time"] <= data["start_time"]:
            raise ValidationError("The end time must be after the start time.")
        conflicts = self.ctx.schedule.entry_conflicts(data["weekday"], data["start_time"], data["end_time"],
                                                      self.entry.id if self.entry else None)
        if conflicts and not confirm(self, "Overlapping class",
                                     "This overlaps with:\n• " + "\n• ".join(conflicts[:5]) + "\n\nSave anyway?",
                                     "Save anyway", danger=False):
            raise ValidationError("Not saved — adjust the time or save anyway.")
        if self.entry:
            self.ctx.schedule.update_entry(self.entry.id, **data)
        else:
            self.ctx.schedule.create_entry(**data)
        bus.notify("schedule")


# -- month grid -------------------------------------------------------------------

class MonthGrid(QWidget):
    selected = Signal(object)
    activated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.year, self.month = today().year, today().month
        self.first_weekday = 0
        self.selected_day = today()
        self.items: dict[date, list[AgendaItem]] = {}
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(QSize(420, 380))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Month calendar. Use arrow keys to change day, Enter to add an event.")
        theme.changed.connect(self.update)

    def grid_start(self) -> date:
        return month_grid_start(self.year, self.month, self.first_weekday)

    def set_month(self, year: int, month: int) -> None:
        self.year, self.month = year, month
        self.update()

    def _cell(self, index: int) -> QRectF:
        header = 26
        w = self.width() / 7
        h = (self.height() - header) / 6
        return QRectF((index % 7) * w, header + (index // 7) * h, w, h)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = p.font()
        start = self.grid_start()
        ref = today()
        w = self.width() / 7
        p.setPen(theme.color("text3"))
        small = p.font()
        small.setPointSizeF(8.5)
        p.setFont(small)
        for i in range(7):
            p.drawText(QRectF(i * w, 0, w, 22), Qt.AlignmentFlag.AlignCenter,
                       WEEKDAY_SHORT[(self.first_weekday + i) % 7])
        line_h = p.fontMetrics().height() + 2
        for i in range(42):
            d = start + timedelta(days=i)
            r = self._cell(i).adjusted(2, 2, -2, -2)
            in_month = d.month == self.month
            if d == self.selected_day:
                p.setPen(QPen(theme.color("accent"), 1.5 if self.hasFocus() else 1))
                p.setBrush(theme.color("accent_soft"))
                p.drawRoundedRect(r, 8, 8)
            elif in_month:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color("surface"))
                p.drawRoundedRect(r, 8, 8)
            # day number
            num_rect = QRectF(r.x() + 6, r.y() + 5, 24, 20)
            if d == ref:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color("accent"))
                p.drawEllipse(QRectF(num_rect.x() - 3, num_rect.y() - 1, 22, 22))
                p.setPen(theme.color("on_accent"))
            else:
                p.setPen(theme.color("text") if in_month else theme.color("text3"))
            bold = p.font()
            bold.setPointSizeF(9)
            bold.setBold(d == ref)
            p.setFont(bold)
            p.drawText(QRectF(num_rect.x() - 3, num_rect.y() - 1, 22, 22), Qt.AlignmentFlag.AlignCenter, str(d.day))
            p.setFont(small)
            items = self.items.get(d, [])
            max_lines = max(0, int((r.height() - 30) // line_h))
            shown = items[:max_lines] if len(items) <= max_lines else items[:max(0, max_lines - 1)]
            y = r.y() + 28
            for item in shown:
                color = theme.color(KIND_COLORS.get(item.kind, "text2"))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(QRectF(r.x() + 6, y + line_h / 2 - 3, 6, 6), 2, 2)
                p.setPen(theme.color("text2") if in_month else theme.color("text3"))
                text = p.fontMetrics().elidedText(item.title, Qt.TextElideMode.ElideRight, int(r.width() - 22))
                p.drawText(QRectF(r.x() + 16, y, r.width() - 20, line_h), Qt.AlignmentFlag.AlignVCenter, text)
                y += line_h
            hidden = len(items) - len(shown)
            if hidden > 0:
                p.setPen(theme.color("text3"))
                p.drawText(QRectF(r.x() + 16, y, r.width() - 20, line_h), Qt.AlignmentFlag.AlignVCenter, f"+{hidden} more")
        p.setFont(f)
        p.end()

    def _index_at(self, pos) -> int:
        for i in range(42):
            if self._cell(i).contains(pos):
                return i
        return -1

    def mousePressEvent(self, event) -> None:  # noqa: N802
        i = self._index_at(event.position())
        if i >= 0:
            self.select(self.grid_start() + timedelta(days=i))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        i = self._index_at(event.position())
        if i >= 0:
            self.activated.emit(self.grid_start() + timedelta(days=i))

    def select(self, d: date) -> None:
        self.selected_day = d
        if (d.year, d.month) != (self.year, self.month):
            self.set_month(d.year, d.month)
        self.setAccessibleDescription(format_long_date(d))
        self.selected.emit(d)
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        moves = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -7, Qt.Key.Key_Down: 7}
        if event.key() in moves:
            self.select(self.selected_day + timedelta(days=moves[event.key()]))
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.emit(self.selected_day)
            return
        super().keyPressEvent(event)


# -- page ---------------------------------------------------------------------------

class CalendarPage(Page):
    domains = ("schedule", "exams", "tasks", "subjects", "settings")
    title = "Calendar"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        header = PageHeader("Calendar", "Events, deadlines, exams and your weekly timetable in one place.", eyebrow="Your schedule")
        header.add_action(button("Weekly class", "", "plus", lambda: TimetableDialog(self.ctx, self).exec(),
                                 "Add a class that repeats every week"))
        header.add_action(button("New event", "primary", "plus", self.new_item, "New event (Ctrl+N)"))
        self.root.addWidget(header)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(tool_button("chev-left", "Previous", lambda: self._step(-1)))
        bar.addWidget(tool_button("chev-right", "Next", lambda: self._step(1)))
        self.period_label = label("", "section")
        bar.addWidget(self.period_label)
        bar.addWidget(button("Today", "ghost", on_click=self._go_today))
        bar.addStretch(1)
        self.show_tasks = QCheckBox("Show tasks")
        self.show_tasks.setChecked(bool(ctx.settings.get("calendar.show_tasks")))
        self.show_tasks.toggled.connect(self._toggle_tasks)
        bar.addWidget(self.show_tasks)
        self.view = SegmentBar([("day", "Day"), ("week", "Week"), ("month", "Month"), ("timetable", "Timetable")],
                               "month")
        self.view.changed.connect(lambda _: self.refresh())
        bar.addWidget(self.view)
        self.root.addLayout(bar)

        self.conflict_banner = QFrame()
        self.conflict_banner.setObjectName("Banner")
        self.conflict_banner.setProperty("tone", "warning")
        self.conflict_banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cb = QHBoxLayout(self.conflict_banner)
        cb.setContentsMargins(14, 8, 10, 8)
        self.conflict_text = label("", "warning", wrap=True)
        cb.addWidget(self.conflict_text, 1)
        cb.addWidget(button("Review overlaps", "link", "chev-right", self._review_conflicts))
        self.conflict_banner.hide()
        self.root.addWidget(self.conflict_banner)

        self.views = QStackedLayout()
        holder = QWidget()
        holder.setLayout(self.views)
        self.root.addWidget(holder, 1)

        # month view: grid + day panel
        month = QSplitter(Qt.Orientation.Horizontal)
        month.setHandleWidth(14)
        month.setChildrenCollapsible(False)
        self.grid = MonthGrid()
        self.grid.selected.connect(lambda d: self._fill_day(d))
        self.grid.activated.connect(lambda d: EventDialog(self.ctx, self, day=d).exec())
        month.addWidget(self.grid)
        day_panel = QFrame()
        day_panel.setProperty("panel", True)
        dl = QVBoxLayout(day_panel)
        dl.setContentsMargins(16, 14, 16, 14)
        self.day_title = label("", "section")
        self.day_sub = label("", "caption")
        dl.addWidget(self.day_title)
        dl.addWidget(self.day_sub)
        self.day_items = QWidget()
        self.day_layout = QVBoxLayout(self.day_items)
        self.day_layout.setContentsMargins(0, 6, 0, 0)
        self.day_layout.setSpacing(6)
        dl.addWidget(scroll_wrap(self.day_items), 1)
        add_row = QHBoxLayout()
        add_row.addWidget(button("Event", "", "plus", lambda: EventDialog(self.ctx, self, day=self.grid.selected_day).exec()))
        add_row.addWidget(button("Deadline", "", "plus", lambda: EventDialog(self.ctx, self, day=self.grid.selected_day, kind="deadline").exec()))
        add_row.addStretch(1)
        dl.addLayout(add_row)
        day_panel.setMinimumWidth(360)
        month.addWidget(day_panel)
        month.setSizes([680, 380])
        month.setStretchFactor(0, 1)
        self.views.addWidget(month)

        # week view
        self.week_widget = QWidget()
        self.week_layout = QVBoxLayout(self.week_widget)
        self.week_layout.setContentsMargins(0, 0, 0, 0)
        self.week_layout.setSpacing(10)
        self.views.addWidget(scroll_wrap(self.week_widget))

        # timetable view
        self.tt_widget = QWidget()
        self.tt_layout = QVBoxLayout(self.tt_widget)
        self.tt_layout.setContentsMargins(0, 0, 0, 0)
        self.tt_layout.setSpacing(10)
        self.views.addWidget(scroll_wrap(self.tt_widget))

        # day view: untimed items on top, then the hour timeline
        day_box = QWidget()
        dbl = QVBoxLayout(day_box)
        dbl.setContentsMargins(0, 0, 8, 0)
        dbl.setSpacing(10)
        self.day_untimed = QVBoxLayout()
        self.day_untimed.setSpacing(4)
        dbl.addLayout(self.day_untimed)
        self.timeline = DayTimeline()
        self.timeline.item_clicked.connect(lambda item, pos: self._item_menu(item, None, pos))
        self.timeline.slot_activated.connect(
            lambda hhmm: EventDialog(self.ctx, self, day=self._day_anchor, start_time=hhmm).exec())
        tl_card = QFrame()
        tl_card.setProperty("card", True)
        tll = QVBoxLayout(tl_card)
        tll.setContentsMargins(10, 10, 14, 10)
        tll.addWidget(self.timeline)
        dbl.addWidget(tl_card)
        dbl.addWidget(label("Double-click an empty slot to add an event at that time.", "caption"))
        dbl.addStretch(1)
        self.day_scroll = scroll_wrap(day_box)
        self.views.addWidget(self.day_scroll)
        self._week_anchor = today()
        self._day_anchor = today()

    def _toggle_tasks(self, on: bool) -> None:
        self.ctx.settings.set("calendar.show_tasks", on)
        self.refresh()

    # -- navigation ---------------------------------------------------------------
    def _step(self, direction: int) -> None:
        view = self.view.current()
        if view == "month":
            d = add_months(date(self.grid.year, self.grid.month, 1), direction)
            self.grid.set_month(d.year, d.month)
            if (self.grid.selected_day.year, self.grid.selected_day.month) != (d.year, d.month):
                self.grid.selected_day = d
        elif view == "week":
            self._week_anchor += timedelta(days=7 * direction)
        elif view == "day":
            self._day_anchor += timedelta(days=direction)
        self.refresh()

    def _go_today(self) -> None:
        self._week_anchor = today()
        self._day_anchor = today()
        self.grid.select(today())
        self.refresh()

    # -- refresh --------------------------------------------------------------------
    def refresh(self) -> None:
        self.grid.first_weekday = self.week_start
        view = self.view.current()
        self.show_tasks.setVisible(view != "timetable")
        if view == "month":
            self.views.setCurrentIndex(0)
            start = self.grid.grid_start()
            self.grid.items = self.ctx.schedule.agenda(start, start + timedelta(days=41), self.show_tasks.isChecked())
            self.grid.update()
            self.period_label.setText(f"{MONTH_NAMES[self.grid.month - 1]} {self.grid.year}")
            self._fill_day(self.grid.selected_day)
            self._update_conflicts(date(self.grid.year, self.grid.month, 1),
                                   add_months(date(self.grid.year, self.grid.month, 1), 1) - timedelta(days=1))
        elif view == "week":
            self.views.setCurrentIndex(1)
            self._fill_week()
            start = week_start(self._week_anchor, self.week_start)
            self._update_conflicts(start, start + timedelta(days=6))
        elif view == "day":
            self.views.setCurrentIndex(3)
            self._fill_day_view()
            self._update_conflicts(self._day_anchor, self._day_anchor)
        else:
            self.views.setCurrentIndex(2)
            self.period_label.setText("Weekly timetable")
            self._fill_timetable()
            self.conflict_banner.hide()

    def _fill_day_view(self) -> None:
        d = self._day_anchor
        rel = relative_day(d)
        self.period_label.setText(format_long_date(d, self.date_style)
                                  + (f" · {rel}" if rel in ("Today", "Tomorrow", "Yesterday") else ""))
        clear_layout(self.day_untimed)
        items = self.ctx.schedule.day_agenda(d, self.show_tasks.isChecked())
        untimed = [i for i in items if not i.start_time]
        for item in untimed:
            self.day_untimed.addWidget(self._item_widget(item))
        if not items:
            self.day_untimed.addWidget(label("Nothing scheduled — a free day.", "muted"))
        from src.services.dates import now as _now

        current = _now()
        now_min = current.hour * 60 + current.minute if d == current.date() else None
        self.timeline.set_items(items, self.clock24, now_min)

    def _update_conflicts(self, start: date, end: date) -> None:
        self._conflicts = self.ctx.schedule.conflicts_between(start, end)
        n = len(self._conflicts)
        if n:
            days = len({c[0] for c in self._conflicts})
            self.conflict_text.setText(
                f"{n} overlapping time{'s' if n != 1 else ''} on {days} day{'s' if days != 1 else ''} in this view. "
                "Nothing was moved; review them when you have a moment.")
        self.conflict_banner.setVisible(bool(n))

    def _review_conflicts(self) -> None:
        dlg = ConflictsDialog(self, getattr(self, "_conflicts", []))
        dlg.exec()

    def _item_widget(self, item: AgendaItem, with_actions: bool = True) -> QWidget:
        w = QWidget()
        w.setObjectName("Row")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(w)
        row.setContentsMargins(8, 6, 6, 6)
        row.setSpacing(10)
        if item.start_time:
            when = format_time(item.start_time, self.clock24)
            if item.end_time:
                when += f"–{format_time(item.end_time, self.clock24)}"
        else:
            when = "All day" if item.kind != "task" else "Any time"
        t = label(when, "muted")
        t.setFixedWidth(84 if self.clock24 else 118)
        row.addWidget(t, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        title = label(item.title, "rowtitle", wrap=True)
        if item.kind == "task" and item.detail == "Completed":
            title.setProperty("strike", "true")
        col.addWidget(title)
        if item.detail and item.kind != "task":
            col.addWidget(label(item.detail, "caption", wrap=True))
        row.addLayout(col, 1)
        row.addWidget(chip(KIND_NAMES[item.kind], KIND_TONES[item.kind]), 0, Qt.AlignmentFlag.AlignTop)
        if with_actions:
            more = tool_button("more", f"Actions for {item.title}", size=16)
            more.clicked.connect(lambda: self._item_menu(item, more))
            row.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        return w

    def _fill_day(self, d: date) -> None:
        clear_layout(self.day_layout)
        self.day_title.setText(format_long_date(d, self.date_style))
        rel = relative_day(d)
        self.day_sub.setText(rel if rel in ("Today", "Tomorrow", "Yesterday") else "")
        items = self.ctx.schedule.day_agenda(d, self.show_tasks.isChecked())
        if not items:
            self.day_layout.addWidget(EmptyState("calendar", "Free day", "Nothing scheduled. Double-click a day to add an event.", compact=True))
        for item in items:
            self.day_layout.addWidget(self._item_widget(item))
        self.day_layout.addStretch(1)

    def _fill_week(self) -> None:
        clear_layout(self.week_layout)
        start = week_start(self._week_anchor, self.week_start)
        end = start + timedelta(days=6)
        self.period_label.setText(f"{format_date(start, self.date_style)} – {format_date(end, self.date_style)}")
        agenda = self.ctx.schedule.agenda(start, end, self.show_tasks.isChecked())
        ref = today()
        for i in range(7):
            d = start + timedelta(days=i)
            card = QFrame()
            card.setProperty("card", True)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(4)
            head = QHBoxLayout()
            head.addWidget(label(format_date(d, self.date_style, with_weekday=True), "section"))
            if d == ref:
                head.addWidget(chip("Today", "accent"))
            head.addStretch(1)
            head.addWidget(tool_button("plus", f"Add event on {format_date(d, self.date_style)}",
                                       lambda d=d: EventDialog(self.ctx, self, day=d).exec(), 16))
            cl.addLayout(head)
            items = agenda.get(d, [])
            if not items:
                cl.addWidget(label("Nothing scheduled", "caption"))
            for item in items:
                cl.addWidget(self._item_widget(item))
            self.week_layout.addWidget(card)
        self.week_layout.addStretch(1)

    def _fill_timetable(self) -> None:
        clear_layout(self.tt_layout)
        entries = self.ctx.schedule.entries()
        if not entries:
            self.tt_layout.addWidget(EmptyState(
                "calendar", "No weekly classes yet",
                "Add the classes or activities that repeat every week. They'll appear on the calendar and on Today.",
                [("Add weekly class", lambda: TimetableDialog(self.ctx, self).exec())]))
            return
        order = [(self.week_start + i) % 7 for i in range(7)]
        ref = today().isoformat()
        for wd in order:
            day_entries = [e for e in entries if e.weekday == wd]
            card = QFrame()
            card.setProperty("card", True)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(4)
            head = QHBoxLayout()
            head.addWidget(label(WEEKDAY_NAMES[wd], "section"), 1)
            head.addWidget(tool_button("plus", f"Add class on {WEEKDAY_NAMES[wd]}",
                                       lambda wd=wd: TimetableDialog(self.ctx, self, weekday=wd).exec(), 16))
            cl.addLayout(head)
            if not day_entries:
                cl.addWidget(label("No classes", "caption"))
            for e in day_entries:
                w = QWidget()
                w.setObjectName("Row")
                w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                r = QHBoxLayout(w)
                r.setContentsMargins(8, 5, 6, 5)
                t = label(f"{format_time(e.start_time, self.clock24)}–{format_time(e.end_time, self.clock24)}", "muted")
                t.setMinimumWidth(96 if self.clock24 else 130)
                r.addWidget(t)
                r.addWidget(label(e.title), 1)
                details = [x for x in (e.subject_name, e.location) if x]
                if e.valid_until and e.valid_until < ref:
                    details.append(f"ended {e.valid_until}")
                elif e.valid_from or e.valid_until:
                    details.append(f"{e.valid_from or '…'} → {e.valid_until or '…'}")
                if details:
                    r.addWidget(label(" · ".join(details), "caption"))
                r.addWidget(tool_button("edit", "Edit this weekly class", lambda e=e: TimetableDialog(self.ctx, self, e).exec(), 16))
                r.addWidget(tool_button("trash", "Delete this weekly class", lambda e=e: self._delete_entry(e), 16))
                cl.addWidget(w)
            self.tt_layout.addWidget(card)
        self.tt_layout.addStretch(1)

    # -- item actions ---------------------------------------------------------------
    def _item_menu(self, item: AgendaItem, anchor: QWidget | None, global_pos=None) -> None:
        menu = QMenu(self)
        if item.kind in ("event", "deadline") and item.recurring:
            menu.addAction("Skip on this day", lambda: self._skip_event(item))
            menu.addAction("Edit every occurrence…", lambda: self._edit_event(item.ref_id))
            menu.addAction("End repeats after this day…", lambda: self._end_event_series(item))
            menu.addSeparator()
            menu.addAction("Delete whole series…", lambda: self._delete_event(item.ref_id))
        elif item.kind in ("event", "deadline"):
            menu.addAction("Edit…", lambda: self._edit_event(item.ref_id))
            menu.addAction("Delete…", lambda: self._delete_event(item.ref_id))
        elif item.kind == "class":
            menu.addAction("Skip on this day", lambda: self._skip(item))
            menu.addAction("Edit every week…", lambda: self._edit_entry(item.ref_id))
            menu.addAction("End series after this day…", lambda: self._end_series(item))
            menu.addSeparator()
            menu.addAction("Delete whole series…", lambda: self._delete_entry(self.ctx.schedule.get_entry(item.ref_id)))
        elif item.kind == "exam":
            menu.addAction("Open in Exams", lambda: self.main.navigate("exams"))
        elif item.kind == "task":
            task = self.ctx.tasks.get(item.ref_id)
            if task:
                menu.addAction("Reopen" if task.done else "Mark complete", lambda: self._toggle_task(task.id, not task.done))
                menu.addAction("Open in Tasks", lambda: self.main.navigate("tasks"))
        menu.exec(global_pos if global_pos is not None else anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _skip_event(self, item: AgendaItem) -> None:
        if guarded(self, lambda: self.ctx.schedule.skip_event_occurrence(item.ref_id, item.date)):
            bus.notify("schedule")
            self.toast(f"Skipped “{item.title}” on {format_date(item.date, self.date_style)}")

    def _end_event_series(self, item: AgendaItem) -> None:
        if confirm(self, "Stop repeating?",
                   f"“{item.title}” will stop repeating after {format_date(item.date, self.date_style)}. "
                   "Earlier occurrences stay on the calendar.", "End repeats", danger=False):
            if guarded(self, lambda: self.ctx.schedule.end_event_series(item.ref_id, item.date)):
                bus.notify("schedule")

    def _toggle_task(self, task_id: int, done: bool) -> None:
        if guarded(self, lambda: self.ctx.tasks.set_completed(task_id, done)):
            bus.notify("tasks")

    def _edit_event(self, event_id: int) -> None:
        event = self.ctx.schedule.get_event(event_id)
        if event:
            EventDialog(self.ctx, self, event).exec()

    def _delete_event(self, event_id: int) -> None:
        event = self.ctx.schedule.get_event(event_id)
        what = (f"“{event.title}” and every repeat of it will be deleted." if event and event.recurrence
                else f"“{event.title}” on {event.date} will be deleted." if event else "")
        if event and confirm(self, "Delete entry?", what):
            if guarded(self, lambda: self.ctx.schedule.delete_event(event_id)):
                bus.notify("schedule")
                self.toast("Entry deleted")

    def _edit_entry(self, entry_id: int) -> None:
        entry = self.ctx.schedule.get_entry(entry_id)
        if entry:
            TimetableDialog(self.ctx, self, entry).exec()

    def _skip(self, item: AgendaItem) -> None:
        if guarded(self, lambda: self.ctx.schedule.skip_occurrence(item.ref_id, item.date)):
            bus.notify("schedule")
            self.toast(f"Skipped “{item.title}” on {format_date(item.date, self.date_style)}", "Undo",
                       lambda: self._unskip(item))

    def _unskip(self, item: AgendaItem) -> None:
        if guarded(self, lambda: self.ctx.schedule.unskip_occurrence(item.ref_id, item.date)):
            bus.notify("schedule")

    def _end_series(self, item: AgendaItem) -> None:
        if confirm(self, "End this weekly class?",
                   f"“{item.title}” will stop repeating after {format_date(item.date, self.date_style)}. "
                   "Earlier weeks stay on the calendar.", "End series", danger=False):
            if guarded(self, lambda: self.ctx.schedule.end_series(item.ref_id, item.date)):
                bus.notify("schedule")

    def _delete_entry(self, entry: TimetableEntry | None) -> None:
        if entry and confirm(self, "Delete weekly class?",
                             f"“{entry.title}” will be removed from every week, past and future. "
                             "To keep past weeks, use “End series” instead."):
            if guarded(self, lambda: self.ctx.schedule.delete_entry(entry.id)):
                bus.notify("schedule")
                self.toast("Weekly class deleted")

    def new_item(self) -> None:
        EventDialog(self.ctx, self, day=self.grid.selected_day).exec()


class ConflictsDialog(FadeDialog):
    """Lists overlapping items so the user can decide what to change (nothing moves automatically)."""

    def __init__(self, page: "CalendarPage", conflicts: list) -> None:
        super().__init__(page)
        self.setWindowTitle("Overlapping times")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Overlapping times", "section"))
        lay.addWidget(label("These items share time on the same day. Open one to change it, or keep both if "
                            "that's intended.", "muted", wrap=True))
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        for day, a, b in conflicts:
            box = QFrame()
            box.setProperty("inset", True)
            r = QVBoxLayout(box)
            r.setContentsMargins(12, 8, 12, 8)
            r.addWidget(label(format_date(day, page.date_style, with_weekday=True), "heading"))
            for it in (a, b):
                row = QHBoxLayout()
                row.addWidget(label(f"{format_time(it.start_time, page.clock24)}–{format_time(it.end_time, page.clock24)}",
                                    "muted"))
                row.addWidget(label(it.title, "", wrap=True), 1)
                row.addWidget(chip(KIND_NAMES[it.kind], KIND_TONES[it.kind]))
                if it.kind in ("event", "deadline"):
                    row.addWidget(button("Edit", "link", on_click=lambda i=it: (self.accept(), page._edit_event(i.ref_id))))
                elif it.kind == "class":
                    row.addWidget(button("Edit", "link", on_click=lambda i=it: (self.accept(), page._edit_entry(i.ref_id))))
                r.addLayout(row)
            bl.addWidget(box)
        bl.addStretch(1)
        area = scroll_wrap(body)
        area.setMinimumHeight(min(420, 90 * max(1, len(conflicts)) + 20))
        lay.addWidget(area, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Close", "primary", on_click=self.accept))
        lay.addLayout(row)
