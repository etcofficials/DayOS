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

## 2026-09-28 — 1.1.0: botanical redesign and single-file release

**Design.** New token system (warm cream/sage light theme as the first-launch
default, coordinated warm dark theme; spec colours kept for fills, darker text
variants where the spec colours fell below 4.5:1). Georgia for editorial
headings, Cambria for numbers (lining figures), Segoe UI for body text.
Original procedural SVG artwork (`tools/make_art.py`): logo sprout, sidebar
branch, window-and-plants vignette, landscape strip, corner leaves, sprig, pot;
recoloured at runtime for the dark theme.

**Motion.** `src/ui/anim.py` centralises durations/easing and the reduced-motion
switch. Page cross-fade and theme cross-fade use a snapshot overlay that is
transparent to the mouse (no input blocking); sidebar and segmented-control
selection pills glide; animated buttons (hover/press), cards (hover lift, painted
layered shadow — no blur effects), check marks, progress bars, focus ring
colour/progress and completion pulse, dialog fade in/out, toast rise/fade,
collapsible sections, empty-state fade-in.

**Today** rebuilt to match the reference: header vignette + date/headline/
greeting, intention banner (edit in place), A gentle plan, Your day timeline,
Study nook (drives the Study page's single timer via a signal), Small rituals,
Coming up (exams, deadlines, goals). Task completion defers list refresh 260 ms
so the check animation finishes.

**Packaging.** One-file windowed `dist/DayOS.exe` (26.4 MB, x64, GUI subsystem,
version resource). Unused Qt parts trimmed (software OpenGL, translations,
network/TLS plugins, extra image codecs). Data folder for the EXE: `DAYOS_HOME`
→ `DayOS Data` beside the EXE → user-chosen folder (asked, remembered).
`--self-test write|verify` drives real UI actions for release verification;
`--debug` for diagnostics.

**Verification.** 87 unit/UI tests pass. Packaged EXE: self-test write (pages,
themes, task add+complete, note, study session, timer) and verify-after-relaunch
(all persisted, integrity OK) both passed; first launch in a clean folder
created `DayOS Data`, opened in the light theme with empty states; no database,
log or personal data inside the EXE; temporary unpack folder removed on exit;
launch-to-window 3.0–3.3 s; ≈85 MB working set.

## 2.0.0 — DayOS v2 (2026-10-01)

Phases 0–9 of the v2 plan: five-theme design system and module registry; planning
upgrades (projects, recurrence, reminders, inbox, capture, Ctrl+K search); StudyForge;
SecondBrain and opt-in ClipVault; FilePilot; AudioDock; weather, news, money, skills,
projects and optional AI; automatic backups, documentation and a v2 self-test. Database
schema 1 → 8 through append-only migrations with a verified pre-upgrade backup.
See PROJECT_STATUS.md for details and verification notes.

### 2.0.0 — layout fixes before release (2026-10-02)

Fixed widgets overlapping in small windows. The window allows 980×640, but several pages needed more room than that, so Qt squeezed widgets below their minimum size. Changes:

* Every page now sits in a scroll frame.
* The sidebar folds to icons below 1120 px wide.
* Wide rows wrap.
* Grids drop columns when their cards don't fit.
* List rows count the stylesheet padding.
* Long titles end in "…".
* The Today illustration no longer sits under its buttons.
* The CBSE dialog's date fields are no longer squashed.

Checked every page, tab, Settings section and 24 dialogs at six window sizes and two text sizes. `tests/test_layout.py` keeps those checks.
