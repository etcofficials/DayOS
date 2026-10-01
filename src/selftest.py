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
FINAL_THEME = "zen"
V2_COURSE = "Self-test course"
V2_BOOKMARK = "Self-test bookmark"
V2_SNIPPET = "Self-test snippet"
V2_MONEY = "self-test expense"
V2_SKILL = "Self-test skill"


def _v2_persisted(ctx) -> bool:
    db = ctx.db
    return all((
        db.scalar("SELECT COUNT(*) FROM sf_courses WHERE name = ?", (V2_COURSE,)) == 1,
        db.scalar("SELECT COUNT(*) FROM sf_questions WHERE text LIKE 'The self-test%'") == 1,
        db.scalar("SELECT COUNT(*) FROM notes WHERE kind = 'bookmark' AND title = ?", (V2_BOOKMARK,)) == 1,
        db.scalar("SELECT COUNT(*) FROM cv_entries WHERE title = ?", (V2_SNIPPET,)) == 1,
        db.scalar("SELECT COUNT(*) FROM money_entries WHERE note = ? AND amount = 12345", (V2_MONEY,)) == 1,
        db.scalar("SELECT COUNT(*) FROM skill_logs l JOIN skills s ON s.id = l.skill_id WHERE s.name = ?",
                  (V2_SKILL,)) == 1,
        ctx.search.search("self-test bookmark") != [],
    ))


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
            from src.modules import registry

            keys = [m.key for m in registry.MODULES] + ["settings"]
            for key in keys:
                window.navigate(key)
                _wait(250)
                if window.stack.currentWidget() is not window.page(key):
                    return False
            window.navigate("today")
            _wait(250)
            return window.stack.currentWidget() is window.pages["today"]

        def themes() -> bool:
            from src.ui.theme import theme

            modes = {}
            for theme_id in ("midnight", "zen", "aurora", "espresso", "paper", FINAL_THEME):
                ctx.settings.set("theme", theme_id)  # applied live through the settings listener
                _wait(300)
                modes[theme_id] = theme.mode
            return modes == {"midnight": "dark", "zen": "light", "aurora": "dark", "espresso": "dark",
                             "paper": "light"}

        def bundled_libraries() -> bool:
            import pypdf  # noqa: F401 - StudyForge PDF import
            from PySide6 import QtSvg  # noqa: F401 - icons and art

            import anthropic  # noqa: F401 - optional AI (imported only when used)
            return True

        def v2_records() -> bool:
            sf = ctx.services["studyforge"]
            course = sf.courses.create(V2_COURSE)
            chapter = sf.courses.add_node(course, "chapter", "Self-test chapter")
            sf.bank.add(course, "tf", "The self-test can write questions.", node_id=chapter, answer="true")
            ctx.services["brain"].add_bookmark("https://example.com/dayos-self-test", V2_BOOKMARK)
            ctx.services["clipvault"].add("self-test snippet", kind="text", title=V2_SNIPPET)
            from src.modules.money.repository import MoneyRepository
            from src.services.dates import today

            MoneyRepository(ctx.db).add_entry("expense", 12345, today(), note=V2_MONEY)
            from src.modules.skills.repository import SkillRepository

            skill = SkillRepository(ctx.db).save(None, name=V2_SKILL)
            SkillRepository(ctx.db).log(skill, "practice", 15, "self-test")
            return True

        def filepilot_scan() -> bool:
            from src.modules.filepilot import scanner
            from src.modules.filepilot.duplicates import find_duplicates

            folder = ctx.paths.home / "selftest-files"
            (folder / "a").mkdir(parents=True, exist_ok=True)
            (folder / "b").mkdir(parents=True, exist_ok=True)
            (folder / "a" / "one.txt").write_bytes(b"same bytes" * 200)
            (folder / "b" / "two.txt").write_bytes(b"same bytes" * 200)
            result = scanner.scan([str(folder)])
            groups = find_duplicates(result.files)
            return len(result.files) == 2 and len(groups) == 1

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

        for name, fn in (("pages", pages), ("themes", themes), ("bundled_libraries", bundled_libraries),
                         ("task", add_and_complete_task), ("note", save_note), ("study_session", log_study),
                         ("focus_timer", focus_timer), ("v2_records", v2_records),
                         ("filepilot_scan", filepilot_scan)):
            check(name, fn)
    else:
        check("task_persisted", lambda: any(t.title == TASK_TITLE and t.done for t in ctx.tasks.list("all")))
        check("note_persisted", lambda: any(n.title == NOTE_TITLE and n.content == NOTE_BODY for n in ctx.notes.list()))
        check("study_persisted", lambda: any(s.note == "self-test" for s in ctx.study.history()))
        check("theme_persisted", lambda: ctx.settings.get("theme") == FINAL_THEME)
        check("v2_records_persisted", lambda: _v2_persisted(ctx))
        check("schema_latest", lambda: ctx.db.user_version == __import__(
            "src.database.schema", fromlist=["LATEST_VERSION"]).LATEST_VERSION)
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
