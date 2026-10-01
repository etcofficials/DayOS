from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from src.models import Habit
from src.repositories.routines import ROUTINES
from src.services.dates import WEEKDAY_SHORT, ValidationError, format_date, format_time, today, week_start
from src.services.streaks import completion_rate
from src.ui.bus import bus
from src.ui.pages.base import Page
from src.ui.theme import theme
from src.ui.widgets.common import (
    Card,
    CollapsibleSection,
    EmptyState,
    FormDialog,
    OptionalTime,
    PageHeader,
    RoundCheck,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    tool_button,
)

WEEKS_SHOWN = 12


def schedule_text(weekdays: int) -> str:
    if weekdays == 127:
        return "Every day"
    if weekdays == 0b0011111:
        return "Weekdays"
    if weekdays == 0b1100000:
        return "Weekends"
    return ", ".join(WEEKDAY_SHORT[i] for i in range(7) if weekdays & (1 << i))


class HabitHistory(QWidget):
    """Weeks × weekdays grid. Click (or arrows + Space) toggles a past day."""

    toggled = Signal(object, bool)  # date, new state

    CELL = 15
    GAP = 4

    def __init__(self, habit: Habit, done: set[date], ref: date, first_weekday: int, date_style: str) -> None:
        super().__init__()
        self.habit = habit
        self.done = done
        self.ref = ref
        self.date_style = date_style
        self.start = week_start(ref, first_weekday) - timedelta(weeks=WEEKS_SHOWN - 1)
        self.first_weekday = first_weekday
        self.cursor: date = ref
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"History for {habit.name}. Use arrow keys and Space to correct past days.")
        w = WEEKS_SHOWN * (self.CELL + self.GAP)
        h = 7 * (self.CELL + self.GAP) + 16
        self.setFixedSize(QSize(w + 30, h))
        theme.changed.connect(self.update)

    def _cell_rect(self, d: date) -> QRectF:
        offset = (d - self.start).days
        col, row = divmod(offset, 7)
        return QRectF(30 + col * (self.CELL + self.GAP), 14 + row * (self.CELL + self.GAP), self.CELL, self.CELL)

    def _date_at(self, pos: QPointF) -> date | None:
        x, y = pos.x() - 30, pos.y() - 14
        if x < 0 or y < 0:
            return None
        col, row = int(x // (self.CELL + self.GAP)), int(y // (self.CELL + self.GAP))
        if col >= WEEKS_SHOWN or row >= 7:
            return None
        return self.start + timedelta(days=col * 7 + row)

    def _describe(self, d: date) -> str:
        state = "done" if d in self.done else ("not scheduled" if not self.habit.is_scheduled(d) else "not done")
        if d > self.ref:
            state = "in the future"
        return f"{format_date(d, self.date_style, with_weekday=True)}: {state}"

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        f = p.font()
        f.setPointSizeF(7.5)
        p.setFont(f)
        p.setPen(theme.color("text3"))
        for row in range(7):
            wd = (self.first_weekday + row) % 7
            if row % 2 == 0:
                p.drawText(QRectF(0, 14 + row * (self.CELL + self.GAP), 26, self.CELL),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, WEEKDAY_SHORT[wd][:2])
        for i in range(WEEKS_SHOWN * 7):
            d = self.start + timedelta(days=i)
            r = self._cell_rect(d)
            if d.day == 1 or i == 0:
                p.setPen(theme.color("text3"))
                p.drawText(QRectF(r.x(), 0, 40, 12), Qt.AlignmentFlag.AlignLeft, d.strftime("%b"))
            scheduled = self.habit.is_scheduled(d)
            if d > self.ref:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color("track"))
                p.drawRoundedRect(r, 4, 4)
            elif d in self.done:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color("accent"))
                p.drawRoundedRect(r, 4, 4)
            elif scheduled and d >= self.habit.start:
                p.setPen(QPen(theme.color("border"), 1.2))
                p.setBrush(theme.color("hover"))
                p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), 4, 4)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color("divider"))
                p.drawEllipse(r.center(), 2, 2)
            if d == self.ref:
                p.setPen(QPen(theme.color("text"), 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 5, 5)
            if self.hasFocus() and d == self.cursor:
                p.setPen(QPen(theme.color("blue"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(-2.5, -2.5, 2.5, 2.5), 5, 5)
        p.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        d = self._date_at(event.position())
        if d:
            QToolTip.showText(event.globalPosition().toPoint(), self._describe(d) + ("" if d > self.ref else " — click to change"), self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        d = self._date_at(event.position())
        if d and d <= self.ref:
            self.cursor = d
            self.toggled.emit(d, d not in self.done)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        moves = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1, Qt.Key.Key_Left: -7, Qt.Key.Key_Right: 7}
        if event.key() in moves:
            nd = self.cursor + timedelta(days=moves[event.key()])
            if self.start <= nd <= self.ref:
                self.cursor = nd
                self.setAccessibleDescription(self._describe(nd))
                QToolTip.showText(self.mapToGlobal(self._cell_rect(nd).center().toPoint()), self._describe(nd), self)
                self.update()
            return
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.toggled.emit(self.cursor, self.cursor not in self.done)
            return
        super().keyPressEvent(event)

    def focusInEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().focusOutEvent(e)


class HabitDialog(FormDialog):
    def __init__(self, ctx, parent=None, habit: Habit | None = None) -> None:
        super().__init__("Edit habit" if habit else "New habit", parent)
        self.ctx = ctx
        self.habit = habit
        self.name = QLineEdit(habit.name if habit else "")
        self.name.setPlaceholderText("e.g. Read for 20 minutes")
        self.add_row("Name", self.name)
        self.desc = QPlainTextEdit(habit.description if habit else "")
        self.desc.setPlaceholderText("Why it matters to you (optional)")
        self.desc.setFixedHeight(64)
        self.add_row("Description", self.desc)
        days = QHBoxLayout()
        days.setSpacing(4)
        self.day_buttons: list[QPushButton] = []
        mask = habit.weekdays if habit else 127
        for i, name in enumerate(WEEKDAY_SHORT):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(bool(mask & (1 << i)))
            b.setProperty("segment", True)
            b.setAccessibleName(f"Scheduled on {name}")
            self.day_buttons.append(b)
            days.addWidget(b)
        self.add_row("Repeat on", days)
        presets = QHBoxLayout()
        for text, m in (("Every day", 127), ("Weekdays", 0b0011111), ("Weekends", 0b1100000)):
            presets.addWidget(button(text, "link", on_click=lambda m=m: self._preset(m)))
        presets.addStretch(1)
        self.add_row("", presets)
        self.target = QSpinBox()
        self.target.setRange(0, 7)
        self.target.setSpecialValueText("Every scheduled day")
        self.target.setSuffix(" times a week")
        self.target.setValue(habit.weekly_target or 0 if habit else 0)
        self.target.setToolTip("Flexible habits only need to be done a number of times each week, on any day.")
        self.add_row("Goal", self.target)
        self.remind = OptionalTime("Remind me at", habit.remind_time if habit else None,
                                   bool(ctx.settings.get("clock_24h")))
        self.add_row("Reminder", self.remind)
        self.form.addRow(label("Reminders appear in DayOS (and as Windows notifications if you allow them in "
                               "Settings). They stop for the day once the habit is done.", "caption", wrap=True))
        self.name.setFocus()

    def _preset(self, mask: int) -> None:
        for i, b in enumerate(self.day_buttons):
            b.setChecked(bool(mask & (1 << i)))

    def save(self) -> None:
        mask = sum(1 << i for i, b in enumerate(self.day_buttons) if b.isChecked())
        if not mask:
            raise ValidationError("Choose at least one day of the week.")
        target = self.target.value() or None
        remind = self.remind.value()
        if self.habit:
            self.ctx.habits.update(self.habit.id, self.name.text(), self.desc.toPlainText(), mask, remind, target)
        else:
            self.ctx.habits.create(self.name.text(), self.desc.toPlainText(), mask, remind_time=remind,
                                   weekly_target=target)
        if remind and not self.ctx.settings.get("notify.habit"):
            self.ctx.settings.set("notify.habit", True)
        bus.notify("habits", "reminders")


class RoutinesCard(Card):
    """Optional morning / evening checklists, ticked off per day."""

    def __init__(self, page: "HabitsPage") -> None:
        super().__init__("Routines", "routine")
        self.page = page
        self.collapse = CollapsibleSection("Morning checklist and evening wind-down", expanded=False)
        self.body.addWidget(self.collapse)
        row = QHBoxLayout()
        row.setSpacing(18)
        self.columns: dict[str, QVBoxLayout] = {}
        self.adders: dict[str, QLineEdit] = {}
        for key, title in ROUTINES.items():
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(label(title, "heading"))
            items = QVBoxLayout()
            items.setSpacing(2)
            col.addLayout(items)
            add = QLineEdit()
            add.setPlaceholderText("Add an item and press Enter")
            add.setAccessibleName(f"Add to {title}")
            add.returnPressed.connect(lambda k=key: self._add(k))
            col.addWidget(add)
            col.addStretch(1)
            self.columns[key] = items
            self.adders[key] = add
            row.addLayout(col, 1)
        self.collapse.body.addLayout(row)
        self.summary = label("", "caption")
        self.add_action(self.summary)

    def refresh(self) -> None:
        ctx = self.page.ctx
        day = today()
        done = ctx.routines.done_on(day)
        total = done_n = 0
        for key, layout in self.columns.items():
            clear_layout(layout)
            items = ctx.routines.items(key)
            if not items:
                layout.addWidget(label("No items yet.", "caption"))
            for item in items:
                r = QHBoxLayout()
                cb = QCheckBox(item.title)
                cb.setChecked(item.id in done)
                cb.toggled.connect(lambda on, i=item.id: self._tick(i, on))
                r.addWidget(cb, 1)
                r.addWidget(tool_button("close", f"Remove “{item.title}”", lambda i=item.id: self._remove(i), 14))
                layout.addLayout(r)
                total += 1
                done_n += item.id in done
        self.summary.setText(f"{done_n} of {total} done today" if total else "")

    def _add(self, key: str) -> None:
        text = self.adders[key].text().strip()
        if text and guarded(self, lambda: self.page.ctx.routines.add(key, text)):
            self.adders[key].clear()
            self.refresh()
            self.collapse.set_expanded(True)

    def _tick(self, item_id: int, on: bool) -> None:
        if guarded(self, lambda: self.page.ctx.routines.set_done(item_id, today(), on)):
            bus.notify("routines")

    def _remove(self, item_id: int) -> None:
        if guarded(self, lambda: self.page.ctx.routines.remove(item_id)):
            self.refresh()


class HabitsPage(Page):
    domains = ("habits", "settings", "routines")
    title = "Habits"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.root.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(34, 28, 34, 28)
        outer.setSpacing(16)
        self.header = PageHeader("Small rituals", "", eyebrow="Habits")
        self.show_archived = QCheckBox("Show archived")
        self.show_archived.toggled.connect(lambda _: self.refresh())
        self.header.add_action(self.show_archived)
        self.header.add_action(button("New habit", "primary", "plus", self.new_item, "New habit (Ctrl+N)"))
        outer.addWidget(self.header)
        rules = label(
            "Streaks count consecutive scheduled days you completed. Days a habit isn't scheduled never break "
            "a streak, and today only counts once it's done. Click any past day in the history to correct it.",
            "caption", wrap=True)
        outer.addWidget(rules)
        self.routines = RoutinesCard(self)
        outer.addWidget(self.routines)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(12)
        outer.addLayout(self.list_layout)
        outer.addStretch(1)
        self.root.addWidget(scroll_wrap(content))

    def refresh(self) -> None:
        clear_layout(self.list_layout)
        ref = today()
        self.routines.refresh()
        habits = self.ctx.habits.list(include_archived=self.show_archived.isChecked())
        active = [h for h in habits if not h.archived]
        done_today = self.ctx.habits.done_on(ref)
        due_today = [h for h in active if h.is_scheduled(ref)]
        self.header.set_subtitle(
            f"{sum(1 for h in due_today if h.id in done_today)} of {len(due_today)} done today"
            if due_today else ("No habits scheduled today" if active else "Build gentle routines, one day at a time.")
        )
        if not habits:
            self.list_layout.addWidget(EmptyState(
                "habits", "No habits yet",
                "Create a habit and choose the days it applies to. Tick it off each day to build a streak.",
                [("Create a habit", self.new_item)]))
            return
        for habit in habits:
            self.list_layout.addWidget(self._habit_card(habit, ref, habit.id in done_today))

    def _habit_card(self, habit: Habit, ref: date, done_today: bool) -> Card:
        card = Card()
        top = QHBoxLayout()
        top.setSpacing(12)
        scheduled_today = habit.is_scheduled(ref) and not habit.archived
        check = RoundCheck(done_today, 22, f"Done today: {habit.name}")
        check.setEnabled(not habit.archived)
        check.setToolTip("Mark done for today" if scheduled_today else "Not scheduled today — you can still log it")
        check.toggled.connect(lambda on: self._set_done(habit.id, ref, on))
        top.addWidget(check, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.addWidget(label(habit.name, "section"))
        name_row.addWidget(chip(schedule_text(habit.weekdays), "accent"))
        if habit.weekly_target:
            ws0 = week_start(ref, self.week_start)
            n = self.ctx.habits.week_count(habit.id, ws0)
            name_row.addWidget(chip(f"{n} of {habit.weekly_target} this week",
                                    "accent" if n >= habit.weekly_target else "blue"))
        if habit.remind_time:
            name_row.addWidget(label(f"⏰ {format_time(habit.remind_time, self.clock24)}", "caption"))
        if habit.archived:
            name_row.addWidget(chip("Archived", ""))
        name_row.addStretch(1)
        text.addLayout(name_row)
        if habit.description:
            text.addWidget(label(habit.description, "muted", wrap=True))
        top.addLayout(text, 1)
        more = tool_button("more", f"More actions for {habit.name}")
        more.clicked.connect(lambda: self._menu(habit, more))
        top.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(top)

        done = self.ctx.habits.done_dates(habit.id)
        info = self.ctx.habits.streak_info(habit, ref)
        ws = week_start(ref, self.week_start)
        week_done, week_total = completion_rate(habit.weekdays, habit.start, done, ws, ws + timedelta(days=6), ref)
        m_done, m_total = completion_rate(habit.weekdays, habit.start, done, ref - timedelta(days=29), ref, ref)
        stats = QHBoxLayout()
        stats.setSpacing(28)
        for value, caption in (
            (f"{info.current}", "current streak"),
            (f"{info.longest}", "longest streak"),
            (f"{week_done}/{week_total}" if week_total else "–", "this week"),
            (f"{round(100 * m_done / m_total)}%" if m_total else "–", "last 30 days"),
        ):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(value, "metric"))
            col.addWidget(label(caption, "metricLabel"))
            stats.addLayout(col)
        stats.addStretch(1)
        stats_box = QVBoxLayout()
        stats_box.addLayout(stats)
        stats_box.addStretch(1)
        history = HabitHistory(habit, done, ref, self.week_start, self.date_style)
        history.toggled.connect(lambda d, on, hid=habit.id: self._set_done(hid, d, on))
        history.setEnabled(not habit.archived)
        wrap = QHBoxLayout()
        wrap.addLayout(stats_box, 1)
        wrap.addWidget(history, 0, Qt.AlignmentFlag.AlignRight)
        card.body.addLayout(wrap)
        return card

    def _set_done(self, habit_id: int, day: date, done: bool) -> None:
        def run() -> None:
            self.ctx.habits.set_done(habit_id, day, done)
            bus.notify("habits")

        guarded(self, run, "Couldn't update the habit")

    def _menu(self, habit: Habit, anchor: QWidget) -> None:
        menu = QMenu(self)
        menu.addAction("Edit…", lambda: HabitDialog(self.ctx, self, habit).exec())
        if habit.archived:
            menu.addAction("Restore", lambda: self._archive(habit, False))
        else:
            menu.addAction("Archive", lambda: self._archive(habit, True))
        menu.addSeparator()
        menu.addAction("Delete…", lambda: self._delete(habit))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _archive(self, habit: Habit, archived: bool) -> None:
        if guarded(self, lambda: self.ctx.habits.set_archived(habit.id, archived)):
            bus.notify("habits")
            self.toast("Habit archived — its history is kept" if archived else "Habit restored")

    def _delete(self, habit: Habit) -> None:
        count = len(self.ctx.habits.done_dates(habit.id))
        if confirm(self, "Delete habit?",
                   f"“{habit.name}” and its {count} completion record(s) will be permanently deleted. "
                   "Archive it instead if you'd like to keep the history."):
            if guarded(self, lambda: self.ctx.habits.delete(habit.id)):
                bus.notify("habits")
                self.toast("Habit deleted")

    def new_item(self) -> None:
        HabitDialog(self.ctx, self).exec()
