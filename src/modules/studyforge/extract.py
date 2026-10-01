"""Local text extraction from course documents (nothing is uploaded anywhere).

Supported: PDF (text layer, via pypdf), plain text / Markdown / CSV, and Word .docx.
Scanned PDFs have no text layer; DayOS does not bundle OCR, so such pages are
reported clearly ("no text — probably scanned") instead of being skipped silently.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

log = logging.getLogger(__name__)

MAX_BYTES = 150 * 1024 * 1024
MAX_PAGES = 2500
TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv"}
SUPPORTED = {".pdf", ".docx", *TEXT_EXTS}


class Cancelled(Exception):
    pass


@dataclass
class Extracted:
    pages: list[str]
    sha256: str
    status: str = "parsed"  # parsed | partial | unreadable
    problems: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.pages)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            if encoding == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _paginate(text: str, size: int = 3500) -> list[str]:
    if "\f" in text:
        return [p for p in text.split("\f")]
    lines = text.splitlines()
    pages, cur, n = [], [], 0
    for line in lines:
        cur.append(line)
        n += len(line) + 1
        if n >= size:
            pages.append("\n".join(cur))
            cur, n = [], 0
    if cur or not pages:
        pages.append("\n".join(cur))
    return pages


def _docx_text(path: Path) -> list[str]:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("word/document.xml")
        if info.file_size > 50 * 1024 * 1024:
            raise ValueError("The document is too large.")
        root = ElementTree.fromstring(zf.read(info))
    paragraphs = []
    for p in root.iter(f"{ns}p"):
        parts = []
        for node in p.iter():
            if node.tag == f"{ns}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{ns}tab":
                parts.append("\t")
            elif node.tag in (f"{ns}br", f"{ns}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return _paginate("\n".join(paragraphs))


def extract(path: Path | str, cancel: threading.Event | None = None) -> Extracted:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"{ext or 'This file type'} isn't supported. Use PDF, Word (.docx), text or CSV files.")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ValueError("The file is larger than 150 MB.")
    digest = file_hash(path)
    if ext in TEXT_EXTS:
        pages = _paginate(_read_text(path))
        return Extracted(pages, digest, "parsed" if any(p.strip() for p in pages) else "unreadable",
                         [] if any(p.strip() for p in pages) else ["The file is empty."])
    if ext == ".docx":
        try:
            pages = _docx_text(path)
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError) as exc:
            return Extracted([], digest, "unreadable", [f"The Word file couldn't be read ({exc})."])
        return Extracted(pages, digest, "parsed" if any(p.strip() for p in pages) else "unreadable")
    return _extract_pdf(path, digest, cancel)


def _extract_pdf(path: Path, digest: str, cancel: threading.Event | None) -> Extracted:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # pragma: no cover - dependency missing in a broken build
        return Extracted([], digest, "unreadable", ["PDF support is not available in this installation."])
    problems: list[str] = []
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    return Extracted([], digest, "unreadable", ["The PDF is password-protected."])
            except Exception:
                return Extracted([], digest, "unreadable", ["The PDF is encrypted and can't be read."])
        total = len(reader.pages)
    except (PdfReadError, OSError, ValueError) as exc:
        return Extracted([], digest, "unreadable", [f"The PDF couldn't be opened ({exc})."])
    except Exception as exc:  # malformed files can raise almost anything inside the parser
        log.warning("PDF open failed", exc_info=True)
        return Extracted([], digest, "unreadable", [f"The PDF couldn't be opened ({type(exc).__name__})."])
    if total > MAX_PAGES:
        problems.append(f"Only the first {MAX_PAGES} of {total} pages were read.")
        total = MAX_PAGES
    pages: list[str] = []
    empty: list[int] = []
    failed: list[int] = []
    for i in range(total):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:
            log.debug("Page %d failed", i + 1, exc_info=True)
            failed.append(i + 1)
            text = ""
        text = re.sub(r"[ \t]+\n", "\n", text)
        if len(text.strip()) < 15 and (i + 1) not in failed:
            empty.append(i + 1)
        pages.append(text)
    if failed:
        problems.append(f"{len(failed)} page(s) couldn't be read: {_ranges(failed)}.")
    if empty:
        problems.append(f"{len(empty)} page(s) have no text layer (probably scanned images): {_ranges(empty)}. "
                        "DayOS doesn't include OCR, so these pages were not analysed — type or paste anything "
                        "important from them.")
    readable = total - len(failed) - len(empty)
    status = "parsed" if readable == total else ("partial" if readable > 0 else "unreadable")
    return Extracted(pages, digest, status, problems)


def _ranges(nums: list[int]) -> str:
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}" if start == prev else f"{start}–{prev}")
            start = prev = n
    if start is not None:
        out.append(f"{start}" if start == prev else f"{start}–{prev}")
    return ", ".join(out[:12]) + (" …" if len(out) > 12 else "")
