"""How ClipVault plugs into DayOS: the clipboard monitor, its pause button in the
sidebar, the optional system-wide shortcut, palette commands and the Settings section."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton

from src.modules.clipvault.monitor import ClipMonitor
from src.services.search import SearchHit
from src.ui.bus import bus
from src.ui.icons import bind_icon
from src.ui.shell.commands import Command


def install(window) -> None:
    ctx = window.ctx
    repo = ctx.services["clipvault"]
    monitor = ClipMonitor(ctx, repo)
    window.clip_monitor = monitor
    window.shutdown_hooks.append(monitor.stop)

    def page():
        window.navigate("clipvault")
        return window.page("clipvault")

    # -- obvious pause control in the sidebar (only while ClipVault is turned on)
    btn = QToolButton()
    btn.setObjectName("BellButton")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    btn.clicked.connect(lambda: toggle_pause())
    window.sidebar_bottom.insertWidget(1, btn)
    window.clip_button = btn

    def update_button() -> None:
        btn.setVisible(monitor.enabled)
        if monitor.paused:
            bind_icon(btn, "pause-circle", "amber", 18)
            text = "Clipboard history is paused — click to resume"
        else:
            bind_icon(btn, "clipboard", "text2", 18)
            text = "Clipboard history is on — click to pause"
        btn.setToolTip(text)
        btn.setAccessibleName(text)

    def toggle_pause() -> None:
        if not monitor.enabled:
            page()
            return
        monitor.set_paused(not monitor.paused)
        bus.notify("clips")
        window.toast.show_message("Clipboard history paused" if monitor.paused else "Clipboard history resumed")

    monitor.state_changed.connect(update_button)
    update_button()

    # -- system-wide shortcut to open the quick picker
    def sequence() -> str | None:
        return str(ctx.settings.get("clip.hotkey")) if ctx.settings.get("clip.global") else None

    def open_picker() -> None:
        from src.modules.clipvault import win32
        from src.modules.clipvault.ui.picker import ClipPicker

        previous = win32.foreground_window()
        if win32.is_own_window(previous):
            previous = 0
        ClipPicker.open(window, previous)

    window.add_global_hotkey("clipvault", sequence, open_picker, ("clip.global", "clip.hotkey"))
    window.open_clip_picker = lambda: open_picker()

    # -- palette
    add = window.commands.add
    add(Command("clipvault.picker", "Clipboard history", "Search and copy something you copied earlier", "",
                "clipboard", open_picker, ("clipboard", "paste", "history", "clipvault", "snippet")))
    add(Command("clipvault.pause", "Pause or resume clipboard history", "Stop or restart saving what you copy", "",
                "pause-circle", toggle_pause, ("clipboard", "privacy", "stop", "clipvault")))
    add(Command("clipvault.template", "New text template", "A reusable text with {date}, {time} or {clipboard}", "",
                "copy", lambda: page().new_entry("template"), ("template", "snippet", "clipvault")))
    add(Command("clipvault.snippet", "New ClipVault snippet", "Keep a snippet or command ready to copy", "", "code",
                lambda: page().new_entry("code"), ("snippet", "command", "clipvault")))

    def provider(text: str, limit: int) -> list[SearchHit]:
        if not ctx.settings.get("clip.search_in_palette"):
            return []
        return [SearchHit("clip", e.id, e.label[:160], (e.category or e.kind)) for e in repo.list(text, limit=limit)]

    ctx.search.add_provider("clipvault", provider)
    window.shutdown_hooks.append(lambda: ctx.search.remove_provider("clipvault"))

    def open_clip(entry_id: int) -> None:
        page().select_entry(entry_id)

    window.openers.register("clip", open_clip)

    from src.modules.clipvault.ui.settings import register_settings

    register_settings()
