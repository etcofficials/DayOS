# DayOS development log

## 2026-09-27 — 1.0.0

**Environment.** Workspace `G:\DayOS` was empty (only `.claude\`). Python 3.12.10
(the only installed interpreter) used to create `G:\DayOS\.venv`. Installed into the
venv only: `PySide6-Essentials 6.11.2`, later `pyinstaller 6.22.3` for packaging.
pip cache, TEMP and the PyInstaller cache were redirected to `G:\DayOS\.cache`.
Disk before starting: C: 84.6 GB free, G: 424.4 GB free.

**Phase 1–2 — foundation.** Central path config (dev / packaged / `DAYOS_HOME`),
rotating log, SQLite layer (autocommit + explicit `BEGIN IMMEDIATE`, savepoints for
nesting, WAL, foreign keys), schema v1 with CHECK constraints and indexes,
append-only migrations with automatic pre-upgrade backup and newer-schema refusal.
Repositories for every area with validation; pure services for dates, streaks,
revision, stats, timer, backup, transfer, settings.

**Phase 3–7 — features.** Design system (tokens, generated QSS, SVG line icons,
cards, round checks, painted charts), main window with collapsible sidebar,
shortcuts, toast/undo, midnight rollover; all ten pages.

**Visual QA.** Rendered every page in both themes with sample data seeded only into
a throwaway `.cache\testhome`. Fixed: clipped wrapped text in empty states; card
content vertically centred; `QListWidget` rows clipped (replaced the task list with
focusable rows + keyboard handling; added `fit_list_items` for other lists);
duplicate integer axis labels; spacing in stats rows.

**Phase 9 — tests.** 73 unittest cases (DB init/migrations/rollback, CRUD for every
area, validation, date boundaries, streak rules, revision rule and queue, study
idempotency, timer engine, backup/restore, JSON/CSV export and import rollback,
settings persistence/corruption, dashboard refresh, notes flush-on-leave, all
dialogs). Bugs found by tests and fixed:
* Timer reported "idle" when paused immediately after starting (Windows monotonic
  clock resolution is 15.6 ms, so elapsed could be 0). Now tracks an explicit
  `active` flag.
* `Ctrl+Enter` started the timer from any page; scoped to the Study page.

Also added: sleep-gap detection (Windows `GetTickCount64` counts sleep), so a
running timer pauses at the last tick instead of recording sleep as study.

**Phase 10 — release.** `dayos.spec` + `build.ps1` one-folder build →
`dist\DayOS\DayOS.exe` (≈92 MB). Verified: `--smoke-test` exit 0 with all 10 pages,
data created beside the exe, window captured and rendered correctly, required Qt
plugins (qwindows, qsvg, qsvgicon) bundled. Verification artefacts removed from
`dist\DayOS` afterwards so the first real launch starts clean.

Measured on this PC: running instance ≈82 MB working set / 50 MB private (dev
build); packaged launch-to-window 1.24–1.37 s over three runs.
