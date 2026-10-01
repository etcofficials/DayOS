"""Read-only folder scanning, file categories and storage summaries.

Scanning only reads directory listings and file metadata. It never opens file
contents (that happens only for duplicate detection, see :mod:`.duplicates`),
never follows junctions or symbolic links, and skips Windows system folders.
It runs on a worker thread and checks ``cancel`` between entries.
"""

from __future__ import annotations

import os
import re
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

SKIP_DIR_NAMES = {"$recycle.bin", "system volume information", "$windows.~bt", "$windows.~ws", "$sysreset",
                  "windowsapps", "config.msi", "recovery"}
MAX_ERROR_SAMPLES = 50

CATEGORY_LABELS = {
    "images": "Images", "screenshots": "Screenshots", "videos": "Videos", "audio": "Audio",
    "documents": "Documents", "pdf": "PDFs", "spreadsheets": "Spreadsheets", "presentations": "Presentations",
    "archives": "Archives", "installers": "Installers", "code": "Code", "other": "Other",
}

_EXT = {
    "images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff", ".svg", ".ico",
               ".raw", ".cr2", ".nef", ".arw", ".dng", ".psd"},
    "videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".mpg", ".mpeg", ".3gp", ".ts"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".mid", ".midi"},
    "documents": {".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pages", ".epub", ".tex"},
    "pdf": {".pdf"},
    "spreadsheets": {".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".numbers"},
    "presentations": {".ppt", ".pptx", ".odp", ".key"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".iso", ".img", ".cab"},
    "installers": {".msi", ".msix", ".msixbundle", ".appx", ".appxbundle"},
    "code": {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".rb",
             ".php", ".html", ".css", ".scss", ".json", ".xml", ".yml", ".yaml", ".toml", ".sql", ".sh", ".ps1",
             ".bat", ".ipynb", ".kt", ".swift", ".dart", ".lua", ".r"},
}
_BY_EXT = {ext: cat for cat, exts in _EXT.items() for ext in exts}
_SCREENSHOT = re.compile(r"(screenshot|screen shot|screen_shot|scr_|snip|capture)", re.IGNORECASE)
_INSTALLER_NAME = re.compile(r"(setup|install|installer|update|_x64|_x86|win64|win32)", re.IGNORECASE)


def categorize(path: str, downloads: str | None = None) -> str:
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    cat = _BY_EXT.get(ext)
    if cat == "images":
        parent = os.path.basename(os.path.dirname(path)).lower()
        if _SCREENSHOT.search(name) or parent in ("screenshots", "screen captures"):
            return "screenshots"
        return "images"
    if ext == ".exe":
        if (downloads and is_within(path, downloads)) or _INSTALLER_NAME.search(name):
            return "installers"
        return "other"
    return cat or "other"


def normcase(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def is_within(path: str, folder: str) -> bool:
    p, f = normcase(path), normcase(folder)
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


def default_downloads() -> str:
    return str(Path.home() / "Downloads")


def protected_roots() -> list[str]:
    """Folders whose contents FilePilot never moves or recycles."""
    env = os.environ
    roots = [env.get("SystemRoot", r"C:\Windows"), env.get("ProgramFiles", r"C:\Program Files"),
             env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), env.get("ProgramW6432", r"C:\Program Files"),
             env.get("ProgramData", r"C:\ProgramData")]
    appdata = [env.get("APPDATA"), env.get("LOCALAPPDATA")]
    return [r for r in roots + appdata if r]


