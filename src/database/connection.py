"""SQLite connection handling with explicit transactions."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

log = logging.getLogger(__name__)


class DatabaseError(RuntimeError):
    """A user-presentable database problem."""


def open_connection(path: Path | str, *, readonly: bool = False) -> sqlite3.Connection:
    """Open a connection with DayOS's standard pragmas.

    ``isolation_level=None`` puts the driver in autocommit mode so that
    :meth:`Database.transaction` has full control over BEGIN/COMMIT.
    """
    if readonly:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=10)
    else:
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


class Database:
    """Owns the application's single read/write connection (UI thread).

    Background workers open their own short-lived connections through
    :func:`open_connection` instead of sharing this one.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.conn = open_connection(self.path)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Could not open the database at {self.path}: {exc}") from exc
        self._depth = 0

    # -- transactions -----------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block atomically. Nested calls use savepoints."""
        if self._depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
        else:
            self.conn.execute(f"SAVEPOINT sp_{self._depth}")
        self._depth += 1
        try:
            yield self.conn
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("ROLLBACK")
            else:
                self.conn.execute(f"ROLLBACK TO sp_{self._depth}")
                self.conn.execute(f"RELEASE sp_{self._depth}")
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("COMMIT")
            else:
                self.conn.execute(f"RELEASE sp_{self._depth}")

    # -- helpers ----------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] | dict = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        return self.conn.executemany(sql, rows)

    def query(self, sql: str, params: Sequence[Any] | dict = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] | dict = (), default: Any = None) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        if row is None or row[0] is None:
            return default
        return row[0]

    def insert(self, sql: str, params: Sequence[Any] | dict = ()) -> int:
        cur = self.conn.execute(sql, params)
        return int(cur.lastrowid)

    @property
    def user_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def integrity_check(self) -> list[str]:
        """Return a list of problems; an empty list means the database is healthy."""
        rows = self.conn.execute("PRAGMA integrity_check").fetchall()
        problems = [r[0] for r in rows if r[0] != "ok"]
        fk = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        problems.extend(f"Foreign key problem in table {r[0]} (row {r[1]})" for r in fk)
        return problems

    def checkpoint(self) -> None:
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            log.warning("WAL checkpoint failed", exc_info=True)

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        try:
            self.checkpoint()
            self.conn.close()
        except sqlite3.Error:
            log.warning("Error while closing the database", exc_info=True)
