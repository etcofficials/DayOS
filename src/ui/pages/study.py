from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLineEdit,
    QGridLayout,
    QHBoxLayout,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.services.dates import WEEKDAY_SHORT, format_date, format_duration, format_time, now, today, week_start
from src.services.timer import FOCUS, LONG_BREAK, SHORT_BREAK, SLEEP_GAP_SECONDS, FocusTimer
from src.repositories.study import KINDS as SESSION_KINDS, new_session_uid
from src.ui.bus import bus
from src.ui.dialogs import ManualStudyDialog, subject_items
from src.ui.pages.base import Page
from src.ui.subjects_dialog import SubjectsDialog
from src.ui.widgets.charts import BarChart, ProgressRing
from src.ui.widgets.common import (
    Card,
    EmptyState,
    IdCombo,
    PageHeader,
    ResponsiveGrid,
    SegmentBar,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    install_shortcut,
    label,
    scroll_wrap,
    tool_button,
)

log = logging.getLogger(__name__)

CHECKPOINT_KEY = "state.study.active"
MODE_LABELS = {FOCUS: "Focus", SHORT_BREAK: "Short break", LONG_BREAK: "Long break"}
MIN_SAVE_SECONDS = 60


def _mmss(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class CloseDialog(QDialog):
    """Asked when closing DayOS while a focus session is in progress."""

    SAVE, KEEP = 1, 2

    def __init__(self, parent, elapsed: float) -> None:
        super().__init__(parent)
        self.setWindowTitle("Focus session in progress")
        self.choice = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label("A focus session is still running", "section"))
        lay.addWidget(label(
            f"You've studied for {format_duration(elapsed)} so far. Save it now, or keep it and DayOS will offer "
            "to save it the next time it opens.", "muted", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", "ghost", on_click=self.reject))
        row.addWidget(button("Keep for later", "", on_click=lambda: self._done(self.KEEP)))
        save = button("Save session & quit", "primary", on_click=lambda: self._done(self.SAVE))
        save.setDefault(True)
        row.addWidget(save)
        lay.addLayout(row)

    def _done(self, choice: int) -> None:
        self.choice = choice
        self.accept()


class StudyPage(Page):
    domains = ("study", "subjects", "settings", "tasks", "projects")
    title = "Focus"
    timer_changed = Signal()  # the dashboard's Study nook mirrors the one real timer

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.timer = FocusTimer()
        self.focus_count = 0
        self._last_label = ""
        self._last_checkpoint = 0.0
        self._last_tick_clock: float | None = None
        self.root.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(34, 28, 34, 28)
        outer.setSpacing(16)
        header = PageHeader("Focus", "A calm focus timer and an honest record of your time.",
                            eyebrow="Focus & study time")
        self.focus_mode_btn = button("Focus mode", "ghost", "eye", self.toggle_focus_mode,
                                     "Hide everything except the timer (Esc to leave)")
        header.add_action(self.focus_mode_btn)
        header.add_action(button("Subjects", "ghost", "subject", lambda: SubjectsDialog(self.ctx, self).exec()))
        header.add_action(button("Log session", "", "plus", lambda: ManualStudyDialog(self.ctx, self, self.subject.current_id()).exec(),
                                 "Record a session you did without the timer"))
        outer.addWidget(header)

        top = ResponsiveGrid((0, 1 << 20))  # two columns when both cards fit, otherwise stacked
        outer.addWidget(top)

        # -- timer card
        self.timer_card = Card("Focus timer", "study")
        self.mode = SegmentBar([(FOCUS, "Focus"), (SHORT_BREAK, "Short break"), (LONG_BREAK, "Long break")],
                               style="accent")
        self.mode.changed.connect(self._mode_changed)
        self.timer_card.body.addWidget(self.mode, 0, Qt.AlignmentFlag.AlignHCenter)
        presets = QHBoxLayout()
        presets.addStretch(1)
        presets.addWidget(label("Presets", "caption"))
        for focus_m, break_m in ((25, 5), (50, 10), (90, 20)):
            presets.addWidget(button(f"{focus_m}/{break_m}", "link", on_click=lambda f=focus_m, b=break_m: self.apply_preset(f, b)))
        presets.addStretch(1)
        self.presets_row = QWidget()
        self.presets_row.setLayout(presets)
        self.timer_card.body.addWidget(self.presets_row)
        ring_holder = QWidget()
        ring_holder.setMinimumHeight(250)
        grid = QGridLayout(ring_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        self.ring = ProgressRing(240)
        grid.addWidget(self.ring, 0, 0)
        center = QVBoxLayout()
        center.setSpacing(0)
        center.addStretch(1)
        self.time_label = label("25:00", "timer")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setAccessibleName("Time remaining")
        self.state_label = label("Ready when you are", "muted")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.addWidget(self.time_label)
        center.addWidget(self.state_label)
        center.addStretch(1)
        overlay = QWidget()
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setLayout(center)
        grid.addWidget(overlay, 0, 0)
        self.timer_card.body.addWidget(ring_holder)

        form = QHBoxLayout()
        form.setSpacing(8)
        self.subject = IdCombo("No subject")
        self.subject.setAccessibleName("Subject")
        form.addWidget(self.subject, 1)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setSuffix(" min")
        self.minutes.setAccessibleName("Duration in minutes")
        self.minutes.valueChanged.connect(self._duration_changed)
        form.addWidget(self.minutes)
        self.timer_card.body.addLayout(form)
        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        self.task_combo = IdCombo("Not linked to a task")
        self.task_combo.setAccessibleName("Task this session is for")
        self.task_combo.setToolTip("Time from this session is added to the task's 'time spent'.")
        link_row.addWidget(self.task_combo, 2)
        self.project_combo = IdCombo("No project")
        self.project_combo.setAccessibleName("Project this session is for")
        link_row.addWidget(self.project_combo, 1)
        self.topic_combo = IdCombo("No course topic")
        self.topic_combo.setAccessibleName("StudyForge course topic this session is for")
        self.topic_combo.setToolTip("Link the session to a StudyForge chapter or topic.")
        link_row.addWidget(self.topic_combo, 1)
        self.kind_combo = QComboBox()
        for key, text in SESSION_KINDS.items():
            self.kind_combo.addItem(text, key)
        self.kind_combo.setAccessibleName("Type of session")
        self.kind_combo.setToolTip("Study and reading count as learning; practice and work count as doing.")
        link_row.addWidget(self.kind_combo)
        link_row.setContentsMargins(0, 0, 0, 0)
        self.link_box = QWidget()
        self.link_box.setLayout(link_row)
        self.timer_card.body.addWidget(self.link_box)
        self.session_note = QLineEdit()
        self.session_note.setPlaceholderText("Session note (optional): what you're working on")
        self.session_note.setAccessibleName("Session note")
        self.session_note.setMaxLength(500)
        self.timer_card.body.addWidget(self.session_note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.reset_btn = tool_button("reset", "Reset timer", self._reset, 20)
        buttons.addWidget(self.reset_btn)
        self.start_btn = button("Start", "primary", "play", self._start_pause, "Start or pause (Ctrl+Enter)")
        self.start_btn.setMinimumWidth(140)
        buttons.addWidget(self.start_btn)
        self.finish_btn = tool_button("stop", "Stop now and save the time studied", self._finish_early, 20)
        buttons.addWidget(self.finish_btn)
        buttons.addStretch(1)
        self.timer_card.body.addLayout(buttons)
        self.notice = label("", "success", wrap=True)
        self.notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notice.hide()
        self.timer_card.body.addWidget(self.notice)
        top.add(self.timer_card)

        # -- stats card
        self.stats_card = Card("This week", "insights")
        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(28)
        self.stats_card.body.addLayout(self.stats_row)
        self.week_chart = BarChart("accent", lambda v: f"{v:.0f}m")
        self.week_chart.setMinimumHeight(180)
        self.stats_card.body.addWidget(self.week_chart, 1)
        self.subject_line = label("", "caption", wrap=True)
        self.stats_card.body.addWidget(self.subject_line)
        top.add(self.stats_card)

        # -- history
        self.history_card = Card("Recent sessions", "clock")
        outer.addWidget(self.history_card)
        outer.addStretch(1)
        self.root.addWidget(scroll_wrap(content))

        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._on_tick)
        install_shortcut(self, "Ctrl+Return", self._start_pause)
        install_shortcut(self, "Escape", lambda: self.toggle_focus_mode(False))
        self._focus_mode = False
        self._break_hinted = False
        self._tray: QSystemTrayIcon | None = None
        self._apply_mode(FOCUS)
        self._update_controls()

    # -- data ---------------------------------------------------------------
    def refresh(self) -> None:
        self.subject.set_items(subject_items(self.ctx))
        self.subject.setEnabled(not self.timer.is_active)
        horizon = today() + timedelta(days=7)
        open_tasks = [t for t in self.ctx.tasks.list("all", limit=400)
                      if not t.done and (t.due is None or t.due <= horizon)][:80]
        self.task_combo.set_items([(t.id, t.title[:70]) for t in open_tasks])
        self.project_combo.set_items(self.ctx.projects.choices())
        self.project_combo.setVisible(self.project_combo.count() > 1)
        self.topic_combo.set_items(self._topic_choices())
        self.topic_combo.setVisible(self.topic_combo.count() > 1)
        ref = today()
        ws = week_start(ref, self.week_start)
        daily = self.ctx.study.daily_seconds(ws, ws + timedelta(days=6))
        self.week_chart.set_data(
            [(WEEKDAY_SHORT[(ws + timedelta(days=i)).weekday()], daily.get(ws + timedelta(days=i), 0) / 60) for i in range(7)]
        )
        clear_layout(self.stats_row)
        week_total = sum(daily.values())
        days_studied = sum(1 for v in daily.values() if v > 0)
        for value, caption in ((self.ctx.study.seconds_on(ref), "today"), (week_total, "this week")):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(format_duration(value) if value else "0 min", "metric"))
            col.addWidget(label(caption, "metricLabel"))
            self.stats_row.addLayout(col)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(f"{days_studied}/7", "metric"))
        col.addWidget(label("days studied", "metricLabel"))
        self.stats_row.addLayout(col)
        self.stats_row.addStretch(1)
        by_subject = self.ctx.study.by_subject(ws, ws + timedelta(days=6))
        self.subject_line.setText(
            "By subject: " + ", ".join(f"{n} {format_duration(s)}" for n, s in by_subject[:6]) if by_subject else
            "Study time by subject will appear here once you've recorded a session this week."
        )
        self._fill_history()

    def _fill_history(self) -> None:
        body = self.history_card.body
        clear_layout(body)
        sessions = self.ctx.study.history(40)
        if not sessions:
            body.addWidget(EmptyState("clock", "No sessions yet",
                                      "Start the focus timer, or log a session you've already done.",
                                      [("Log session", lambda: ManualStudyDialog(self.ctx, self).exec())], compact=True))
            return
        last_day = None
        for s in sessions:
            d = date.fromisoformat(s.date)
            if d != last_day:
                body.addWidget(label(format_date(d, self.date_style, with_weekday=True), "caption"))
                last_day = d
            w = QWidget()
            w.setObjectName("Row")
            w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row = QHBoxLayout(w)
            row.setContentsMargins(8, 4, 6, 4)
            started = datetime.fromisoformat(s.started_at)
            row.addWidget(label(format_time(started.time(), self.clock24), "muted"))
            row.addWidget(label(format_duration(s.actual_seconds)))
            row.addWidget(label(s.subject_name or "No subject", "muted"))
            if s.kind and s.kind != "study":
                row.addWidget(chip(SESSION_KINDS.get(s.kind, s.kind), "blue"))
            if s.task_title:
                row.addWidget(label(f"→ {s.task_title}", "caption"))
            if s.project_name:
                row.addWidget(chip(s.project_name, "accent"))
            if s.note:
                row.addWidget(label(s.note, "caption"), 1)
            else:
                row.addStretch(1)
            if s.source == "manual":
                row.addWidget(chip("Logged manually", ""))
            elif s.source == "recovered":
                row.addWidget(chip("Recovered", "amber"))
            elif not s.completed:
                row.addWidget(chip("Stopped early", ""))
            row.addWidget(tool_button("trash", "Delete this session", lambda sid=s.id: self._delete_session(sid), 15))
            body.addWidget(w)

    def _delete_session(self, session_id: int) -> None:
        if confirm(self, "Delete study session?", "This session will be removed from your history and totals."):
            if guarded(self, lambda: self.ctx.study.delete(session_id)):
                bus.notify("study")

    # -- timer controls ---------------------------------------------------------
    def _durations(self) -> dict[str, int]:
        s = self.ctx.settings
        return {FOCUS: int(s.get("study.focus_minutes")), SHORT_BREAK: int(s.get("study.short_break")),
                LONG_BREAK: int(s.get("study.long_break"))}

    def _apply_mode(self, mode: str) -> None:
        self.mode.set_current(mode)
        self.minutes.blockSignals(True)
        self.minutes.setValue(self._durations()[mode])
        self.minutes.blockSignals(False)
        self.timer.mode = mode
        self.timer.duration_s = self.minutes.value() * 60
        self._render()

    def _mode_changed(self, mode: str) -> None:
        if self.timer.is_active:
            self.mode.set_current(self.timer.mode)
            self.toast("Reset or finish the current timer before switching")
            return
        self.timer.reset()
        self._apply_mode(mode)
        self._update_controls()

    def _duration_changed(self, value: int) -> None:
        if not self.timer.is_active:
            self.timer.duration_s = value * 60
            self.timer.finished = False
            key = {FOCUS: "study.focus_minutes", SHORT_BREAK: "study.short_break", LONG_BREAK: "study.long_break"}[self.timer.mode]
            if self.ctx.settings.get(key) != value:
                self.ctx.settings.set(key, value)
            self._render()

    def _start_pause(self) -> None:
        state = self.timer.state
        if state == "running":
            self.timer.pause()
            self._tick.stop()
            self._save_checkpoint()
        elif state == "paused":
            self.timer.resume()
            self._last_tick_clock = None
            self._tick.start()
        else:
            self.notice.hide()
            mode = self.mode.current()
            uid = new_session_uid() if mode == FOCUS else None
            self.timer.start(self.minutes.value() * 60, mode, uid, self.subject.current_id())
            self.timer.extra = {"task_id": self.task_combo.current_id(), "project_id": self.project_combo.current_id(),
                                "node_id": self.topic_combo.current_id(),
                                "kind": self.kind_combo.currentData(), "note": self.session_note.text().strip()}
            self._break_hinted = False
            self._last_tick_clock = None
            self._tick.start()
            self._save_checkpoint()
        self._update_controls()
        self._render()

    def _reset(self) -> None:
        if self.timer.mode == FOCUS and self.timer.is_active and self.timer.elapsed() >= MIN_SAVE_SECONDS:
            if not confirm(self, "Reset without saving?",
                           f"The {format_duration(self.timer.elapsed())} studied in this session won't be recorded. "
                           "Use the stop button instead to save it.", "Reset"):
                return
        self._tick.stop()
        self.timer.reset()
        self._clear_checkpoint()
        self._apply_mode(self.mode.current())
        self._update_controls()

    def _finish_early(self) -> None:
        if not self.timer.is_active:
            return
        if self.timer.mode != FOCUS:
            self._reset()
            return
        self.timer.pause()
        self._tick.stop()
        elapsed = self.timer.elapsed()
        if elapsed < MIN_SAVE_SECONDS:
            if confirm(self, "Very short session", "Sessions under a minute aren't saved. Discard it?", "Discard"):
                self.timer.reset()
                self._clear_checkpoint()
                self._apply_mode(FOCUS)
            else:
                self.timer.resume()
                self._tick.start()
            self._update_controls()
            return
        if self._record(completed=False):
            self.notice.setText(f"Saved {format_duration(elapsed)} of focus. Nice work.")
            self.notice.show()
        self.timer.reset()
        self._apply_mode(FOCUS)
        self._update_controls()

    def _record(self, completed: bool, source: str = "timer") -> bool:
        t = self.timer
        if not t.session_uid or not t.started_wall:
            return False
        seconds = int(round(t.elapsed()))
        extra = t.extra or {}
        note = self.session_note.text().strip() or str(extra.get("note") or "")
        ok = guarded(self, lambda: self.ctx.study.record(
            session_uid=t.session_uid, subject_id=t.subject_id, started_at=t.started_wall,
            actual_seconds=seconds, planned_minutes=t.duration_s // 60, completed=completed, source=source,
            note=note, task_id=extra.get("task_id"), project_id=extra.get("project_id"),
            kind=extra.get("kind") or "study", node_id=self._existing_node(extra.get("node_id")),
        ), "Couldn't save the study session")
        if ok:
            self._clear_checkpoint()
            self.session_note.clear()
            bus.notify("study", "tasks", "projects")
        return ok

    # -- ticking ------------------------------------------------------------------
    def _on_tick(self) -> None:
        now_clock = self.timer.clock()
        last = self._last_tick_clock
        self._last_tick_clock = now_clock
        if last is not None and now_clock - last > SLEEP_GAP_SECONDS and self.timer.state == "running":
            # The computer was probably asleep: don't count that time as study.
            self.timer.pause_at(last)
            self._tick.stop()
            self._save_checkpoint()
            self._update_controls()
            self._render()
            self.notice.setText("Paused while your computer was asleep. Resume when you're ready.")
            self.notice.show()
            return
        if self.timer.check_finished():
            self._tick.stop()
            self._on_finished()
            return
        self._render()
        if self.timer.state == "running" and self.timer.mode == FOCUS:
            elapsed = self.timer.elapsed()
            if elapsed - self._last_checkpoint >= 30:
                self._save_checkpoint()
            limit = int(self.ctx.settings.get("focus.break_reminder")) * 60
            if limit and elapsed >= limit and not self._break_hinted:
                self._break_hinted = True
                self.notice.setText(f"You've been focusing for {format_duration(elapsed)}. A short break helps — "
                                    "the timer keeps going until you pause it.")
                self.notice.show()
                self.toast("Time for a short break?")

    def _on_finished(self) -> None:
        mode = self.timer.mode
        if mode == FOCUS:
            self._record(completed=True)
            self.focus_count += 1
            cycles = int(self.ctx.settings.get("focus.cycles"))
            nxt = LONG_BREAK if self.focus_count % cycles == 0 else SHORT_BREAK
            message = f"Focus session complete — {format_duration(self.timer.duration_s)} recorded. Time for a {MODE_LABELS[nxt].lower()}."
        else:
            nxt = FOCUS
            message = "Break's over. Ready for another focus session when you are."
        self.timer.reset()
        self._apply_mode(nxt)
        self.notice.setText(message)
        self.notice.show()
        self._update_controls()
        self.ring.pulse()
        self._notify_desktop(message)
        _flash_taskbar(self)

    def _notify_desktop(self, message: str) -> None:
        if not self.ctx.settings.get("notify_desktop") or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(self.main.windowIcon(), self)
            self._tray.setToolTip("DayOS")
        self._tray.show()
        self._tray.showMessage("DayOS", message, self.main.windowIcon(), 6000)
        QTimer.singleShot(8000, self._tray.hide)

    def _render(self) -> None:
        t = self.timer
        remaining = t.remaining() if t.state != "idle" else t.duration_s
        text = _mmss(remaining)
        if text != self._last_label:
            self._last_label = text
            self.time_label.setText(text)
        frac = t.elapsed() / t.duration_s if t.duration_s and t.state != "idle" else 0.0
        self.ring.set_fraction(frac, "accent" if t.mode == FOCUS else "blue")
        states = {"idle": "Ready when you are", "running": MODE_LABELS[t.mode], "paused": "Paused",
                  "finished": "Done"}
        subject = self.subject.currentText() if t.mode == FOCUS and self.subject.current_id() else ""
        self.state_label.setText(states[t.state] + (f" · {subject}" if subject and t.state != "idle" else ""))
        hint = ""
        if t.state == "running":
            hint = f"{MODE_LABELS[t.mode]} · {text} left"
        elif t.state == "paused":
            hint = f"{MODE_LABELS[t.mode]} paused · {text} left"
        self.main.set_timer_hint(hint)
        self.timer_changed.emit()

    def _update_controls(self) -> None:
        state = self.timer.state
        from src.ui.icons import bind_icon

        if state == "running":
            self.start_btn.setText("Pause")
            bind_icon(self.start_btn, "pause", "on_primary", 16)
        else:
            self.start_btn.setText("Resume" if state == "paused" else "Start")
            bind_icon(self.start_btn, "play", "on_primary", 16)
        active = self.timer.is_active
        self.reset_btn.setEnabled(active)
        self.finish_btn.setEnabled(active)
        self.subject.setEnabled(not active)
        self.minutes.setEnabled(not active)
        self.link_box.setEnabled(not active)
        self.presets_row.setEnabled(not active)
        self.timer_changed.emit()

    def apply_preset(self, focus_minutes: int, break_minutes: int) -> None:
        if self.timer.is_active:
            return
        self.ctx.settings.set("study.focus_minutes", focus_minutes)
        self.ctx.settings.set("study.short_break", break_minutes)
        self.ctx.settings.set("study.long_break", min(120, break_minutes * 3))
        self._apply_mode(self.mode.current())
        self.toast(f"Focus {focus_minutes} min, breaks {break_minutes} min")

    def toggle_focus_mode(self, on: bool | None = None) -> None:
        """Reduced-distraction layout: just the timer. Never blocks or changes other apps."""
        on = (not self._focus_mode) if on is None else on
        if on == self._focus_mode:
            return
        self._focus_mode = on
        # A temporary fold: the sidebar preference the user saved is left alone.
        if on:
            self._was_collapsed = self.main._collapsed
            self.main.set_sidebar_collapsed(True, remember=False)
        elif not getattr(self, "_was_collapsed", False):
            self.main.set_sidebar_collapsed(False, remember=False)
        for w in (self.stats_card, self.history_card):
            w.setVisible(not on)
        self.focus_mode_btn.setText("Leave focus mode" if on else "Focus mode")

    def _topic_choices(self) -> list[tuple[int, str]]:
        """StudyForge chapters and topics of active courses, as "Course › Topic"."""
        try:
            rows = self.ctx.db.query(
                "SELECT n.id, c.name, n.title FROM sf_nodes n JOIN sf_courses c ON c.id = n.course_id "
                "WHERE c.status = 'active' AND n.kind IN ('unit', 'chapter', 'topic') "
                "ORDER BY c.name COLLATE NOCASE, n.position, n.id LIMIT 300")
        except Exception:  # StudyForge tables missing: simply no topics to offer
            return []
        return [(int(r[0]), f"{r[1]} › {r[2]}"[:80]) for r in rows]

    def _existing_node(self, node_id) -> int | None:
        if not node_id:
            return None
        return int(node_id) if self.ctx.db.scalar("SELECT 1 FROM sf_nodes WHERE id = ?", (node_id,)) else None

    def link_topic(self, node_id: int) -> None:
        """Pre-select a StudyForge topic for the next focus session (used by StudyForge)."""
        self.topic_combo.set_items(self._topic_choices())
        self.topic_combo.setVisible(self.topic_combo.count() > 1)
        self.topic_combo.set_current_id(node_id)

    def link_task(self, task_id: int) -> None:
        """Pre-select a task for the next session (e.g. 'Focus on this' from a task)."""
        if not self.timer.is_active:
            self.refresh()
            if self.task_combo.findData(task_id) < 0:
                task = self.ctx.tasks.get(task_id)
                if task:
                    self.task_combo.addItem(task.title[:70], task.id)
            self.task_combo.set_current_id(task_id)

    # -- public API used by the Today dashboard ------------------------------------
    def start_pause(self) -> None:
        self._start_pause()

    def choose_mode(self, mode: str) -> None:
        if mode != self.timer.mode or not self.timer.is_active:
            self._mode_changed(mode)

    def choose_subject(self, subject_id: int | None) -> None:
        if not self.timer.is_active:
            self.subject.set_current_id(subject_id)

    def dashboard_state(self) -> dict:
        t = self.timer
        remaining = t.remaining() if t.state != "idle" else t.duration_s
        return {
            "text": _mmss(remaining),
            "fraction": t.elapsed() / t.duration_s if t.duration_s and t.state != "idle" else 0.0,
            "state": t.state,
            "mode": t.mode,
            "mode_label": MODE_LABELS[t.mode],
            "active": t.is_active,
            "subject_id": self.subject.current_id(),
        }

    def timer_summary(self) -> str:
        t = self.timer
        if not t.is_active:
            return ""
        return f"{MODE_LABELS[t.mode]} {'running' if t.state == 'running' else 'paused'} · {_mmss(t.remaining())} left"

    # -- crash safety -----------------------------------------------------------------
    def _save_checkpoint(self) -> None:
        data = self.timer.checkpoint()
        if data is None:
            return
        try:
            self.ctx.settings.set(CHECKPOINT_KEY, data)
            self._last_checkpoint = self.timer.elapsed()
        except Exception:
            log.warning("Could not save timer checkpoint", exc_info=True)

    def _clear_checkpoint(self) -> None:
        self._last_checkpoint = 0.0
        if self.ctx.settings.get(CHECKPOINT_KEY) is not None:
            try:
                self.ctx.settings.set(CHECKPOINT_KEY, None)
            except Exception:
                log.warning("Could not clear timer checkpoint", exc_info=True)

    def check_recovery(self) -> None:
        """Offer to save a focus session interrupted by a crash or 'keep for later'."""
        data = self.ctx.settings.get(CHECKPOINT_KEY)
        if not isinstance(data, dict):
            return
        uid = data.get("session_uid")
        try:
            elapsed = float(data.get("elapsed_s", 0))
            started = datetime.fromisoformat(str(data.get("started_wall")))
            duration = int(data.get("duration_s", 0))
        except (TypeError, ValueError):
            log.warning("Discarding unreadable timer checkpoint")
            self._clear_checkpoint()
            return
        if not uid or self.ctx.study.exists(uid) or elapsed < MIN_SAVE_SECONDS:
            self._clear_checkpoint()
            return
        subject_id = data.get("subject_id")
        subject = self.ctx.subjects.get(subject_id) if subject_id else None
        text = (f"A focus session{' for ' + subject.name if subject else ''} started "
                f"{format_date(started.date(), self.date_style)} at {format_time(started.time(), self.clock24)} "
                f"wasn't saved. {format_duration(elapsed)} were recorded before DayOS closed.")
        if confirm(self.main, "Save interrupted session?", text, "Save session", danger=False):
            extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
            task_id = extra.get("task_id") if extra.get("task_id") and self.ctx.tasks.get(extra["task_id"]) else None
            project_id = extra.get("project_id") if extra.get("project_id") and self.ctx.projects.get(extra["project_id"]) else None
            ok = guarded(self.main, lambda: self.ctx.study.record(
                session_uid=uid, subject_id=subject.id if subject else None, started_at=started,
                actual_seconds=int(elapsed), planned_minutes=duration // 60 or None,
                completed=elapsed >= duration > 0, source="recovered", task_id=task_id, project_id=project_id,
                node_id=self._existing_node(extra.get("node_id")),
                kind=extra.get("kind") if extra.get("kind") in SESSION_KINDS else "study",
                note=str(extra.get("note") or "")[:500]))
            if ok:
                bus.notify("study")
                self.toast("Interrupted session saved")
        self._clear_checkpoint()

    def confirm_close(self) -> bool:
        """Called by the main window before quitting."""
        if not (self.timer.is_active and self.timer.mode == FOCUS):
            return True
        self.timer.pause()
        self._tick.stop()
        elapsed = self.timer.elapsed()
        if elapsed < MIN_SAVE_SECONDS:
            self._clear_checkpoint()
            return True
        dlg = CloseDialog(self.main, elapsed)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.timer.resume()
            self._tick.start()
            return False
        if dlg.choice == CloseDialog.SAVE:
            self._record(completed=False)
        else:
            self._save_checkpoint()
        return True

    def new_item(self) -> None:
        ManualStudyDialog(self.ctx, self, self.subject.current_id()).exec()


def _flash_taskbar(widget: QWidget) -> None:
    """Flash the taskbar button gently (no sound) when a timer completes."""
    from PySide6.QtWidgets import QApplication

    QApplication.alert(widget.window(), 0)
