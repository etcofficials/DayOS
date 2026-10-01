"""Money: an optional, manual tracker for income, expenses, budgets, savings and subscriptions.

No bank connections. Amounts and notes are never written to logs.
"""

from __future__ import annotations

from src.modules import registry
from src.modules.registry import ModuleSpec

registry.register(ModuleSpec(
    "money", "Money", "money", "life", "src.modules.money.ui.page:MoneyPage",
    "Income, expenses, monthly budgets, savings goals and subscription reminders — kept on this computer."))


def services(ctx) -> None:
    from src.modules.money.repository import MoneyRepository

    repo = MoneyRepository(ctx.db)
    ctx.services["money"] = repo

    def bills(start, end):
        return repo.upcoming_bills(start, end) if ctx.settings.get("notify.bill") else []

    ctx.notifications.add_provider("bill", bills)


def install(window) -> None:
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

    from datetime import date

    from src.modules.money.repository import format_amount
    from src.services.dates import today
    from src.ui.shell.commands import Command
    from src.ui.widgets.common import Card, button, clear_layout, label

    ctx = window.ctx
    repo = ctx.services["money"]

    def page():
        window.navigate("money")
        return window.page("money")

    window.commands.add(Command("money.expense", "Add expense", "Record something you spent", "", "money",
                                lambda: page().add_entry("expense"), ("spend", "money", "expense", "paid")))
    window.commands.add(Command("money.income", "Add income", "Record money that came in", "", "money",
                                lambda: page().add_entry("income"), ("money", "income", "salary")))
    window.commands.add(Command("money.subscription", "Add subscription", "Get reminded before it renews", "",
                                "repeat", lambda: page().add_sub(), ("bill", "subscription", "renewal")))

    def open_subscription(_sid: int) -> None:
        page().tabs.setCurrentIndex(2)

    window.openers.register("subscription", open_subscription)

    card = Card("Bills & budget", "money")
    box = QVBoxLayout()
    card.body.addLayout(box)

    def fill(_card, _day) -> None:
        clear_layout(box)
        cur = str(ctx.settings.get("money.currency") or "")
        month = today().strftime("%Y-%m")
        totals = repo.month_totals(month)
        box.addWidget(label(f"This month: {format_amount(totals['expense'], cur)} out · "
                            f"{format_amount(totals['income'], cur)} in", "", wrap=True))
        overall = repo.budgets().get(None)
        if overall:
            left = overall - totals["expense"]
            box.addWidget(label(f"{format_amount(left, cur)} left of your monthly budget" if left >= 0 else
                                f"{format_amount(-left, cur)} over your monthly budget", "caption", wrap=True))
        soon = [s for s in repo.subscriptions(active_only=True)
                if (date.fromisoformat(s.next_date) - today()).days <= 7]
        for s in soon[:3]:
            box.addWidget(label(f"• {s.name}: {format_amount(s.amount, cur)} on {s.next_date}", "caption", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Add expense", "soft", "plus", lambda: page().add_entry("expense")))
        row.addStretch(1)
        box.addLayout(row)

    window.pages["today"].register_widget("money", card, fill)
