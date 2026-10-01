"""Manual money tracker: income, expenses, categories, budgets, savings goals, subscriptions.

No bank connections and no predictions. Amounts are integers in minor units (1/100);
nothing here logs amounts or notes.
"""

from __future__ import annotations

import calendar
import csv
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.repositories.base import Repository, clean_text
from src.services.dates import ValidationError, iso, now_stamp, today

CYCLES = {"weekly": "Every week", "monthly": "Every month", "quarterly": "Every 3 months", "yearly": "Every year"}
SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "AUD": "A$", "CAD": "C$",
           "SGD": "S$", "AED": "AED ", "CHF": "CHF ", "NZD": "NZ$", "ZAR": "R", "BRL": "R$", "KRW": "₩", "RUB": "₽",
           "BDT": "৳", "PKR": "Rs ", "LKR": "Rs ", "NPR": "Rs "}
COMMON_CURRENCIES = ["INR", "USD", "EUR", "GBP", "AUD", "CAD", "SGD", "AED", "JPY", "CNY", "CHF", "NZD", "ZAR",
                     "BRL", "KRW", "BDT", "PKR", "LKR", "NPR"]


def parse_amount(text: str | float | int) -> int:
    """'1,234.50' -> 123450 minor units. Raises ValidationError."""
    raw = str(text).strip().replace(",", "").replace(" ", "")
    for sym in set(SYMBOLS.values()):
        raw = raw.replace(sym.strip(), "")
    try:
        if raw.count(".") > 1 or not raw:
            raise ValueError
        whole, _, frac = raw.partition(".")
        if len(frac) > 2 or (whole and not whole.isdigit()) or (frac and not frac.isdigit()):
            raise ValueError
        value = int(whole or "0") * 100 + int((frac + "00")[:2])
    except ValueError:
        raise ValidationError("Enter an amount like 250 or 1,299.50.") from None
    if value <= 0:
        raise ValidationError("The amount must be more than zero.")
    if value > 10**13:
        raise ValidationError("That amount is too large.")
    return value


def format_amount(minor: int, currency: str = "") -> str:
    sign = "−" if minor < 0 else ""
    minor = abs(int(minor))
    whole, frac = divmod(minor, 100)
    if currency == "INR":  # Indian digit grouping: 12,34,567.89
        s = str(whole)
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            s = ",".join(groups) + "," + tail
        number = s
    else:
        number = f"{whole:,}"
    number += f".{frac:02d}" if frac else ""
    symbol = SYMBOLS.get(currency, f"{currency} " if currency else "")
    return f"{sign}{symbol}{number}"


def add_cycle(day: date, cycle: str) -> date:
    if cycle == "weekly":
        return day + timedelta(days=7)
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}[cycle]
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass
class Category:
    id: int
    name: str
    kind: str


@dataclass
class Entry:
    id: int
    kind: str
    amount: int
    category_id: int | None
    date: str
    note: str
    subscription_id: int | None
    category: str = ""


@dataclass
class Subscription:
    id: int
    name: str
    amount: int
    cycle: str
    next_date: str
    category_id: int | None
    remind_days: int
    active: int
    url: str
    note: str

    @property
    def monthly_cost(self) -> float:
        return self.amount * {"weekly": 52 / 12, "monthly": 1, "quarterly": 1 / 3, "yearly": 1 / 12}[self.cycle]


@dataclass
class SavingsGoal:
    id: int
    name: str
    target: int
    saved: int
    target_date: str | None

    @property
    def fraction(self) -> float:
        return min(1.0, self.saved / self.target) if self.target else 0.0


def _month_bounds(month: str) -> tuple[str, str]:
    y, m = (int(x) for x in month.split("-"))
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


