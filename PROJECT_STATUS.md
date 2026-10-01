# DayOS — Project Status

This file is the hand-over document for resuming work. Update it at the end of each substantial session.

## Current version

* Released: **1.1.0** (GitHub release `v1.1.0`, commit `5ba1907`)
* In development: **2.0.0** ("DayOS v2")
* Safe checkpoint before v2 work: git tag `v1.1.0-checkpoint` and the verified backup
  `backups/dayos-backup-20261001-114000-manual.db` (development database, schema 1, no user records).

## Phase 0 baseline (2026-10-01)

* Python 3.12.10 venv at `G:\DayOS\.venv`. Runtime dependency is only `PySide6-Essentials 6.11.2`
  (QtCore/Gui/Widgets/Svg). Build-only is `pyinstaller 6.22.3`. Tests use the standard `unittest`
  module, not pytest.
* SQLite 3.49.1 with FTS5 available. Schema version 1 (`PRAGMA user_version`), WAL mode, and
  foreign keys on.
* 87 automated tests pass: `python -m unittest discover -s tests -t .` with `QT_QPA_PLATFORM=offscreen`.
* Existing architecture:
  * `src/database` holds the connection and migrations.
  * `src/repositories` holds data access (no Qt).
  * `src/services` holds logic: dates, backup, transfer, timer, revision, streaks and stats.
  * `src/ui` holds the theme, anim, icons, widgets and pages.
  * `bus` is the change notification that refreshes pages.
* Two themes (light/dark) and 10 pages: Today, Tasks, Calendar, Study, Exams, Notes, Habits,
  Goals, Insights and Settings.

## v2 architecture plan

* **Module registry** (`src/modules/registry.py`): each module declares its key, title, icon, nav
  group, a lazily imported page factory, palette commands and search providers. The main window
  builds its grouped, scrollable sidebar from the registry and creates pages on first visit. User
  profiles decide which modules are shown.
* **Feature packages** for the new modules live in `src/modules/<name>/`:
  * `studyforge`, `brain` (SecondBrain), `clipvault`, `filepilot`, `audiodock`
  * `briefing` (weather and news), `growth` (skills), `projects`, `money`
  * Each package has a Qt-free repository/service layer and a separate UI module.
  * The existing Home pages stay in `src/ui/pages`.
* **Shared services** (`src/services`):
  * settings, theme, backup/restore, import/export
  * search (SQLite FTS5 maintained by triggers), reminders/notifications, credentials (Windows
    Credential Manager), HTTP (timeouts, size caps, caching), AI provider abstraction
  * global hotkeys (Win32 `RegisterHotKey`), background jobs with cancellation
* **Database**: append-only migrations 2, 3, … Each migration only adds tables or columns, so v1
  data is never rewritten. The existing pre-upgrade backup hook runs before every upgrade of a
  populated database.
* **Threading**:
  * The UI thread owns the single main connection.
  * Background jobs (scans, hashing, parsing, HTTP) never touch it. They return plain data, or open
    their own short-lived connection.
* **Themes**:
  * The `src/ui/themes.py` registry defines five themes: Paper & Sage, Midnight Focus, Zen Minimal,
    Aurora and Espresso.
  * Each theme has its own colour tokens, typography, shape and art. The shared stylesheet and
    painted widgets read only semantic tokens.

## Status by phase

| Phase | Scope | Status |
|---|---|---|
| 0 | Inspection, baseline, checkpoint, plan | DONE |
| 1 | Theme engine, five themes, registry and navigation | IN PROGRESS |
| 2 | Home: tasks, calendar, habits, goals, reviews, dashboard widgets, capture, search, palette, notifications | NOT STARTED |
| 3 | StudyForge | NOT STARTED |
| 4 | SecondBrain and ClipVault | NOT STARTED |
| 5 | FilePilot | NOT STARTED |
| 6 | AudioDock | NOT STARTED |
| 7 | Weather, news, skills, projects, money, profiles, GitHub, AI | NOT STARTED |
| 8 | Integration and hardening | NOT STARTED |
| 9 | Windows build and GitHub release | NOT STARTED |

## Next concrete tasks

1. Theme registry and ThemeManager with font scale, accent options and per-theme art.
2. Theme selection screen in Settings.
3. Module registry, grouped sidebar and lazy page creation.
