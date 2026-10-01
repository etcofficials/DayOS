"""Keep the active theme in sync with the user's saved appearance preferences.

Appearance settings are ``theme`` (a theme id or ``"system"``), ``theme.accents``
(the chosen accent per theme) and ``font_scale``. Changing any of them restyles
the app immediately; no restart, and no user records are touched.
"""

from __future__ import annotations

from src.ui.theme import theme

APPEARANCE_KEYS = ("theme", "theme.accents", "font_scale")


def accent_for(settings, theme_id: str) -> str | None:
    accents = settings.get("theme.accents") or {}
    return accents.get(theme_id) or None


def apply_from_settings(settings) -> None:
    preference = settings.get("theme")
    resolved = theme.resolve(preference)
    theme.apply(preference, accent=accent_for(settings, resolved.id), scale=float(settings.get("font_scale")))


def watch_settings(settings) -> None:
    def on_change(key: str, _value) -> None:
        if key in APPEARANCE_KEYS:
            apply_from_settings(settings)

    settings.subscribe(on_change)


def set_accent(settings, theme_id: str, accent: str | None) -> None:
    accents = settings.get("theme.accents") or {}
    if accent:
        accents[theme_id] = accent
    else:
        accents.pop(theme_id, None)
    settings.set("theme.accents", accents)
