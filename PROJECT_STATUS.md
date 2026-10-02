# DayOS — Project Status

This file is the hand-over document for resuming work. Update it at the end of each substantial session.

## Current version

* Current version: **2.0.0** ("DayOS v2"), released as GitHub release `v2.0.0` (commit `20d91a9`).
* Previous release: **1.1.0** (GitHub release `v1.1.0`, commit `5ba1907`).
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
| 7 | Weather, news, skills, projects, money, profiles, GitHub, AI | DONE (see below) |
| 8 | Integration and hardening | DONE (see below) |
| 9 | Windows build and GitHub release | DONE (released v2.0.0, see *Build and release*) |


## What exists now

* **Schema version 8.** Each migration only adds tables or columns (the full table is in `docs/ARCHITECTURE.md`):
  * Migration 2 maps the theme setting (light→paper, dark→midnight).
  * Migration 3 adds the planning tables and the FTS5 `search_index`.
  * Migration 4 adds StudyForge; 5 SecondBrain and ClipVault; 6 FilePilot; 7 AudioDock; 8 news read state, money and skills.
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
* **Phase 7** (schema 8)
  * Shared online plumbing:
    * `src/services/http.py`: http(s) only, timeouts, size caps, `Retry-After` honoured, no retries or polling. Logs show host and status only.
    * `http_cache`.
    * `src/services/credentials.py`: Windows Credential Manager.
  * Weather (`src/modules/briefing/weather.py`): Open-Meteo, checked for terms (non-commercial, no key, CC BY 4.0) and verified live.
  * News (`news.py`): publishers' own RSS/Atom feeds. All 15 default feeds were verified live; `hnrss.org` was excluded because it isn't a publisher.
  * Both are off by default, refresh at most once per interval with a 15-minute back-off after failures, label offline and stale data, and never fill in missing values or headlines.
  * Money (`src/modules/money`): manual tracker with exact amounts in minor units.
    * Currency is chosen by the user.
    * Budgets, savings goals, subscriptions with renewal reminders (notification category `bill`), and CSV export.
    * No bank access and no predictions.
  * Skills (`src/modules/skills`): roadmaps with milestones, resources and practice tasks.
    * Prerequisites, with cycles refused.
    * Learn / practice / build logs with evidence links.
    * Weekly review with no scores or shaming.
  * Projects page (`src/modules/projects`) over the existing project data.
    * Optional read-only GitHub panel through the official REST API; the token lives in Credential Manager only.
    * Verified live against the public DayOS repository.
  * Optional AI (`src/services/ai.py`, official `anthropic` SDK 1.11.0, model `claude-opus-5-5` by default):
    * The user's own key is stored in Credential Manager.
    * A consent dialog shows exactly what will be sent; the preview and the request come from the same payload function.
    * JSON-schema outputs are validated.
    * `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) is on for Opus and Sonnet, and refusals are handled.
    * Features: note summary and tags, project task suggestions, and StudyForge practice questions (saved as `ai`, not verified).
    * No live AI call has been made: no key is configured on this machine.
* **Phase 8**
  * Automatic backups (`src/services/autobackup.py`): weekly by default, daily or off, run on a worker thread 20 s after start-up. Only `-auto` backups are rotated (keep N); manual and safety backups are never removed.
  * SecondBrain imports skip notes that already exist (same title and text).
  * Focus sessions can be linked to a StudyForge topic (`study_sessions.node_id`).
  * Migration of a copy of the real dev database (schema 1 → 8) is tested.
  * Repository hygiene test: no databases, logs or secrets are tracked.
  * The self-test covers every page, all five themes, bundled pypdf and anthropic, StudyForge, SecondBrain, ClipVault, money and skills records, and a FilePilot scan.
  * Docs: README, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, `docs/DATA_AND_PRIVACY.md`, `docs/THEMES.md`, fresh screenshots.
  * Version 2.0.0.
  * Start-up measured from source on this PC (`tools/measure_startup.py`, Windows platform, empty database):
    * imports 0.70 s, then database plus window shown 1.43 s;
    * 18 pages each first visited in at most 0.45 s;
    * 140 MB working set after visiting every page.
* Main window: `add_global_hotkey()` lets features claim shortcuts; `shutdown_hooks` run on close.
* **Layout fixes (overlapping widgets, reported 2026-10-02).**
  * Cause: the window may be made as small as 980×640, but several pages needed more room than that. Qt then squeezes widgets below their minimum size and they overlap: filter tabs (Tasks, ClipVault), SecondBrain's toolbar combos, ClipVault's privacy text, FilePilot's options, and the Exams detail pane was cut off.
  * Every page now sits in a `PageFrame` (a scroll area): a page that doesn't fit scrolls instead of being squeezed.
  * Below 1120 px wide the sidebar folds to icons automatically, without changing the saved preference. Expanding it by hand sticks. Focus mode's fold is also temporary now.
  * Page side margins shrink from 34 to 20 px when a page is narrower than 960 px.
  * Wide rows wrap (`FlowLayout` with `add_stretch()`): Tasks filters, SecondBrain editor toolbar, goal actions, automatic-backup settings.
  * `ResponsiveGrid` never uses more columns than its cards fit in. The Study page cards and the Settings theme cards use it.
  * Segment buttons and chips never shrink below their text. Splitter panels use `min_width_floor()` instead of `setMinimumWidth()`, which had let their contents be squeezed.
  * Every list row includes the stylesheet's item padding (`LIST_ITEM_PADDING`). Exams, Goals, SecondBrain, ClipVault and the command palette had text cut off at the bottom.
  * Long one-line titles end in "…" (`ElidedLabel`) instead of being cut mid-letter.
  * The Today header's illustration no longer sits under the theme and settings buttons.
  * The CBSE setup dialog's date fields were squashed to 7 px: a nested grid layout in a form row kept stale heights. Fixed by putting the grid in its own widget.
  * Checked every page, every tab, every Settings section and 24 dialogs at 980×640, 1100×700 (text 1.25×), 1260×820 (text 1.0× and 1.25×), 1360×860 and 1920×1040. No overlaps or clipped text remain. At the smallest sizes some pages scroll vertically.
  * `tests/test_layout.py` repeats the page checks at 980×640 and at 1260×820 with 1.25× text. Tests now measure text with the Windows fonts (`tests/__init__.py`), like the real app.
* **Tests:** see Latest test results below.

## Build and release

* **Build:** `dist\DayOS.exe` was built with `build.ps1` (PyInstaller 6.22.3, one file, windowed).
  * Rebuilt after the layout fixes: 37,475,789 bytes (35.7 MB), PE machine 0x8664 (x64), GUI subsystem.
  * SHA-256 `06baaa035ff5af1130b163bf9a7e56c03a1e8afec02fca6bb2dc80e80c45225f`.
  * The first rebuild attempt stopped inside PyInstaller with Windows error 0xC0000006, an in-page I/O error reading a file. The retry built cleanly. Like the incident note below, this points at drive G: rather than the code.
* **Bug found by testing the real EXE:** the first v2 build couldn't start. Pages and feature packages are imported by name at run time, so PyInstaller missed them. `dayos.spec` now bundles `collect_submodules("src")`, and `tests/test_hardening.py` guards it.
* **Verified with the actual EXE** (throwaway folders under `release\`, git-ignored):
  * `--self-test write`: exit code 0. It visited all pages, cycled all five themes, imported the bundled pypdf, QtSvg and anthropic, created and completed a task through the dashboard, saved a note through the editor, logged a study session, ran the focus timer, wrote StudyForge, SecondBrain, ClipVault, money and skills records, and ran a FilePilot scan that found the duplicate.
  * `--self-test verify` after a restart: exit code 0. All of the above persisted, schema is 8, integrity ok. No ERROR lines in the log.
  * The self-test and the upgrade check were both repeated with the rebuilt EXE, in fresh folders (`release\v2check2`, `release\v1upgrade2`), and passed.
  * **v1 → v2 upgrade:** a copy of the database written by the v1.1.0 EXE's own self-test was opened with the v2 EXE (`--smoke-test`, exit 0, 19 pages).
    * It wrote `pre-upgrade-v1-to-v8` first, then upgraded to schema 8 with integrity ok.
    * The v1 task (completed), note and study session were preserved, and the theme preference (`system`) was kept.
  * **Start-up of the EXE on this PC:** about 4 s from launch until Python starts (the one-file EXE unpacks itself), then about 1.0–1.5 s to the main window.
  * **Package contents:** listed with `pyi-archive_viewer`. There are no databases, logs, backups or personal files, only code and `assets\`.
* **Release:** published and verified on 2026-10-02 as [DayOS 2.0.0 — Windows Desktop Release](https://github.com/etcofficials/DayOS/releases/tag/v2.0.0).
  * Tag `v2.0.0` (annotated) points at commit `20d91a9`, which is on `origin/main`. It is not a draft or pre-release, and it is marked Latest.
  * Asset `DayOS.exe`: 37,475,789 bytes, state *uploaded*.
  * The asset was downloaded again with `gh release download`. Its SHA-256 matches the local build exactly.
  * The page and the download link both return HTTP 200 without signing in.
  * The downloaded copy itself passed `--smoke-test` (19 pages).

## Latest test results

* 245 automated tests, all passing (`python -m unittest discover -s tests -t .`, offscreen).
* Built-in self-test passes from source and from the built EXE (write and verify).

## Known issues and unverified items

* AI: no real API call has been made (no key on this machine); the provider is tested with stand-ins.
* AudioDock: the microphone meter and test recording were not run against real hardware (no recording without the user's action). Default-device switching was verified only by setting the current default to itself.
* Windows toast notifications and *Open at sign-in* have not been exercised end-to-end.
* The EXE isn't code-signed.
* Tested on Windows 10 Pro x64 at one display scale.

## Next concrete tasks

1. After release: watch for feedback on start-up time (single-file unpacking takes about 4 s); a one-folder build would start faster if that matters.
2. Exercise the AI features with a real key, and AudioDock's microphone check on real hardware, with the user present.

## Incident note (2026-10-01)

During phase 3, three tracked files were found truncated to 0 bytes even though their committed content was intact:
* `src/ui/dialogs.py`
* `src/ui/widgets/theme_preview.py`
* `assets/art/mark.svg`

Their modification times still pointed to their last legitimate edit. No session edit explains this.

They were restored from `HEAD` with nothing lost. A full scan of every tracked and untracked file found no other empty, NUL-filled or uncompilable files, and `git fsck` was clean.

If this happens again, suspect an external process or an unclean write on drive G:.
