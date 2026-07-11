#!/usr/bin/env python3
"""
osint_app.py — точка входа GUI-приложения OSINT Scraper.

v1.3.4: раннее логирование в файл на каждом шаге, чтобы диагностировать
падения, которые происходят до инициализации Python logging.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def _crash_log_path() -> Path:
    """Платформенно-корректный путь для crash-логов (раньше logging module)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OSINTScraper" / "logs"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs" / "OSINTScraper"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "osint-scraper"
    base.mkdir(parents=True, exist_ok=True)
    return base / "crash.log"


def _early_log(msg: str) -> None:
    """Прямая запись в файл — без Python logging, чтобы работал даже при падении импортов."""
    try:
        path = _crash_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass
    # Также в stderr (если консоль видна)
    try:
        print(f"[early] {msg}", file=sys.stderr, flush=True)
    except Exception:
        pass


def get_app_dir() -> str:
    """Возвращает корень приложения (dev / onedir / onefile)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    elif getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(*parts: str) -> str:
    """Возвращает путь к ресурсу."""
    base = get_app_dir()
    path = os.path.join(base, *parts)
    if os.path.exists(path):
        return path
    internal_path = os.path.join(base, "_internal", *parts)
    if os.path.exists(internal_path):
        return internal_path
    return path


APP_DIR = get_app_dir()
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
INTERNAL_DIR = os.path.join(APP_DIR, "_internal")
if os.path.isdir(INTERNAL_DIR) and INTERNAL_DIR not in sys.path:
    sys.path.insert(0, INTERNAL_DIR)


def setup_qt_platform():
    """Настройка Qt-платформы."""
    if sys.platform.startswith("linux"):
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
        if not os.environ.get("QT_OPENGL"):
            os.environ["QT_OPENGL"] = "software"


def main():
    _early_log("=== OSINT Scraper startup ===")
    _early_log(f"sys.argv: {sys.argv}")
    _early_log(f"sys.executable: {sys.executable}")
    _early_log(f"sys.version: {sys.version}")
    _early_log(f"sys.platform: {sys.platform}")
    _early_log(f"APP_DIR: {APP_DIR}")
    _early_log(f"frozen: {getattr(sys, 'frozen', False)}")
    if getattr(sys, "frozen", False):
        _early_log(f"_MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")

    setup_qt_platform()
    _early_log("Qt platform setup OK")

    # Парсим --debug до импорта GUI
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--console", action="store_true")
    args, _ = parser.parse_known_args()
    _early_log(f"args: {args}")

    # Явные импорты для PyInstaller — поэтапно с логированием
    _early_log("Importing requests...")
    try:
        import requests  # noqa: F401
        _early_log("  requests OK")
    except ImportError as e:
        _early_log(f"  requests FAILED: {e}")

    _early_log("Importing bs4, lxml, openpyxl...")
    try:
        import bs4  # noqa: F401
        import lxml  # noqa: F401
        import openpyxl  # noqa: F401
        _early_log("  bs4/lxml/openpyxl OK")
    except ImportError as e:
        _early_log(f"  bs4/lxml/openpyxl FAILED: {e}")

    _early_log("Importing pdfplumber (optional)...")
    try:
        import pdfplumber  # noqa: F401
        import pdfminer  # noqa: F401
        _early_log("  pdfplumber OK")
    except ImportError as e:
        _early_log(f"  pdfplumber not available (will use pdftotext): {e}")

    _early_log("Importing project modules...")
    try:
        import utils  # noqa: F401
        import collectors  # noqa: F401
        import reporters  # noqa: F401
        import orchestrator  # noqa: F401
        _early_log("  utils/collectors/reporters/orchestrator OK")
    except ImportError as e:
        _early_log(f"  project modules FAILED: {e}")
        # Это критично — без них приложение не работает
        try:
            from PySide6 import QtWidgets
            app = QtWidgets.QApplication(sys.argv)
            QtWidgets.QMessageBox.critical(
                None, "Ошибка импорта",
                f"Не удалось загрузить основные модули:\n\n{e}\n\n"
                f"Приложение будет закрыто."
            )
        except Exception:
            pass
        sys.exit(1)

    _early_log("Importing gui modules...")
    try:
        import gui.workers  # noqa: F401
        import gui.updater  # noqa: F401
        import gui.main_window  # noqa: F401
        import __version__  # noqa: F401
        _early_log("  gui modules OK")
    except ImportError as e:
        _early_log(f"  gui modules FAILED: {e}")
        try:
            from PySide6 import QtWidgets
            app = QtWidgets.QApplication(sys.argv)
            QtWidgets.QMessageBox.critical(
                None, "Ошибка импорта GUI",
                f"Не удалось загрузить GUI модули:\n\n{e}\n\n"
                f"Приложение будет закрыто."
            )
        except Exception:
            pass
        sys.exit(1)

    _early_log("Importing PySide6...")
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        _early_log("  PySide6 OK")
    except ImportError as e:
        _early_log(f"  PySide6 FAILED: {e}")
        sys.exit(1)

    _early_log("Importing MainWindow...")
    try:
        from gui.main_window import MainWindow, APP_STYLE
        _early_log("  MainWindow OK")
    except Exception as e:
        _early_log(f"  MainWindow FAILED: {e}")
        import traceback
        _early_log(traceback.format_exc())
        sys.exit(1)

    # Логирование через logging module
    import logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        from utils import setup_file_logger
        setup_file_logger(log_level)
        _early_log("File logger initialized")
    except Exception as e:
        _early_log(f"File logger failed: {e}")

    # Глобальный excepthook
    def _global_excepthook(exc_type, exc_value, exc_tb):
        import traceback
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _early_log(f"UNHANDLED EXCEPTION:\n{tb_text}")
        logging.getLogger("osint.crash").error("Unhandled exception:\n%s", tb_text)
        try:
            if QtWidgets.QApplication.instance():
                QtWidgets.QMessageBox.critical(
                    None, "Непредвиденная ошибка",
                    f"Произошла ошибка:\n\n{exc_value}\n\n"
                    f"Логи:\n  {_crash_log_path()}\n\n"
                    f"Traceback:\n{tb_text[:1000]}"
                )
        except Exception:
            pass
        sys.exit(1)

    sys.excepthook = _global_excepthook
    _early_log("Excepthook installed")

    # Создание QApplication
    _early_log("Creating QApplication...")
    try:
        app = QtWidgets.QApplication(sys.argv)
        app.setApplicationName("OSINT Scraper")
        app.setApplicationDisplayName("OSINT Scraper")
        app.setOrganizationName("OSINT Tools")
        app.setApplicationVersion(getattr(__version__, "__version__", "1.3.4"))
        app.setStyleSheet(APP_STYLE)
        _early_log("QApplication created")
    except Exception as e:
        _early_log(f"QApplication FAILED: {e}")
        import traceback
        _early_log(traceback.format_exc())
        sys.exit(1)

    # Иконка
    icon_path = get_resource_path("gui", "resources", "icon.png")
    if os.path.exists(icon_path):
        try:
            app.setWindowIcon(QtGui.QIcon(icon_path))
            _early_log(f"Icon set: {icon_path}")
        except Exception as e:
            _early_log(f"Icon failed: {e}")
    else:
        _early_log(f"Icon not found: {icon_path}")

    # Главное окно
    _early_log("Creating MainWindow...")
    try:
        window = MainWindow()
        window.show()
        _early_log("MainWindow shown")
    except Exception as e:
        _early_log(f"MainWindow FAILED: {e}")
        import traceback
        _early_log(traceback.format_exc())
        QtWidgets.QMessageBox.critical(
            None, "Ошибка инициализации",
            f"Не удалось создать главное окно:\n\n{e}\n\n"
            f"Логи: {_crash_log_path()}"
        )
        sys.exit(1)

    _early_log("Entering event loop...")
    try:
        sys.exit(app.exec())
    except Exception as e:
        _early_log(f"Event loop FAILED: {e}")
        import traceback
        _early_log(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
