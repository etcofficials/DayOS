"""Registry of Settings sections, so feature modules can add their own preferences.

A section is built lazily the first time it is opened. ``builder(page)`` returns
the section's content widget; it may call ``page.on_refresh(callback)`` to be
told when settings change elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    icon: str
    order: int
    builder: Callable  # (SettingsPage) -> QWidget


SECTIONS: list[SectionSpec] = []


def register(spec: SectionSpec) -> None:
    if any(s.key == spec.key for s in SECTIONS):
        return
    SECTIONS.append(spec)
    SECTIONS.sort(key=lambda s: s.order)
