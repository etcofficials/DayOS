"""SecondBrain: the knowledge vault (notes, bookmarks, snippets, commands, ideas, troubleshooting notes).

It grows out of v1 Notes: the sidebar entry keeps the ``notes`` key so existing
navigation, profiles and links keep working, and every v1 note is kept as is.
"""

from __future__ import annotations


def services(ctx) -> None:
    from src.modules.brain.service import SecondBrain

    ctx.services["brain"] = SecondBrain(ctx.db, ctx.notes)


def install(window) -> None:
    from src.modules.brain.ui import hooks

    hooks.install(window)
