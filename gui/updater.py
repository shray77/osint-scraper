"""gui/updater.py — авто-проверка обновлений через GitHub Releases API."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger("osint.updater")

GITHUB_API = "https://api.github.com/repos/shray77/osint-scraper/releases/latest"
CACHE_TTL_SECONDS = 24 * 3600


def _cache_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OSINTScraper"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "OSINTScraper"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "osint-scraper"
    base.mkdir(parents=True, exist_ok=True)
    return base / "update_check.json"


def _parse_version(v):
    v = (v or "").lstrip("vV").strip()
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _load_cached():
    p = _cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - data.get("checked_at", 0) > CACHE_TTL_SECONDS:
            return None
        return data
    except Exception:
        return None


def _save_cached(data):
    p = _cache_path()
    try:
        data["checked_at"] = time.time()
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def fetch_latest_release(timeout=10):
    cached = _load_cached()
    if cached:
        return cached
    import requests
    try:
        r = requests.get(GITHUB_API, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OSINT-Scraper-Updater",
        }, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        result = {
            "tag_name": data.get("tag_name", ""),
            "name": data.get("name", ""),
            "html_url": data.get("html_url", ""),
            "published_at": data.get("published_at", ""),
            "body": (data.get("body") or "")[:1000],
            "assets": [
                {"name": a.get("name", ""), "url": a.get("browser_download_url", ""),
                 "size_mb": round(a.get("size", 0) / 1024 / 1024, 1)}
                for a in data.get("assets", [])
            ],
        }
        _save_cached(result)
        return result
    except Exception:
        return None


class UpdateCheckerWorker(QtCore.QObject):
    update_available = QtCore.Signal(dict)
    no_update = QtCore.Signal(str)
    error = QtCore.Signal(str)

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version

    @QtCore.Slot()
    def run(self):
        try:
            release = fetch_latest_release()
            if not release or not release.get("tag_name"):
                self.error.emit("no release")
                return
            latest = _parse_version(release["tag_name"])
            current = _parse_version(self.current_version)
            if latest > current:
                release["current_version"] = self.current_version
                self.update_available.emit(release)
            else:
                self.no_update.emit(self.current_version)
        except Exception as e:
            logger.warning("UpdateCheckerWorker: %s", e)
            self.error.emit(str(e))


class UpdateNotificationBar(QtWidgets.QFrame):
    download_clicked = QtCore.Signal(str)
    dismissed = QtCore.Signal()

    def __init__(self, release_info, parent=None):
        super().__init__(parent)
        self.release_info = release_info
        self.setObjectName("updateBar")
        self.setStyleSheet("""
            QFrame#updateBar { background-color: #fef3c7; border-bottom: 1px solid #f59e0b; padding: 8px 16px; }
            QLabel { color: #92400e; }
            QPushButton { background-color: #2563eb; color: white; border: none; border-radius: 4px; padding: 4px 12px; font-weight: 600; }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton#dismissBtn { background-color: transparent; color: #92400e; border: none; padding: 4px 8px; }
            QPushButton#dismissBtn:hover { background-color: #fde68a; }
        """)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(12)
        icon = QtWidgets.QLabel("🎉")
        icon.setStyleSheet("font-size: 18px;")
        layout.addWidget(icon)
        new_v = release_info.get("tag_name", "?")
        cur_v = release_info.get("current_version", "?")
        msg = QtWidgets.QLabel(f"<b>Доступна новая версия {new_v}</b> (у вас — {cur_v})")
        msg.setStyleSheet("color: #92400e; font-size: 13px;")
        layout.addWidget(msg, 1)
        btn_dl = QtWidgets.QPushButton("⬇ Скачать")
        btn_dl.clicked.connect(self._on_download)
        layout.addWidget(btn_dl)
        btn_dismiss = QtWidgets.QPushButton("✕")
        btn_dismiss.setObjectName("dismissBtn")
        btn_dismiss.setFixedSize(28, 28)
        btn_dismiss.clicked.connect(self._on_dismiss)
        layout.addWidget(btn_dismiss)

    def _on_download(self):
        url = self.release_info.get("html_url", "https://github.com/shray77/osint-scraper/releases")
        self.download_clicked.emit(url)

    def _on_dismiss(self):
        self.hide()
        self.dismissed.emit()


class UpdateCheckMixin:
    def _setup_update_checker(self):
        try:
            from __version__ import __version__
        except ImportError:
            __version__ = "1.4.0"
        try:
            self._update_worker = UpdateCheckerWorker(__version__)
            self._update_thread = QtCore.QThread()
            self._update_worker.moveToThread(self._update_thread)
            self._update_thread.started.connect(self._update_worker.run)
            self._update_worker.update_available.connect(self._on_update_available)
            self._update_worker.no_update.connect(self._on_no_update)
            self._update_worker.error.connect(self._on_update_error)
            self._update_worker.update_available.connect(self._update_thread.quit)
            self._update_worker.no_update.connect(self._update_thread.quit)
            self._update_worker.error.connect(self._update_thread.quit)
            QtCore.QTimer.singleShot(3000, self._safe_start_update_thread)
            self._update_bar = None
        except Exception as e:
            logger.warning("_setup_update_checker: %s", e)

    def _safe_start_update_thread(self):
        try:
            if hasattr(self, "_update_thread") and self._update_thread:
                self._update_thread.start()
        except Exception as e:
            logger.warning("_safe_start: %s", e)

    @QtCore.Slot(dict)
    def _on_update_available(self, info):
        try:
            from __version__ import __version__
        except ImportError:
            __version__ = "1.4.0"
        try:
            dismissed = self._load_dismissed_version()
            if dismissed == info.get("tag_name", ""):
                return
            if self._update_bar is not None:
                return
            self._update_bar = UpdateNotificationBar(info, parent=self)
            self._update_bar.download_clicked.connect(self._open_release_url)
            self._update_bar.dismissed.connect(lambda: self._on_dismiss_update(info.get("tag_name", "")))
            central = self.centralWidget()
            layout = central.layout() if central else None
            if layout:
                layout.insertWidget(0, self._update_bar)
        except Exception as e:
            logger.warning("_on_update_available: %s", e)

    @QtCore.Slot(str)
    def _on_no_update(self, current):
        pass

    @QtCore.Slot(str)
    def _on_update_error(self, msg):
        pass

    def _open_release_url(self, url):
        import webbrowser
        webbrowser.open(url)

    def _on_dismiss_update(self, version):
        self._save_dismissed_version(version)
        self._update_bar = None

    def _load_dismissed_version(self):
        try:
            if sys.platform == "win32":
                base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OSINTScraper"
            elif sys.platform == "darwin":
                base = Path.home() / "Library" / "Preferences" / "OSINTScraper"
            else:
                base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "osint-scraper"
            base.mkdir(parents=True, exist_ok=True)
            p = base / "dismissed_update.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8")).get("version", "")
        except Exception:
            pass
        return ""

    def _save_dismissed_version(self, version):
        try:
            if sys.platform == "win32":
                base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OSINTScraper"
            elif sys.platform == "darwin":
                base = Path.home() / "Library" / "Preferences" / "OSINTScraper"
            else:
                base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "osint-scraper"
            base.mkdir(parents=True, exist_ok=True)
            p = base / "dismissed_update.json"
            p.write_text(json.dumps({"version": version, "dismissed_at": time.time()}), encoding="utf-8")
        except Exception:
            pass

    def check_for_updates_manual(self):
        try:
            from __version__ import __version__
        except ImportError:
            __version__ = "1.4.0"
        self.statusBar().showMessage("Проверяю обновления...")
        QtWidgets.QApplication.processEvents()
        try:
            p = _cache_path()
            if p.exists():
                p.unlink()
        except Exception:
            pass
        release = fetch_latest_release(timeout=15)
        if not release:
            QtWidgets.QMessageBox.warning(self, "Проверка обновлений",
                "Не удалось проверить обновления.\nhttps://github.com/shray77/osint-scraper/releases")
            return
        latest = _parse_version(release.get("tag_name", ""))
        current = _parse_version(__version__)
        if latest > current:
            release["current_version"] = __version__
            self._on_update_available(release)
        else:
            QtWidgets.QMessageBox.information(self, "Обновления",
                f"У вас последняя версия: {__version__}\nРелиз: {release.get('tag_name', '?')}")
        self.statusBar().showMessage("Готово", 2000)
