"""SecondBrain: collections, attachments, [[wiki links]], and Markdown import / export.

Everything here works offline and has no Qt dependency. Imports only ever add
notes; exports always go to a new folder and never overwrite an existing file.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

from src.database import Database
from src.models import Note
from src.repositories.base import Repository, clean_text
from src.repositories.notes import MAX_CONTENT, NOTE_KINDS, NoteRepository, normalize_tags, normalize_url
from src.services.dates import ValidationError, now_stamp

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_FILE_BYTES = 2 * 1024 * 1024
MAX_IMPORT_FILES = 2000
IMPORT_SUFFIXES = {".md": "markdown", ".markdown": "markdown", ".txt": "plain", ".text": "plain"}

WIKILINK = re.compile(r"\[\[([^\[\]\n|]{1,200})(?:\|([^\[\]\n]{1,200}))?\]\]")
NOTE_SCHEME = "dayos-note"
ATTACHMENT_SCHEME = "dayos-attachment"

# Starting text for new notes of some kinds (only used when the note is empty).
KIND_TEMPLATES = {
    "troubleshooting": "## Problem\n\n\n## What I tried\n\n\n## Cause\n\n\n## Fix\n\n",
    "idea": "## The idea\n\n\n## Why it matters\n\n\n## First steps\n\n- [ ] \n",
    "study": "## Key points\n\n- \n\n## Questions\n\n- \n",
}

_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_filename(name: str, fallback: str = "Untitled", max_len: int = 80) -> str:
    """A Windows-safe file name (no path characters, reserved names or trailing dots)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(name or ""))
    name = " ".join(name.split()).strip(" .")[:max_len].strip(" .")
    if not name or name.lower().split(".")[0] in _RESERVED:
        name = fallback if not name else f"_{name}"
    return name


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    candidate = folder / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


# -- collections ----------------------------------------------------------------------
@dataclass
class Collection:
    id: int
    name: str
    count: int = 0


class CollectionRepository(Repository):
    def list(self) -> list[Collection]:
        rows = self.db.query(
            "SELECT c.id, c.name, (SELECT COUNT(*) FROM notes n WHERE n.collection_id = c.id AND n.archived = 0) AS n "
            "FROM sb_collections c ORDER BY c.position, c.name COLLATE NOCASE")
        return [Collection(int(r["id"]), r["name"], int(r["n"])) for r in rows]

    def add(self, name: str) -> int:
        name = clean_text(name, field="Collection name", required=True, max_len=60)
        if self.db.scalar("SELECT 1 FROM sb_collections WHERE name = ? COLLATE NOCASE", (name,)):
            raise ValidationError(f"A collection called “{name}” already exists.")
        position = int(self.db.scalar("SELECT COALESCE(MAX(position), 0) + 1 FROM sb_collections", default=1))
        with self.db.transaction():
            return self.db.insert("INSERT INTO sb_collections (name, position, created_at) VALUES (?, ?, ?)",
                                  (name, position, now_stamp()))

    def rename(self, collection_id: int, name: str) -> None:
        name = clean_text(name, field="Collection name", required=True, max_len=60)
        if self.db.scalar("SELECT 1 FROM sb_collections WHERE name = ? COLLATE NOCASE AND id != ?",
                          (name, collection_id)):
            raise ValidationError(f"A collection called “{name}” already exists.")
        with self.db.transaction():
            self.db.execute("UPDATE sb_collections SET name = ? WHERE id = ?", (name, collection_id))

    def delete(self, collection_id: int) -> None:
        """Remove the collection only; its notes stay and become unfiled."""
        with self.db.transaction():
            self.db.execute("UPDATE notes SET collection_id = NULL WHERE collection_id = ?", (collection_id,))
            self.db.execute("DELETE FROM sb_collections WHERE id = ?", (collection_id,))

    def name_of(self, collection_id: int | None) -> str:
        if collection_id is None:
            return ""
        return str(self.db.scalar("SELECT name FROM sb_collections WHERE id = ?", (collection_id,), default="") or "")

    def find_or_create(self, name: str) -> int:
        name = clean_text(name, field="Collection name", required=True, max_len=60)
        existing = self.db.scalar("SELECT id FROM sb_collections WHERE name = ? COLLATE NOCASE", (name,))
        return int(existing) if existing else self.add(name)


# -- attachments ----------------------------------------------------------------------
@dataclass
class Attachment:
    id: int
    note_id: int
    filename: str
    mime: str
    size: int
    sha256: str
    created_at: str


