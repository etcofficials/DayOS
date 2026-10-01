"""ClipVault storage: clipboard history, snippets, templates and exclusion rules.

History entries are deduplicated by content: copying the same text again moves
the existing entry to the top instead of adding a copy. Pinned and favourite
entries, templates and anything added by hand are never removed by retention.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.repositories.base import Repository, clean_text
from src.repositories.notes import normalize_tags
from src.services.dates import ValidationError, now_stamp
from src.services.dates import now as _now

from .privacy import Rule, validate_rule
from .schema import CLIP_KINDS, RULE_KINDS

MAX_ENTRY_CHARS = 200_000
KEPT = "(pinned = 1 OR favorite = 1 OR kind = 'template' OR origin = 'manual')"

_COMMAND_START = re.compile(
    r"^(\$ |> |PS [A-Z]:\\|git |npm |npx |yarn |pnpm |pip |pip3 |python |py |node |cd |ls |dir |mkdir |rm |del |cp |"
    r"mv |copy |move |docker |kubectl |winget |choco |scoop |ssh |scp |curl |wget |sudo |apt |apt-get |brew |"
    r"cargo |go |dotnet |gh |code |Get-|Set-|New-|Remove-|Start-|Stop-|Invoke-|Test-)")
_CODE_HINTS = ("def ", "class ", "{", "};", "=>", "import ", "#include", "function ", "SELECT ", "</", "return ",
               "const ", "let ", "var ", "public ", "private ")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def guess_kind(text: str) -> str:
    t = text.strip()
    if "\n" not in t and re.fullmatch(r"https?://\S+", t):
        return "url"
    if "\n" not in t and _COMMAND_START.match(t):
        return "command"
    lines = t.split("\n")
    if len(lines) > 1 and (any(h in t for h in _CODE_HINTS) or sum(ln.startswith(("    ", "\t")) for ln in lines) >= 2):
        return "code"
    return "text"


def expand_template(text: str, clipboard: str = "", now: datetime | None = None) -> str:
    """Fill {date}, {time}, {datetime} and {clipboard}. Other braces are left as they are."""
    now = now or _now()
    values = {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
              "datetime": now.strftime("%Y-%m-%d %H:%M"), "clipboard": clipboard}
    return re.sub(r"\{(date|time|datetime|clipboard)\}", lambda m: values[m.group(1)], text)


@dataclass
class ClipEntry:
    id: int
    content: str
    kind: str = "text"
    title: str = ""
    category: str = ""
    tags: str = ""
    pinned: int = 0
    favorite: int = 0
    origin: str = "captured"
    source_app: str = ""
    created_at: str = ""
    last_used_at: str = ""
    use_count: int = 0

    @property
    def label(self) -> str:
        if self.title:
            return self.title
        first = next((ln.strip() for ln in self.content.split("\n") if ln.strip()), "")
        return first[:120] or "(blank)"

    @property
    def kept(self) -> bool:
        return bool(self.pinned or self.favorite or self.kind == "template" or self.origin == "manual")


@dataclass
class RuleRow:
    id: int
    kind: str
    value: str
    enabled: int

    @property
    def description(self) -> str:
        return f"{RULE_KINDS.get(self.kind, self.kind)}: {self.value}"


_COLS = ("id, content, kind, title, category, tags, pinned, favorite, origin, source_app, created_at, "
         "last_used_at, use_count")


def _entry(row) -> ClipEntry:
    return ClipEntry(**dict(row))


class ClipRepository(Repository):
    # -- history ----------------------------------------------------------------------
    def record(self, text: str, source_app: str = "") -> tuple[int, bool]:
        """Store a captured clipboard text. Returns (entry id, created)."""
        if not text or not text.strip():
            raise ValidationError("Nothing to save.")
        if len(text) > MAX_ENTRY_CHARS:
            raise ValidationError("That text is too long to keep.")
        digest = content_hash(text)
        stamp = now_stamp()
        with self.db.transaction():
            existing = self.db.scalar("SELECT id FROM cv_entries WHERE content_hash = ?", (digest,))
            if existing:
                self.db.execute("UPDATE cv_entries SET last_used_at = ? WHERE id = ?", (stamp, existing))
                return int(existing), False
            entry_id = self.db.insert(
                "INSERT INTO cv_entries (content, content_hash, kind, source_app, origin, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, 'captured', ?, ?)",
                (text, digest, guess_kind(text), clean_text(source_app, field="App", max_len=120), stamp, stamp))
            return entry_id, True

    def add(self, content: str, kind: str = "", title: str = "", category: str = "", tags: str = "",
            favorite: bool = False) -> int:
        """A snippet, command or template added by hand (kept until deleted)."""
        if not content or not content.strip():
            raise ValidationError("Write the text to keep.")
        if len(content) > MAX_ENTRY_CHARS:
            raise ValidationError("That text is too long to keep.")
        kind = kind or guess_kind(content)
        if kind not in CLIP_KINDS:
            raise ValidationError(f"Unknown type: {kind}")
        digest = content_hash(content)
        stamp = now_stamp()
        title = clean_text(title, field="Title", max_len=120)
        category = clean_text(category, field="Category", max_len=40)
        with self.db.transaction():
            existing = self.db.scalar("SELECT id FROM cv_entries WHERE content_hash = ?", (digest,))
            if existing:
                self.db.execute(
                    "UPDATE cv_entries SET origin = 'manual', kind = ?, title = CASE WHEN ? != '' THEN ? ELSE title END, "
                    "category = CASE WHEN ? != '' THEN ? ELSE category END, tags = ?, "
                    "favorite = MAX(favorite, ?), last_used_at = ? WHERE id = ?",
                    (kind, title, title, category, category, normalize_tags(tags), int(favorite), stamp, existing))
                return int(existing)
            return self.db.insert(
                "INSERT INTO cv_entries (content, content_hash, kind, title, category, tags, favorite, origin, "
                "created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)",
                (content, digest, kind, title, category, normalize_tags(tags), int(favorite), stamp, stamp))

    def update(self, entry_id: int, *, content: str | None = None, kind: str | None = None,
               title: str | None = None, category: str | None = None, tags: str | None = None) -> None:
        fields: dict = {}
        if content is not None:
            if not content.strip():
                raise ValidationError("The text can't be empty.")
            if len(content) > MAX_ENTRY_CHARS:
                raise ValidationError("That text is too long to keep.")
            digest = content_hash(content)
            clash = self.db.scalar("SELECT id FROM cv_entries WHERE content_hash = ? AND id != ?", (digest, entry_id))
            if clash:
                raise ValidationError("Another entry already has exactly this text.")
            fields.update(content=content, content_hash=digest)
        if kind is not None:
            if kind not in CLIP_KINDS:
                raise ValidationError(f"Unknown type: {kind}")
            fields["kind"] = kind
        if title is not None:
            fields["title"] = clean_text(title, field="Title", max_len=120)
        if category is not None:
            fields["category"] = clean_text(category, field="Category", max_len=40)
        if tags is not None:
            fields["tags"] = normalize_tags(tags)
        if not fields:
            return
        with self.db.transaction():
            self.db.execute(f"UPDATE cv_entries SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                            (*fields.values(), entry_id))

    def get(self, entry_id: int) -> ClipEntry | None:
        row = self.db.query_one(f"SELECT {_COLS} FROM cv_entries WHERE id = ?", (entry_id,))
        return _entry(row) if row else None

    def list(self, search: str = "", view: str = "all", category: str = "", limit: int = 500) -> list[ClipEntry]:
        """``view``: all, pinned, favorites, snippets (code + commands), templates or history (captured)."""
        where: list[str] = []
        params: list = []
        if search.strip():
            like = f"%{search.strip()}%"
            where.append("(content LIKE ? OR title LIKE ? OR tags LIKE ? OR category LIKE ?)")
            params += [like, like, like, like]
        views = {"pinned": "pinned = 1", "favorites": "favorite = 1", "snippets": "kind IN ('code', 'command')",
                 "templates": "kind = 'template'", "history": "origin = 'captured'"}
        if view in views:
            where.append(views[view])
        if category:
            where.append("category = ?")
            params.append(category)
        sql = f"SELECT {_COLS} FROM cv_entries"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY pinned DESC, last_used_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        return [_entry(r) for r in self.db.query(sql, params)]

    def categories(self) -> list[str]:
        return [r[0] for r in self.db.query(
            "SELECT DISTINCT category FROM cv_entries WHERE category != '' ORDER BY category COLLATE NOCASE")]

    def mark_used(self, entry_id: int) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE cv_entries SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
                            (now_stamp(), entry_id))

    def set_flag(self, entry_id: int, flag: str, on: bool) -> None:
        if flag not in ("pinned", "favorite"):
            raise ValueError(flag)
        with self.db.transaction():
            self.db.execute(f"UPDATE cv_entries SET {flag} = ? WHERE id = ?", (int(on), entry_id))

    def delete(self, entry_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM cv_entries WHERE id = ?", (entry_id,))

    def clear_history(self, everything: bool = False) -> int:
        """Delete captured history (keeping pinned, favourites, templates and hand-added
        entries), or with ``everything`` delete every ClipVault entry. Returns how many."""
        with self.db.transaction():
            cur = self.db.execute("DELETE FROM cv_entries" + ("" if everything else f" WHERE NOT {KEPT}"))
        return int(cur.rowcount or 0)

    def enforce_retention(self, days: int, max_items: int, now: datetime | None = None) -> int:
        """Remove old captured history. ``days`` 0 keeps by age; ``max_items`` caps unkept entries."""
        removed = 0
        with self.db.transaction():
            if days > 0:
                cutoff = ((now or _now()) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                cur = self.db.execute(f"DELETE FROM cv_entries WHERE NOT {KEPT} AND last_used_at < ?", (cutoff,))
                removed += int(cur.rowcount or 0)
            cur = self.db.execute(
                f"DELETE FROM cv_entries WHERE id IN (SELECT id FROM cv_entries WHERE NOT {KEPT} "
                "ORDER BY last_used_at DESC, id DESC LIMIT -1 OFFSET ?)", (int(max_items),))
            removed += int(cur.rowcount or 0)
        return removed

    def counts(self) -> dict[str, int]:
        row = self.db.query_one(
            "SELECT COUNT(*) AS total, SUM(origin = 'captured' AND NOT " + KEPT + ") AS history, "
            "SUM(pinned) AS pinned, SUM(favorite) AS favorites, SUM(kind = 'template') AS templates "
            "FROM cv_entries")
        return {k: int(row[k] or 0) for k in ("total", "history", "pinned", "favorites", "templates")}

    # -- exclusion rules ----------------------------------------------------------------
    def rules(self) -> list[RuleRow]:
        return [RuleRow(int(r["id"]), r["kind"], r["value"], int(r["enabled"]))
                for r in self.db.query("SELECT id, kind, value, enabled FROM cv_rules ORDER BY id")]

    def active_rules(self) -> list[Rule]:
        return [Rule(r.kind, r.value, bool(r.enabled)) for r in self.rules() if r.enabled]

    def add_rule(self, kind: str, value: str) -> int:
        if kind not in RULE_KINDS:
            raise ValidationError(f"Unknown rule type: {kind}")
        try:
            value = validate_rule(kind, value)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        if self.db.scalar("SELECT 1 FROM cv_rules WHERE kind = ? AND value = ?", (kind, value)):
            raise ValidationError("That rule already exists.")
        with self.db.transaction():
            return self.db.insert("INSERT INTO cv_rules (kind, value, enabled, created_at) VALUES (?, ?, 1, ?)",
                                  (kind, value, now_stamp()))

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        with self.db.transaction():
            self.db.execute("UPDATE cv_rules SET enabled = ? WHERE id = ?", (int(enabled), rule_id))

    def delete_rule(self, rule_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM cv_rules WHERE id = ?", (rule_id,))
