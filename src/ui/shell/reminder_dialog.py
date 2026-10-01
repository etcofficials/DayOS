"""Create or edit a standalone reminder."""

from __future__ import annotations

from datetime import timedelta

from PySide6.QtWidgets import QDateTimeEdit, QLineEdit, QPlainTextEdit

from src.services.dates import ValidationError, now
from src.ui.bus import bus
from src.ui.widgets.common import FormDialog, label


class ReminderDialog(FormDialog):
    def __init__(self, ctx, parent=None, title: str = "", note: str = "", reminder=None) -> None:
        super().__init__("Edit reminder" if reminder else "New reminder", parent, save_text="Save reminder")
        self.ctx = ctx
        self.reminder = reminder
        self.saved_id: int | None = None
        self.title_edit = QLineEdit(reminder.title if reminder else title)
        self.title_edit.setPlaceholderText("Remind me to…")
        self.add_row("Reminder", self.title_edit)
        self.when = QDateTimeEdit()
        self.when.setCalendarPopup(True)
        clock24 = bool(ctx.settings.get("clock_24h"))
        self.when.setDisplayFormat("ddd d MMM yyyy  " + ("HH:mm" if clock24 else "h:mm AP"))
        from datetime import datetime

        start = datetime.fromisoformat(reminder.due_at) if reminder else now().replace(second=0, microsecond=0) + timedelta(hours=1)
        self.when.setDateTime(start)
        self.add_row("When", self.when)
        self.note = QPlainTextEdit(reminder.note if reminder else note)
        self.note.setFixedHeight(70)
        self.note.setPlaceholderText("Optional details")
        self.add_row("Note", self.note)
        self.form.addRow(label("You'll see it in DayOS's notification centre, and as a Windows notification if you "
                               "allow them in Settings.", "caption", wrap=True))
        self.title_edit.setFocus()

    def save(self) -> None:
        at = self.when.dateTime().toPython()
        if not self.title_edit.text().strip():
            raise ValidationError("What should DayOS remind you about?")
        if self.reminder:
            self.ctx.reminders.delete(self.reminder.id)
        self.saved_id = self.ctx.reminders.add(self.title_edit.text(), at, note=self.note.toPlainText())
        bus.notify("reminders")
