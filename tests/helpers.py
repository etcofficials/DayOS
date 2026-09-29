"""Test helpers: every test gets its own throwaway data folder under tests/.tmp.

Tests never touch the real database in data/dayos.db.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.config import AppPaths, ensure_writable
from src.context import AppContext
from src.services import dates

TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
FIXED_NOW = datetime(2026, 9, 27, 10, 0, 0)  # a Sunday


class TempHomeTestCase(unittest.TestCase):
    """Provides ``self.ctx`` backed by a fresh database, with the clock pinned."""

    now = FIXED_NOW

    def setUp(self) -> None:
        TMP_ROOT.mkdir(exist_ok=True)
        self.home = Path(tempfile.mkdtemp(prefix="dayos-", dir=TMP_ROOT))
        self.paths = AppPaths(self.home)
        ensure_writable(self.paths)
        assert self.paths.db_path != Path(__file__).resolve().parent.parent / "data" / "dayos.db"
        self.set_now(self.now)
        self.ctx = AppContext.open(self.paths)

    def tearDown(self) -> None:
        try:
            self.ctx.close()
        finally:
            dates.set_now_provider(None)
            shutil.rmtree(self.home, ignore_errors=True)

    def set_now(self, value: datetime) -> None:
        dates.set_now_provider(lambda: value)

    def reopen(self) -> AppContext:
        self.ctx.close()
        self.ctx = AppContext.open(self.paths)
        return self.ctx
