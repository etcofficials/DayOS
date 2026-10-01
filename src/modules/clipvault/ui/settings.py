"""Settings → ClipVault: capture, privacy, retention, shortcut and exclusion rules."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.modules.clipvault.schema import RULE_KINDS
from src.ui import settings_sections
from src.ui.bus import bus
from src.ui.widgets.common import Card, button, clear_layout, confirm, guarded, label, repolish, tool_button


def register_settings() -> None:
    settings_sections.register(settings_sections.SectionSpec("clipvault", "ClipVault", "clipboard", 40, build))


def build(page) -> QWidget:
    from src.modules.clipvault.ui.page import RETENTION, WHAT_IS_STORED

    ctx = page.ctx
    repo = ctx.services["clipvault"]
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)

    card = Card("Clipboard history", "clipboard")
    card.body.addWidget(label(WHAT_IS_STORED, "muted", wrap=True))
    enabled = QCheckBox("Save text I copy (clipboard history)")
    enabled.toggled.connect(lambda v: page.set_pref("clip.enabled", v))
    card.body.addWidget(enabled)
    paused = QCheckBox("Paused — don't save anything for now")
    paused.toggled.connect(lambda v: page.set_pref("clip.paused", v))
    card.body.addWidget(paused)
    row = QHBoxLayout()
    row.addWidget(label("Keep history for", "muted"))
    retention = QComboBox()
    retention.setAccessibleName("Keep history for")
    for days, text in RETENTION:
        retention.addItem(text, days)
    retention.activated.connect(lambda _i: page.set_pref("clip.retention_days", int(retention.currentData())))
    row.addWidget(retention)
    row.addSpacing(12)
    row.addWidget(label("and at most", "muted"))
    max_items = QSpinBox()
    max_items.setRange(20, 5000)
    max_items.setSingleStep(50)
    max_items.setSuffix(" entries")
    max_items.setAccessibleName("Maximum entries")
    max_items.valueChanged.connect(lambda v: page.set_pref("clip.max_items", int(v)))
    row.addWidget(max_items)
    row.addStretch(1)
    card.body.addLayout(row)
    row = QHBoxLayout()
    row.addWidget(label("Skip copies longer than", "muted"))
    max_chars = QSpinBox()
    max_chars.setRange(200, 200000)
    max_chars.setSingleStep(1000)
    max_chars.setSuffix(" characters")
    max_chars.setAccessibleName("Longest text to keep")
    max_chars.valueChanged.connect(lambda v: page.set_pref("clip.max_chars", int(v)))
    row.addWidget(max_chars)
    row.addStretch(1)
    card.body.addLayout(row)
    private_apps = QCheckBox("Skip copies from password managers and copies an app marks as private")
    private_apps.toggled.connect(lambda v: page.set_pref("clip.skip_private_apps", v))
    card.body.addWidget(private_apps)
    sensitive = QCheckBox("Skip text that looks like a password, access key, one-time code or card number")
    sensitive.toggled.connect(lambda v: page.set_pref("clip.skip_sensitive", v))
    card.body.addWidget(sensitive)
    in_palette = QCheckBox("Show clipboard history in Ctrl+K search results")
    in_palette.toggled.connect(lambda v: page.set_pref("clip.search_in_palette", v))
    card.body.addWidget(in_palette)
    lay.addWidget(card)

    card = Card("Shortcut", "keyboard")
    use_key = QCheckBox("Open the clipboard picker from anywhere in Windows")
    use_key.toggled.connect(lambda v: page.set_pref("clip.global", v))
    card.body.addWidget(use_key)
    key_row = QHBoxLayout()
    key_edit = QKeySequenceEdit()
    key_edit.setMaximumSequenceLength(1)
    key_edit.setAccessibleName("ClipVault shortcut")
    key_row.addWidget(key_edit)
    key_row.addStretch(1)
    card.body.addLayout(key_row)
    key_status = label("", "caption", wrap=True)
    card.body.addWidget(key_status)
    card.body.addWidget(label("Only this exact combination is claimed; DayOS never records other typing. Avoid "
                              "Ctrl+Alt+V if you use Paste Special in Office.", "caption", wrap=True))

    def key_changed() -> None:
        text = key_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if text:
            page.set_pref("clip.hotkey", text)
        QTimer.singleShot(50, show_key_status)

    key_edit.editingFinished.connect(key_changed)

    def show_key_status() -> None:
        hk = page.main.hotkeys
        if not ctx.settings.get("clip.global"):
            key_status.setText("System-wide shortcut is off. Ctrl+K → “Clipboard history” works inside DayOS.")
            key_status.setProperty("role", "caption")
        elif hk.is_registered("clipvault"):
            key_status.setText(f"Active: press {ctx.settings.get('clip.hotkey')} anywhere.")
            key_status.setProperty("role", "success")
        else:
            key_status.setText(hk.errors.get("clipvault", "Not registered."))
            key_status.setProperty("role", "warning")
        repolish(key_status)

    lay.addWidget(card)

    card = Card("Exclusion rules", "shield")
    card.body.addWidget(label("Copies matching a rule are never saved. Use “Copied from app” with a program's file "
                              "name (for example banking-app.exe).", "muted", wrap=True))
    rules_box = QVBoxLayout()
    rules_box.setSpacing(2)
    card.body.addLayout(rules_box)
    add_row = QHBoxLayout()
    rule_kind = QComboBox()
    rule_kind.setAccessibleName("Rule type")
    for key, name in RULE_KINDS.items():
        rule_kind.addItem(name, key)
    add_row.addWidget(rule_kind)
    rule_value = QLineEdit()
    rule_value.setPlaceholderText("e.g. bankapp.exe, “confidential”, or a pattern")
    rule_value.setAccessibleName("Rule value")
    rule_value.setMaxLength(200)
    add_row.addWidget(rule_value, 1)

    def add_rule() -> None:
        if guarded(page, lambda: repo.add_rule(rule_kind.currentData(), rule_value.text())):
            rule_value.clear()
            fill_rules()

    rule_value.returnPressed.connect(add_rule)
    add_row.addWidget(button("Add rule", "soft", "plus", add_rule))
    card.body.addLayout(add_row)

    def fill_rules() -> None:
        clear_layout(rules_box)
        rules = repo.rules()
        if not rules:
            rules_box.addWidget(label("No exclusion rules yet.", "caption"))
        for rule in rules:
            r = QHBoxLayout()
            cb = QCheckBox(rule.description)
            cb.setChecked(bool(rule.enabled))
            cb.toggled.connect(lambda v, rid=rule.id: repo.set_rule_enabled(rid, v))
            r.addWidget(cb, 1)
            r.addWidget(tool_button("close", "Remove rule", lambda rid=rule.id: (repo.delete_rule(rid), fill_rules()),
                                    14))
            rules_box.addLayout(r)

    lay.addWidget(card)

    card = Card("Delete", "trash")
    row = QHBoxLayout()

    def clear(everything: bool) -> None:
        text = ("Every ClipVault entry — history, pinned items, snippets and templates — will be permanently deleted."
                if everything else "Copied history will be permanently deleted. Pinned and favourite entries, "
                                   "templates and anything you added yourself are kept.")
        if confirm(page, "Delete everything?" if everything else "Clear history?", text,
                   "Delete everything" if everything else "Clear history"):
            n: dict = {}
            if guarded(page, lambda: n.setdefault("n", repo.clear_history(everything))):
                bus.notify("clips")
                page.main.toast.show_message(f"Deleted {n['n']} entr{'y' if n['n'] == 1 else 'ies'}")

    row.addWidget(button("Clear history…", "ghost", "trash", lambda: clear(False)))
    row.addWidget(button("Delete everything in ClipVault…", "danger", "trash", lambda: clear(True)))
    row.addStretch(1)
    card.body.addLayout(row)
    lay.addWidget(card)

    def load() -> None:
        s = ctx.settings
        enabled.setChecked(bool(s.get("clip.enabled")))
        paused.setChecked(bool(s.get("clip.paused")))
        paused.setEnabled(bool(s.get("clip.enabled")))
        retention.setCurrentIndex(max(0, retention.findData(int(s.get("clip.retention_days")))))
        if retention.findData(int(s.get("clip.retention_days"))) < 0:
            retention.addItem(f"{int(s.get('clip.retention_days'))} days", int(s.get("clip.retention_days")))
            retention.setCurrentIndex(retention.count() - 1)
        max_items.setValue(int(s.get("clip.max_items")))
        max_chars.setValue(int(s.get("clip.max_chars")))
        private_apps.setChecked(bool(s.get("clip.skip_private_apps")))
        sensitive.setChecked(bool(s.get("clip.skip_sensitive")))
        in_palette.setChecked(bool(s.get("clip.search_in_palette")))
        use_key.setChecked(bool(s.get("clip.global")))
        key_edit.setKeySequence(QKeySequence(str(s.get("clip.hotkey"))))
        show_key_status()
        fill_rules()

    page.on_refresh(load)
    return box
