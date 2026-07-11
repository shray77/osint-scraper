"""gui/workers.py — QThread workers v1.4 через orchestrator.py."""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import HttpClient, HAS_PLAYWRIGHT, setup_file_logger
from orchestrator import OSINTOrchestrator, save_reports


class QtLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record)
            QtCore.QTimer.singleShot(0, lambda m=msg: self.callback(m))
        except Exception:
            pass


class SearchWorker(QtCore.QObject):
    started = QtCore.Signal(str)
    collector_started = QtCore.Signal(str, str)
    collector_finished = QtCore.Signal(str, dict)
    progress = QtCore.Signal(int, int, str)
    log_message = QtCore.Signal(str)
    finished = QtCore.Signal(dict, dict)
    error = QtCore.Signal(str)

    def __init__(self, query, deep=True, fetch_site=True, enable_playwright=True,
                 use_cache=True, skip_cloudflare=True, output_dir=""):
        super().__init__()
        self.query = query
        self.deep = deep
        self.fetch_site = fetch_site
        self.enable_playwright = enable_playwright and HAS_PLAYWRIGHT
        self.use_cache = use_cache
        self.skip_cloudflare = skip_cloudflare
        self.output_dir = output_dir or str(Path.cwd() / "output")
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    @QtCore.Slot()
    def run(self):
        try:
            self.started.emit(self.query)
            self.log_message.emit(f"Запуск OSINT-сбора для: {self.query}")
            gui_handler = QtLogHandler(self.log_message.emit)
            gui_handler.setLevel(logging.INFO)
            gui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
            root_logger = logging.getLogger()
            root_logger.addHandler(gui_handler)
            try:
                setup_file_logger(logging.INFO)
            except Exception:
                pass
            try:
                http = HttpClient(use_cache=self.use_cache, enable_playwright=self.enable_playwright)
                orch = OSINTOrchestrator(http, deep=self.deep, fetch_site=self.fetch_site,
                                         skip_cloudflare_blocked=self.skip_cloudflare)
                report = orch.run(
                    self.query,
                    on_collector_started=lambda n, q="": self.collector_started.emit(n, q),
                    on_collector_finished=lambda n, s: self.collector_finished.emit(n, s),
                    on_progress=lambda c, t, m: self.progress.emit(c, t, m),
                    on_log=lambda m: self.log_message.emit(m),
                    stop_flag=lambda: self._stop_flag,
                )
                http.close()
            finally:
                root_logger.removeHandler(gui_handler)
            if self._stop_flag:
                self.error.emit("Сбор остановлен пользователем")
                return
            output_paths = save_reports(report, self.output_dir, self.query)
            self.log_message.emit(f"Отчёты сохранены")
            self.finished.emit(report, output_paths)
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")


class BatchSearchWorker(QtCore.QObject):
    started = QtCore.Signal(int)
    company_started = QtCore.Signal(int, str)
    company_finished = QtCore.Signal(int, dict, dict)
    progress = QtCore.Signal(int, int, str)
    log_message = QtCore.Signal(str)
    all_finished = QtCore.Signal(str, str)
    error = QtCore.Signal(str)

    def __init__(self, queries, deep=True, fetch_site=True, enable_playwright=True,
                 use_cache=True, skip_cloudflare=True, output_dir=""):
        super().__init__()
        self.queries = queries
        self.deep = deep
        self.fetch_site = fetch_site
        self.enable_playwright = enable_playwright and HAS_PLAYWRIGHT
        self.use_cache = use_cache
        self.skip_cloudflare = skip_cloudflare
        self.output_dir = output_dir or str(Path.cwd() / "output")
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    @QtCore.Slot()
    def run(self):
        try:
            total = len(self.queries)
            self.started.emit(total)
            self.log_message.emit(f"Batch-режим: {total} компаний")
            from reporters import CsvReporter
            out_dir = Path(self.output_dir) / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            out_dir.mkdir(parents=True, exist_ok=True)
            all_reports = []
            http = HttpClient(use_cache=self.use_cache, enable_playwright=self.enable_playwright)
            orch = OSINTOrchestrator(http, deep=self.deep, fetch_site=self.fetch_site,
                                     skip_cloudflare_blocked=self.skip_cloudflare)
            for i, query in enumerate(self.queries):
                if self._stop_flag:
                    break
                self.company_started.emit(i, query)
                self.progress.emit(i, total, f"[{i+1}/{total}] {query}")
                self.log_message.emit(f"\n=== [{i+1}/{total}] {query} ===")
                try:
                    report = orch.run(query, on_log=lambda m: self.log_message.emit(m),
                                     stop_flag=lambda: self._stop_flag)
                    paths = save_reports(report, str(out_dir), query)
                    all_reports.append(report)
                    self.company_finished.emit(i, report, paths)
                except Exception as e:
                    self.log_message.emit(f"❌ {query}: {e}")
                    empty = {"company_input": query, "company": {}, "market": {},
                             "company_site": {}, "sources_used": [],
                             "errors": [f"batch_exception: {e}"],
                             "collector_stats": {},
                             "generated_at": datetime.now().isoformat(timespec="seconds")}
                    all_reports.append(empty)
                    self.company_finished.emit(i, empty, {})
            http.close()
            csv_path = ""
            if all_reports:
                csv_path = str(out_dir / "batch_summary.csv")
                CsvReporter().save_batch(all_reports, csv_path)
                self.log_message.emit(f"\n📊 Сводный CSV: {csv_path}")
            self.all_finished.emit(csv_path, str(out_dir))
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")
