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
| 4 | SecondBrain and ClipVault | DONE (see below) |
| 5 | FilePilot | DONE (see below) |
| 6 | AudioDock | DONE (see below) |
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
* **Phase 4: SecondBrain** (`src/modules/brain/`, evolves v1 Notes; the sidebar key is still `notes`)
  * Note kinds: note, bookmark, code snippet, terminal command, project idea, troubleshooting, study note, reference.
  * Plain text or Markdown with a read-only preview. The preview loads nothing from the internet or the disk.
  * Collections (deleting one never deletes its notes), tags, pinning, archiving.
  * Bookmarks: URLs validated (http/https only); the same URL is never saved twice.
  * `[[wiki links]]` with backlinks.
  * Links to tasks, projects, courses, questions and more.
  * Attachments: copies stored in the database, up to 10 MB each, so backups and exports include them. Executable attachments are only ever saved as copies, never opened.
  * Markdown/text import (only ever adds notes). Markdown export always goes to a new folder and never overwrites.
  * JSON export encodes attachment bytes as base64.
* **Phase 4: ClipVault** (`src/modules/clipvault/`)
  * Opt-in: off by default. The first-use card explains what is stored, where, and what is skipped.
  * While off or paused, the clipboard is not read at all (the signal is disconnected).
  * Skipped:
    * copies an app marks private (`ExcludeClipboardContentFromMonitorProcessing` and related formats)
    * copies from known password managers (clipboard owner, or the foreground app as a fallback)
    * text that looks like keys, tokens, passwords, one-time codes or card numbers (Luhn check)
    * text matching the user's exclusion rules (app / contains / regex)
  * Skip reasons never contain the clipboard text, and history is never logged.
  * Entries are deduplicated. Retention covers both age and count; pinned, favourite, template and hand-added entries are always kept.
  * Clear history, or delete everything.
  * Templates expand `{date}`, `{time}`, `{datetime}` and `{clipboard}`.
  * Quick picker on an optional system-wide shortcut (default `Ctrl+Alt+Shift+V`, off by default; conflicts are reported in Settings). Shift+Enter pastes into the previous window with a single Ctrl+V.
  * A sidebar pause button appears while ClipVault is on.
  * History (`cv_entries`) is a private table: excluded from JSON export unless chosen, never in the FTS index, and shown in Ctrl+K only when allowed.
* **Phase 5: FilePilot** (`src/modules/filepilot/`, schema 6)
  * Scanning:
    * Read-only scans of the folders the user chooses (never automatic), in the background with progress and Cancel.
    * Links and junctions are never followed. Windows, system, hidden, `$Recycle.Bin` and similar folders are skipped.
    * Online-only cloud files are listed but never read.
  * Results:
    * Storage summary by type (images, screenshots, videos, documents, archives, installers …), biggest folders, large files and old downloads.
    * Sortable tables with checkboxes.
  * Duplicates:
    * Found by content only: grouped by size, then a first/last-64 KB fingerprint, then full SHA-256.
    * Files of 128 KB or less are hashed in full, and hard links are not reported.
    * One copy per group is always kept.
  * Operations:
    * Move, and send to the Recycle Bin (`SHFileOperationW` with `FOF_ALLOWUNDO`, fixed drives only). There is no permanent delete.
    * Every operation is previewed with its path, size, reason, destination and any conflict. Nothing is ever overwritten (skip, or keep both with a new name).
    * Files that changed since the scan are skipped. Windows, Program Files, AppData and DayOS's own folders are protected.
    * Moves are verified (size, plus SHA-256 across drives) before the original is removed.
    * Each result is recorded as it happens, on the worker's own connection.
    * Moves can be undone from History; undo never overwrites either.
  * Verified on this machine: a scratch file was recycled and found in `$Recycle.Bin` through its `$I` record.
* **Phase 6: AudioDock** (`src/modules/audiodock/`, schema 7). No new dependencies: Core Audio and winmm through ctypes.
  * Lists input and output endpoints with name, adapter, format and state, plus the default and communications devices.
  * Per-device volume slider and mute.
  * "Make default" uses `IPolicyConfig` (undocumented; the Sound control panel uses it). The default is read back to confirm, otherwise the user is pointed to Sound settings.
  * Microphone check:
    * Live peak meter (waveIn, 16 kHz mono). It only runs on request and stops when you leave the page.
    * 5-second test recording, kept in memory and played back with `winsound`. Never written to disk.
  * Profiles (Recording, Voiceover, OBS / streaming, Calls & meetings, custom): preferred devices, a communications flag, microphone volume and a checklist.
  * Applying a profile reports, device by device, what changed and what couldn't.
  * Troubleshooting details and tips. If Windows audio is unavailable, the page explains why and the rest of DayOS is unaffected.
  * The page states that it does not route audio, apply effects or change other apps.
  * Verified on this machine (read-only):
    * 3 active inputs and 4 active outputs listed with formats.
    * Defaults and volumes read.
    * Setting the current default to itself confirmed the switching path.
    * Every active input mapped to its waveIn device.
  * **Not exercised live:** opening the microphone (the meter and test recording). DayOS must not record without the user's action; the logic is tested against a simulated driver.
* Main window: `add_global_hotkey()` lets features claim shortcuts; `shutdown_hooks` run on close.
* **Tests:** 210 automated tests pass.

## Next concrete tasks

1. Phase 7: integrations (Open-Meteo, RSS, Credential Manager, AI consent).
2. Phase 8: hardening and documentation.
3. Phase 9:
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
