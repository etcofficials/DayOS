"""Create or edit a project."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit

from src.repositories.projects import STATUSES
from src.ui.bus import bus
from src.ui.widgets.common import FormDialog, IdCombo, OptionalDate, label


class ProjectDialog(FormDialog):
    def __init__(self, ctx, parent=None, project=None, name: str = "", description: str = "") -> None:
        super().__init__("Edit project" if project else "New project", parent, width=540)
        self.ctx = ctx
        self.project = project
        self.saved_id: int | None = project.id if project else None
        self.name = QLineEdit(project.name if project else name)
        self.name.setPlaceholderText("Project name")
        self.add_row("Name", self.name)
        self.desc = QPlainTextEdit(project.description if project else description)
        self.desc.setPlaceholderText("What is it, and what does done look like?")
        self.desc.setFixedHeight(90)
        self.add_row("Description", self.desc)
        self.status = QComboBox()
        for key, text in STATUSES.items():
            self.status.addItem(text, key)
        self.status.setCurrentIndex(max(0, self.status.findData(project.status if project else "active")))
        self.add_row("Status", self.status)
        self.goal = IdCombo("Not linked to a goal")
        self.goal.set_items([(g.id, g.title) for g in ctx.goals.list() if g.status != "completed"
                             or (project and project.goal_id == g.id)])
        self.goal.set_current_id(project.goal_id if project else None)
        self.add_row("Goal", self.goal)
        from datetime import date

        self.start = OptionalDate("Starts", date.fromisoformat(project.start_date) if project and project.start_date else None)
        self.add_row("Start", self.start)
        self.target = OptionalDate("Target", date.fromisoformat(project.target_date) if project and project.target_date else None)
        self.add_row("Target date", self.target)
        self.repo = QLineEdit(project.repo_url if project else "")
        self.repo.setPlaceholderText("Optional, e.g. https://github.com/you/project")
        self.add_row("Repository", self.repo)
        self.form.addRow(label("The repository link is only stored and opened in your browser when you click it. "
                               "DayOS doesn't contact GitHub unless you turn on the optional integration.",
                               "caption", wrap=True))
        self.name.setFocus()

    def save(self) -> None:
        data = dict(name=self.name.text(), description=self.desc.toPlainText(), status=self.status.currentData(),
                    goal_id=self.goal.current_id(), start_date=self.start.value(), target_date=self.target.value(),
                    repo_url=self.repo.text())
        if self.project:
            self.ctx.projects.update(self.project.id, **data)
        else:
            self.saved_id = self.ctx.projects.create(**data)
        bus.notify("projects", "tasks")
