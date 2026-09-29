# DayOS

A cozy, local-first personal command center for students — daily planning, tasks,
schoolwork, study sessions, notes, habits, goals, exams and gentle insights.
Built by **ETC Labs** for Windows 10/11 with Python and PySide6 (Qt Widgets).

Everything is stored in a single SQLite file on your own computer. There are no
accounts, no cloud, no telemetry and no paid APIs; every feature works offline.

---

## Features

| Area | What you can do |
|---|---|
| **Today** | Time-aware greeting, date and clock; daily intention; today's tasks and overdue tasks with progress; today's schedule (classes, events, exams); habit checklist; study time today/this week; active goals; exams and deadlines in the next 3 weeks plus chapters due for revision; quick add for tasks, notes and study sessions; end-of-day review. |
| **Tasks** | Create, edit, complete, reopen, delete (with confirmation **and** Undo). Title, notes, due date + optional time, priority, subject, category, linked goal, time estimate, checklist. Filters (Today, Upcoming, Overdue, No date, Completed, All) with live counts, search, 4 sort orders, clear overdue markers. Quick add understands `tomorrow`, weekday names, `!high`, `!low`, `#category`. |
| **Calendar** | Month grid with per-day items, day agenda, week agenda, weekly timetable. One-off events and deadlines; weekly classes with optional start/end dates; skip a single occurrence, end a series, or delete it. Overlap warnings. Exams and (optionally) task due dates appear automatically. |
| **Study** | Focus timer with short/long breaks, subject, adjustable lengths; start / pause / resume / reset / stop-and-save. Accurate monotonic timing (minimising the window doesn't drift it; computer sleep is not counted). Sessions saved once only (unique session ID). Interrupted sessions (crash or "keep for later") are offered for saving on next launch. Manual session logging, history, weekly chart, time by subject. |
| **Exams** | Subjects; exams with date/time, syllabus, notes and live countdowns; chapters with status (Not started → Learning → Needs revision → Revised → Mastered); revision logging with a transparent rule-based schedule; revision queue; mistake notebook linked to subject/chapter; mock-test results with validation and a score chart. |
| **Notes** | Plain-text notes with title, tags, pinning, search and tag filter. Debounced autosave (0.9 s) with Unsaved / Saving / Saved status; saved immediately when you switch note, change page or close DayOS. Empty new notes are discarded. |
| **Habits** | Daily or chosen weekdays; tick today; click any past day in the 12-week history to correct it (keyboard: arrows + Space); current and longest streak; this-week and 30-day rates; archive or delete. |
| **Goals** | Measurable (target + unit) or open goals, category, deadline, status (active / paused / completed); every progress update kept as history; linked tasks (completing tasks never auto-completes a goal). **Journal** tab lists daily intentions and reviews. |
| **Insights** | 7 / 30 / 90-day / 12-month ranges: tasks completed, study time per day or week, study by subject, habit completion, test scores, goal progress, recent activity. All numbers come from your records — no scores or rankings. |
| **Settings** | System / light / dark theme (applies instantly, persists), your name for the greeting, clock visibility, reduce motion, week start, 12/24-hour clock, date format, timer lengths, optional Windows notification, optional launch at sign-in (off by default), backups & restore, JSON/CSV export, JSON import, database health check, shortcuts, about, reset settings (data untouched). |

### Keyboard shortcuts

| Keys | Action |
|---|---|
| `Ctrl+1` … `Ctrl+9` | Today, Tasks, Calendar, Study, Exams, Notes, Habits, Goals, Insights |
| `Ctrl+,` | Settings |
| `Ctrl+N` / `Ctrl+F` | New item / search on the current page |
| `Ctrl+Shift+T` / `Ctrl+Shift+N` | Quick task / quick note from anywhere |
| `Ctrl+S` | Save the current note now |
| `Ctrl+B` | Collapse / expand the sidebar |
| `F5` / `F1` | Refresh page / show shortcuts |
| Tasks: `↑` `↓` `Space` `Enter` `Delete` | Move, complete, edit, delete |
| Study: `Ctrl+Enter` | Start / pause the timer |
| Calendar: arrows, `Enter` | Move the selected day, add an event |

---

## Requirements

* Windows 10 or 11
* Python **3.12** (developed and tested with 3.12.10)
* `PySide6-Essentials 6.11.2` (Qt Core/Gui/Widgets/Svg only — no web engine)
* Build only: `pyinstaller 6.22.3`

## Setup

All commands are run from `G:\DayOS`. The virtual environment lives in `G:\DayOS\.venv`.

```bash
py -3.12 -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install --cache-dir .cache\pip -r requirements.txt
```

To activate the environment in PowerShell (optional — every command below also works without activation):

```bash
.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the script, use `.venv\Scripts\activate.bat` from `cmd`, or just call `.venv\Scripts\python.exe` directly. DayOS never needs the machine-wide execution policy changed.

## Run

```bash
.venv\Scripts\python.exe main.py
```

Use `pythonw.exe` instead of `python.exe` to start without a console window.

## Test

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

The suite (73 tests) uses throwaway databases in `tests\.tmp\` and pins the clock, so it never touches your real data. UI tests run Qt offscreen automatically.

Other checks:

```bash
.venv\Scripts\python.exe main.py --smoke-test
```

```bash
.venv\Scripts\python.exe database.py check
```

(`--smoke-test` opens the real window, visits every page and exits; `database.py check` initialises/migrates the database and runs SQLite's integrity and foreign-key checks. `database.py info` prints record counts; `database.py backup` writes a backup.)

---

## Where your data lives

| What | Development (`main.py`) | Packaged (`DayOS.exe`) |
|---|---|---|
| Database | `G:\DayOS\data\dayos.db` | `<DayOS folder>\data\dayos.db` |
| Backups | `G:\DayOS\backups\` | `<DayOS folder>\backups\` |
| Exports | `G:\DayOS\exports\` (default) | `<DayOS folder>\exports\` |
| Logs | `G:\DayOS\logs\dayos.log` (rotating, 3 × 1 MB) | `<DayOS folder>\logs\` |
| Small cache (theme images) | `G:\DayOS\.cache\` | `<DayOS folder>\.cache\` |

Setting the `DAYOS_HOME` environment variable points DayOS at a different folder. If the folder isn't writable, DayOS shows an explanation and stops — it never silently moves your data to another drive. Logs contain technical events only, never note or task contents.

### Backups, restore, export and import

* **Back up now** (Settings → Backups) writes a verified, timestamped snapshot using SQLite's online backup API: `backups\dayos-backup-YYYYMMDD-HHMMSS-manual.db`. Backups are never deleted or overwritten automatically.
* Before a database schema upgrade, a restore, or an import, DayOS automatically writes a `pre-upgrade`, `pre-restore` or `pre-import` backup first.
* **Restore** validates the file (SQLite header, integrity check, DayOS tables, schema version), shows what it contains, asks for confirmation, then replaces the data in one step.
* **Export JSON** writes every table to one file that **Import JSON** can bring back. Import replaces all data: the file is validated first (format, version, tables, columns, values), and all rows are inserted in a single transaction — a malformed file changes nothing.
* **Export CSV** writes one readable spreadsheet file per record type (tasks, notes, study sessions, habits, goals, events, timetable, exams, chapters, tests, mistakes, journal).

**Manual backup procedure** (without opening DayOS): close DayOS, then copy `data\dayos.db` somewhere safe. Or, with DayOS open or closed, run `.venv\Scripts\python.exe database.py backup`. To restore manually, close DayOS and copy a backup file over `data\dayos.db` (delete any `dayos.db-wal` / `dayos.db-shm` files next to it first).

---

## Architecture

```
G:\DayOS
├── main.py                 entry point (python main.py [--smoke-test])
├── database.py             maintenance CLI: check / info / backup
├── dayos.spec, build.ps1   PyInstaller one-folder release
├── requirements*.txt
├── assets\                 dayos.svg (logo), dayos.ico (generated by tools\make_icon.py)
├── src\
│   ├── app.py              bootstrap: paths, logging, error handler, theme, window
│   ├── config.py           all file paths (dev vs packaged vs DAYOS_HOME), logging
│   ├── context.py          AppContext: database + repositories + settings
│   ├── models.py           dataclasses returned by repositories
│   ├── database\           connection (transactions/savepoints, pragmas), schema + migrations
│   ├── repositories\       all SQL (parameterised), validation, one module per area
│   ├── services\           pure logic: dates, streaks, revision rule, stats, timer,
│   │                       backup/restore, export/import, settings, quick-add, startup
│   └── ui\
│       ├── theme.py        design tokens (light/dark), generated stylesheet
│       ├── icons.py        original line icons (SVG), theme-aware
│       ├── bus.py          change notifications → pages refresh lazily
│       ├── main_window.py  sidebar, navigation, shortcuts, toasts, midnight rollover
│       ├── dialogs.py, task_actions.py, subjects_dialog.py, worker.py
│       ├── widgets\        cards, empty states, round checks, charts (QPainter), task row
│       └── pages\          today, tasks, calendar, study, exams, notes, habits, goals,
│                           insights, settings
├── tests\                  unittest suite
└── tools\make_icon.py
```

Principles: SQL lives only in repositories; UI code never builds SQL; business rules
(streaks, revision schedule, stats, timer) are pure functions with unit tests;
pages refresh only when their data changes (and only when visible); slow file
work (backup/export) runs on a background thread with its own SQLite connection.

### Data conventions

* Dates are your **local** calendar dates (`YYYY-MM-DD`), times are local `HH:MM`, timestamps local `YYYY-MM-DD HH:MM:SS`. UTC is never mixed in.
* Schema version is kept in `PRAGMA user_version`; migrations are append-only and run in transactions. A database from a newer DayOS is refused rather than modified.
* Foreign keys are enforced. Deleting a subject or goal keeps linked records (the link is cleared). Deleting a task removes only that task and its own checklist.

### Rules you can rely on

* **Habit streaks** count consecutive *scheduled* days completed. Unscheduled days never break a streak; completions on them are kept but don't extend it. Today counts only once done (an unfinished today doesn't break your streak). Future dates can't be marked. Rates = completed scheduled days ÷ scheduled days so far.
* **Revision schedule** (simple and deterministic — not AI, not "optimised"): *Hard* → review tomorrow; *Okay* → interval doubles (2–30 days); *Easy* → interval triples (4–60 days), "Mastered" from 21 days. Reviews are pulled to the day before the exam if they'd fall after it. The queue shows chapters due today or overdue, then Learning / Needs-revision chapters of upcoming exams, ordered by lateness, then exam date.
* **Study time** counts on the date a session started. The timer never records more than the planned length; sleep gaps over 60 s pause it.

---

## Packaging (Windows one-folder build)

```bash
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

(`-ExecutionPolicy Bypass` applies to that one process only.) The script regenerates the icon and runs PyInstaller with all caches and temp files under `G:\DayOS\.cache`, work files in `G:\DayOS\build\` and output in **`G:\DayOS\dist\DayOS\DayOS.exe`** (≈92 MB folder). Copy the whole `dist\DayOS` folder anywhere writable; its data is created next to `DayOS.exe`.

---

## Known limitations

* **Launch at sign-in** is implemented (a per-user `HKCU\…\Run` entry, off by default) but was **not exercised end-to-end** during development to avoid changing your Windows startup configuration. Please try it once from Settings.
* **Windows notifications** for finished timers use a tray balloon and are **untested visually**; they're off by default. The in-app message and taskbar flash always work.
* Events can't cross midnight (split them into two entries). Editing a weekly class changes every week; single days can be skipped.
* Notes are plain text (no rich text or Markdown rendering).
* JSON import replaces all data; there's no merge import. CSV is export-only.
* The release is a portable folder: no installer, and the executable is not code-signed, so Windows SmartScreen may ask for confirmation the first time.
* Verified on this development PC (Windows 10 Pro, one display); other display-scaling factors were not tested. A running instance measured about 82 MB working set / 50 MB private memory; the packaged app opened its window in about 1.3 s.
* Lists are bounded for speed (500 tasks per view, 1000 notes, 40 recent study sessions in the history panel); full data is always kept and exported.
