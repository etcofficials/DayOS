"""Explicit consent before anything is sent to an AI provider, and the shared run helper.

The dialog shows exactly what will be sent (the same text the request contains), to
which provider and model, and is shown for every request that includes the user's own
notes, records or documents. Nothing is sent if the user cancels.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QVBoxLayout

from src.services import ai
from src.ui.widgets.common import FadeDialog, button, label, show_error, show_info
from src.ui.worker import run_in_background


class ConsentDialog(FadeDialog):
    def __init__(self, parent, feature: str, provider_label: str, preview: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Send to AI?")
        self.setModal(True)
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label(f"Send this to {provider_label}?", "section"))
        lay.addWidget(label(f"For: {feature}. Exactly the text below will be sent — nothing else from DayOS. The "
                            "provider processes it under its own terms. The result is a suggestion you can review "
                            "before anything is saved.", "muted", wrap=True))
        box = QPlainTextEdit(preview)
        box.setReadOnly(True)
        box.setAccessibleName("Text that will be sent")
        lay.addWidget(box, 1)
        lay.addWidget(label(f"{len(preview):,} characters", "caption"))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", "ghost", on_click=self.reject))
        send = button("Send", "primary", "sparkle", self.accept)
        row.addWidget(send)
        lay.addLayout(row)


def run_ai(parent, settings, feature: str, preview: str, work: Callable[[ai.Provider], object],
           done: Callable[[object], None], toast: Callable[[str], None] | None = None) -> bool:
    """Ask for consent, then run ``work(provider)`` in the background. Returns False if not sent."""
    config = ai.config_from_settings(settings)
    if config is None or not ai.is_configured(settings):
        show_info(parent, "AI isn't set up", "DayOS works fully without AI. To use AI suggestions, choose a provider "
                                             "and add your own API key in Settings → AI.")
        return False
    if ConsentDialog(parent, feature, config.label, preview).exec() == 0:
        return False
    try:
        provider = ai.provider_for(settings)
    except ai.AIError as exc:
        show_error(parent, "AI unavailable", str(exc))
        return False
    if toast:
        toast("Asking the AI… you can keep working")

    def failed(exc: Exception) -> None:
        message = str(exc) if isinstance(exc, ai.AIError) else "Something went wrong talking to the AI."
        show_error(parent, "No AI result", message)

    run_in_background(lambda: work(provider), done, failed)
    return True


class ReviewDialog(FadeDialog):
    """Lets the user pick which AI suggestions to keep (all start unticked or ticked as chosen)."""

    def __init__(self, parent, title: str, note: str, items: list[str], checked: bool = True,
                 accept_text: str = "Add selected") -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox, QScrollArea, QWidget

        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label(title, "section"))
        lay.addWidget(label(note, "muted", wrap=True))
        holder = QWidget()
        inner = QVBoxLayout(holder)
        self.checks: list = []
        for text in items:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            cb.setStyleSheet("QCheckBox { padding: 4px 0; }")
            self.checks.append(cb)
            inner.addWidget(cb)
        inner.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(holder)
        lay.addWidget(area, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", "ghost", on_click=self.reject))
        row.addWidget(button(accept_text, "primary", "check", self.accept))
        lay.addLayout(row)

    def selected(self) -> list[int]:
        return [i for i, cb in enumerate(self.checks) if cb.isChecked()]