class AttachmentRepository(Repository):
    """Copies of files kept inside DayOS's own database (the original file is never changed)."""

    _COLS = "id, note_id, filename, mime, size, sha256, created_at"

    def add(self, note_id: int, path: str | Path) -> int:
        path = Path(path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ValidationError(f"Couldn't read “{path.name}”: {exc.strerror or exc}") from None
        if not path.is_file():
            raise ValidationError(f"“{path.name}” is not a file.")
        if size > MAX_ATTACHMENT_BYTES:
            raise ValidationError(f"“{path.name}” is {size / 1048576:.1f} MB. Attachments can be up to "
                                  f"{MAX_ATTACHMENT_BYTES // 1048576} MB; link to larger files instead.")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ValidationError(f"Couldn't read “{path.name}”: {exc.strerror or exc}") from None
        if not self.db.scalar("SELECT 1 FROM notes WHERE id = ?", (note_id,)):
            raise ValidationError("That note no longer exists.")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with self.db.transaction():
            return self.db.insert(
                "INSERT INTO sb_attachments (note_id, filename, mime, size, sha256, data, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (note_id, safe_filename(path.name, "attachment", 120), mime, len(data),
                 hashlib.sha256(data).hexdigest(), data, now_stamp()))

    def list(self, note_id: int) -> list[Attachment]:
        rows = self.db.query(f"SELECT {self._COLS} FROM sb_attachments WHERE note_id = ? ORDER BY id", (note_id,))
        return [Attachment(**dict(r)) for r in rows]

    def get(self, attachment_id: int) -> Attachment | None:
        row = self.db.query_one(f"SELECT {self._COLS} FROM sb_attachments WHERE id = ?", (attachment_id,))
        return Attachment(**dict(row)) if row else None

    def data(self, attachment_id: int) -> bytes | None:
        value = self.db.scalar("SELECT data FROM sb_attachments WHERE id = ?", (attachment_id,))
        return bytes(value) if value is not None else None

    def save_copy(self, attachment_id: int, folder: str | Path) -> Path:
        """Write the attachment into ``folder`` under a new name if needed (never overwrites)."""
        att = self.get(attachment_id)
        data = self.data(attachment_id)
        if att is None or data is None:
            raise ValidationError("That attachment no longer exists.")
        folder = Path(folder)
        stem, suffix = Path(att.filename).stem, Path(att.filename).suffix
        target = unique_path(folder, safe_filename(stem, "attachment"), suffix)
        tmp = target.with_name(target.name + ".part")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            if target.exists():  # appeared meanwhile: pick another name
                target = unique_path(folder, safe_filename(stem, "attachment"), suffix)
            tmp.replace(target)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise ValidationError(f"Couldn't save the file: {exc.strerror or exc}") from None
        return target

    def remove(self, attachment_id: int) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM sb_attachments WHERE id = ?", (attachment_id,))

    def total_size(self) -> int:
        return int(self.db.scalar("SELECT COALESCE(SUM(size), 0) FROM sb_attachments", default=0))


# -- wiki links -----------------------------------------------------------------------
def wiki_targets(content: str) -> list[str]:
    """Titles referenced as [[Title]] or [[Title|label]], in order, without duplicates."""
    seen: dict[str, str] = {}
    for match in WIKILINK.finditer(content or ""):
        title = match.group(1).strip()
        if title:
            seen.setdefault(title.lower(), title)
    return list(seen.values())


def markdown_for_preview(content: str) -> str:
    """Turn [[Title]] into clickable links for the Markdown preview (code blocks left alone)."""
    out: list[str] = []
    in_fence = False
    for line in (content or "").split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        def repl(m: re.Match) -> str:
            title = m.group(1).strip()
            text = (m.group(2) or title).strip().replace("]", "\\]").replace("[", "\\[")
            return f"[{text}]({NOTE_SCHEME}:{quote(title, safe='')})"

        out.append(WIKILINK.sub(repl, line))
    return "\n".join(out)


def title_from_link(href: str) -> str | None:
    if href.startswith(NOTE_SCHEME + ":"):
        return unquote(href[len(NOTE_SCHEME) + 1:]).strip() or None
    return None


# -- import / export ------------------------------------------------------------------
def _front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, text
    for i in range(1, min(len(lines), 60)):
        if lines[i].strip() == "---":
            meta: dict[str, str] = {}
            for line in lines[1:i]:
                key, sep, value = line.partition(":")
                if sep and key.strip():
                    meta[key.strip().lower()] = value.strip().strip('"')
            return meta, "\n".join(lines[i + 1:]).lstrip("\n")
    return {}, text


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@dataclass
class ImportReport:
    created: list[int] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (file name, reason)


@dataclass
class ExportReport:
    folder: Path
    written: int = 0


