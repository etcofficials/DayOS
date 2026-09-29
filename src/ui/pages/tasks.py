from __future__ import annotations

from datetime import timedelta

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from src.services.dates import today
from src.services.quickadd import parse_quick_task
from src.ui.bus import bus
from src.ui.dialogs import TaskDialog
from src.ui.pages.base import Page
from src.ui.task_actions import TaskActions
from src.ui.widgets.common import (
    Card,
    EmptyState,
    PageHeader,
    SearchField,
    SegmentBar,
    button,
    clear_layout,
    guarded,
    label,
    scroll_wrap,
)
from src.ui.widgets.task_row import TaskRow, connect_row

FILTER_LABELS = [
    ("today", "Today"),
    ("upcoming", "Upcoming"),
    ("overdue", "Overdue"),
    ("nodate", "No date"),
    ("completed", "Completed"),
    ("all", "All"),
]

EMPTY_TEXT = {
    "today": ("Nothing due today", "Enjoy the space — or add something you'd like to get done today."),
    "upcoming": ("Nothing scheduled ahead", "Tasks with a future due date will appear here."),
    "overdue": ("You're all caught up", "No open tasks are past their due date."),
    "nodate": ("No undated tasks", "Tasks without a due date collect here, like an inbox."),
    "completed": ("No completed tasks yet", "Finished tasks are kept here so you can look back or reopen them."),
    "all": ("No tasks yet", "Add your first task above. Try: “Essay outline tomorrow !high #English”."),
}


