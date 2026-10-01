"""DayOS feature modules and the registry that ties them into the main window.

Each feature package exposes three optional hooks:

* importing it registers its sidebar page(s) with :mod:`src.modules.registry`;
* ``services(ctx)`` adds Qt-free services to ``ctx.services``;
* ``install(window)`` adds palette commands, record openers and dashboard hooks.

A feature that fails to load is logged and skipped, so the rest of DayOS still opens.
"""

from __future__ import annotations

import importlib
import logging

log = logging.getLogger(__name__)

FEATURES = [
    "src.modules.studyforge",
    "src.modules.brain",
    "src.modules.clipvault",
    "src.modules.filepilot",
    "src.modules.audiodock",
]

_loaded: list = []


def load_features() -> list:
    if _loaded:
        return _loaded
    for name in FEATURES:
        try:
            _loaded.append(importlib.import_module(name))
        except Exception:
            log.exception("Feature %s failed to load; continuing without it", name)
    return _loaded


def install_services(ctx) -> None:
    for module in load_features():
        hook = getattr(module, "services", None)
        if hook is not None:
            try:
                hook(ctx)
            except Exception:
                log.exception("Services for %s failed", module.__name__)


def install_ui(window) -> None:
    for module in load_features():
        hook = getattr(module, "install", None)
        if hook is not None:
            try:
                hook(window)
            except Exception:
                log.exception("UI hooks for %s failed", module.__name__)