class SecondBrain:
    def __init__(self, db: Database, notes: NoteRepository) -> None:
        self.db = db
        self.notes = notes
        self.collections = CollectionRepository(db)
        self.attachments = AttachmentRepository(db)

    # wiki links
    def backlinks(self, note: Note) -> list[Note]:
        """Notes that mention ``note`` as [[its title]]."""
        title = (note.title or "").strip()
        if not title:
            return []
        rows = self.db.query(
            "SELECT * FROM notes WHERE id != ? AND (content LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\') "
            "ORDER BY updated_at DESC LIMIT 100",
            (note.id, f"%[[{_like(title)}]]%", f"%[[{_like(title)}|%"))
        from src.models import from_row

        found = [from_row(Note, r) for r in rows]
        return [n for n in found if title.lower() in (t.lower() for t in wiki_targets(n.content))]

    def resolve(self, title: str) -> Note | None:
        return self.notes.find_by_title(title)

    def create_linked(self, title: str, fmt: str = "markdown") -> int:
        existing = self.resolve(title)
        if existing:
            return existing.id
        return self.notes.create(title, "", format=fmt)

    # bookmarks
    def add_bookmark(self, url: str, title: str = "", note: str = "", tags: str = "") -> tuple[int, bool]:
        """Returns (note id, created). An existing bookmark for the same URL is reused, not duplicated."""
        url = normalize_url(url)
        if not url:
            raise ValidationError("Enter a web address.")
        existing = self.notes.find_by_url(url)
        if existing:
            return existing.id, False
        return self.notes.create(title or url, note, tags, kind="bookmark", url=url), True

    # import
    def import_files(self, paths: list[str | Path], collection_id: int | None = None) -> ImportReport:
        report = ImportReport()
        for raw in list(paths)[:MAX_IMPORT_FILES]:
            path = Path(raw)
            fmt = IMPORT_SUFFIXES.get(path.suffix.lower())
            if fmt is None:
                report.skipped.append((path.name, "only .md and .txt files can be imported"))
                continue
            try:
                if path.stat().st_size > MAX_IMPORT_FILE_BYTES:
                    report.skipped.append((path.name, "larger than 2 MB"))
                    continue
                text = _read_text(path)
            except OSError as exc:
                report.skipped.append((path.name, exc.strerror or str(exc)))
                continue
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            meta, body = _front_matter(text)
            title = meta.get("title", "")
            if not title:
                first = body.lstrip("\n").split("\n", 1)[0]
                title = first[2:].strip() if first.startswith("# ") else path.stem
            kind = meta.get("kind", "note")
            if kind not in NOTE_KINDS:
                kind = "note"
            try:
                url = normalize_url(meta.get("url", ""))
            except ValidationError:
                url = ""
            target = collection_id
            if target is None and meta.get("collection"):
                target = self.collections.find_or_create(meta["collection"][:60])
            try:
                note_id = self.notes.create(title[:200], body[:MAX_CONTENT], normalize_tags(meta.get("tags", "")),
                                            kind=kind, format=fmt, collection_id=target, url=url,
                                            language=meta.get("language", "")[:40], source=f"import: {path.name}"[:200])
            except ValidationError as exc:
                report.skipped.append((path.name, str(exc)))
                continue
            report.created.append(note_id)
        for raw in list(paths)[MAX_IMPORT_FILES:]:
            report.skipped.append((Path(raw).name, f"more than {MAX_IMPORT_FILES} files at once"))
        return report

    # export
    def export_markdown(self, out_dir: str | Path, note_ids: list[int] | None = None,
                        include_archived: bool = True) -> ExportReport:
        """Write notes as .md files (with a small front-matter header) into a new dated folder."""
        out_dir = Path(out_dir)
        folder = unique_path(out_dir, f"secondbrain-{datetime.now().strftime('%Y%m%d-%H%M%S')}", "")
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise ValidationError(f"Couldn't create the export folder: {exc.strerror or exc}") from None
        report = ExportReport(folder)
        notes = ([self.notes.get(i) for i in note_ids] if note_ids is not None
                 else self.notes.list(limit=1_000_000, archived=None if include_archived else False))
        names = {c.id: c.name for c in self.collections.list()}
        for note in notes:
            if note is None:
                continue
            sub = folder
            if note.collection_id in names:
                sub = folder / safe_filename(names[note.collection_id], "Collection")
            meta = [("title", note.title), ("kind", note.kind), ("tags", note.tags), ("url", note.url),
                    ("language", note.language), ("collection", names.get(note.collection_id, "")),
                    ("created", note.created_at), ("updated", note.updated_at)]
            header = "\n".join(f"{k}: {' '.join(str(v).split())}" for k, v in meta if v)
            text = f"---\n{header}\n---\n\n{note.content}"
            try:
                sub.mkdir(parents=True, exist_ok=True)
                target = unique_path(sub, safe_filename(note.title, f"Note {note.id}"), ".md")
                target.write_text(text, encoding="utf-8")
            except OSError as exc:
                raise ValidationError(f"Couldn't write the export: {exc.strerror or exc}") from None
            for att in self.attachments.list(note.id):
                self.attachments.save_copy(att.id, sub / f"{target.stem} files")
            report.written += 1
        return report


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
