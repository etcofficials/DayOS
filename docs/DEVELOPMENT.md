# Developing, testing, building and releasing DayOS

## Setup

Requires Windows 10/11 x64 and Python 3.12 (developed with 3.12.10). Everything
installs into the project's own virtual environment. Nothing is installed globally.

```bash
py -3.12 -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python.exe main.py
```

When running from source, data lives in the project folder (`data\`, `backups\`,
`exports\`, `logs\`). These folders are git-ignored and never committed.
Set `DAYOS_HOME` to use a different folder, for example a throwaway one for experiments.

## Tests

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

* The tests use `unittest`, and every test gets a throwaway data folder under `tests\.tmp\`.
* UI tests run offscreen when `QT_QPA_PLATFORM=offscreen` is set.
* Network calls, AI providers, audio devices and the Recycle Bin are stand-ins in the tests. Nothing on your machine is changed, and no request is sent.
* One test copies `data\dayos.db` (read-only) and migrates the copy to the latest schema.

Useful developer tools:

* `tools\shots.py --demo --pages today,notes --themes paper,midnight` takes screenshots with example data in a temporary folder.
* `tools\measure_startup.py` measures start-up time, first page visits and memory against a temporary folder.
* `tools\make_art.py` and `tools\make_icon.py` regenerate the illustrations and the icon.

## Build the Windows executable

```bash
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

```bash
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

* `-ExecutionPolicy Bypass` applies to that one command only; the system policy is not changed.
* Output: `dist\DayOS.exe`, a single windowed x64 executable.
* PyInstaller caches and temporary files stay inside the project (`.cache\`, `build\`).
* `dayos.spec` bundles only `assets\`. No database, backups or logs are packaged.

Verify the built EXE against a throwaway folder:

```bat
set DAYOS_HOME=%TEMP%\dayos-check
dist\DayOS.exe --self-test write
dist\DayOS.exe --self-test verify
```

## Release procedure

1. Update `src\version.py` and `version_info.txt`, and update `PROJECT_STATUS.md`.
2. Run the full test suite, build, and run both self-test steps on the EXE.
3. Commit, then push `main` (never force-push).
4. Tag `vX.Y.Z`, then create the GitHub release with `dist\DayOS.exe` attached (`gh release create`).
5. Check the release page, and check that the asset downloads and matches the local file's SHA-256.
