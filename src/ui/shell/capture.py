"""Quick capture: jot down a task, note, idea, link or snippet in two seconds, from anywhere.

Captures go to the Inbox to be organised later, or become a real task / note /
reminder straight away. Dates found in the text are only *suggested*; nothing
is applied unless the user ticks it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDateTimeEdit, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout

from src.repositories.inbox import KINDS
from src.services.dates import format_date, now, today
from src.services.quickadd import parse_quick_task
from src.ui.bus import bus
from src.ui.widgets.common import FadeDialog, SegmentBar, button, guarded, label

ORDER = ["task", "note", "idea", "link", "snippet", "reminder", "project", "study"]


def guess_kind(text: str) -> str | None:
    t = text.strip()
    if t.lower().startswith(("http://", "https://")) and " " not in t:
        return "link"
    if "\n" in t and any(tok in t for tok in ("def ", "{", "};", "=>", "import ", "SELECT ", "</")):
        return "snippet"
    return None


class CaptureWindow(FadeDialog):
    def __init__(self, window, standalone: bool = False) -> None:
        super().__init__(None if standalone else window)
        self.main = window
        self.ctx = window.ctx
        self.setWindowTitle("Quick capture — DayOS")
        self.setWindowIcon(window.windowIcon())
        flags = Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(label("Quick capture", "section"))
        self.kind = SegmentBar([(k, KINDS[k].replace("Code ", "").replace(" action", "")) for k in ORDER], "idea")
        self.kind.changed.connect(self._kind_changed)
        lay.addWidget(self.kind)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("What's on your mind? (Ctrl+Enter to save)")
        self.text.setAccessibleName("Capture text")
        self.text.setFixedHeight(110)
        self.text.textChanged.connect(self._text_changed)
        lay.addWidget(self.text)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…")
        self.url.setAccessibleName("Link address")
        self.url.hide()
        lay.addWidget(self.url)
        self.when = QDateTimeEdit()
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("ddd d MMM yyyy  HH:mm" if self.ctx.settings.get("clock_24h") else "ddd d MMM yyyy  h:mm AP")
        self.when.setDateTime(now().replace(second=0, microsecond=0) + timedelta(hours=1))
        self.when.setAccessibleName("Remind me at")
        self.when.hide()
        lay.addWidget(self.when)
        self.date_hint = QCheckBox()
        self.date_hint.hide()
        lay.addWidget(self.date_hint)
        self.note = label("Saved to your Inbox so you can sort it later. Nothing leaves this computer.", "caption", wrap=True)
        lay.addWidget(self.note)
        row = QHBoxLayout()
        row.addWidget(button("Open Inbox", "link", "inbox", self._open_inbox))
        row.addStretch(1)
        row.addWidget(button("Cancel", "ghost", on_click=self.reject))
        self.now_btn = button("Create task now", "", on_click=self._create_now)
        row.addWidget(self.now_btn)
        self.save_btn = button("Save to Inbox", "primary", "inbox", self._save)
        row.addWidget(self.save_btn)
        lay.addLayout(row)
        self._parsed = None
        self._user_kind = False
        self._kind_changed("idea", user=False)
        from src.ui.widgets.common import install_shortcut

        install_shortcut(self, "Ctrl+Return", self._save, Qt.ShortcutContext.WindowShortcut)
        install_shortcut(self, "Ctrl+Enter", self._save, Qt.ShortcutContext.WindowShortcut)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.text.setFocus()

    def _kind_changed(self, kind: str, user: bool = True) -> None:
        if user:
            self._user_kind = True
        self.url.setVisible(kind == "link")
        self.when.setVisible(kind == "reminder")
        labels = {"task": "Create task now", "note": "Create note now", "reminder": "Create reminder now",
                  "project": "Create project now", "link": "Save as bookmark", "snippet": "Create snippet now"}
        self.now_btn.setVisible(kind in labels)
        self.now_btn.setText(labels.get(kind, ""))
        self._text_changed()

    def _text_changed(self) -> None:
        text = self.text.toPlainText()
        guess = guess_kind(text)
        if guess and not self._user_kind and self.kind.current() != guess:
            self.kind.set_current(guess)
            self._kind_changed(guess, user=False)
            if guess == "link":
                self.url.setText(text.strip())
        kind = self.kind.current()
        self._parsed = parse_quick_task(text, today()) if kind in ("task", "reminder") and text.strip() else None
        if self._parsed and self._parsed.due_date:
            self.date_hint.setText(f"Use the date I wrote: {format_date(self._parsed.due_date, str(self.ctx.settings.get('date_format')))}"
                                   f" (and title “{self._parsed.title}”)")
            self.date_hint.show()
        else:
            self.date_hint.hide()
            self.date_hint.setChecked(False)

    def _payload(self) -> tuple[str, str, str]:
        return self.kind.current(), self.text.toPlainText().strip(), self.url.text().strip()

    def _save(self) -> None:
        kind, text, url = self._payload()
        if not text and url:
            text = url
        if guarded(self, lambda: self.ctx.inbox.add(kind, text, url), "Couldn't save the capture"):
            bus.notify("inbox")
            self.main.toast.show_message("Captured to your Inbox", "Open", self._open_inbox)
            self.accept()

    def _create_now(self) -> None:
        kind, text, url = self._payload()
        if not text and not url:
            self.text.setFocus()
            return
        use_date = not self.date_hint.isHidden() and self.date_hint.isChecked() and self._parsed is not None
        title = self._parsed.title if use_date and self._parsed else text.splitlines()[0][:200] if text else url
        result: dict = {}

        def run() -> None:
            if kind == "task":
                due = self._parsed.due_date if use_date and self._parsed else None
                result["id"] = self.ctx.tasks.create(title, description=text if "\n" in text else "", due_date=due)
                bus.notify("tasks")
            elif kind == "reminder":
                at = self.when.dateTime().toPython()
                if use_date and self._parsed and self._parsed.due_date:
                    at = datetime.combine(self._parsed.due_date, at.time())
                result["id"] = self.ctx.reminders.add(title, at)
                bus.notify("reminders")
            elif kind == "project":
                result["id"] = self.ctx.projects.create(title, description=text)
                bus.notify("projects")
            elif kind == "link" and url:
                note_title = text.splitlines()[0][:120] if text and text != url else ""
                result["id"] = self.ctx.services["brain"].add_bookmark(
                    url, note_title, text if text and text != url else "")[0]
                bus.notify("notes")
            else:  # note / idea / snippet (and a link without an address)
                body = (url + "\n\n" + text if url and url not in text else text)
                note_title = title if kind != "link" else (text.splitlines()[0][:120] if text and text != url else url)
                note_kind = {"snippet": "snippet", "idea": "idea"}.get(kind, "note")
                fmt = "plain" if note_kind == "snippet" else str(self.ctx.settings.get("brain.default_format"))
                result["id"] = self.ctx.notes.create(note_title if len(text) > 60 or kind == "link" else "", body,
                                                     kind=note_kind, format=fmt, source="Quick capture")
                bus.notify("notes")

        if guarded(self, run, "Couldn't create it"):
            names = {"task": "Task added", "reminder": "Reminder set", "project": "Project created"}
            self.main.toast.show_message(names.get(kind, "Note saved"))
            self.accept()

    def _open_inbox(self) -> None:
        self.accept()
        self.main.show_and_raise()
        self.main.navigate("inbox")
