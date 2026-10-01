"""Command registry for the palette, plus "openers" that show any record by kind and id."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Command:
    id: str
    title: str
    description: str = ""
    shortcut: str = ""
    icon: str = "command"
    run: Callable[[], None] = lambda: None
    keywords: tuple[str, ...] = ()
    group: str = "Commands"
    available: Callable[[], bool] = field(default=lambda: True)


def fuzzy_score(query: str, text: str) -> int:
    """Higher is better; 0 means no match. Prefers word starts and contiguous runs."""
    q = query.lower().strip()
    t = text.lower()
    if not q:
        return 1
    if q in t:
        bonus = 60 if t.startswith(q) else (40 if re.search(r"\b" + re.escape(q), t) else 20)
        return 100 + bonus - min(len(t), 40) // 4
    # subsequence match
    pos = 0
    score = 0
    for ch in q:
        found = t.find(ch, pos)
        if found < 0:
            return 0
        score += 6 if found == pos else 2
        if found == 0 or t[found - 1] in " -_/":
            score += 4
        pos = found + 1
    return score


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def add(self, command: Command) -> None:
        self._commands[command.id] = command

    def get(self, command_id: str) -> Command | None:
        return self._commands.get(command_id)

    def all(self) -> list[Command]:
        return [c for c in self._commands.values() if c.available()]

    def match(self, query: str, limit: int = 30) -> list[Command]:
        scored = []
        for cmd in self.all():
            haystacks = [cmd.title, cmd.description, " ".join(cmd.keywords)]
            score = max(fuzzy_score(query, h) for h in haystacks if h) if query.strip() else 1
            if cmd.title.lower().startswith(query.lower().strip()):
                score += 30
            if score:
                scored.append((score, cmd))
        scored.sort(key=lambda x: (-x[0], x[1].title))
        return [c for _, c in scored[:limit]]

    def run(self, command_id: str) -> bool:
        cmd = self._commands.get(command_id)
        if cmd is None or not cmd.available():
            return False
        cmd.run()
        return True


class Openers:
    """``kind -> callable(ref_id)`` used by search results, links and notifications."""

    def __init__(self) -> None:
        self._fns: dict[str, Callable[[int], None]] = {}

    def register(self, kind: str, fn: Callable[[int], None]) -> None:
        self._fns[kind] = fn

    def can_open(self, kind: str) -> bool:
        return kind in self._fns

    def open(self, kind: str, ref_id: int) -> bool:
        fn = self._fns.get(kind)
        if fn is None:
            return False
        fn(ref_id)
        return True