class MoneyRepository(Repository):
    # categories
    def categories(self, kind: str | None = None) -> list[Category]:
        sql = "SELECT id, name, kind FROM money_categories"
        rows = self.db.query(sql + (" WHERE kind = ?" if kind else "") + " ORDER BY kind, position, name",
                             (kind,) if kind else ())
        return [Category(int(r[0]), r[1], r[2]) for r in rows]

    def add_category(self, name: str, kind: str) -> int:
        if kind not in ("expense", "income"):
            raise ValidationError("Choose expense or income.")
        name = clean_text(name, field="Category", required=True, max_len=40)
        if self.db.scalar("SELECT 1 FROM money_categories WHERE name = ? COLLATE NOCASE AND kind = ?", (name, kind)):
            raise ValidationError(f"“{name}” already exists.")
        pos = int(self.db.scalar("SELECT COALESCE(MAX(position), 0) + 1 FROM money_categories", default=1))
        with self.db.transaction():
            return self.db.insert("INSERT INTO money_categories (name, kind, position, created_at) VALUES (?, ?, ?, ?)",
                                  (name, kind, pos, now_stamp()))

    def delete_category(self, category_id: int) -> None:
        """Entries keep their amounts and become uncategorised."""
        with self.db.transaction():
            self.db.execute("DELETE FROM money_categories WHERE id = ?", (category_id,))

    # entries
    def add_entry(self, kind: str, amount: int, day: date, category_id: int | None = None, note: str = "",
                  subscription_id: int | None = None) -> int:
        if kind not in ("expense", "income"):
            raise ValidationError("Choose expense or income.")
        if not isinstance(amount, int) or amount <= 0:
            raise ValidationError("The amount must be more than zero.")
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO money_entries (kind, amount, category_id, date, note, subscription_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, amount, category_id, iso(day), clean_text(note, field="Note", max_len=300), subscription_id,
                 now_stamp()))

    def update_entry(self, entry_id: int, kind: str, amount: int, day: date, category_id: int | None,
                     note: str) -> None:
        if kind not in ("expense", "income") or amount <= 0:
            raise ValidationError("Check the type and amount.")
        with self.db.transaction():
            self.db.execute("UPDATE money_entries SET kind = ?, amount = ?, date = ?, category_id = ?, note = ? "
                            "WHERE id = ?", (kind, amount, iso(day), category_id,
                                             clean_text(note, field="Note", max_len=300), entry_id))

    def delete_entry(self, entry_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM money_entries WHERE id = ?", (entry_id,))

    def entries(self, month: str | None = None, search: str = "", limit: int = 2000) -> list[Entry]:
        where, params = [], []
        if month:
            start, end = _month_bounds(month)
            where.append("e.date BETWEEN ? AND ?")
            params += [start, end]
        if search.strip():
            where.append("(e.note LIKE ? OR c.name LIKE ?)")
            params += [f"%{search.strip()}%"] * 2
        sql = ("SELECT e.id, e.kind, e.amount, e.category_id, e.date, e.note, e.subscription_id, "
               "COALESCE(c.name, '') AS category FROM money_entries e LEFT JOIN money_categories c "
               "ON c.id = e.category_id")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY e.date DESC, e.id DESC LIMIT ?"
        return [Entry(**dict(r)) for r in self.db.query(sql, (*params, limit))]

    def month_totals(self, month: str) -> dict[str, int]:
        start, end = _month_bounds(month)
        rows = self.db.query("SELECT kind, SUM(amount) FROM money_entries WHERE date BETWEEN ? AND ? GROUP BY kind",
                             (start, end))
        totals = {"income": 0, "expense": 0}
        for kind, total in rows:
            totals[kind] = int(total or 0)
        totals["net"] = totals["income"] - totals["expense"]
        return totals

    def by_category(self, month: str, kind: str = "expense") -> list[tuple[str, int, int | None]]:
        start, end = _month_bounds(month)
        rows = self.db.query(
            "SELECT COALESCE(c.name, 'Uncategorised'), SUM(e.amount), e.category_id FROM money_entries e "
            "LEFT JOIN money_categories c ON c.id = e.category_id WHERE e.kind = ? AND e.date BETWEEN ? AND ? "
            "GROUP BY e.category_id ORDER BY SUM(e.amount) DESC", (kind, start, end))
        return [(r[0], int(r[1]), r[2]) for r in rows]

    def history(self, months: int = 6, end_month: str | None = None) -> list[tuple[str, int, int]]:
        """(YYYY-MM, income, expense) for the last ``months`` months, oldest first."""
        end = date.fromisoformat((end_month or today().strftime("%Y-%m")) + "-01")
        out = []
        for i in range(months - 1, -1, -1):
            m = end.month - 1 - i
            y = end.year + m // 12
            key = f"{y:04d}-{m % 12 + 1:02d}"
            t = self.month_totals(key)
            out.append((key, t["income"], t["expense"]))
        return out

    # budgets (monthly; category None = overall)
    def budgets(self) -> dict[int | None, int]:
        return {r[0]: int(r[1]) for r in self.db.query("SELECT category_id, amount FROM money_budgets")}

    def set_budget(self, category_id: int | None, amount: int | None) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM money_budgets WHERE COALESCE(category_id, 0) = ?", (category_id or 0,))
            if amount:
                self.db.execute("INSERT INTO money_budgets (category_id, amount, created_at) VALUES (?, ?, ?)",
                                (category_id, int(amount), now_stamp()))

    # savings goals
    def goals(self) -> list[SavingsGoal]:
        return [SavingsGoal(**dict(r)) for r in
                self.db.query("SELECT id, name, target, saved, target_date FROM savings_goals ORDER BY id")]

    def add_goal(self, name: str, target: int, target_date: date | None = None) -> int:
        name = clean_text(name, field="Goal", required=True, max_len=80)
        if target <= 0:
            raise ValidationError("The target must be more than zero.")
        with self.db.transaction():
            return self.db.insert("INSERT INTO savings_goals (name, target, saved, target_date, created_at) "
                                  "VALUES (?, ?, 0, ?, ?)", (name, target, iso(target_date) if target_date else None,
                                                             now_stamp()))

    def add_to_goal(self, goal_id: int, amount: int) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE savings_goals SET saved = MAX(0, saved + ?) WHERE id = ?", (int(amount), goal_id))

    def delete_goal(self, goal_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM savings_goals WHERE id = ?", (goal_id,))

    # subscriptions
    def subscriptions(self, active_only: bool = False) -> list[Subscription]:
        sql = ("SELECT id, name, amount, cycle, next_date, category_id, remind_days, active, url, note "
               "FROM subscriptions" + (" WHERE active = 1" if active_only else "") + " ORDER BY active DESC, next_date")
        return [Subscription(**dict(r)) for r in self.db.query(sql)]

    def save_subscription(self, sub_id: int | None, *, name: str, amount: int, cycle: str, next_date: date,
                          category_id: int | None = None, remind_days: int = 3, active: bool = True, url: str = "",
                          note: str = "") -> int:
        name = clean_text(name, field="Name", required=True, max_len=80)
        if cycle not in CYCLES:
            raise ValidationError("Choose how often it renews.")
        if amount <= 0:
            raise ValidationError("The amount must be more than zero.")
        if not 0 <= int(remind_days) <= 30:
            raise ValidationError("Reminders can be 0 to 30 days before.")
        from src.repositories.notes import normalize_url

        url = normalize_url(url)
        values = (name, amount, cycle, iso(next_date), category_id, int(remind_days), int(bool(active)), url,
                  clean_text(note, field="Note", max_len=500))
        with self.db.transaction():
            if sub_id is None:
                return self.db.insert(
                    "INSERT INTO subscriptions (name, amount, cycle, next_date, category_id, remind_days, active, url, "
                    "note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (*values, now_stamp()))
            self.db.execute("UPDATE subscriptions SET name = ?, amount = ?, cycle = ?, next_date = ?, category_id = ?, "
                            "remind_days = ?, active = ?, url = ?, note = ? WHERE id = ?", (*values, sub_id))
            return sub_id

    def delete_subscription(self, sub_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))

    def mark_paid(self, sub_id: int, record_expense: bool = True) -> date:
        """Record this renewal (optionally as an expense) and move the next date on one cycle."""
        sub = next((s for s in self.subscriptions() if s.id == sub_id), None)
        if sub is None:
            raise ValidationError("That subscription no longer exists.")
        due = date.fromisoformat(sub.next_date)
        if record_expense:
            self.add_entry("expense", sub.amount, due, sub.category_id, sub.name, sub.id)
        nxt = add_cycle(due, sub.cycle)
        with self.db.transaction():
            self.db.execute("UPDATE subscriptions SET next_date = ? WHERE id = ?", (iso(nxt), sub_id))
        return nxt

    def upcoming_bills(self, start: datetime, end: datetime):
        """Notification provider: renewals whose reminder falls in [start, end)."""
        from src.services.notifications import Notice

        out = []
        for s in self.subscriptions(active_only=True):
            due = date.fromisoformat(s.next_date)
            remind_at = datetime.combine(due - timedelta(days=s.remind_days), datetime.min.time()).replace(hour=9)
            if start <= remind_at < end:
                when = "today" if s.remind_days == 0 else f"on {due.strftime('%d %b')}"
                out.append(Notice(f"bill:{s.id}:{s.next_date}", "bill", f"{s.name} renews {when}",
                                  "Open Money to mark it paid or change it.", remind_at, "subscription", s.id))
        return out

    # export
    def export_csv(self, folder: Path) -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"dayos-money-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
        n = 2
        while target.exists():
            target = folder / f"dayos-money-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{n}.csv"
            n += 1
        tmp = target.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["date", "type", "amount", "category", "note"])
            for e in reversed(self.entries(limit=1_000_000)):
                writer.writerow([e.date, e.kind, f"{e.amount / 100:.2f}", e.category, e.note])
        os.replace(tmp, target)
        return target
