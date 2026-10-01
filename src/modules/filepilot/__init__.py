"""FilePilot: read-only scans of folders you choose, duplicates by content, and safe,
previewed, recorded moves or Recycle Bin operations (never permanent deletion)."""

from __future__ import annotations

from src.modules import registry
from src.modules.registry import ModuleSpec

registry.register(ModuleSpec(
    "filepilot", "FilePilot", "file-search", "tools", "src.modules.filepilot.ui.page:FilePilotPage",
    "Storage summary, large files, true duplicates and old downloads, with previewed and undoable clean-up."))


def install(window) -> None:
    from src.ui.shell.commands import Command

    def page():
        window.navigate("filepilot")
        return window.page("filepilot")

    window.commands.add(Command("filepilot.scan", "Scan folders for clutter", "Large files, duplicates and old "
                                "downloads", "", "file-search", lambda: page().start_scan(),
                                ("files", "storage", "duplicates", "disk", "cleanup", "filepilot")))
    window.commands.add(Command("filepilot.add", "Add a folder to FilePilot", "Choose a folder or drive to scan", "",
                                "folder", lambda: page().add_folder(), ("files", "scan", "filepilot")))
