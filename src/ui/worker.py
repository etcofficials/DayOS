"""Run slow file operations (backup, export) off the UI thread."""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)

_active: set["_Job"] = set()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # reported to the UI via the failed signal
            log.exception("Background job failed")
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


def run_in_background(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[Exception], None],
) -> None:
    """Run ``fn`` on the thread pool; callbacks are delivered on the UI thread.

    ``fn`` must not use the UI thread's SQLite connection; background code opens
    its own connection via :func:`src.database.open_connection`.
    """
    job = _Job(fn)
    _active.add(job)

    def finish(callback: Callable[[Any], None], value: Any) -> None:
        _active.discard(job)
        callback(value)

    job.signals.done.connect(lambda r: finish(on_done, r))
    job.signals.failed.connect(lambda e: finish(on_error, e))
    QThreadPool.globalInstance().start(job)


def wait_for_background(timeout_ms: int = 10000) -> bool:
    return QThreadPool.globalInstance().waitForDone(timeout_ms)
