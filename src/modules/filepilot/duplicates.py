"""Duplicate files by content, never by name.

Files are first grouped by size (no reading at all). Only same-size files are
read: first a quick fingerprint of the beginning and end, then a full SHA-256
for the files whose fingerprints still match. Hard links to the same file are
not reported as duplicates, and online-only cloud files are never read.
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass

from .scanner import FileInfo, ScanProgress

CHUNK = 1024 * 1024
EDGE = 64 * 1024


@dataclass
class DuplicateGroup:
    size: int
    sha256: str
    files: list[FileInfo]

    @property
    def wasted(self) -> int:
        """Space that removing all but one copy would free."""
        return self.size * (len(self.files) - 1)


def file_sha256(path: str, cancel: threading.Event | None = None) -> str | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                if cancel is not None and cancel.is_set():
                    return None
                block = fh.read(CHUNK)
                if not block:
                    break
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def _edges(path: str, size: int) -> str | None:
    """SHA-256 of the first and last 64 KB; for files up to 128 KB this is the whole file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            if size <= 2 * EDGE:
                while True:
                    block = fh.read(CHUNK)
                    if not block:
                        break
                    h.update(block)
            else:
                h.update(fh.read(EDGE))
                fh.seek(size - EDGE)
                h.update(fh.read(EDGE))
    except OSError:
        return None
    return h.hexdigest()


def _identity(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino) if st.st_ino else None


def find_duplicates(files: list[FileInfo], cancel: threading.Event | None = None,
                    progress: ScanProgress | None = None, min_size: int = 1) -> list[DuplicateGroup]:
    cancel = cancel or threading.Event()
    progress = progress or ScanProgress()
    by_size: dict[int, list[FileInfo]] = {}
    for f in files:
        if f.size >= max(1, min_size) and not f.cloud:
            by_size.setdefault(f.size, []).append(f)
    candidates = [group for group in by_size.values() if len(group) > 1]
    progress.phase = "hashing"
    progress.to_hash = sum(len(g) for g in candidates)
    progress.hashed = 0
    groups: list[DuplicateGroup] = []
    for same_size in candidates:
        if cancel.is_set():
            break
        # hard links share one copy on disk: keep only one path per file identity
        unique: dict[object, FileInfo] = {}
        for f in same_size:
            key = _identity(f.path) or f.path
            unique.setdefault(key, f)
        if len(unique) < 2:
            progress.hashed += len(same_size)
            continue
        by_edge: dict[str, list[FileInfo]] = {}
        for f in unique.values():
            if cancel.is_set():
                break
            progress.current = f.path
            edge = _edges(f.path, f.size)
            if edge is not None:
                by_edge.setdefault(edge, []).append(f)
        for edge, maybe in by_edge.items():
            if len(maybe) < 2:
                progress.hashed += len(maybe)
                continue
            if maybe[0].size <= 2 * EDGE:  # the fingerprint already covered every byte
                progress.hashed += len(maybe)
                groups.append(DuplicateGroup(maybe[0].size, edge, sorted(maybe, key=lambda x: x.mtime)))
                continue
            by_hash: dict[str, list[FileInfo]] = {}
            for f in maybe:
                if cancel.is_set():
                    break
                progress.current = f.path
                digest = file_sha256(f.path, cancel)
                progress.hashed += 1
                if digest is not None:
                    by_hash.setdefault(digest, []).append(f)
            for digest, same in by_hash.items():
                if len(same) > 1:
                    groups.append(DuplicateGroup(same[0].size, digest, sorted(same, key=lambda x: x.mtime)))
    progress.current = ""
    return sorted(groups, key=lambda g: -g.wasted)