def is_protected(path: str, extra: list[str] | None = None) -> str | None:
    """Why ``path`` must not be moved or recycled, or None if it may be."""
    for root in protected_roots():
        if is_within(path, root):
            return "it is inside a Windows, program or app-data folder"
    for root in extra or []:
        if is_within(path, root):
            return "it belongs to DayOS's own data"
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    if rest.strip("\\/") == "":
        return "it is a drive root"
    try:
        attrs = getattr(os.stat(path, follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return None
    if attrs & FILE_ATTRIBUTE_SYSTEM:
        return "Windows marks it as a system file"
    return None


# -- scanning ---------------------------------------------------------------------------
@dataclass(slots=True)
class FileInfo:
    path: str
    size: int
    mtime: float
    category: str
    cloud: bool = False  # online-only (OneDrive etc.): never read, so it isn't downloaded

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)


@dataclass
class ScanProgress:
    """Shared between the worker and the UI (plain attributes; the UI only reads them)."""

    phase: str = "scanning"
    files: int = 0
    bytes: int = 0
    folders: int = 0
    current: str = ""
    hashed: int = 0
    to_hash: int = 0


@dataclass
class ScanResult:
    roots: list[str]
    files: list[FileInfo] = field(default_factory=list)
    folder_sizes: dict[str, int] = field(default_factory=dict)  # every folder, including its subfolders
    errors: int = 0
    error_samples: list[tuple[str, str]] = field(default_factory=list)
    skipped: int = 0  # system folders, links and hidden items left out
    cancelled: bool = False
    started: float = 0.0
    finished: float = 0.0

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


def prepare_roots(roots: list[str]) -> list[str]:
    """Absolute, existing folders; a folder inside another selected folder is scanned once."""
    clean: list[str] = []
    for root in roots:
        root = os.path.abspath(root)
        if os.path.isdir(root) and root not in clean:
            clean.append(root)
    clean.sort(key=lambda r: len(normcase(r)))
    out: list[str] = []
    for root in clean:
        if not any(is_within(root, kept) for kept in out):
            out.append(root)
    return out


def scan(roots: list[str], cancel: threading.Event | None = None, progress: ScanProgress | None = None,
         include_hidden: bool = False, downloads: str | None = None) -> ScanResult:
    cancel = cancel or threading.Event()
    progress = progress or ScanProgress()
    downloads = downloads or default_downloads()
    windows_dir = os.environ.get("SystemRoot", r"C:\Windows")
    result = ScanResult(prepare_roots(roots), started=time.time())
    direct: dict[str, int] = {}
    for root in result.roots:
        stack = [root]
        while stack:
            if cancel.is_set():
                result.cancelled = True
                break
            folder = stack.pop()
            progress.current = folder
            progress.folders += 1
            direct.setdefault(folder, 0)
            try:
                entries = os.scandir(folder)
            except OSError as exc:
                result.errors += 1
                if len(result.error_samples) < MAX_ERROR_SAMPLES:
                    result.error_samples.append((folder, exc.strerror or str(exc)))
                continue
            with entries:
                for entry in entries:
                    if cancel.is_set():
                        result.cancelled = True
                        break
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        result.errors += 1
                        if len(result.error_samples) < MAX_ERROR_SAMPLES:
                            result.error_samples.append((entry.path, exc.strerror or str(exc)))
                        continue
                    attrs = getattr(st, "st_file_attributes", 0)
                    is_dir = stat.S_ISDIR(st.st_mode)
                    if stat.S_ISLNK(st.st_mode) or (is_dir and attrs & FILE_ATTRIBUTE_REPARSE_POINT):
                        result.skipped += 1  # links and junctions are never followed
                        continue
                    hidden = bool(attrs & FILE_ATTRIBUTE_HIDDEN) or entry.name.startswith(".")
                    if is_dir:
                        if (entry.name.lower() in SKIP_DIR_NAMES or attrs & FILE_ATTRIBUTE_SYSTEM
                                or is_within(entry.path, windows_dir) or (hidden and not include_hidden)):
                            result.skipped += 1
                            continue
                        stack.append(entry.path)
                        continue
                    if not stat.S_ISREG(st.st_mode) or attrs & FILE_ATTRIBUTE_SYSTEM or (hidden and not include_hidden):
                        result.skipped += 1
                        continue
                    info = FileInfo(entry.path, int(st.st_size), float(st.st_mtime),
                                    categorize(entry.path, downloads), bool(attrs & CLOUD_ONLY))
                    result.files.append(info)
                    direct[folder] = direct.get(folder, 0) + info.size
                    progress.files += 1
                    progress.bytes += info.size
            if result.cancelled:
                break
        if result.cancelled:
            break
    result.folder_sizes = _roll_up(direct, result.roots)
    result.finished = time.time()
    progress.current = ""
    return result


def _roll_up(direct: dict[str, int], roots: list[str]) -> dict[str, int]:
    totals = dict(direct)
    root_set = {normcase(r) for r in roots}
    for folder in sorted(direct, key=lambda f: f.count(os.sep), reverse=True):
        if normcase(folder) in root_set:
            continue
        parent = os.path.dirname(folder)
        if parent and parent != folder:
            totals[parent] = totals.get(parent, 0) + totals.get(folder, 0)
    return totals


# -- summaries ----------------------------------------------------------------------------
def by_category(files: list[FileInfo]) -> list[tuple[str, int, int]]:
    """(category, file count, bytes), largest first."""
    sums: dict[str, list[int]] = {}
    for f in files:
        s = sums.setdefault(f.category, [0, 0])
        s[0] += 1
        s[1] += f.size
    return sorted(((c, n, b) for c, (n, b) in sums.items()), key=lambda x: -x[2])


def largest(files: list[FileInfo], min_bytes: int = 0, limit: int = 500) -> list[FileInfo]:
    return sorted((f for f in files if f.size >= min_bytes), key=lambda f: -f.size)[:limit]


def old_downloads(files: list[FileInfo], days: int, now: float | None = None,
                  downloads: str | None = None) -> list[FileInfo]:
    downloads = downloads or default_downloads()
    cutoff = (now or time.time()) - days * 86400
    return sorted((f for f in files if f.mtime < cutoff and is_within(f.path, downloads)), key=lambda f: -f.size)


def biggest_folders(result: ScanResult, limit: int = 200) -> list[tuple[str, int]]:
    return sorted(result.folder_sizes.items(), key=lambda x: -x[1])[:limit]


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