class TasksPage(Page):
    domains = ("tasks", "subjects", "goals", "settings")
    title = "Tasks"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.actions = TaskActions(ctx, self, lambda t, a, c: self.toast(t, a, c))
        self.header = PageHeader("Tasks", "", eyebrow="A gentle plan")
        self.header.add_action(button("New task", "primary", "plus", self.new_item, "New task (Ctrl+N)"))
        self.root.addWidget(self.header)

        self.quick = QLineEdit()
        self.quick.setPlaceholderText("Add a task and press Enter — e.g. “Revise algebra tomorrow !high #Maths”")
        self.quick.setAccessibleName("Quick add task")
        self.quick.returnPressed.connect(self._quick_add)
        self.quick.setToolTip(
            "Quick add understands: today, tomorrow, weekday names (mon…sun), !high, !low and #category."
        )
        self.root.addWidget(self.quick)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.filters = SegmentBar(FILTER_LABELS, "today")
        self.filters.changed.connect(lambda _: self.refresh())
        bar.addWidget(self.filters)
        bar.addStretch(1)
        self.search = SearchField("Search tasks")
        self.search.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.search)
        self.sort = QComboBox()
        for key, text in [("due", "Sort: due date"), ("priority", "Sort: priority"),
                          ("created", "Sort: newest"), ("title", "Sort: title")]:
            self.sort.addItem(text, key)
        self.sort.currentIndexChanged.connect(lambda _: self.refresh())
        self.sort.setAccessibleName("Sort tasks")
        bar.addWidget(self.sort)
        self.root.addLayout(bar)

        self.body = QWidget()
        self.stack = QStackedLayout(self.body)
        self.list_holder = QWidget()
        self.list_layout = QVBoxLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(2)
        self.list_holder.setAccessibleName("Task list. Use Up and Down to move, Space to complete, Enter to edit, Delete to remove.")
        self.list = scroll_wrap(self.list_holder)
        self.stack.addWidget(self.list)
        self.empty_holder = QWidget()
        self.empty_layout = QHBoxLayout(self.empty_holder)
        self.stack.addWidget(self.empty_holder)
        self.list_card = Card(margins=14)
        self.list_card.body.addWidget(self.body, 1)
        self.list_card.layout().setStretch(0, 1)
        self.list_card.layout().setStretch(1, 0)
        self.root.addWidget(self.list_card, 1)
        self.footer = label("", "caption")
        self.root.addWidget(self.footer)
        self._rows: dict[int, TaskRow] = {}

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        ref = today()
        counts = self.ctx.tasks.counts(ref)
        for key, text in FILTER_LABELS:
            n = counts.get(key, 0)
            self.filters.set_label(key, f"{text} {n}" if key in ("today", "upcoming", "overdue", "nodate") and n else text)
        open_total = counts.get("total", 0) - counts.get("completed", 0)
        self.header.set_subtitle(
            f"{open_total} open · {counts.get('completed', 0)} completed" if counts.get("total") else
            "Capture what you need to do, then check it off."
        )
        filter_name = self.filters.current()
        selected = self.selected_id()
        had_focus = selected is not None and self._rows[selected].hasFocus()
        tasks = self.ctx.tasks.list(filter_name, self.search.text(), self.sort.currentData(), ref)
        clear_layout(self.list_layout)
        self._rows.clear()
        for task in tasks:
            row = TaskRow(task, ref, clock24=self.clock24, date_style=self.date_style)
            connect_row(row, self.actions.toggle, self.actions.edit, self.actions.delete)
            row.menu_requested.connect(self._context_menu)
            self.list_layout.addWidget(row)
            self._rows[task.id] = row
        self.list_layout.addStretch(1)
        if had_focus and selected in self._rows:
            self._rows[selected].setFocus()
        if tasks:
            self.stack.setCurrentWidget(self.list)
        else:
            self._show_empty(filter_name)
        self.footer.setText(
            f"Showing {len(tasks)} task{'s' if len(tasks) != 1 else ''}" + (" (limit 500)" if len(tasks) >= 500 else "")
            if tasks else ""
        )

    def _show_empty(self, filter_name: str) -> None:
        while self.empty_layout.count():
            w = self.empty_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        if self.search.text().strip():
            title, text = "No matching tasks", "Try a different search or another filter."
            actions = [("Clear search", self.search.clear)]
        else:
            title, text = EMPTY_TEXT[filter_name]
            actions = [("New task", self.new_item)] if filter_name not in ("overdue", "completed") else []
        self.empty_layout.addWidget(EmptyState("tasks", title, text, actions))
        self.stack.setCurrentWidget(self.empty_holder)

    # -- selection -----------------------------------------------------------
    def selected_id(self) -> int | None:
        for task_id, row in self._rows.items():
            if row.property("selected") == "true":
                return task_id
        return None

    def row_for(self, task_id: int) -> TaskRow | None:
        return self._rows.get(task_id)

    def _context_menu(self, task_id: int, global_pos) -> None:
        task = self.ctx.tasks.get(task_id)
        if task is None:
            return
        menu = QMenu(self)
        menu.addAction("Edit…", lambda: self.actions.edit(task_id))
        menu.addAction("Reopen" if task.done else "Mark complete", lambda: self.actions.toggle(task_id, not task.done))
        menu.addSeparator()
        menu.addAction("Due today", lambda: self._set_due(task_id, 0))
        menu.addAction("Due tomorrow", lambda: self._set_due(task_id, 1))
        menu.addAction("Remove due date", lambda: self._set_due(task_id, None))
        menu.addSeparator()
        menu.addAction("Delete…", lambda: self.actions.delete(task_id))
        menu.exec(global_pos)

    def _set_due(self, task_id: int, days: int | None) -> None:
        due = None if days is None else today() + timedelta(days=days)

        def run() -> None:
            if due is None:
                self.ctx.tasks.update(task_id, due_date=None, due_time=None)
            else:
                self.ctx.tasks.update(task_id, due_date=due)
            bus.notify("tasks")

        guarded(self, run, "Couldn't change the due date")

    # -- actions -------------------------------------------------------------
    def _quick_add(self) -> None:
        text = self.quick.text().strip()
        if not text:
            return
        parsed = parse_quick_task(text, today())
        if parsed.due_date is None and self.filters.current() == "today":
            parsed.due_date = today()

        def run() -> None:
            self.ctx.tasks.create(parsed.title, due_date=parsed.due_date, priority=parsed.priority,
                                  category=parsed.category)
            bus.notify("tasks")

        if guarded(self, run, "Couldn't add the task"):
            self.quick.clear()
            self.toast(f"Added “{parsed.title}”")

    def new_item(self) -> None:
        default_due = today() if self.filters.current() == "today" else None
        TaskDialog(self.ctx, self, default_due=default_due).exec()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()
