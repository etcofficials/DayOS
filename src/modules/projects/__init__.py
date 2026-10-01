"""Project Workshop: the Projects page, a dashboard widget and optional GitHub access."""

from __future__ import annotations

from src.modules import registry
from src.modules.registry import ModuleSpec

registry.register(ModuleSpec(
    "projects", "Projects", "project", "create", "src.modules.projects.ui.page:ProjectsPage",
    "Projects with milestones, tasks, notes, time, changelog, releases and optional GitHub details."))


def install(window) -> None:
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

    from src.ui import settings_sections
    from src.ui.shell.commands import Command
    from src.ui.widgets.common import Card, button, clear_layout, label

    ctx = window.ctx

    def page():
        window.navigate("projects")
        return window.page("projects")

    window.openers.register("project", lambda pid: page().open_project(pid))
    window.commands.add(Command("projects.open", "Projects", "Open the project workshop", "", "project", page,
                                ("project", "workshop", "milestones", "release")))

    card = Card("Active projects", "project")
    box = QVBoxLayout()
    card.body.addLayout(box)

    def fill(_card, _day) -> None:
        clear_layout(box)
        projects = ctx.projects.list(("active",))[:4]
        if not projects:
            box.addWidget(label("No active projects.", "muted"))
        for p in projects:
            total = p.open_tasks + p.done_tasks
            text = f"{p.name} · {p.done_tasks}/{total} tasks" if total else p.name
            if p.target_date:
                text += f" · target {p.target_date}"
            btn = button(text, "link", "chev-right", lambda pid=p.id: page().open_project(pid))
            btn.setStyleSheet("text-align: left;")
            box.addWidget(btn)
        row = QHBoxLayout()
        row.addWidget(button("New project", "soft", "plus", lambda: page().new_item()))
        row.addStretch(1)
        box.addLayout(row)

    window.pages["today"].register_widget("projects", card, fill)
    settings_sections.register(settings_sections.SectionSpec("github", "GitHub", "external", 60, _github_settings))


def _github_settings(page):
    from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

    from src.modules.projects import github
    from src.services import credentials
    from src.ui.widgets.common import Card, button, confirm, label, show_error
    from src.ui.worker import run_in_background

    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    card = Card("GitHub (optional)", "external")
    card.body.addWidget(label(
        "Projects with a github.com repository link can show open issues, pull requests and releases. Public "
        "repositories work without signing in (GitHub allows about 60 requests an hour). For private repositories, "
        "create a fine-grained personal access token on github.com with read-only access to the repositories you "
        "want, and paste it below. DayOS keeps it in Windows Credential Manager only — never in its database, "
        "backups, exports or logs — and only ever reads from GitHub.", "muted", wrap=True))
    status = label("", "", wrap=True)
    card.body.addWidget(status)
    row = QHBoxLayout()
    token = QLineEdit()
    token.setEchoMode(QLineEdit.EchoMode.Password)
    token.setPlaceholderText("Paste a personal access token")
    token.setAccessibleName("GitHub access token")
    row.addWidget(token, 1)
    save_btn = button("Check and save", "primary", "check")
    row.addWidget(save_btn)
    card.body.addLayout(row)
    remove_btn = button("Remove saved token", "ghost", "trash")
    card.body.addWidget(remove_btn)
    lay.addWidget(card)

    def load() -> None:
        saved = github.saved_token()
        status.setText(f"A token is saved ({credentials.mask(saved)})." if saved else "No token saved — public "
                       "repositories only.")
        remove_btn.setVisible(bool(saved))

    def save() -> None:
        value = token.text().strip()
        if not value:
            return
        save_btn.setEnabled(False)
        status.setText("Checking with GitHub…")

        def done(login: str) -> None:
            save_btn.setEnabled(True)
            try:
                credentials.save(github.CREDENTIAL, value)
            except credentials.CredentialError as exc:
                show_error(page, "Couldn't save the token", str(exc))
                return
            token.clear()
            load()
            status.setText(status.text() + f" It belongs to {login}.")

        def failed(exc: Exception) -> None:
            save_btn.setEnabled(True)
            status.setText(f"GitHub didn't accept that token: {exc}")

        run_in_background(lambda: github.check_token(value), done, failed)

    def remove() -> None:
        if confirm(page, "Remove the GitHub token?", "DayOS will forget the token. You can also revoke it on "
                                                     "github.com.", "Remove"):
            credentials.delete(github.CREDENTIAL)
            load()

    save_btn.clicked.connect(lambda _=False: save())
    token.returnPressed.connect(save)
    remove_btn.clicked.connect(lambda _=False: remove())
    page.on_refresh(load)
    return box
