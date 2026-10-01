"""Money page: a manual tracker for income, expenses, budgets, savings and subscriptions."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QLocale, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.modules.money.repository import (
    COMMON_CURRENCIES,
    CYCLES,
    MoneyRepository,
    format_amount,
    parse_amount,
)
from src.services.dates import today
from src.ui.bus import bus
from src.ui.pages.base import Page
from src.ui.widgets.charts import HBarList
from src.ui.widgets.common import (
    Card,
    DateEdit,
    FormDialog,
    OptionalDate,
    PageHeader,
    SearchField,
    button,
    clear_layout,
    confirm,
    guarded,
    label,
    scroll_wrap,
    tool_button,
)


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def shift_month(key: str, delta: int) -> str:
    y, m = (int(x) for x in key.split("-"))
    m += delta
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def month_name(key: str) -> str:
    return date.fromisoformat(key + "-01").strftime("%B %Y")


class EntryDialog(FormDialog):
    def __init__(self, page: "MoneyPage", kind: str = "expense", entry=None) -> None:
        super().__init__("Edit entry" if entry else ("Add income" if kind == "income" else "Add expense"), page)
        self.page = page
        self.entry = entry
        self.kind = QComboBox()
        self.kind.addItem("Expense", "expense")
        self.kind.addItem("Income", "income")
        self.kind.setCurrentIndex(self.kind.findData(entry.kind if entry else kind))
        self.kind.currentIndexChanged.connect(lambda _i: self._fill_categories())
        self.add_row("Type", self.kind)
        self.amount = QLineEdit(f"{entry.amount / 100:.2f}" if entry else "")
        self.amount.setPlaceholderText(f"Amount in {page.currency}")
        self.add_row("Amount", self.amount)
        self.date = DateEdit()
        self.date.set_value(date.fromisoformat(entry.date) if entry else today())
        self.add_row("Date", self.date)
        self.category = QComboBox()
        self.add_row("Category", self.category)
        self.note = QLineEdit(entry.note if entry else "")
        self.note.setMaxLength(300)
        self.note.setPlaceholderText("What was it for? (optional)")
        self.add_row("Note", self.note)
        self._fill_categories()
        if entry:
            self.category.setCurrentIndex(max(0, self.category.findData(entry.category_id)))
        self.amount.setFocus()

    def _fill_categories(self) -> None:
        self.category.clear()
        self.category.addItem("No category", None)
        for c in self.page.money.categories(self.kind.currentData()):
            self.category.addItem(c.name, c.id)

    def save(self) -> None:
        amount = parse_amount(self.amount.text())
        args = (self.kind.currentData(), amount, self.date.value(), self.category.currentData(), self.note.text())
        if self.entry:
            self.page.money.update_entry(self.entry.id, *args)
        else:
            self.page.money.add_entry(*args)


class SubscriptionDialog(FormDialog):
    def __init__(self, page: "MoneyPage", sub=None) -> None:
        super().__init__("Edit subscription" if sub else "Add subscription or bill", page)
        self.page = page
        self.sub = sub
        self.name = QLineEdit(sub.name if sub else "")
        self.name.setMaxLength(80)
        self.add_row("Name", self.name)
        self.amount = QLineEdit(f"{sub.amount / 100:.2f}" if sub else "")
        self.add_row("Amount", self.amount)
        self.cycle = QComboBox()
        for key, text in CYCLES.items():
            self.cycle.addItem(text, key)
        self.cycle.setCurrentIndex(max(0, self.cycle.findData(sub.cycle if sub else "monthly")))
        self.add_row("Renews", self.cycle)
        self.next_date = DateEdit()
        self.next_date.set_value(date.fromisoformat(sub.next_date) if sub else today() + timedelta(days=30))
        self.add_row("Next payment", self.next_date)
        self.remind = QSpinBox()
        self.remind.setRange(0, 30)
        self.remind.setSuffix(" days before")
        self.remind.setSpecialValueText("On the day")
        self.remind.setValue(sub.remind_days if sub else 3)
        self.add_row("Remind me", self.remind)
        self.category = QComboBox()
        self.category.addItem("No category", None)
        for c in page.money.categories("expense"):
            self.category.addItem(c.name, c.id)
        default_cat = next((c.id for c in page.money.categories("expense") if c.name == "Subscriptions"), None)
        self.category.setCurrentIndex(max(0, self.category.findData(sub.category_id if sub else default_cat)))
        self.add_row("Category", self.category)
        self.url = QLineEdit(sub.url if sub else "")
        self.url.setPlaceholderText("Account or cancellation page (optional)")
        self.add_row("Link", self.url)
        self.active = QCheckBox("Active")
        self.active.setChecked(bool(sub.active) if sub else True)
        self.add_row("", self.active)

    def save(self) -> None:
        self.page.money.save_subscription(
            self.sub.id if self.sub else None, name=self.name.text(), amount=parse_amount(self.amount.text()),
            cycle=self.cycle.currentData(), next_date=self.next_date.value(), category_id=self.category.currentData(),
            remind_days=self.remind.value(), active=self.active.isChecked(), url=self.url.text())


class GoalDialog(FormDialog):
    def __init__(self, page: "MoneyPage") -> None:
        super().__init__("New savings goal", page)
        self.page = page
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.add_row("Saving for", self.name)
        self.target = QLineEdit()
        self.add_row("Target", self.target)
        self.when = OptionalDate("Target date")
        self.add_row("By", self.when)

    def save(self) -> None:
        self.page.money.add_goal(self.name.text(), parse_amount(self.target.text()), self.when.value())


class MoneyPage(Page):
    domains = ("money", "settings")
    title = "Money"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.money = MoneyRepository(ctx.db)
        self.month = month_key(today())
        header = PageHeader("Money", "A private, manual record of what comes in and goes out. No bank connections; "
                                     "nothing leaves this computer.", eyebrow="Bills & budget")
        header.add_action(button("Export CSV", "ghost", "download", self.export_csv))
        header.add_action(button("Add income", "ghost", "plus", lambda: self.add_entry("income")))
        header.add_action(button("Add expense", "primary", "plus", lambda: self.add_entry("expense")))
        self.root.addWidget(header)

        self.setup = Card("Choose your currency", "money")
        self.setup.body.addWidget(label("Amounts are shown in the currency you pick. DayOS doesn't convert currencies.",
                                        "muted", wrap=True))
        row = QHBoxLayout()
        self.currency_combo = QComboBox()
        local = QLocale.system().currencySymbol(QLocale.CurrencySymbolFormat.CurrencyIsoCode)
        codes = COMMON_CURRENCIES if local in COMMON_CURRENCIES or not local else [local] + COMMON_CURRENCIES
        for code in codes:
            self.currency_combo.addItem(code, code)
        self.currency_combo.setCurrentIndex(max(0, self.currency_combo.findData(local)))
        row.addWidget(self.currency_combo)
        row.addWidget(button("Use this currency", "primary", "check", self._set_currency))
        row.addStretch(1)
        self.setup.body.addLayout(row)
        self.root.addWidget(self.setup)

        nav = QHBoxLayout()
        nav.addWidget(tool_button("chev-left", "Previous month", lambda: self._go(-1)))
        self.month_label = label("", "section")
        nav.addWidget(self.month_label)
        nav.addWidget(tool_button("chev-right", "Next month", lambda: self._go(1)))
        nav.addWidget(button("This month", "link", on_click=lambda: self._go(0)))
        nav.addStretch(1)
        self.root.addLayout(nav)

        self.tabs = QTabWidget()
        self.overview_holder = QWidget()
        self.overview = QVBoxLayout(self.overview_holder)
        self.overview.setContentsMargins(0, 10, 6, 0)
        self.overview.setSpacing(14)
        self.tabs.addTab(scroll_wrap(self.overview_holder), "Overview")
        entries = QWidget()
        el = QVBoxLayout(entries)
        el.setContentsMargins(0, 10, 0, 0)
        self.search = SearchField("Search notes and categories")
        self.search.textChanged.connect(lambda _t: self._fill_entries())
        el.addWidget(self.search)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date", "Type", "Amount", "Category", "Note"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.itemDoubleClicked.connect(lambda _i: self.edit_selected())
        self.table.setAccessibleName("Entries")
        el.addWidget(self.table, 1)
        er = QHBoxLayout()
        er.addStretch(1)
        er.addWidget(button("Edit", "ghost", "edit", self.edit_selected))
        er.addWidget(button("Delete", "ghost", "trash", self.delete_selected))
        el.addLayout(er)
        self.tabs.addTab(entries, "Entries")
        self.subs_holder = QWidget()
        self.subs = QVBoxLayout(self.subs_holder)
        self.subs.setContentsMargins(0, 10, 6, 0)
        self.tabs.addTab(scroll_wrap(self.subs_holder), "Subscriptions")
        self.goals_holder = QWidget()
        self.goals = QVBoxLayout(self.goals_holder)
        self.goals.setContentsMargins(0, 10, 6, 0)
        self.tabs.addTab(scroll_wrap(self.goals_holder), "Savings")
        self.cats_holder = QWidget()
        self.cats = QVBoxLayout(self.cats_holder)
        self.cats.setContentsMargins(0, 10, 6, 0)
        self.tabs.addTab(scroll_wrap(self.cats_holder), "Categories && budgets")
        self.root.addWidget(self.tabs, 1)

    @property
    def currency(self) -> str:
        return str(self.ctx.settings.get("money.currency") or "")

    def fmt(self, minor: int) -> str:
        return format_amount(minor, self.currency)

    def _set_currency(self) -> None:
        self.ctx.settings.set("money.currency", self.currency_combo.currentData())
        bus.notify("settings", "money")

    def _go(self, delta: int) -> None:
        self.month = month_key(today()) if delta == 0 else shift_month(self.month, delta)
        self.refresh()

    def refresh(self) -> None:
        self.setup.setVisible(not self.currency)
        self.month_label.setText(month_name(self.month))
        self._fill_overview()
        self._fill_entries()
        self._fill_subs()
        self._fill_goals()
        self._fill_categories()

    # -- overview ----------------------------------------------------------------------
    def _fill_overview(self) -> None:
        clear_layout(self.overview)
        totals = self.money.month_totals(self.month)
        top = QHBoxLayout()
        for value, caption in ((self.fmt(totals["income"]), "came in"), (self.fmt(totals["expense"]), "went out"),
                               (self.fmt(totals["net"]), "left over" if totals["net"] >= 0 else "more out than in")):
            col = QVBoxLayout()
            col.addWidget(label(value, "metric"))
            col.addWidget(label(caption, "metricLabel"))
            top.addLayout(col)
        top.addStretch(1)
        self.overview.addLayout(top)
        budgets = self.money.budgets()
        spent = {cid: amount for _name, amount, cid in self.money.by_category(self.month)}
        card = Card("Budgets this month", "chart")
        if budgets:
            bars = HBarList()
            rows = []
            names = {c.id: c.name for c in self.money.categories("expense")}
            for cid, limit in sorted(budgets.items(), key=lambda x: (x[0] is not None, names.get(x[0], ""))):
                used = totals["expense"] if cid is None else spent.get(cid, 0)
                tone = "danger" if used > limit else "amber" if used > 0.85 * limit else "accent"
                rows.append(("Overall" if cid is None else names.get(cid, "Category"), min(1.0, used / limit),
                             f"{self.fmt(used)} of {self.fmt(limit)}", tone))
            bars.set_rows(rows)
            card.body.addWidget(bars)
        else:
            card.body.addWidget(label("No budgets yet. Set them in Categories & budgets if they help you.", "muted",
                                      wrap=True))
        self.overview.addWidget(card)
        card = Card("Where it went", "money")
        cats = self.money.by_category(self.month)
        if cats:
            biggest = max(a for _n, a, _c in cats)
            bars = HBarList()
            bars.set_rows([(n, a / biggest, self.fmt(a), "terracotta") for n, a, _c in cats[:10]])
            card.body.addWidget(bars)
        else:
            card.body.addWidget(label("No expenses recorded this month.", "muted"))
        self.overview.addWidget(card)
        card = Card("Last six months", "insights")
        hist = self.money.history(6, self.month)
        peak = max([max(i, e) for _m, i, e in hist] + [1])
        bars = HBarList()
        rows = []
        for m, inc, exp in hist:
            rows.append((f"{month_name(m)} in", inc / peak, self.fmt(inc), "accent"))
            rows.append((f"{month_name(m)} out", exp / peak, self.fmt(exp), "terracotta"))
        bars.set_rows(rows)
        card.body.addWidget(bars)
        card.body.addWidget(label("Only what you recorded. DayOS doesn't forecast or give financial advice.",
                                  "caption", wrap=True))
        self.overview.addWidget(card)
        self.overview.addStretch(1)

    # -- entries ---------------------------------------------------------------------------
    def _fill_entries(self) -> None:
        entries = self.money.entries(self.month, self.search.text())
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            values = [e.date, "Income" if e.kind == "income" else "Expense",
                      ("+" if e.kind == "income" else "") + self.fmt(e.amount), e.category or "—", e.note]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, e.id)
                if col == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self._entries = {e.id: e for e in entries}

    def _selected_entry(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self._entries.get(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))

    def add_entry(self, kind: str = "expense") -> None:
        if not self.currency:
            self._set_currency()
        if EntryDialog(self, kind).exec():
            bus.notify("money")

    def edit_selected(self) -> None:
        entry = self._selected_entry()
        if entry and EntryDialog(self, entry.kind, entry).exec():
            bus.notify("money")

    def delete_selected(self) -> None:
        entry = self._selected_entry()
        if entry and confirm(self, "Delete entry?", f"The {entry.kind} of {self.fmt(entry.amount)} on {entry.date} "
                                                    "will be deleted.") \
                and guarded(self, lambda: self.money.delete_entry(entry.id)):
            bus.notify("money")

    # -- subscriptions ---------------------------------------------------------------------
    def _fill_subs(self) -> None:
        clear_layout(self.subs)
        subs = self.money.subscriptions()
        active = [s for s in subs if s.active]
        monthly = sum(s.monthly_cost for s in active)
        top = QHBoxLayout()
        top.addWidget(label(f"{len(active)} active · about {self.fmt(round(monthly))} a month · "
                            f"{self.fmt(round(monthly * 12))} a year", "", wrap=True), 1)
        top.addWidget(button("Add subscription", "soft", "plus", self.add_sub))
        self.subs.addLayout(top)
        for s in subs:
            card = Card(s.name + ("" if s.active else " (paused)"), "repeat")
            due = date.fromisoformat(s.next_date)
            days = (due - today()).days
            when = "today" if days == 0 else f"in {days} days" if days > 0 else f"{-days} days ago — not marked paid"
            card.body.addWidget(label(f"{self.fmt(s.amount)} · {CYCLES[s.cycle].lower()} · next {due.strftime('%d %b %Y')} "
                                      f"({when})", "warning" if days < 0 else "", wrap=True))
            row = QHBoxLayout()
            row.addWidget(button("Mark paid", "soft", "check", lambda sid=s.id: self.mark_paid(sid)))
            row.addWidget(button("Edit", "link", "edit", lambda sub=s: self.edit_sub(sub)))
            if s.url:
                row.addWidget(button("Open link", "link", "external",
                                     lambda u=s.url: QDesktopServices.openUrl(QUrl(u))))
            row.addWidget(button("Delete", "link", "trash", lambda sub=s: self.delete_sub(sub)))
            row.addStretch(1)
            card.body.addLayout(row)
            self.subs.addWidget(card)
        if not subs:
            self.subs.addWidget(label("No subscriptions yet. Add streaming, phone, software or rent to get a gentle "
                                      "reminder before each renewal.", "muted", wrap=True))
        self.subs.addStretch(1)

    def add_sub(self) -> None:
        if SubscriptionDialog(self).exec():
            bus.notify("money")

    def edit_sub(self, sub) -> None:
        if SubscriptionDialog(self, sub).exec():
            bus.notify("money")

    def delete_sub(self, sub) -> None:
        if confirm(self, "Delete subscription?", f"“{sub.name}” will be removed. Past payments stay in your entries.") \
                and guarded(self, lambda: self.money.delete_subscription(sub.id)):
            bus.notify("money")

    def mark_paid(self, sub_id: int) -> None:
        result: dict = {}
        if guarded(self, lambda: result.setdefault("next", self.money.mark_paid(sub_id))):
            bus.notify("money", "reminders")
            self.toast(f"Recorded. Next payment {result['next'].strftime('%d %b %Y')}")

    # -- savings -----------------------------------------------------------------------------
    def _fill_goals(self) -> None:
        clear_layout(self.goals)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("New savings goal", "soft", "plus", self.add_goal))
        self.goals.addLayout(row)
        goals = self.money.goals()
        if goals:
            bars = HBarList()
            bars.set_rows([(g.name, g.fraction, f"{self.fmt(g.saved)} of {self.fmt(g.target)}"
                            + (f" · by {g.target_date}" if g.target_date else ""), "accent") for g in goals])
            self.goals.addWidget(bars)
            for g in goals:
                r = QHBoxLayout()
                r.addWidget(label(g.name, "rowtitle"), 1)
                amount = QLineEdit()
                amount.setPlaceholderText("Amount")
                amount.setMaximumWidth(120)
                r.addWidget(amount)
                r.addWidget(button("Add", "soft", "plus", lambda gid=g.id, a=amount: self.goal_add(gid, a.text(), 1)))
                r.addWidget(button("Take out", "link", on_click=lambda gid=g.id, a=amount: self.goal_add(gid, a.text(), -1)))
                r.addWidget(tool_button("trash", "Delete goal", lambda gg=g: self.delete_goal(gg)))
                self.goals.addLayout(r)
        else:
            self.goals.addWidget(label("No savings goals yet.", "muted"))
        self.goals.addStretch(1)

    def add_goal(self) -> None:
        if GoalDialog(self).exec():
            bus.notify("money")

    def goal_add(self, goal_id: int, text: str, sign: int) -> None:
        if guarded(self, lambda: self.money.add_to_goal(goal_id, sign * parse_amount(text))):
            bus.notify("money")

    def delete_goal(self, goal) -> None:
        if confirm(self, "Delete goal?", f"“{goal.name}” will be deleted.") and \
                guarded(self, lambda: self.money.delete_goal(goal.id)):
            bus.notify("money")

    # -- categories and budgets ----------------------------------------------------------------
    def _fill_categories(self) -> None:
        clear_layout(self.cats)
        budgets = self.money.budgets()
        self.cats.addWidget(label("Monthly budgets are optional. Leave a box empty for no budget.", "muted", wrap=True))
        overall = QHBoxLayout()
        overall.addWidget(label("Overall monthly spending", "rowtitle"), 1)
        self.cats.addLayout(overall)
        self._budget_edit(overall, None, budgets.get(None))
        for kind, title in (("expense", "Expense categories"), ("income", "Income categories")):
            self.cats.addWidget(label(title, "section"))
            for c in self.money.categories(kind):
                r = QHBoxLayout()
                r.addWidget(label(c.name), 1)
                if kind == "expense":
                    self._budget_edit(r, c.id, budgets.get(c.id))
                r.addWidget(tool_button("trash", f"Delete {c.name}", lambda cat=c: self.delete_category(cat)))
                self.cats.addLayout(r)
            add = QHBoxLayout()
            name = QLineEdit()
            name.setPlaceholderText("New category")
            name.setMaxLength(40)
            add.addWidget(name, 1)
            add.addWidget(button("Add", "soft", "plus", lambda n=name, k=kind: self.add_category(n, k)))
            self.cats.addLayout(add)
        self.cats.addStretch(1)

    def _budget_edit(self, row: QHBoxLayout, category_id, current) -> None:
        edit = QLineEdit(f"{current / 100:.2f}" if current else "")
        edit.setPlaceholderText("No budget")
        edit.setMaximumWidth(140)
        edit.setAccessibleName("Monthly budget")
        edit.editingFinished.connect(lambda e=edit, cid=category_id: self.set_budget(cid, e.text()))
        row.addWidget(edit)

    def set_budget(self, category_id, text: str) -> None:
        amount = None
        if text.strip():
            try:
                amount = parse_amount(text)
            except Exception as exc:
                self.toast(str(exc))
                return
        if self.money.budgets().get(category_id) != amount and guarded(
                self, lambda: self.money.set_budget(category_id, amount)):
            self._fill_overview()

    def add_category(self, edit: QLineEdit, kind: str) -> None:
        if guarded(self, lambda: self.money.add_category(edit.text(), kind)):
            bus.notify("money")

    def delete_category(self, cat) -> None:
        if confirm(self, "Delete category?", f"“{cat.name}” will be removed. Entries keep their amounts and become "
                                             "uncategorised.") and guarded(self, lambda: self.money.delete_category(cat.id)):
            bus.notify("money")

    def export_csv(self) -> None:
        result: dict = {}
        if guarded(self, lambda: result.setdefault("p", self.money.export_csv(self.ctx.paths.exports_dir))):
            path = result["p"]
            self.toast(f"Exported {path.name}", "Show folder",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent))))
