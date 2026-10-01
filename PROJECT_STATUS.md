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
| 1 | Theme engine, five themes, registry and navigation | DONE (commit `e0effd5`) |
| 2 | Home: tasks, calendar, habits, goals, reviews, dashboard widgets, capture, search, palette, notifications | DONE (commits `89dfc55`, `501492c`) |
| 3 | StudyForge | DONE (see below) |
| 4 | SecondBrain and ClipVault | NOT STARTED |
| 5 | FilePilot | NOT STARTED |
| 6 | AudioDock | NOT STARTED |
| 7 | Weather, news, skills, projects, money, profiles, GitHub, AI | NOT STARTED |
| 8 | Integration and hardening | NOT STARTED |
| 9 | Windows build and GitHub release | NOT STARTED |

Nothing from v2 has been pushed to GitHub yet. Commits are local on `main`.

## What exists now

* **Schema version 4.** Each migration only adds tables or columns:
  * Migration 2 maps the theme setting (light→paper, dark→midnight).
  * Migration 3 adds the planning tables and the FTS5 `search_index`.
  * Migration 4 adds the StudyForge `sf_*` tables and extra columns on `mistakes` and `study_sessions`.
* **Phase 1**
  * Theme registry: `src/ui/themes.py`, with contrast tests in `tests/test_themes.py`.
  * Font scale and accent options.
  * Module registry and profiles: `src/modules/registry.py`, `src/modules/profiles.py`.
  * Grouped sidebar with lazy pages, and sectioned Settings.
* **Phase 2**
  * Planning features:
    * projects
    * recurring tasks and events
    * task dependencies, tags and actual time
    * reminders, quiet hours and a notification centre
    * inbox and quick capture (global hotkey, Ctrl+Alt+N by default)
    * Ctrl+K command palette with FTS search
    * entity links, routines, workload and weekly review
  * The shell lives in `src/ui/shell/`.
* **Phase 3: StudyForge** (`src/modules/studyforge/`). The data and service layers have no Qt dependency; the UI is in `ui/`.
  * Courses as trees: subject → unit → chapter → topic → subtopic.
  * Local document import:
    * PDF via `pypdf`, `.docx` and text.
    * Scanned or encrypted pages are reported, never guessed.
    * Every import goes through a review step before anything is saved.
  * CBSE Class 10 starter template:
    * Chapter lists are marked *provisional*, with their source.
    * The user enters exam dates.
  * Question bank with provenance (official / imported / user / ai) and a verified flag. Duplicates are detected by content hash.
  * Blueprints. A blueprint can only be "verified" when it has a source.
  * Test generation:
    * Each test is built from the bank with a seed. Questions are snapshotted into the test.
    * If the bank is short of questions, the shortfall is explained.
  * Test taking: timer, autosave, resume, flags and a navigator.
  * Marking:
    * Objective answers are auto-marked.
    * Written answers are self-marked with a rubric.
    * AI estimates are kept separate and never replace a self mark or feed accuracy or the revision schedule.
  * Spaced revision (SM-2 style) with reasons shown for each topic.
  * Mistake notebook: three correct retries resolve a mistake.
  * Flashcards and study materials.
  * Analytics compare only tests with the same configuration.
  * Printable papers are labelled "not an official paper".
* **Tests:** 165 automated tests pass.

## Next concrete tasks

1. Phase 4:
   * SecondBrain: evolve Notes with kinds, collections, Markdown and links.
   * ClipVault: opt-in, pause, retention, exclusions, and skipping password-manager clipboard formats.
2. Phase 5: FilePilot. It only proposes changes, never auto-deletes, and offers undo.
3. Phase 6: AudioDock.
4. Phase 7: integrations (Open-Meteo, RSS, Credential Manager, AI consent).
5. Phase 8: hardening and documentation.
6. Phase 9:
   * Build and verify `dist/DayOS.exe`. `pypdf` is already in `requirements.txt` and in `hiddenimports`.
   * Push, publish the v2.0.0 release and verify the asset.

## Incident note (2026-10-01)

During phase 3, three tracked files were found truncated to 0 bytes even though their committed content was intact:
* `src/ui/dialogs.py`
* `src/ui/widgets/theme_preview.py`
* `assets/art/mark.svg`

Their modification times still pointed to their last legitimate edit. No session edit explains this.

They were restored from `HEAD` with nothing lost. A full scan of every tracked and untracked file found no other empty, NUL-filled or uncompilable files, and `git fsck` was clean.

If this happens again, suspect an external process or an unclean write on drive G:.
