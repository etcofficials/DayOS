"""Project Workshop: projects with milestones, tasks, notes, time, changelog and releases,
plus an optional read-only GitHub panel for projects whose repository is on GitHub."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.modules.projects import github
from src.repositories.projects import STATUSES
from src.services import http
from src.services.dates import format_duration, today
from src.ui.bus import bus
from src.ui.pages.base import Page
from src.ui.widgets.common import (
    Card,
    EmptyState,
    PageHeader,
    SegmentBar,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    min_width_floor,
    scroll_wrap,
    tool_button,
)
from src.ui.worker import run_in_background

LOG_TITLES = {"note": "Notes", "changelog": "Changelog", "release": "Release notes", "time": "Time"}
GITHUB_CACHE_MINUTES = 15


class ProjectsPage(Page):
    domains = ("projects", "tasks", "links", "settings")
    title = "Projects"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.current_id: int | None = None
        self.cache = http.HttpCache(ctx.db)
        self.github_busy: set[int] = set()
        self.github_error: dict[int, str] = {}
        from src.ui.task_actions import TaskActions

        self.actions = TaskActions(ctx, self, lambda t, a, c: self.toast(t, a, c))
        header = PageHeader("Projects", "Plans, milestones, tasks, notes, time and releases in one place.",
                            eyebrow="Workshop")
        header.add_action(button("New project", "primary", "plus", self.new_item, "New project (Ctrl+N)"))
        self.root.addWidget(header)
        self.filter = SegmentBar([("open", "Current"), ("done", "Done & archived"), ("all", "All")], "open")
        self.filter.changed.connect(lambda _k: self.refresh())
        self.root.addWidget(self.filter, 0, Qt.AlignmentFlag.AlignLeft)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(14)
        left = QFrame()
        left.setProperty("panel", True)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        self.list = QListWidget()
        self.list.setAccessibleName("Projects")
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)
        min_width_floor(left, 250)
        split.addWidget(left)
        self.holder = QWidget()
        self.detail = QVBoxLayout(self.holder)
        self.detail.setContentsMargins(0, 0, 6, 0)
        self.detail.setSpacing(14)
        split.addWidget(scroll_wrap(self.holder))
        split.setSizes([290, 760])
        self.root.addWidget(split, 1)

    def _statuses(self):
        key = self.filter.current()
        return {"open": ("idea", "active", "paused"), "done": ("done", "archived"), "all": None}[key]

    def refresh(self) -> None:
        projects = self.ctx.projects.list(self._statuses())
        self.list.blockSignals(True)
        self.list.clear()
        for p in projects:
            due = ""
            if p.target_date and p.status in ("idea", "active", "paused"):
                days = (date.fromisoformat(p.target_date) - today()).days
                due = f" · due in {days} d" if days >= 0 else f" · {-days} d past target"
            item = QListWidgetItem(f"{p.name}\n{STATUSES.get(p.status, p.status)} · {p.open_tasks} open task"
                                   f"{'s' if p.open_tasks != 1 else ''}{due}")
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.list.addItem(item)
            if p.id == self.current_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if (self.current_id is None or self.current_id not in {p.id for p in projects}) and projects:
            self.current_id = projects[0].id
            self.list.setCurrentRow(0)
        elif not projects:
            self.current_id = None
        self._fill()

    def _on_select(self, item, _prev) -> None:
        if item is not None:
            self.current_id = int(item.data(Qt.ItemDataRole.UserRole))
            self._fill()

    def open_project(self, project_id: int) -> None:
        self.current_id = project_id
        self.filter.set_current("all")
        self.refresh()

    def new_item(self) -> None:
        from src.ui.pages.projects_dialog import ProjectDialog

        dlg = ProjectDialog(self.ctx, self)
        if dlg.exec():
            self.current_id = dlg.saved_id
            bus.notify("projects")
            self.filter.set_current("open")
            self.refresh()

    # -- detail ---------------------------------------------------------------------------
    def _fill(self) -> None:
        clear_layout(self.detail)
        p = self.ctx.projects.get(self.current_id) if self.current_id else None
        if p is None:
            self.detail.addWidget(EmptyState("project", "No projects here",
                                             "Start a project for anything with several steps: an app, an essay, a "
                                             "video series, a home move.", [("New project", self.new_item)]))
            self.detail.addStretch(1)
            return
        top = Card(p.name, "project")
        row = QHBoxLayout()
        row.addWidget(chip(STATUSES.get(p.status, p.status), "accent" if p.status == "active" else ""))
        if p.goal_title:
            row.addWidget(chip(f"Goal: {p.goal_title}"))
        if p.target_date:
            row.addWidget(chip(f"Target {p.target_date}"))
        row.addStretch(1)
        status = QComboBox()
        for key, text in STATUSES.items():
            status.addItem(text, key)
        status.setCurrentIndex(max(0, status.findData(p.status)))
        status.setAccessibleName("Project status")
        status.activated.connect(lambda _i, s=status: self._set_status(p.id, s.currentData()))
        row.addWidget(status)
        row.addWidget(button("Edit", "link", "edit", lambda: self.edit(p)))
        row.addWidget(button("Delete", "link", "trash", lambda: self.delete(p)))
        top.body.addLayout(row)
        if p.description:
            top.body.addWidget(label(p.description, "", wrap=True))
        total_minutes = int(p.minutes or 0)
        top.body.addWidget(label(f"{p.done_tasks} of {p.done_tasks + p.open_tasks} tasks done · time recorded "
                                 f"{format_duration(total_minutes * 60) if total_minutes else 'none yet'}",
                                 "caption", wrap=True))
        if p.repo_url:
            r = QHBoxLayout()
            r.addWidget(label(p.repo_url, "caption"), 1)
            r.addWidget(button("Open repository", "link", "external",
                               lambda: QDesktopServices.openUrl(QUrl(p.repo_url))))
            top.body.addLayout(r)
        self.detail.addWidget(top)
        self.detail.addWidget(self._milestones(p))
        self.detail.addWidget(self._tasks(p))
        self.detail.addWidget(self._logs(p))
        if github.parse_repo(p.repo_url):
            self.detail.addWidget(self._github(p))
        links = Card("Linked notes, files and more", "link")
        from src.repositories.links import KIND_TABLES
        from src.ui.widgets.links import LinksPanel

        kinds = [k for k in ("note", "task", "goal", "skill", "course", "event") if k in KIND_TABLES]
        links.body.addWidget(LinksPanel(self.ctx, "project", p.id, kinds))
        self.detail.addWidget(links)
        self.detail.addStretch(1)

    def _milestones(self, p) -> Card:
        card = Card("Milestones", "flag")
        for m in self.ctx.milestones.list("project", p.id):
            r = QHBoxLayout()
            cb = QCheckBox(m.title + (f"  ·  {m.due_date}" if getattr(m, "due_date", None) else ""))
            cb.setChecked(bool(m.done_at))
            cb.toggled.connect(lambda v, mid=m.id: guarded(self, lambda: self.ctx.milestones.set_done("project", mid, v)))
            r.addWidget(cb, 1)
            r.addWidget(tool_button("close", "Remove milestone", lambda mid=m.id: self._del_milestone(mid), 14))
            card.body.addLayout(r)
        add = QHBoxLayout()
        title = QLineEdit()
        title.setPlaceholderText("Next milestone")
        add.addWidget(title, 1)
        add.addWidget(button("Add", "soft", "plus", lambda: self._add_milestone(p.id, title)))
        title.returnPressed.connect(lambda: self._add_milestone(p.id, title))
        card.body.addLayout(add)
        return card

    def _tasks(self, p) -> Card:
        card = Card("Tasks", "tasks")
        tasks = self.ctx.tasks.list("all", project_id=p.id)
        open_tasks = [t for t in tasks if not t.done][:15]
        for t in open_tasks:
            r = QHBoxLayout()
            cb = QCheckBox(t.title + (f"  ·  due {t.due_date}" if t.due_date else ""))
            cb.toggled.connect(lambda v, tid=t.id: self._toggle_task(tid, v))
            r.addWidget(cb, 1)
            r.addWidget(tool_button("edit", "Open task", lambda tid=t.id: self.main.openers.open("task", tid), 14))
            card.body.addLayout(r)
        if not open_tasks:
            card.body.addWidget(label("No open tasks.", "muted"))
        add = QHBoxLayout()
        title = QLineEdit()
        title.setPlaceholderText("Add a task to this project")
        add.addWidget(title, 1)
        add.addWidget(button("Add", "soft", "plus", lambda: self._add_task(p.id, title)))
        title.returnPressed.connect(lambda: self._add_task(p.id, title))
        card.body.addLayout(add)
        hint = QHBoxLayout()
        hint.addWidget(label("Open a task to set its deadline or what it's waiting on.", "caption"), 1)
        hint.addWidget(button("Suggest tasks with AI…", "link", "sparkle", lambda: self.ai_tasks(p)))
        card.body.addLayout(hint)
        return card

    def ai_tasks(self, p) -> None:
        from src.services import ai
        from src.ui.ai_consent import ReviewDialog, run_ai

        existing = [t.title for t in self.ctx.tasks.list("all", project_id=p.id)] + \
                   [m.title for m in self.ctx.milestones.list("project", p.id)]
        name, description, project_id = p.name, p.description, p.id

        def done(tasks) -> None:
            items = [f"{title}  ·  about {minutes} min" for title, minutes in tasks]
            dlg = ReviewDialog(self, "Suggested tasks", "Suggested by AI. Tick the ones worth doing; they are added to "
                                                        "this project as ordinary tasks you can edit.", items,
                               checked=False)
            if not dlg.exec():
                return
            added = 0
            for i in dlg.selected():
                title, minutes = tasks[i]
                if guarded(self, lambda t=title, m=minutes: self.ctx.tasks.create(t, project_id=project_id,
                                                                                   estimate_minutes=m)):
                    added += 1
            if added:
                self._changed("tasks")
                self.toast(f"Added {added} task{'s' if added != 1 else ''}")

        run_ai(self, self.ctx.settings, "task ideas for this project", ai.project_payload(name, description, existing),
               lambda provider: ai.suggest_tasks(provider, name, description, existing), done, self.toast)

    def _logs(self, p) -> Card:
        card = Card("Log", "list")
        kind = QComboBox()
        for key, text in LOG_TITLES.items():
            kind.addItem(text, key)
        form = QHBoxLayout()
        form.addWidget(kind)
        version = QLineEdit()
        version.setPlaceholderText("Version, e.g. 1.2.0")
        version.setMaximumWidth(140)
        form.addWidget(version)
        minutes = QSpinBox()
        minutes.setRange(1, 1440)
        minutes.setValue(60)
        minutes.setSuffix(" min")
        form.addWidget(minutes)
        text = QLineEdit()
        text.setPlaceholderText("What happened")
        form.addWidget(text, 1)
        form.addWidget(button("Add", "soft", "plus", lambda: self._add_log(p.id, kind.currentData(), text, version,
                                                                          minutes.value())))

        def kind_changed() -> None:
            k = kind.currentData()
            version.setVisible(k in ("release", "changelog"))
            minutes.setVisible(k == "time")

        kind.currentIndexChanged.connect(lambda _i: kind_changed())
        kind_changed()
        card.body.addLayout(form)
        for log in self.ctx.projects.logs(p.id, limit=20):
            r = QHBoxLayout()
            bits = [log.date, LOG_TITLES.get(log.kind, log.kind)]
            if log.version:
                bits.append(log.version)
            if log.minutes:
                bits.append(format_duration(log.minutes * 60))
            if log.text:
                bits.append(log.text)
            r.addWidget(label(" · ".join(bits), "", wrap=True), 1)
            r.addWidget(tool_button("close", "Delete entry", lambda lid=log.id: self._del_log(lid), 14))
            card.body.addLayout(r)
        return card

    def _github(self, p) -> Card:
        card = Card("GitHub", "external")
        owner, repo = github.parse_repo(p.repo_url)
        cached = self.cache.get(f"github:{owner}/{repo}".lower())
        row = QHBoxLayout()
        state = ("Loading…" if p.id in self.github_busy else self.github_error.get(p.id, ""))
        if cached:
            state = (state + " · " if state else "") + f"Updated {http.describe_age(cached[1])}"
        row.addWidget(label(state or "Shows issues, pull requests and releases. Read-only.", "caption", wrap=True), 1)
        row.addWidget(button("Load from GitHub" if not cached else "Refresh", "soft", "refresh",
                             lambda: self.load_github(p.id, owner, repo)))
        card.body.addLayout(row)
        if cached:
            info = cached[0]
            card.body.addWidget(label(f"{info['full_name']}{' (private)' if info.get('private') else ''} · "
                                      f"★ {info.get('stars', 0)} · {info.get('forks', 0)} forks", "rowtitle", wrap=True))
            if info.get("description"):
                card.body.addWidget(label(info["description"], "muted", wrap=True))
            for title, key in (("Open issues", "issues"), ("Open pull requests", "pulls"), ("Releases", "releases")):
                items = info.get(key) or []
                card.body.addWidget(label(f"{title} ({len(items)}{'+' if len(items) >= 10 else ''})", "caption"))
                for it in items[:5]:
                    text = (f"#{it['number']} {it['title']}" if key != "releases" else
                            f"{it['name']} ({it['tag']}){' · draft' if it.get('draft') else ''}"
                            f"{' · pre-release' if it.get('prerelease') else ''} · {it.get('published', '')[:10]}")
                    btn = button(text, "link", on_click=lambda u=it.get("url", ""): QDesktopServices.openUrl(QUrl(u))
                                 if u.startswith("https://") else None)
                    btn.setStyleSheet("text-align: left;")
                    card.body.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
                if not items:
                    card.body.addWidget(label("None.", "muted"))
        return card

    def load_github(self, project_id: int, owner: str, repo: str) -> None:
        if project_id in self.github_busy:
            return
        self.github_busy.add(project_id)
        self.github_error.pop(project_id, None)
        token = github.saved_token()

        def done(info) -> None:
            self.github_busy.discard(project_id)
            self.cache.put(f"github:{owner}/{repo}".lower(), info.__dict__)
            if self.current_id == project_id:
                self._fill()

        def failed(exc) -> None:
            self.github_busy.discard(project_id)
            self.github_error[project_id] = str(exc)
            if self.current_id == project_id:
                self._fill()

        run_in_background(lambda: github.fetch_repo(owner, repo, token), done, failed)
        self._fill()

    # -- actions ------------------------------------------------------------------------------
    def _changed(self, *domains: str) -> None:
        bus.notify("projects", *domains)
        self.refresh()

    def _set_status(self, project_id: int, status: str) -> None:
        if guarded(self, lambda: self.ctx.projects.update(project_id, status=status)):
            self._changed()

    def edit(self, p) -> None:
        from src.ui.pages.projects_dialog import ProjectDialog

        if ProjectDialog(self.ctx, self, p).exec():
            self._changed()

    def delete(self, p) -> None:
        if confirm(self, "Delete project?", f"“{p.name}”, its milestones and log will be deleted. Its tasks are kept "
                                            "(without a project).") and guarded(self, lambda: self.ctx.projects.delete(p.id)):
            self.current_id = None
            self._changed("tasks")

    def _add_milestone(self, project_id: int, edit: QLineEdit) -> None:
        if edit.text().strip() and guarded(self, lambda: self.ctx.milestones.add("project", project_id, edit.text())):
            self._changed()

    def _del_milestone(self, milestone_id: int) -> None:
        if guarded(self, lambda: self.ctx.milestones.delete("project", milestone_id)):
            self._changed()

    def _add_task(self, project_id: int, edit: QLineEdit) -> None:
        if edit.text().strip() and guarded(self, lambda: self.ctx.tasks.create(edit.text(), project_id=project_id)):
            self._changed("tasks")

    def _toggle_task(self, task_id: int, done: bool) -> None:
        self.actions.toggle(task_id, done)  # handles repeats, undo and notifications
        self.refresh()

    def _add_log(self, project_id: int, kind: str, text: QLineEdit, version: QLineEdit, minutes: int) -> None:
        if guarded(self, lambda: self.ctx.projects.add_log(project_id, kind, text.text(), minutes=minutes,
                                                           version=version.text())):
            self._changed()

    def _del_log(self, log_id: int) -> None:
        if guarded(self, lambda: self.ctx.projects.delete_log(log_id)):
            self._changed()
