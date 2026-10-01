"""ClipVault page: clipboard history (opt-in), snippets, commands and templates."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from src.modules.clipvault.schema import CLIP_KINDS
from src.modules.clipvault.ui.picker import preview_line
from src.ui.bus import bus
from src.ui.icons import icon
from src.ui.pages.base import Page
from src.ui.theme import mono
from src.ui.widgets.common import (
    Card,
    EmptyState,
    FormDialog,
    PageHeader,
    SearchField,
    SegmentBar,
    button,
    chip,
    confirm,
    fit_list_items,
    guarded,
    label,
    repolish,
    tool_button,
)

KIND_ICONS = {"text": "notes", "url": "link", "code": "code", "command": "terminal", "template": "copy"}
VIEWS = [("all", "All"), ("pinned", "Pinned"), ("favorites", "Favourites"), ("snippets", "Snippets"),
         ("templates", "Templates")]
RETENTION = [(1, "1 day"), (7, "7 days"), (30, "30 days"), (90, "90 days"), (365, "1 year"),
             (0, "Until I clear it")]

WHAT_IS_STORED = (
    "<b>What is saved:</b> text you copy (not images or files), which app it came from, and when.<br>"
    "<b>Where:</b> only in DayOS's database on this computer. It is never uploaded, never sent to an AI service, "
    "never written to log files, and left out of exports unless you choose to include it.<br>"
    "<b>What is skipped:</b> copies an app marks as private (most password managers do), copies from known "
    "password managers, text that looks like a password, access key, one-time code or card number, and anything "
    "matching your exclusion rules.<br>"
    "<b>Please note:</b> this detection helps but cannot be perfect. Pause clipboard history before copying "
    "something sensitive; you can clear it at any time."
)


class ClipRow(QWidget):
    def __init__(self, entry, clock: str) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 7, 8, 7)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        ic = label("", "caption")
        ic.setPixmap(icon(KIND_ICONS.get(entry.kind, "notes"), "text2", 14).pixmap(14, 14))
        top.addWidget(ic)
        title = label(entry.title or preview_line(entry.content))
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if entry.title:
            title.setStyleSheet("font-weight: 600;")
        top.addWidget(title, 1)
        if entry.pinned:
            top.addWidget(label("Pinned", "caption"))
        if entry.favorite:
            top.addWidget(label("★", "caption"))
        lay.addLayout(top)
        bits = [CLIP_KINDS.get(entry.kind, entry.kind)]
        if entry.category:
            bits.append(entry.category)
        if entry.source_app:
            bits.append(f"from {entry.source_app}")
        bits.append(clock)
        if entry.use_count:
            bits.append(f"used {entry.use_count}×")
        meta = label(" · ".join(bits), "caption")
        meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(meta)


class ClipVaultPage(Page):
    domains = ("clips", "settings")
    title = "ClipVault"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.repo = ctx.services["clipvault"]
        self.monitor = window.clip_monitor
        self.current_id: int | None = None
        self._loading = False

        header = PageHeader("ClipVault", "Clipboard history, snippets, commands and reusable text — copied back in "
                                         "one click.", eyebrow="Clipboard & snippets")
        self.state_chip = chip("", "accent")
        header.add_action(self.state_chip)
        self.pause_btn = button("Pause", "ghost", "pause-circle", self.toggle_pause)
        header.add_action(self.pause_btn)
        self.clear_btn = button("Clear history…", "ghost", "trash", self.clear_history)
        header.add_action(self.clear_btn)
        self.new_btn = button("New", "primary", "plus")
        menu = QMenu(self.new_btn)
        for kind, name in (("code", "Code snippet"), ("command", "Terminal command"), ("template", "Text template"),
                           ("text", "Text")):
            menu.addAction(icon(KIND_ICONS[kind], "text2", 16), name, lambda k=kind: self.new_entry(k))
        self.new_btn.setMenu(menu)
        header.add_action(self.new_btn)
        self.root.addWidget(header)

        # -- first-use explanation and consent
        self.setup = Card("Clipboard history is off", "shield")
        self.setup.body.addWidget(label(WHAT_IS_STORED, "", wrap=True))
        opts = QHBoxLayout()
        opts.addWidget(label("Keep history for", "muted"))
        self.setup_retention = QComboBox()
        self.setup_retention.setAccessibleName("Keep history for")
        for days, text in RETENTION:
            self.setup_retention.addItem(text, days)
        self.setup_retention.setCurrentIndex(1)
        opts.addWidget(self.setup_retention)
        opts.addStretch(1)
        self.setup.body.addLayout(opts)
        self.setup_hotkey = QCheckBox("Open the clipboard picker from anywhere with "
                                      f"{ctx.settings.get('clip.hotkey')}")
        self.setup_hotkey.setChecked(True)
        self.setup.body.addWidget(self.setup_hotkey)
        row = QHBoxLayout()
        row.addWidget(button("Turn on clipboard history", "primary", "clipboard", self.turn_on))
        row.addWidget(label("You can still keep snippets and templates below without turning it on.", "caption",
                            wrap=True), 1)
        self.setup.body.addLayout(row)
        self.root.addWidget(self.setup)

        self.status = label("", "caption", wrap=True)
        self.root.addWidget(self.status)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(14)
        self.root.addWidget(split, 1)

        left = QFrame()
        left.setProperty("panel", True)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)
        self.view = SegmentBar(VIEWS, "all")
        self.view.changed.connect(lambda _k: self._reload())
        ll.addWidget(self.view)
        self.search = SearchField("Search ClipVault")
        self.search.textChanged.connect(lambda _t: self._reload())
        ll.addWidget(self.search)
        self.category = QComboBox()
        self.category.setAccessibleName("Filter by category")
        self.category.currentIndexChanged.connect(lambda _i: self._reload())
        ll.addWidget(self.category)
        self.list = QListWidget()
        self.list.setAccessibleName("ClipVault entries")
        self.list.currentItemChanged.connect(self._on_select)
        self.list.itemActivated.connect(lambda _i: self.copy_current())
        ll.addWidget(self.list, 1)
        self.count_label = label("", "caption")
        ll.addWidget(self.count_label)
        left.setMinimumWidth(300)
        split.addWidget(left)

        right = QFrame()
        right.setProperty("panel", True)
        self.right_stack = QStackedLayout(right)
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(22, 16, 22, 14)
        dl.setSpacing(8)
        tools = QHBoxLayout()
        self.copy_btn = button("Copy", "primary", "copy", self.copy_current, "Copy to the clipboard (Enter)")
        tools.addWidget(self.copy_btn)
        self.pin_btn = tool_button("pin", "Pin", lambda: self._flag("pinned"))
        self.pin_btn.setCheckable(True)
        tools.addWidget(self.pin_btn)
        self.fav_btn = tool_button("star", "Favourite", lambda: self._flag("favorite"))
        self.fav_btn.setCheckable(True)
        tools.addWidget(self.fav_btn)
        tools.addStretch(1)
        tools.addWidget(button("Save to SecondBrain", "link", "brain", self.save_to_brain))
        tools.addWidget(tool_button("trash", "Delete", self.delete_current))
        dl.addLayout(tools)
        form = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.setAccessibleName("Type")
        for kind, name in CLIP_KINDS.items():
            self.kind_combo.addItem(icon(KIND_ICONS[kind], "text2", 16), name, kind)
        form.addWidget(self.kind_combo)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Title (optional)")
        self.title_edit.setAccessibleName("Title")
        self.title_edit.setMaxLength(120)
        form.addWidget(self.title_edit, 2)
        self.cat_edit = QLineEdit()
        self.cat_edit.setPlaceholderText("Category")
        self.cat_edit.setAccessibleName("Category")
        self.cat_edit.setMaxLength(40)
        form.addWidget(self.cat_edit, 1)
        dl.addLayout(form)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Tags, separated by commas")
        self.tags_edit.setAccessibleName("Tags")
        dl.addWidget(self.tags_edit)
        self.content = QPlainTextEdit()
        self.content.setAccessibleName("Text")
        self._default_font = self.content.font()
        dl.addWidget(self.content, 1)
        self.template_hint = label("Templates fill in {date}, {time}, {datetime} and {clipboard} when copied.",
                                   "caption", wrap=True)
        dl.addWidget(self.template_hint)
        bottom = QHBoxLayout()
        self.meta = label("", "caption", wrap=True)
        bottom.addWidget(self.meta, 1)
        self.save_btn = button("Save changes", "soft", "check", self.save_current)
        bottom.addWidget(self.save_btn)
        dl.addLayout(bottom)
        self.right_stack.addWidget(detail)
        self.placeholder = QWidget()
        pl = QVBoxLayout(self.placeholder)
        self.empty = EmptyState("clipboard", "Nothing selected",
                                "Pick an entry to copy it back, or add a snippet, command or template.",
                                [("New snippet", lambda: self.new_entry("code"))])
        pl.addWidget(self.empty)
        self.right_stack.addWidget(self.placeholder)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 620])

        for w in (self.title_edit, self.cat_edit, self.tags_edit):
            w.textEdited.connect(self._edited)
        self.content.textChanged.connect(self._edited)
        self.kind_combo.activated.connect(lambda _i: self._edited())
        self.monitor.state_changed.connect(self._update_state)
        self.monitor.skipped.connect(lambda _r: self._update_state())
        self.right_stack.setCurrentIndex(1)

    # -- state ---------------------------------------------------------------------------
    def _update_state(self) -> None:
        s = self.ctx.settings
        enabled = self.monitor.enabled
        self.setup.setVisible(not enabled)
        self.state_chip.setText("Off" if not enabled else "Paused" if self.monitor.paused else "Saving copies")
        self.state_chip.setProperty("tone", "amber" if enabled and self.monitor.paused else
                                    "accent" if enabled else "info")
        repolish(self.state_chip)
        self.pause_btn.setVisible(enabled)
        self.pause_btn.setText("Resume" if self.monitor.paused else "Pause")
        if enabled:
            days = int(s.get("clip.retention_days"))
            keep = "until you clear it" if days == 0 else f"for {days} day{'s' if days != 1 else ''}"
            text = (f"History is kept {keep}, up to {int(s.get('clip.max_items'))} entries. Pinned, favourite and "
                    "hand-added entries are always kept.")
            if self.monitor.last_skip:
                text += f" Last skipped copy: {self.monitor.last_skip}."
            self.status.setText(text)
        self.status.setVisible(enabled)

    def turn_on(self) -> None:
        s = self.ctx.settings
        s.set("clip.retention_days", int(self.setup_retention.currentData()))
        s.set("clip.global", self.setup_hotkey.isChecked())
        s.set("clip.paused", False)
        s.set("clip.enabled", True)
        bus.notify("settings", "clips")
        msg = "Clipboard history is on"
        if self.setup_hotkey.isChecked() and not self.main.hotkeys.is_registered("clipvault"):
            msg += " (the shortcut is taken by another app; pick another in Settings)"
        self.toast(msg)

    def toggle_pause(self) -> None:
        self.monitor.set_paused(not self.monitor.paused)
        bus.notify("clips")
        self.toast("Clipboard history paused" if self.monitor.paused else "Clipboard history resumed")

    # -- list ----------------------------------------------------------------------------
    def refresh(self) -> None:
        self._update_state()
        cats = self.repo.categories()
        keep = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", "")
        for c in cats:
            self.category.addItem(c, c)
        self.category.setCurrentIndex(max(0, self.category.findData(keep)))
        self.category.blockSignals(False)
        self.category.setVisible(bool(cats))
        self._reload()

    def _reload(self) -> None:
        entries = self.repo.list(self.search.text(), self.view.current(), self.category.currentData() or "")
        self.list.blockSignals(True)
        self.list.clear()
        selected = None
        for entry in entries:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            row = ClipRow(entry, entry.last_used_at[5:16].replace("-", "/"))
            item.setSizeHint(QSize(100, row.sizeHint().height()))
            item.setData(Qt.ItemDataRole.AccessibleTextRole,
                         f"{CLIP_KINDS.get(entry.kind, entry.kind)}: {entry.title or preview_line(entry.content)}")
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            if entry.id == self.current_id:
                selected = item
        if selected is not None:
            self.list.setCurrentItem(selected)
        self.list.blockSignals(False)
        fit_list_items(self.list)
        counts = self.repo.counts()
        self.count_label.setText(f"{len(entries)} shown · {counts['total']} in ClipVault")
        if self.current_id is not None and self.repo.get(self.current_id) is None:
            self._show(None)

    def _on_select(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        self._show(self.repo.get(int(current.data(Qt.ItemDataRole.UserRole))))

    def select_entry(self, entry_id: int) -> None:
        self.search.clear()
        self.view.set_current("all")
        self.current_id = entry_id
        self.refresh()
        self._show(self.repo.get(entry_id))

    def _show(self, entry) -> None:
        self._loading = True
        try:
            if entry is None:
                self.current_id = None
                self.right_stack.setCurrentIndex(1)
                return
            self.current_id = entry.id
            self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(entry.kind)))
            self.title_edit.setText(entry.title)
            self.cat_edit.setText(entry.category)
            self.tags_edit.setText(entry.tags)
            self.content.setPlainText(entry.content)
            code = entry.kind in ("code", "command")
            self.content.setFont(mono(10.5) if code else self._default_font)
            self.content.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap if code
                                         else QPlainTextEdit.LineWrapMode.WidgetWidth)
            self.template_hint.setVisible(entry.kind == "template")
            self.pin_btn.setChecked(bool(entry.pinned))
            self.fav_btn.setChecked(bool(entry.favorite))
            origin = "Added by you" if entry.origin == "manual" else (
                f"Copied from {entry.source_app}" if entry.source_app else "Copied")
            self.meta.setText(f"{origin} · first saved {entry.created_at[:16]} · last used {entry.last_used_at[:16]}"
                              f" · {len(entry.content):,} characters")
            self.save_btn.setEnabled(False)
            self.right_stack.setCurrentIndex(0)
        finally:
            self._loading = False

    def _edited(self, *_args) -> None:
        if not self._loading and self.current_id is not None:
            self.save_btn.setEnabled(True)

    # -- actions ------------------------------------------------------------------------
    def copy_current(self) -> None:
        if self.current_id is None:
            return
        if self.save_btn.isEnabled():
            self.save_current()
        if self.monitor.copy_entry(self.current_id) is not None:
            self.toast("Copied — paste it anywhere")

    def save_current(self) -> None:
        if self.current_id is None:
            return
        entry_id = self.current_id
        if guarded(self, lambda: self.repo.update(entry_id, content=self.content.toPlainText(),
                                                  kind=self.kind_combo.currentData(), title=self.title_edit.text(),
                                                  category=self.cat_edit.text(), tags=self.tags_edit.text())):
            self.save_btn.setEnabled(False)
            bus.notify("clips")

    def _flag(self, flag: str) -> None:
        if self.current_id is None:
            return
        on = (self.pin_btn if flag == "pinned" else self.fav_btn).isChecked()
        entry_id = self.current_id
        if guarded(self, lambda: self.repo.set_flag(entry_id, flag, on)):
            bus.notify("clips")

    def new_entry(self, kind: str = "code") -> None:
        dlg = ClipEntryDialog(self.repo, kind, self)
        if dlg.exec() and dlg.saved_id is not None:
            bus.notify("clips")
            self.select_entry(dlg.saved_id)

    def delete_current(self) -> None:
        if self.current_id is None:
            return
        if not confirm(self, "Delete entry?", "This ClipVault entry will be permanently deleted."):
            return
        entry_id = self.current_id
        if guarded(self, lambda: self.repo.delete(entry_id)):
            self._show(None)
            bus.notify("clips")

    def clear_history(self) -> None:
        counts = self.repo.counts()
        if not confirm(self, "Clear clipboard history?",
                       f"{counts['history']} copied entr{'y' if counts['history'] == 1 else 'ies'} will be permanently "
                       "deleted. Pinned and favourite entries, templates and anything you added yourself are kept "
                       "(Settings → ClipVault can delete everything).", "Clear history"):
            return
        removed: dict = {}
        if guarded(self, lambda: removed.setdefault("n", self.repo.clear_history())):
            bus.notify("clips")
            self.toast(f"Cleared {removed['n']} entr{'y' if removed['n'] == 1 else 'ies'}")

    def save_to_brain(self) -> None:
        entry = self.repo.get(self.current_id) if self.current_id is not None else None
        if entry is None:
            return
        kind = {"code": "snippet", "command": "command", "url": "bookmark"}.get(entry.kind, "note")
        title = entry.title or preview_line(entry.content)[:120]
        made: dict = {}

        def run() -> None:
            if kind == "bookmark":
                made["id"] = self.ctx.services["brain"].add_bookmark(entry.content.strip(), title)[0]
            else:
                made["id"] = self.ctx.notes.create(title, entry.content, entry.tags, kind=kind, source="ClipVault")

        if guarded(self, run, "Couldn't save it to SecondBrain"):
            bus.notify("notes")
            self.toast("Saved to SecondBrain", "Open", lambda: self.main.openers.open("note", made["id"]))

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()


class ClipEntryDialog(FormDialog):
    """Add a snippet, command, template or text by hand (kept until you delete it)."""

    TITLES = {"code": "New code snippet", "command": "New terminal command", "template": "New text template",
              "text": "New text"}

    def __init__(self, repo, kind: str, parent=None) -> None:
        super().__init__(self.TITLES.get(kind, "New entry"), parent, "Add", 560)
        self.repo = repo
        self.saved_id: int | None = None
        self.kind = QComboBox()
        for key, name in CLIP_KINDS.items():
            self.kind.addItem(icon(KIND_ICONS[key], "text2", 16), name, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.add_row("Type", self.kind)
        self.title = QLineEdit()
        self.title.setMaxLength(120)
        self.title.setPlaceholderText("Optional, e.g. “Reset Git branch”")
        self.add_row("Title", self.title)
        self.category = QLineEdit()
        self.category.setMaxLength(40)
        self.category.setPlaceholderText("Optional, e.g. Git, Email")
        self.add_row("Category", self.category)
        self.text = QPlainTextEdit()
        self.text.setMinimumHeight(160)
        self.text.setAccessibleName("Text")
        if kind in ("code", "command"):
            self.text.setFont(mono(10.5))
        if kind == "template":
            self.text.setPlaceholderText("Hi {clipboard}, … Sent on {date}")
        self.add_row("Text", self.text)
        self.extra.addWidget(label("Templates fill in {date}, {time}, {datetime} and {clipboard} when copied.",
                                   "caption", wrap=True))
        self.text.setFocus()

    def save(self) -> None:
        self.saved_id = self.repo.add(self.text.toPlainText(), kind=self.kind.currentData(),
                                      title=self.title.text(), category=self.category.text())
