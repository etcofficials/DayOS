"""Application bootstrap: paths, logging, error handling, theme and main window."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from src.config import (
    AppPaths,
    DataDirectoryError,
    default_home,
    ensure_writable,
    pointer_file,
    remember_home,
    setup_logging,
)
from src.database import DatabaseError
from src.version import APP_NAME, APP_VERSION, ORGANIZATION

log = logging.getLogger("dayos")


def system_reduced_motion() -> bool:
    """True when Windows 'Show animations in Windows' is turned off."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        value = ctypes.c_bool(True)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0)  # SPI_GETCLIENTAREAANIMATION
        return bool(ok) and not value.value
    except (AttributeError, OSError):
        return False


def _set_app_user_model_id() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ETCLabs.DayOS")
        except (AttributeError, OSError):
            pass


def _install_excepthook(app: QApplication) -> None:
    def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.error("Unhandled error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        try:
            from src.ui.widgets.common import show_error

            show_error(
                app.activeWindow(),
                "Something went wrong",
                "DayOS ran into an unexpected problem. Your saved data is safe; the last action may not have completed.",
                f"{exc_type.__name__}: {exc}\nDetails were written to logs\\dayos.log.",
            )
        except Exception:  # never let the error dialog itself crash the app
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def choose_paths() -> AppPaths | None:
    """Resolve the data folder; if it isn't writable, let the user decide where data goes."""
    paths = AppPaths(default_home())
    while True:
        try:
            ensure_writable(paths)
            return paths
        except DataDirectoryError as exc:
            local = Path(pointer_file().parent)
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Where should DayOS keep your data?")
            box.setText(str(exc))
            box.setInformativeText(
                "You can keep your data in your Windows user folder instead, or choose another folder "
                "(for example on G:). DayOS will remember your choice.")
            use_local = box.addButton(f"Use {local}", QMessageBox.ButtonRole.AcceptRole)
            choose = box.addButton("Choose a folder…", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is use_local:
                target = local
            elif clicked is choose:
                folder = QFileDialog.getExistingDirectory(None, "Choose a folder for DayOS data")
                if not folder:
                    continue
                target = Path(folder) / "DayOS Data"
            else:
                return None
            try:
                remember_home(target)
            except OSError:
                pass
            paths = AppPaths(target)


def log_environment(paths: AppPaths) -> None:
    """One line of environment facts to make bug reports useful (no personal data)."""
    import platform

    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QLibraryInfo, qVersion

    from src.config import is_frozen

    log.info(
        "Environment: Windows %s | Python %s | PySide6 %s / Qt %s | frozen=%s | plugins=%s | data=%s",
        platform.version(), platform.python_version(), pyside_version, qVersion(), is_frozen(),
        QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath), paths.home,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="DayOS", add_help=True)
    parser.add_argument("--smoke-test", action="store_true",
                        help="start, open the main window, visit every page, then exit (for automated checks)")
    parser.add_argument("--self-test", choices=["write", "verify"],
                        help="drive real UI actions against the data folder, then exit (use a throwaway DAYOS_HOME)")
    parser.add_argument("--debug", action="store_true", help="write detailed diagnostic logging")
    args, _unknown = parser.parse_known_args(argv)
    return args


def run(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    _set_app_user_model_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION)

    paths = choose_paths()
    if paths is None:
        return 1
    setup_logging(paths, logging.DEBUG if args.debug else logging.INFO)
    log.info("Starting %s %s (home: %s)", APP_NAME, APP_VERSION, paths.home)
    log_environment(paths)
    _install_excepthook(app)

    from src.context import AppContext
    from src.ui.theme import theme

    theme.set_asset_dir(paths.cache_dir)
    try:
        ctx = AppContext.open(paths)
    except (DatabaseError, OSError) as exc:
        log.exception("Database could not be opened")
        theme.apply("light")
        QMessageBox.critical(
            None, "DayOS can't open your data",
            f"{exc}\n\nYour database file was not changed. Backups are in:\n{paths.backups_dir}",
        )
        return 1

    theme.apply(ctx.settings.get("theme"))
    ctx.settings.subscribe(lambda key, value: theme.apply(value) if key == "theme" else None)
    theme.system_reduced_motion = system_reduced_motion()

    from src.ui.main_window import MainWindow

    window = MainWindow(ctx)
    window.show()
    QTimer.singleShot(400, window.page("study").check_recovery)  # type: ignore[attr-defined]

    if args.self_test:
        from src import selftest

        selftest.schedule(window, args.self_test)

    if args.smoke_test:
        def smoke() -> None:
            for key in window.pages:
                window.navigate(key)
                app.processEvents()
            window.navigate("today")
            log.info("Smoke test visited %d pages", len(window.pages))
            print(f"SMOKE OK: {len(window.pages)} pages, window visible={window.isVisible()}")
            window.close()
            app.quit()

        QTimer.singleShot(1200, smoke)

    code = app.exec()
    from src.ui.worker import wait_for_background

    wait_for_background(15000)
    ctx.close()
    log.info("DayOS closed")
    return code
