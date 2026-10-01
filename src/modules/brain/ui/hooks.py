"""SecondBrain palette commands (the note opener and search are shared with v1 Notes)."""

from __future__ import annotations

from src.modules.brain.schema import NOTE_KIND_ICONS, NOTE_KINDS
from src.ui.shell.commands import Command


def install(window) -> None:
    def page():
        window.navigate("notes")
        return window.page("notes")

    add = window.commands.add
    for kind in ("bookmark", "snippet", "command", "idea", "troubleshooting"):
        name = NOTE_KINDS[kind]
        add(Command(f"brain.new.{kind}", f"New {name.lower()}", f"Add a {name.lower()} to SecondBrain", "",
                    NOTE_KIND_ICONS[kind], lambda k=kind: page().new_item(k), ("secondbrain", "note", kind)))
    add(Command("brain.import", "Import notes", "Import Markdown or text files into SecondBrain", "", "upload",
                lambda: page().import_files(), ("markdown", "md", "txt", "secondbrain")))
    add(Command("brain.export", "Export notes as Markdown", "Write every note to .md files in a new folder", "",
                "download", lambda: page().export_markdown(None), ("markdown", "backup", "secondbrain")))
    add(Command("brain.collections", "Manage note collections", "Add, rename or remove collections", "", "folder",
                lambda: page().manage_collections(), ("folders", "secondbrain")))

    from src.ui import settings_sections

    settings_sections.register(settings_sections.SectionSpec("secondbrain", "SecondBrain", "brain", 30,
                                                             _build_settings))


def _build_settings(page):
    from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget

    from src.ui.widgets.common import Card, button, label

    ctx = page.ctx
    brain = ctx.services["brain"]
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    card = Card("Notes", "brain")
    row = QHBoxLayout()
    row.addWidget(label("New notes use", "muted"))
    fmt = QComboBox()
    fmt.setAccessibleName("Format for new notes")
    fmt.addItem("Markdown (with a preview)", "markdown")
    fmt.addItem("Plain text", "plain")
    fmt.activated.connect(lambda _i: page.set_pref("brain.default_format", fmt.currentData()))
    row.addWidget(fmt)
    row.addStretch(1)
    card.body.addLayout(row)
    usage = label("", "caption", wrap=True)
    card.body.addWidget(usage)
    card.body.addWidget(label("Notes, collections and attachments are part of every backup and JSON export. "
                              "Searching and browsing never need the internet.", "caption", wrap=True))
    row = QHBoxLayout()
    row.addWidget(button("Export all notes as Markdown…", "soft", "download", lambda: (
        page.main.navigate("notes"), page.main.page("notes").export_markdown(None))))
    row.addStretch(1)
    card.body.addLayout(row)
    lay.addWidget(card)

    def load() -> None:
        fmt.setCurrentIndex(max(0, fmt.findData(ctx.settings.get("brain.default_format"))))
        size = brain.attachments.total_size()
        usage.setText(f"{ctx.notes.count()} notes · attachments use {size / 1048576:.1f} MB inside the database.")

    page.on_refresh(load)
    return box
