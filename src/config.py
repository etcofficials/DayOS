"""Centralized path configuration and logging setup.

Every persistent file DayOS writes lives under one *home* directory:

* Development: the project folder (the parent of ``src``), e.g. ``G:\\DayOS``.
* Packaged (PyInstaller): the folder that contains ``DayOS.exe``.
* Override: the ``DAYOS_HOME`` environment variable (used by tests and portable setups).

DayOS never silently relocates data to another drive. If the home directory is
not writable, :func:`ensure_writable` raises :class:`DataDirectoryError` so the
UI can explain the problem.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path


class DataDirectoryError(RuntimeError):
    """The chosen data directory cannot be created or written to."""


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Read-only bundled resources (assets). Never write here."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def default_home() -> Path:
    override = os.environ.get("DAYOS_HOME")
    if override:
        return Path(override).resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppPaths:
    home: Path

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "dayos.db"

    @property
    def backups_dir(self) -> Path:
        return self.home / "backups"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.home / ".cache"

    @property
    def assets_dir(self) -> Path:
        return resource_root() / "assets"

    def writable_dirs(self) -> list[Path]:
        return [self.data_dir, self.backups_dir, self.exports_dir, self.logs_dir, self.cache_dir]


def ensure_writable(paths: AppPaths) -> None:
    """Create the data folders and verify they accept writes."""
    for directory in paths.writable_dirs():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise DataDirectoryError(
                f"DayOS cannot write to '{directory}'.\n\n"
                f"Reason: {exc.strerror or exc}\n\n"
                "Move the DayOS folder to a location you can write to "
                "(for example G:\\DayOS) or set the DAYOS_HOME environment "
                "variable to a writable folder."
            ) from exc


def setup_logging(paths: AppPaths, level: int = logging.INFO) -> None:
    """Log to a small rotating file under ``logs/``. No personal content is logged."""
    root = logging.getLogger()
    if any(getattr(h, "_dayos", False) for h in root.handlers):
        return
    handler = RotatingFileHandler(
        paths.logs_dir / "dayos.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler._dayos = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
