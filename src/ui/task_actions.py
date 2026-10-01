"""Task operations shared by the Tasks page, Today dashboard and goal view."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from src.context import AppContext
from src.services.dates import relative_day, today
from src.ui.bus import bus
from src.ui.dialogs import TaskDialog
from src.ui.widgets.common import confirm, guarded


class TaskActions:
    def __init__(self, ctx: AppContext, parent: QWidget,
                 toast: Callable[[str, str | None, Callable[[], None] | None], None]) -> None:
        self.ctx = ctx
        self.parent = parent
        self.toast = toast

    def toggle(self, task_id: int, done: bool) -> None:
        spawned: list[int | None] = [None]

        def run() -> None:
            spawned[0] = self.ctx.tasks.set_completed(task_id, done)
            # Let the check-mark animation finish before lists rebuild.
            QTimer.singleShot(260, lambda: bus.notify("tasks", "goals", "projects"))

        if guarded(self.parent, run, "Couldn't update the task"):
            if done:
                nxt = self.ctx.tasks.get(spawned[0]) if spawned[0] else None
                text = f"Task completed · next one {relative_day(nxt.due, today()).lower()}" if nxt and nxt.due                     else "Task completed"
                self.toast(text, "Undo", lambda: self.undo_complete(task_id, spawned[0]))
            else:
                self.toast("Task reopened", None, None)

    def undo_complete(self, task_id: int, spawned_id: int | None) -> None:
        def run() -> None:
            self.ctx.tasks.undo_completion(task_id, spawned_id)
            bus.notify("tasks", "goals", "projects")

        guarded(self.parent, run, "Couldn't undo")

    def edit(self, task_id: int) -> None:
        task = self.ctx.tasks.get(task_id)
        if task is None:
            bus.notify("tasks")
            return
        TaskDialog(self.ctx, self.parent, task).exec()

    def delete(self, task_id: int) -> None:
        task = self.ctx.tasks.get(task_id)
        if task is None:
            return
        extra = f" and its {task.subtask_total} checklist item(s)" if task.subtask_total else ""
        if not confirm(self.parent, "Delete task?",
                       f"“{task.title}”{extra} will be deleted. Other records are not affected."):
            return
        snapshot = None

        def run() -> None:
            nonlocal snapshot
            snapshot = self.ctx.tasks.delete(task_id)
            bus.notify("tasks", "goals")

        if guarded(self.parent, run, "Couldn't delete the task") and snapshot is not None:
            snap = snapshot

            def undo() -> None:
                if guarded(self.parent, lambda: self.ctx.tasks.restore(snap), "Couldn't restore the task"):
                    bus.notify("tasks", "goals")
                    self.toast("Task restored", None, None)

            self.toast("Task deleted", "Undo", undo)
