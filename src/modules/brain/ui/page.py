"""SecondBrain page: the knowledge vault that grew out of v1 Notes.

Notes save themselves as you type (as in v1). Each note has a kind (note,
bookmark, snippet, command, idea, troubleshooting, study, reference), an
optional collection, plain or Markdown format with a read-only preview, links to
other DayOS items, [[wiki links]] with backlinks, and attachments.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QStackedWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.models import Note
from src.modules.brain.schema import NOTE_KIND_ICONS, NOTE_KINDS
from src.modules.brain.service import (
    ATTACHMENT_SCHEME,
    KIND_TEMPLATES,
    markdown_for_preview,
    title_from_link,
)
from src.repositories.notes import UNFILED
from src.services.dates import format_date
from src.ui.bus import bus
from src.ui.icons import icon
from src.ui.pages.base import Page
from src.ui.theme import mono
from src.ui.widgets.common import (
    CollapsibleSection,
    ElidedLabel,
    EmptyState,
    FlowLayout,
    PageHeader,
    SearchField,
    button,
    clear_layout,
    confirm,
    fit_list_items,
    guarded,
    install_shortcut,
    label,
    min_width_floor,
    show_error,
    show_info,
    tool_button,
)

log = logging.getLogger(__name__)

AUTOSAVE_MS = 900
LINK_KINDS = ["task", "note", "project", "goal", "event", "exam", "course", "question", "flashcard", "material"]
# Attachments that would run code if opened directly are only ever saved as copies.
UNSAFE_TO_OPEN = {".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
                  ".scr", ".lnk", ".hta", ".cpl", ".jar", ".reg", ".pif", ".url"}


def _snippet(note: Note) -> str:
    if note.kind == "bookmark" and note.url:
        return note.url[:90]
    text = " ".join(note.content.split())
    return text[:90] + ("…" if len(text) > 90 else "")


def _human_size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1048576 else f"{n / 1048576:.1f} MB"


class NoteItem(QWidget):
    def __init__(self, note: Note, date_style: str, collection: str = "") -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        ic = label("", "caption")
        ic.setPixmap(icon(NOTE_KIND_ICONS.get(note.kind, "notes"), "text2", 14).pixmap(14, 14))
        top.addWidget(ic)
        self.title = ElidedLabel(note.title or "Untitled")
        self.title.setStyleSheet("font-weight: 600;")
        top.addWidget(self.title, 1)
        if note.pinned:
            top.addWidget(label("Pinned", "caption"))
        if note.archived:
            top.addWidget(label("Archived", "caption"))
        lay.addLayout(top)
        self.snippet = ElidedLabel(_snippet(note) or "No content yet", "muted")
        lay.addWidget(self.snippet)
        meta = format_date(date.fromisoformat(note.updated_at[:10]), date_style)
        if note.kind != "note":
            meta += " · " + NOTE_KINDS.get(note.kind, note.kind)
        if collection:
            meta += " · " + collection
        if note.tags:
            meta += " · " + note.tags
        self.meta = ElidedLabel(meta, "caption")
        lay.addWidget(self.meta)


class PreviewBrowser(QTextBrowser):
    """Read-only Markdown preview. Loads nothing from the internet or the disk; only
    attachments stored in DayOS can be shown as images."""

    def __init__(self, page: "BrainPage") -> None:
        super().__init__()
        self.page = page
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setProperty("editor", True)
        self.setAccessibleName("Note preview")
        self.anchorClicked.connect(page._on_link)

    def loadResource(self, kind: int, url: QUrl):  # noqa: N802 - Qt override
        if kind == QTextDocument.ResourceType.ImageResource.value and url.scheme() == ATTACHMENT_SCHEME:
            try:
                data = self.page.brain.attachments.data(int(url.path()))
            except (ValueError, TypeError):
                data = None
            if data:
                image = QImage()
                if image.loadFromData(data):
                    return image
        return None


class BrainPage(Page):
    domains = ("notes", "links", "settings")
    title = "SecondBrain"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.brain = ctx.services["brain"]
        self.current: Note | None = None
        self._loading = False
        self._dirty_edit = False
        self._own_notify = False
        self._fresh_empty_ids: set[int] = set()

        header = PageHeader("SecondBrain", "Notes, bookmarks, snippets, commands and ideas — searchable, linked, "
                                           "and kept on this computer.", eyebrow="Your knowledge")
        self.import_btn = button("Import…", "ghost", "upload", self.import_files, "Import Markdown or text files")
        header.add_action(self.import_btn)
        self.export_btn = button("Export…", "ghost", "download", None, "Export as Markdown files")
        export_menu = QMenu(self.export_btn)
        export_menu.addAction("Export everything as Markdown…", lambda: self.export_markdown(None))
        export_menu.addAction("Export this note as Markdown…", self._export_current)
        self.export_btn.setMenu(export_menu)
        header.add_action(self.export_btn)
        self.new_btn = button("New note", "primary", "plus", lambda: self.new_item(), "New note (Ctrl+N)")
        new_menu = QMenu(self.new_btn)
        for kind, name in NOTE_KINDS.items():
            new_menu.addAction(icon(NOTE_KIND_ICONS.get(kind, "notes"), "text2", 16), name,
                               lambda k=kind: self.new_item(k))
        self.new_btn.setMenu(new_menu)
        header.add_action(self.new_btn)
        self.root.addWidget(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(14)
        self.root.addWidget(split, 1)

        # -- list pane
        left = QFrame()
        left.setProperty("panel", True)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)
        self.search = SearchField("Search notes, links and snippets")
        self.search.textChanged.connect(lambda _: self._reload_list())
        ll.addWidget(self.search)
        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.kind_filter = QComboBox()
        self.kind_filter.setAccessibleName("Filter by type")
        self.kind_filter.addItem("All types", "")
        for kind, name in NOTE_KINDS.items():
            self.kind_filter.addItem(icon(NOTE_KIND_ICONS.get(kind, "notes"), "text2", 16), name, kind)
        self.kind_filter.currentIndexChanged.connect(lambda _: self._reload_list())
        filters.addWidget(self.kind_filter, 1)
        self.coll_filter = QComboBox()
        self.coll_filter.setAccessibleName("Filter by collection")
        # Filled after the first show, so it must keep measuring its items, and never be narrower than
        # they are (Qt keeps a stale minimum for combos), or its text is cut off.
        self.coll_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.coll_filter.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.coll_filter.activated.connect(self._coll_filter_activated)
        filters.addWidget(self.coll_filter, 1)
        ll.addLayout(filters)
        self.tag_filter = QComboBox()
        self.tag_filter.setAccessibleName("Filter by tag")
        self.tag_filter.currentIndexChanged.connect(lambda _: self._reload_list())
        ll.addWidget(self.tag_filter)
        self.show_archived = QCheckBox("Show archived")
        self.show_archived.toggled.connect(lambda _: self._reload_list())
        ll.addWidget(self.show_archived)
        self.list = QListWidget()
        self.list.setAccessibleName("Notes")
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)
        self.count_label = label("", "caption")
        ll.addWidget(self.count_label)
        min_width_floor(left, 260)
        split.addWidget(left)

        # -- editor pane
        right = QFrame()
        right.setProperty("panel", True)
        self.right_stack = QStackedLayout(right)
        editor = QWidget()
        el = QVBoxLayout(editor)
        el.setContentsMargins(22, 14, 22, 12)
        el.setSpacing(6)
        tools_box = QWidget()
        tools = FlowLayout(tools_box, spacing=6)  # wraps onto two lines in a narrow window
        self.status = label("", "caption")
        self.status.setAccessibleName("Save status")
        tools.addWidget(self.status)
        tools.add_stretch()
        self.kind_combo = QComboBox()
        self.kind_combo.setAccessibleName("Note type")
        for kind, name in NOTE_KINDS.items():
            self.kind_combo.addItem(icon(NOTE_KIND_ICONS.get(kind, "notes"), "text2", 16), name, kind)
        self.kind_combo.activated.connect(lambda _i: self._meta_changed("kind", self.kind_combo.currentData()))
        tools.addWidget(self.kind_combo)
        self.coll_combo = QComboBox()
        self.coll_combo.setAccessibleName("Collection")
        self.coll_combo.activated.connect(self._coll_combo_activated)
        tools.addWidget(self.coll_combo)
        self.format_combo = QComboBox()
        self.format_combo.setAccessibleName("Format")
        self.format_combo.addItem("Plain text", "plain")
        self.format_combo.addItem("Markdown", "markdown")
        self.format_combo.activated.connect(lambda _i: self._meta_changed("format", self.format_combo.currentData()))
        tools.addWidget(self.format_combo)
        self.preview_btn = tool_button("eye", "Preview Markdown (Ctrl+E)", self.toggle_preview)
        self.preview_btn.setCheckable(True)
        tools.addWidget(self.preview_btn)
        self.copy_btn = tool_button("copy", "Copy to clipboard", self._copy_content)
        tools.addWidget(self.copy_btn)
        self.pin_btn = tool_button("pin", "Pin note", self._toggle_pin)
        self.pin_btn.setCheckable(True)
        tools.addWidget(self.pin_btn)
        more = tool_button("more", "More actions")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(more)
        self.archive_action = self.more_menu.addAction("Archive", self._toggle_archive)
        self.more_menu.addAction("Attach a file…", self.attach_file)
        self.more_menu.addAction("Export as Markdown…", self._export_current)
        self.more_menu.addAction("Summarise with AI…", self.ai_summarize)
        self.more_menu.addSeparator()
        self.more_menu.addAction("Delete…", self._delete)
        more.setMenu(self.more_menu)
        tools.addWidget(more)
        tools.addWidget(tool_button("trash", "Delete note", self._delete))
        el.addWidget(tools_box)

        self.title_edit = QLineEdit()
        self.title_edit.setProperty("flat", True)
        self.title_edit.setProperty("titleEdit", True)
        self.title_edit.setPlaceholderText("Title")
        self.title_edit.setAccessibleName("Note title")
        self.title_edit.setMaxLength(200)
        el.addWidget(self.title_edit)

        self.url_row = QWidget()
        ur = QHBoxLayout(self.url_row)
        ur.setContentsMargins(0, 0, 0, 0)
        self.url_edit = QLineEdit()
        self.url_edit.setProperty("flat", True)
        self.url_edit.setPlaceholderText("https://…")
        self.url_edit.setAccessibleName("Link address")
        self.url_edit.editingFinished.connect(self._url_finished)
        ur.addWidget(self.url_edit, 1)
        self.open_url_btn = button("Open link", "link", "external", self._open_url)
        ur.addWidget(self.open_url_btn)
        el.addWidget(self.url_row)

        self.lang_edit = QLineEdit()
        self.lang_edit.setProperty("flat", True)
        self.lang_edit.setPlaceholderText("Language or shell (e.g. python, powershell, bash)")
        self.lang_edit.setAccessibleName("Language")
        self.lang_edit.setMaxLength(40)
        self.lang_edit.editingFinished.connect(
            lambda: self._meta_changed("language", self.lang_edit.text()) if self.current and
            self.lang_edit.text().strip() != self.current.language else None)
        el.addWidget(self.lang_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setProperty("flat", True)
        self.tags_edit.setPlaceholderText("Add tags, separated by commas")
        self.tags_edit.setAccessibleName("Note tags")
        el.addWidget(self.tags_edit)

        self.body = QStackedWidget()
        self.editor = QPlainTextEdit()
        self.editor.setProperty("editor", True)
        self.editor.setPlaceholderText("Start writing…  Link another note with [[its title]].")
        self.editor.setAccessibleName("Note content")
        self.editor.setTabChangesFocus(False)
        self._default_font = self.editor.font()
        self.body.addWidget(self.editor)
        self.preview = PreviewBrowser(self)
        self.body.addWidget(self.preview)
        el.addWidget(self.body, 1)

        self.details = CollapsibleSection("Links, attachments and backlinks", expanded=False)
        dbox = QWidget()
        dl = QVBoxLayout(dbox)
        dl.setContentsMargins(4, 0, 0, 0)
        dl.setSpacing(6)
        dl.addWidget(label("Linked items", "caption"))
        self.links_holder = QVBoxLayout()
        dl.addLayout(self.links_holder)
        dl.addWidget(label("Attachments (copies kept inside DayOS, up to 10 MB each)", "caption"))
        self.att_list = QVBoxLayout()
        self.att_list.setSpacing(2)
        dl.addLayout(self.att_list)
        dl.addWidget(label("Mentioned in", "caption"))
        self.backlinks_box = QVBoxLayout()
        self.backlinks_box.setSpacing(2)
        dl.addLayout(self.backlinks_box)
        self.details.body.addWidget(dbox)
        el.addWidget(self.details)

        self.meta = label("", "caption")
        el.addWidget(self.meta)
        self.right_stack.addWidget(editor)
        self.placeholder = QWidget()
        pl = QVBoxLayout(self.placeholder)
        pl.addWidget(EmptyState("brain", "No note selected",
                                "Choose a note on the left, or start a note, bookmark, snippet or command.",
                                [("New note", lambda: self.new_item())]))
        self.right_stack.addWidget(self.placeholder)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 700])

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_MS)
        self._timer.timeout.connect(self.save_now)
        for w in (self.title_edit, self.tags_edit):
            w.textEdited.connect(self._changed)
        self.editor.textChanged.connect(self._changed)
        install_shortcut(self, "Ctrl+S", self._manual_save)
        install_shortcut(self, "Ctrl+E", self.toggle_preview)
        self._show_editor(False)

    # -- list -----------------------------------------------------------------
    def _on_data_changed(self, domain: str) -> None:
        if self._own_notify:
            return
        super()._on_data_changed(domain)

    def refresh(self) -> None:
        self._fill_collections()
        tags = self.ctx.notes.all_tags()
        current_tag = self.tag_filter.currentData()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("All tags", "")
        for tag in tags:
            self.tag_filter.addItem(f"#{tag}", tag)
        self.tag_filter.setCurrentIndex(max(0, self.tag_filter.findData(current_tag)))
        self.tag_filter.blockSignals(False)
        self.tag_filter.setVisible(bool(tags))
        self._reload_list()
        if self.current is not None:
            self._fill_details()

    def _fill_collections(self) -> None:
        collections = self.brain.collections.list()
        self._collection_names = {c.id: c.name for c in collections}
        keep = self.coll_filter.currentData()
        self.coll_filter.blockSignals(True)
        self.coll_filter.clear()
        self.coll_filter.addItem("All collections", None)
        self.coll_filter.addItem("Not in a collection", UNFILED)
        for c in collections:
            self.coll_filter.addItem(f"{c.name}  ({c.count})", c.id)
        self.coll_filter.addItem("Manage collections…", "manage")
        index = self.coll_filter.findData(keep)
        self.coll_filter.setCurrentIndex(index if index >= 0 and keep != "manage" else 0)
        self.coll_filter.blockSignals(False)
        self.coll_combo.blockSignals(True)
        self.coll_combo.clear()
        self.coll_combo.addItem("No collection", None)
        for c in collections:
            self.coll_combo.addItem(c.name, c.id)
        self.coll_combo.addItem("New collection…", "new")
        if self.current is not None:
            self.coll_combo.setCurrentIndex(max(0, self.coll_combo.findData(self.current.collection_id)))
        self.coll_combo.blockSignals(False)

    def _coll_filter_activated(self, _index: int) -> None:
        if self.coll_filter.currentData() == "manage":
            self.coll_filter.setCurrentIndex(0)
            self.manage_collections()
            return
        self._reload_list()

    def _reload_list(self) -> None:
        self.save_now()
        coll = self.coll_filter.currentData()
        notes = self.ctx.notes.list(self.search.text(), self.tag_filter.currentData() or "",
                                    kind=self.kind_filter.currentData() or None,
                                    collection_id=coll if isinstance(coll, int) else None,
                                    archived=None if self.show_archived.isChecked() else False)
        keep = self.current.id if self.current else None
        names = getattr(self, "_collection_names", {})
        self.list.blockSignals(True)
        self.list.clear()
        selected_item = None
        for note in notes:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            widget = NoteItem(note, self.date_style, names.get(note.collection_id, ""))
            item.setSizeHint(QSize(100, widget.sizeHint().height()))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{note.title or 'Untitled'}, "
                                                             f"{NOTE_KINDS.get(note.kind, note.kind)}")
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)
            if note.id == keep:
                selected_item = item
        if selected_item:
            self.list.setCurrentItem(selected_item)
        self.list.blockSignals(False)
        fit_list_items(self.list)
        filtered = bool(self.search.text().strip() or self.tag_filter.currentData() or self.kind_filter.currentData()
                        or coll is not None or self.show_archived.isChecked())
        if self.current is None and self.list.count() and not filtered:
            self.list.setCurrentRow(0)
        total = self.ctx.notes.count()
        self.count_label.setText(
            f"{len(notes)} of {total} items" if filtered else f"{total} item{'s' if total != 1 else ''}")
        if self.current and not any(n.id == self.current.id for n in notes):
            if self.ctx.notes.get(self.current.id) is None:
                self._open(None)

    def _on_select(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        note_id = int(current.data(Qt.ItemDataRole.UserRole))
        if self.current and note_id == self.current.id:
            return
        self._open(self.ctx.notes.get(note_id))

    # -- editor -----------------------------------------------------------------
    def _show_editor(self, on: bool) -> None:
        self.right_stack.setCurrentIndex(0 if on else 1)

    def _open(self, note: Note | None) -> None:
        self.save_now()
        self._discard_if_empty()
        self.current = note
        self._loading = True
        try:
            if note is None:
                self._show_editor(False)
            else:
                self.title_edit.setText(note.title)
                self.tags_edit.setText(note.tags)
                self.url_edit.setText(note.url)
                self.lang_edit.setText(note.language)
                self.editor.setPlainText(note.content)
                self.pin_btn.setChecked(bool(note.pinned))
                self.pin_btn.setToolTip("Unpin note" if note.pinned else "Pin note")
                self._apply_kind_ui()
                self._set_status("Archived" if note.archived else "Saved")
                self._update_meta()
                self._fill_details()
                self._show_editor(True)
        finally:
            self._loading = False
        self._dirty_edit = False

    def _apply_kind_ui(self) -> None:
        note = self.current
        if note is None:
            return
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(note.kind)))
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(note.format)))
        self.coll_combo.setCurrentIndex(max(0, self.coll_combo.findData(note.collection_id)))
        self.url_row.setVisible(note.kind == "bookmark" or bool(note.url))
        self.open_url_btn.setEnabled(bool(note.url))
        self.lang_edit.setVisible(note.kind in ("snippet", "command") or bool(note.language))
        code = note.kind in ("snippet", "command")
        self.editor.setFont(mono(10.5) if code else self._default_font)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap if code
                                    else QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.copy_btn.setVisible(code or note.kind == "bookmark")
        self.copy_btn.setToolTip("Copy link" if note.kind == "bookmark" else "Copy to clipboard")
        markdown = note.format == "markdown"
        self.preview_btn.setVisible(markdown)
        if not markdown and self.preview_btn.isChecked():
            self.preview_btn.setChecked(False)
        self._show_body()
        self.archive_action.setText("Restore from archive" if note.archived else "Archive")

    def _show_body(self) -> None:
        preview = self.preview_btn.isChecked() and self.current is not None and self.current.format == "markdown"
        if preview:
            self.preview.setMarkdown(markdown_for_preview(self.editor.toPlainText()))
        self.body.setCurrentWidget(self.preview if preview else self.editor)

    def toggle_preview(self) -> None:
        if self.current is None or self.current.format != "markdown":
            return
        if self.sender() is not self.preview_btn:
            self.preview_btn.setChecked(not self.preview_btn.isChecked())
        self.save_now()
        self._show_body()

    def open_note(self, note_id: int) -> None:
        """Show a specific note (used by search, links and the command palette)."""
        note = self.ctx.notes.get(note_id)
        if note is None:
            return
        for w in (self.search, self.kind_filter, self.coll_filter, self.tag_filter, self.show_archived):
            w.blockSignals(True)
        self.search.clear()
        self.kind_filter.setCurrentIndex(0)
        self.coll_filter.setCurrentIndex(0)
        self.tag_filter.setCurrentIndex(0)
        self.show_archived.setChecked(bool(note.archived))
        for w in (self.search, self.kind_filter, self.coll_filter, self.tag_filter, self.show_archived):
            w.blockSignals(False)
        self._open(note)
        self._reload_list()

    def _update_meta(self) -> None:
        if not self.current:
            return
        words = len(self.editor.toPlainText().split())
        source = f" · From {self.current.source}" if self.current.source else ""
        self.meta.setText(f"Created {self.current.created_at[:16]} · Updated {self.current.updated_at[:16]} · "
                          f"{words} words{source}")

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _changed(self, *_args) -> None:
        if self._loading or self.current is None:
            return
        self._dirty_edit = True
        self._set_status("Unsaved changes…")
        self._timer.start()

    def save_now(self) -> bool:
        """Write pending edits. Returns False if saving failed."""
        self._timer.stop()
        if not self._dirty_edit or self.current is None:
            return True
        self._set_status("Saving…")
        note_id = self.current.id
        try:
            stamp = self.ctx.notes.save(note_id, self.title_edit.text(), self.editor.toPlainText(), self.tags_edit.text())
        except Exception as exc:
            log.exception("Autosave failed")
            self._set_status(f"Not saved — {exc}")
            return False
        self._dirty_edit = False
        if self.title_edit.text().strip() or self.editor.toPlainText().strip():
            if not self._only_template():
                self._fresh_empty_ids.discard(note_id)
        self.current.title = self.title_edit.text().strip()
        self.current.content = self.editor.toPlainText()
        self.current.tags = self.tags_edit.text()
        self.current.updated_at = stamp
        self._set_status("Saved")
        self._update_meta()
        self._update_current_item()
        self._notify()
        return True

    def _notify(self) -> None:
        self._own_notify = True
        try:
            bus.notify("notes")
        finally:
            self._own_notify = False

    def _only_template(self) -> bool:
        if self.current is None or self.title_edit.text().strip() or self.tags_edit.text().strip():
            return False
        template = KIND_TEMPLATES.get(self.current.kind, "")
        return bool(template) and self.editor.toPlainText().strip() == template.strip()

    def _update_current_item(self) -> None:
        if not self.current:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if int(item.data(Qt.ItemDataRole.UserRole)) == self.current.id:
                widget = self.list.itemWidget(item)
                if isinstance(widget, NoteItem):
                    widget.title.setText(self.current.title or "Untitled")
                    widget.snippet.setText(_snippet(self.current) or "No content yet")
                return

    def _manual_save(self) -> None:
        if self.current is not None:
            self._dirty_edit = True
            if self.save_now():
                self.toast("Note saved")

    def _discard_if_empty(self) -> None:
        """Remove a brand-new note that was left empty (or holds only its starting template)."""
        if self.current and self.current.id in self._fresh_empty_ids:
            note = self.ctx.notes.get(self.current.id)
            template = KIND_TEMPLATES.get(note.kind, "").strip() if note else ""
            if (note and not note.title.strip() and not note.tags.strip() and not note.url
                    and note.content.strip() in ("", template)
                    and not self.brain.attachments.list(note.id)):
                self.ctx.notes.delete(note.id)
            self._fresh_empty_ids.discard(self.current.id)

    # -- metadata --------------------------------------------------------------------
    def _meta_changed(self, field: str, value) -> None:
        if self._loading or self.current is None:
            return
        if getattr(self.current, field) == value:
            return
        self.save_now()
        note_id = self.current.id
        try:
            stamp = self.ctx.notes.update_meta(note_id, **{field: value})
        except Exception as exc:
            show_error(self, "Couldn't change the note", str(exc))
            self._loading = True
            try:
                self._apply_kind_ui()
                self.url_edit.setText(self.current.url)
                self.lang_edit.setText(self.current.language)
            finally:
                self._loading = False
            return
        fresh = self.ctx.notes.get(note_id)
        if fresh is None:
            return
        if field == "kind" and not self.editor.toPlainText().strip() and KIND_TEMPLATES.get(value):
            self.editor.setPlainText(KIND_TEMPLATES[value])
            self.save_now()
            fresh = self.ctx.notes.get(note_id) or fresh
        self.current = fresh
        self.current.updated_at = stamp
        self._loading = True
        try:
            self._apply_kind_ui()
        finally:
            self._loading = False
        self._update_meta()
        self._reload_list()
        self._notify()

    def _coll_combo_activated(self, _index: int) -> None:
        if self.current is None:
            return
        data = self.coll_combo.currentData()
        if data == "new":
            name, ok = QInputDialog.getText(self, "New collection", "Collection name")
            if not ok or not name.strip():
                self.coll_combo.setCurrentIndex(max(0, self.coll_combo.findData(self.current.collection_id)))
                return
            made: dict = {}
            if not guarded(self, lambda: made.setdefault("id", self.brain.collections.add(name)),
                           "Couldn't add the collection"):
                self.coll_combo.setCurrentIndex(max(0, self.coll_combo.findData(self.current.collection_id)))
                return
            self._fill_collections()
            data = made["id"]
        self._meta_changed("collection_id", data)
        self._fill_collections()

    def _url_finished(self) -> None:
        if self.current is None or self._loading:
            return
        text = self.url_edit.text().strip()
        if text == self.current.url:
            return
        self._meta_changed("url", text)
        self.url_edit.setText(self.current.url)

    def _open_url(self) -> None:
        if self.current and self.current.url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(self.current.url))

    def _copy_content(self) -> None:
        if self.current is None:
            return
        text = self.current.url if self.current.kind == "bookmark" else self.editor.toPlainText()
        QGuiApplication.clipboard().setText(text)
        self.toast("Copied")

    def _on_link(self, url: QUrl) -> None:
        href = url.toString()
        title = title_from_link(href)
        if title is not None:
            target = self.brain.resolve(title)
            if target is None:
                if not confirm(self, "Create note?", f"There is no note called “{title}” yet. Create it?",
                               "Create note", danger=False):
                    return
                made: dict = {}
                fmt = str(self.ctx.settings.get("brain.default_format"))
                if not guarded(self, lambda: made.setdefault("id", self.brain.create_linked(title, fmt))):
                    return
                bus.notify("notes")
                self.open_note(int(made["id"]))
            else:
                self.open_note(target.id)
            return
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    # -- details: links, attachments, backlinks ------------------------------------------
    def _fill_details(self) -> None:
        clear_layout(self.links_holder)
        clear_layout(self.att_list)
        clear_layout(self.backlinks_box)
        note = self.current
        if note is None:
            return
        from src.repositories.links import KIND_TABLES
        from src.ui.widgets.links import LinksPanel

        kinds = [k for k in LINK_KINDS if k in KIND_TABLES]
        self.links_holder.addWidget(LinksPanel(self.ctx, "note", note.id, kinds))
        attachments = self.brain.attachments.list(note.id)
        if not attachments:
            self.att_list.addWidget(label("No attachments.", "caption"))
        for att in attachments:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(label(f"{att.filename}  ·  {_human_size(att.size)}", "", wrap=True), 1)
            if att.mime.startswith("image/") and note.format == "markdown":
                row.addWidget(tool_button("plus", "Insert image into the note",
                                          lambda a=att: self._insert_image(a), 14))
            if Path(att.filename).suffix.lower() not in UNSAFE_TO_OPEN:
                row.addWidget(tool_button("external", "Open a copy", lambda a=att: self._open_attachment(a), 14))
            row.addWidget(tool_button("download", "Save a copy…", lambda a=att: self._save_attachment(a), 14))
            row.addWidget(tool_button("close", "Remove attachment", lambda a=att: self._remove_attachment(a), 14))
            self.att_list.addLayout(row)
        add_row = QHBoxLayout()
        add_row.addWidget(button("Attach a file…", "link", "plus", self.attach_file))
        add_row.addStretch(1)
        self.att_list.addLayout(add_row)
        backlinks = self.brain.backlinks(note)
        if not backlinks:
            self.backlinks_box.addWidget(label("No other note links here yet. Write [[" + (note.title or "title")
                                               + "]] in another note.", "caption", wrap=True))
        for other in backlinks[:20]:
            self.backlinks_box.addWidget(button(other.title or "Untitled", "link", "notes",
                                                lambda nid=other.id: self.open_note(nid)), 0, Qt.AlignmentFlag.AlignLeft)

    def attach_file(self, path: str | None = None) -> None:
        if self.current is None:
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Attach a file (a copy is kept in DayOS)")
            if not path:
                return
        self.save_now()
        note_id = self.current.id
        if guarded(self, lambda: self.brain.attachments.add(note_id, path), "Couldn't attach the file"):
            self._fresh_empty_ids.discard(note_id)
            if not self.details.toggle.isChecked():
                self.details.set_expanded(True)
            self._fill_details()
            self.toast("File attached")

    def _insert_image(self, att) -> None:
        cursor = self.editor.textCursor()
        cursor.insertText(f"![{att.filename}]({ATTACHMENT_SCHEME}:{att.id})")
        self.editor.setTextCursor(cursor)

    def _open_attachment(self, att) -> None:
        if Path(att.filename).suffix.lower() in UNSAFE_TO_OPEN:
            return
        folder = self.ctx.paths.cache_dir / "attachments" / str(att.id)
        target = folder / att.filename
        try:
            if not target.exists():
                self.brain.attachments.save_copy(att.id, folder)
                target = next(folder.iterdir())
        except Exception as exc:
            show_error(self, "Couldn't open the attachment", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _save_attachment(self, att) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save a copy into…")
        if not folder:
            return
        saved = guarded(self, lambda: self.brain.attachments.save_copy(att.id, folder), "Couldn't save the file")
        if saved:
            self.toast(f"Saved {Path(str(saved)).name}")

    def _remove_attachment(self, att) -> None:
        if not confirm(self, "Remove attachment?", f"DayOS's copy of “{att.filename}” will be deleted. "
                                                   "The original file (if you still have it) is not affected."):
            return
        if guarded(self, lambda: self.brain.attachments.remove(att.id)):
            self._fill_details()

    # -- actions ----------------------------------------------------------------
    def new_item(self, kind: str = "note") -> None:
        self.save_now()
        self._discard_if_empty()
        for w in (self.search, self.kind_filter, self.coll_filter, self.tag_filter):
            w.blockSignals(True)
        self.search.clear()
        self.kind_filter.setCurrentIndex(0)
        self.tag_filter.setCurrentIndex(0)
        coll = self.coll_filter.currentData()
        for w in (self.search, self.kind_filter, self.coll_filter, self.tag_filter):
            w.blockSignals(False)
        fmt = "plain" if kind in ("snippet", "command") else str(self.ctx.settings.get("brain.default_format"))
        note_id = self.ctx.notes.create("", KIND_TEMPLATES.get(kind, ""), kind=kind, format=fmt,
                                        collection_id=coll if isinstance(coll, int) and coll > 0 else None)
        self._fresh_empty_ids.add(note_id)
        self.current = None
        self.preview_btn.setChecked(False)
        self._open(self.ctx.notes.get(note_id))
        self._reload_list()
        (self.url_edit if kind == "bookmark" else self.title_edit).setFocus()

    def _toggle_pin(self) -> None:
        if not self.current:
            return
        pinned = self.pin_btn.isChecked()
        if guarded(self, lambda: self.ctx.notes.set_pinned(self.current.id, pinned)):
            self.current.pinned = int(pinned)
            self.pin_btn.setToolTip("Unpin note" if pinned else "Pin note")
            self._reload_list()

    def _toggle_archive(self) -> None:
        if not self.current:
            return
        archived = not bool(self.current.archived)
        self._fresh_empty_ids.discard(self.current.id)
        self._meta_changed("archived", int(archived))
        if self.current:
            self._set_status("Archived" if archived else "Saved")
            self.toast("Note archived" if archived else "Note restored")

    def _delete(self) -> None:
        if not self.current:
            return
        name = self.title_edit.text().strip() or "Untitled note"
        extra = ""
        n_att = len(self.brain.attachments.list(self.current.id))
        if n_att:
            extra = f" Its {n_att} attachment{'s' if n_att != 1 else ''} will be deleted too."
        if not confirm(self, "Delete note?", f"“{name}” will be permanently deleted.{extra} "
                                             "Archive it instead if you might need it later."):
            return
        note_id = self.current.id
        self._dirty_edit = False
        self._fresh_empty_ids.discard(note_id)
        if guarded(self, lambda: self.ctx.notes.delete(note_id)):
            self.current = None
            self._open(None)
            self.refresh()
            self.toast("Note deleted")

    def manage_collections(self) -> None:
        from src.modules.brain.ui.collections import CollectionsDialog

        CollectionsDialog(self.brain, self).exec()
        self._fill_collections()
        self._reload_list()
        self._notify()

    # -- optional AI ---------------------------------------------------------------------
    def ai_summarize(self) -> None:
        """Ask the configured AI for a summary and tags (after showing exactly what is sent)."""
        if self.current is None:
            return
        self.save_now()
        title, content = self.title_edit.text().strip(), self.editor.toPlainText()
        if not content.strip():
            self.toast("This note is empty")
            return
        from src.services import ai
        from src.ui.ai_consent import ReviewDialog, run_ai

        note_id = self.current.id

        def done(result) -> None:
            summary, tags = result
            items = [f"Add this summary at the top of the note: “{summary}”"] + [f"Add tag: {t}" for t in tags]
            dlg = ReviewDialog(self, "AI suggestions", "Written by AI from this note. Check it is accurate before "
                                                       "keeping it; nothing changes unless you add it.", items)
            if not dlg.exec():
                return
            chosen = dlg.selected()
            note = self.ctx.notes.get(note_id)
            if note is None or not chosen:
                return
            body = note.content
            if 0 in chosen:
                prefix = (f"> **AI summary:** {summary}\n\n" if note.format == "markdown" else
                          f"AI summary: {summary}\n\n")
                body = prefix + body
            new_tags = [tags[i - 1] for i in chosen if i > 0]
            merged = ", ".join([t for t in note.tag_list] + new_tags)
            if guarded(self, lambda: self.ctx.notes.save(note_id, note.title, body, merged)):
                bus.notify("notes")
                if self.current and self.current.id == note_id:
                    self.current = None
                    self._open(self.ctx.notes.get(note_id))
                self.toast("AI suggestions added")

        run_ai(self, self.ctx.settings, "a summary and tag ideas for this note", ai.note_payload(title, content),
               lambda provider: ai.summarize_note(provider, title, content), done, self.toast)

    # -- import / export ---------------------------------------------------------------
    def import_files(self, paths: list[str] | None = None) -> None:
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(self, "Import Markdown or text files", "",
                                                    "Notes (*.md *.markdown *.txt *.text)")
            if not paths:
                return
        self.save_now()
        result: dict = {}

        def run() -> None:
            result["report"] = self.brain.import_files(paths)

        if not guarded(self, run, "Import failed"):
            return
        report = result["report"]
        bus.notify("notes")
        self.refresh()
        text = f"Imported {len(report.created)} note{'s' if len(report.created) != 1 else ''}."
        if report.skipped:
            detail = "\n".join(f"{name}: {why}" for name, why in report.skipped[:30])
            show_info(self, "Import finished", text + f" {len(report.skipped)} file(s) were skipped.", detail)
        else:
            self.toast(text)
        if report.created:
            self.open_note(report.created[0])

    def export_markdown(self, note_ids: list[int] | None) -> None:
        self.save_now()
        result: dict = {}

        def run() -> None:
            result["report"] = self.brain.export_markdown(self.ctx.paths.exports_dir, note_ids)

        if guarded(self, run, "Export failed"):
            report = result["report"]
            self.toast(f"Exported {report.written} note{'s' if report.written != 1 else ''}", "Show folder",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(report.folder))))

    def _export_current(self) -> None:
        if self.current is not None:
            self.export_markdown([self.current.id])

    # -- page hooks ------------------------------------------------------------------
    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def can_leave(self) -> bool:
        ok = self.save_now()
        if ok:
            self._discard_if_empty()
        return ok or confirm(self, "Note not saved",
                             "Your latest changes couldn't be saved. Leave anyway and lose them?",
                             "Leave without saving")

    def hideEvent(self, event) -> None:  # noqa: N802
        self.save_now()
        super().hideEvent(event)
