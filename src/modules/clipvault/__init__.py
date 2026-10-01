"""ClipVault: opt-in clipboard history, snippets, commands and text templates.

Capture is off until the user turns it on after reading what is stored. While it
is off or paused the clipboard is not read at all.
"""

from __future__ import annotations

from src.modules import registry
from src.modules.registry import ModuleSpec

registry.register(ModuleSpec(
    "clipvault", "ClipVault", "clipboard", "tools", "src.modules.clipvault.ui.page:ClipVaultPage",
    "Clipboard history (opt-in), pinned snippets, terminal commands and reusable text templates."))


def services(ctx) -> None:
    from src.modules.clipvault.repository import ClipRepository

    ctx.services["clipvault"] = ClipRepository(ctx.db)


def install(window) -> None:
    from src.modules.clipvault.ui import hooks

    hooks.install(window)
