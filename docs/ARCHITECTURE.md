# DayOS architecture

DayOS is a Python 3.12 + PySide6 (Qt Widgets) desktop app with one SQLite database.
The UI thread owns the database connection; long work (scans, hashing, PDF parsing,
network requests, AI, backups) runs on a thread pool and either returns plain data
or opens its own short-lived connection.

```
main.py                    entry point (--debug, --smoke-test, --self-test write|verify)
src/app.py                 start-up: data folder, logging, crash handler, theme, main window
src/config.py              data-folder strategy (see DATA_AND_PRIVACY.md)
src/context.py             AppContext: database, repositories, services, feature services
src/version.py             APP_VERSION
src/database/              connection (WAL, foreign keys), schema, append-only migrations
src/repositories/          core SQL and validation (tasks, notes, schedule, habits, goals …)
src/services/              Qt-free logic: dates, recurrence, search (FTS5), notifications,
                           backup, autobackup, transfer (JSON/CSV), http, credentials, ai …
src/modules/               feature packages (below) + registry.py + profiles.py
src/ui/                    theme engine, widgets, pages, shell (palette, capture, hotkeys,
                           notifier), settings sections, AI consent
tools/                     developer tools (screenshots, demo data, art, icon, measurements)
tests/                     unittest suite (temporary databases only)
```

## Modules

Each feature package lives in `src/modules/<name>/`. Importing it registers its
sidebar page (`registry.register(ModuleSpec(...))`). Optional hooks are:
* `services(ctx)`, which adds Qt-free services to `ctx.services`;
* `install(window)`, which adds palette commands, openers, dashboard widgets, Settings
  sections and global hotkeys.

A module that fails to load is logged and skipped; the rest of DayOS still opens
(`src/modules/__init__.py`). Pages are created the first time they are opened.

| Package | Responsibility |
|---|---|
| `studyforge` | Courses (subject → unit → chapter → topic). Local document import (`extract.py`, `syllabus.py`, `paperparse.py`). Question bank with provenance. Blueprints. Test assembly and marking (`assembler.py`, `marking.py`). Spaced revision (`srs.py`), mistakes, flashcards, materials, analytics (`service.py`). UI in `ui/`. |
| `brain` | SecondBrain. Note kinds, formats and collections. Attachments (copies stored in the DB). Wiki links and backlinks. Markdown import/export (`service.py`). The sidebar key stays `notes` for compatibility with v1. |
| `clipvault` | Opt-in clipboard history. Privacy decisions (`privacy.py`), storage and retention (`repository.py`), Qt clipboard monitor (`monitor.py`), read-only Win32 probes (`win32.py`), picker, page and settings. |
| `filepilot` | Read-only scanner (`scanner.py`), duplicates by content (`duplicates.py`), planned, verified and recorded operations with undo (`operations.py`), Recycle Bin (`win32fs.py`). |
| `audiodock` | Core Audio over ctypes COM (`coreaudio.py`), waveIn meter and test recording (`wavein.py`), profiles (`service.py`). |
| `briefing` | Open-Meteo weather (`weather.py`), RSS/Atom news (`news.py`), a controller that fetches only when stale. |
| `money` | Manual tracker: entries, categories, budgets, savings, subscriptions, CSV export. |
| `skills` | Skill roadmaps, prerequisites, activity logs and the weekly summary. |
| `projects` | Projects page over the core project data, and the read-only GitHub client. |
| `assist` | Settings → AI. The AI service is `src/services/ai.py`; features live in their own modules. |

Core pages (Today, Tasks, Calendar, Habits, Goals, Focus, Exams, Inbox, Insights,
Settings) are in `src/ui/pages/`. The shell, in `src/ui/shell/`, provides:
* the command registry and Ctrl+K palette;
* openers that open any record from search or links;
* quick capture and system-wide hotkeys (Win32 `RegisterHotKey`, exact combos only);
* the notifier, which uses a single timer to the next due item (no polling).

## Database

* SQLite with WAL and foreign keys. Every write goes through `db.transaction()`, and all SQL is parameterised.
* The schema version is `PRAGMA user_version`. Migrations (in `src/database/schema.py`) only add tables and columns, so v1 rows are never rewritten.
* Before upgrading a database that holds data, a verified backup is written (`pre-upgrade-vX-to-vY`).

| Version | Adds |
|---|---|
| 1 | v1: subjects, tasks, notes, habits, goals, journal, events, timetable, study sessions, exams, chapters, mistakes, mock tests, settings |
| 2 | Theme ids (light→paper, dark→midnight); v1 databases keep their pages and skip onboarding |
| 3 | Projects, milestones, logs. Recurrence, dependencies, tags, reminders, inbox, links, routines, weekly reviews, HTTP cache, FTS5 `search_index` with triggers |
| 4 | StudyForge `sf_*` tables; extra columns on `mistakes` and `study_sessions` |
| 5 | SecondBrain (note columns, `sb_collections`, `sb_attachments`); ClipVault (`cv_entries` is private, plus `cv_rules`) |
| 6 | FilePilot `fp_scans`, `fp_operations` |
| 7 | AudioDock `ad_profiles` (four starter profiles) |
| 8 | `news_read`; money (`money_*`, `subscriptions`, `savings_goals`); skills (`skills`, `skill_*`) |

Search uses one FTS5 table. Each record's rowid is `id * 64 + kind code`, and triggers
keep the index in step with the data. Clipboard history is never indexed.
**Settings → Data & backups → Rebuild search index** recreates it.

Exports (`src/services/transfer.py`):
* JSON export writes every table listed in `TABLE_ORDER`, except private tables (`cv_entries`) unless the user asks for them.
* Binary values are written as `{"$base64": …}`.
* Import validates everything, writes a backup, and replaces the data in one transaction.

## Themes

`src/ui/themes.py` holds the five themes. `src/ui/theme.py` builds the stylesheet
and applies a theme live. See [THEMES.md](THEMES.md).

## Dependencies

| Package | Why | Licence |
|---|---|---|
| PySide6-Essentials 6.11.2 | Qt Widgets/Gui/Svg (no web engine, no QML) | LGPLv3 |
| pypdf 6.1.1 | Local PDF text extraction (StudyForge) | BSD-3-Clause |
| anthropic 1.11.0 | Optional AI through the official SDK (imported only when used) | MIT; its dependencies are MIT, BSD-3 or PSF |
| pyinstaller 6.22.3 | Build only | GPL with bootloader exception |

Windows APIs are used through `ctypes` (Core Audio, winmm, user32/shell32, Credential
Manager), so there are no extra native packages.
