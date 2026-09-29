"""Built-in end-to-end check for the packaged app (``DayOS.exe --self-test write|verify``).

It drives the real window and real UI code paths: adds and completes a task
through the dashboard, saves a note through the editor, logs a study session,
runs the focus timer, visits every page and switches themes. ``verify`` runs in
a second launch and confirms everything persisted.

Always point it at a throwaway data folder, e.g.::

    set DAYOS_HOME=G:\\DayOS\\release\\verify
    DayOS.exe --self-test write
    DayOS.exe --self-test verify

Results are written to ``selftest.json`` in that folder and to the log.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

log = logging.getLogger("dayos.selftest")

TASK_TITLE = "Self-test task"
NOTE_TITLE = "Self-test note"
NOTE_BODY = "Written by the DayOS self-test."


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run(window, phase: str, done: Callable[[int], None]) -> None:
    ctx = window.ctx
    results: dict[str, bool | str] = {}

    def check(name: str, fn: Callable[[], bool]) -> None:
        try:
            results[name] = bool(fn())
        except Exception as exc:  # recorded as a failed check
            log.exception("Self-test step %s failed", name)
            results[name] = f"error: {exc}"

    if phase == "write":
        def pages() -> bool:
            for key in window.pages:
                window.navigate(key)
                _wait(320)
            window.navigate("today")
            _wait(320)
            return window.stack.currentWidget() is window.pages["today"]

        def themes() -> bool:
            ctx.settings.set("theme", "dark")
            _wait(400)
            from src.ui.theme import theme

            dark_ok = theme.mode == "dark"
            ctx.settings.set("theme", "light")
            _wait(400)
            return dark_ok and theme.mode == "light"

        def add_and_complete_task() -> bool:
            today_page = window.pages["today"]
            today_page.quick_edit.setText(TASK_TITLE)
            today_page._quick_task()
            _wait(300)
            task = next(t for t in ctx.tasks.list("today") if t.title == TASK_TITLE)
            today_page.actions.toggle(task.id, True)
            _wait(500)
            return ctx.tasks.get(task.id).done

        def save_note() -> bool:
            window.navigate("notes")
            _wait(300)
            notes = window.pages["notes"]
            notes.new_item()
            notes.title_edit.setText(NOTE_TITLE)
            notes.title_edit.textEdited.emit(NOTE_TITLE)
            notes.editor.setPlainText(NOTE_BODY)
            window.navigate("today")  # leaving the page must flush the autosave
            _wait(300)
            return any(n.title == NOTE_TITLE and n.content == NOTE_BODY for n in ctx.notes.list())

        def log_study() -> bool:
            from src.ui.dialogs import ManualStudyDialog

            dlg = ManualStudyDialog(ctx, window)
            dlg.minutes.setValue(30)
            dlg.note.setText("self-test")
            dlg._on_save()
            return any(s.note == "self-test" for s in ctx.study.history())

        def focus_timer() -> bool:
            study = window.pages["study"]
            window.pages["today"].nook._start()
            _wait(1300)
            running = study.timer.state == "running" and study.timer.elapsed() > 0.5
            study.start_pause()
            paused = study.timer.state == "paused"
            study._reset()
            return running and paused and study.timer.state == "idle"

        for name, fn in (("pages", pages), ("themes", themes), ("task", add_and_complete_task),
                         ("note", save_note), ("study_session", log_study), ("focus_timer", focus_timer)):
            check(name, fn)
    else:
        check("task_persisted", lambda: any(t.title == TASK_TITLE and t.done for t in ctx.tasks.list("all")))
        check("note_persisted", lambda: any(n.title == NOTE_TITLE and n.content == NOTE_BODY for n in ctx.notes.list()))
        check("study_persisted", lambda: any(s.note == "self-test" for s in ctx.study.history()))
        check("theme_persisted", lambda: ctx.settings.get("theme") == "light")
        check("database_healthy", lambda: ctx.db.integrity_check() == [])

    ok = all(v is True for v in results.values())
    report = {"phase": phase, "ok": ok, "results": results}
    log.info("Self-test %s: %s", phase, report)
    try:
        (ctx.paths.home / "selftest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        log.warning("Could not write selftest.json", exc_info=True)
    print(json.dumps(report))
    done(0 if ok else 1)


def schedule(window, phase: str) -> None:
    app = QApplication.instance()
    code = {"value": 1}

    def finish(result: int) -> None:
        code["value"] = result
        window.close()
        app.exit(result)

    QTimer.singleShot(900, lambda: run(window, phase, finish))
