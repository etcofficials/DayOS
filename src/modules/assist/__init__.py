"""Optional AI assistance: the Settings → AI section (features live in their own modules)."""

from __future__ import annotations


def install(window) -> None:
    from src.ui import settings_sections
    from src.ui.ai_settings import build

    settings_sections.register(settings_sections.SectionSpec("ai", "AI (optional)", "sparkle", 70, build))
