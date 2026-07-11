"""
gui/workers.py — QThread workers для асинхронного запуска OSINT-коллекторов.

Без этих workers GUI зависал бы на 30-60 секунд во время сбора данных.
Каждый worker:
1. Создаёт OSINTOrchestrator в своём потоке
2. Шлёт сигналы о прогрессе (collector_started, collector_finished, all_done)
3. Возвращает готовый report в главный поток

Также класс SearchWorker перехватывает логи из модуля osint и шлёт их в GUI.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets

# Импорты из основной папки
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import HttpClient, HAS_PLAYWRIGHT
from collectors import (
    BaseCollector,
    CompanySiteCollector,
    CollectorResult,
    FindCompanyCollector,
    ListOrgCollector,
    MarketSearchCollector,
    NalogEGRULCollector,
    NalogEgrulPdfCollector,
    RosstatCollector,
    RusprofileCollector,
    ZacheBiznesCollector,
)
from reporters import ExcelReporter, MarkdownReporter


# ---------------------------------------------------------------------------
# Лог-хендлер, шлющий сигналы в GUI
# ---------------------------------------------------------------------------
class QtLogHandler(logging.Handler):
    """Лог-хендлер, который пересылает сообщения через Qt-сигнал."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record)
            # Передаём через таймер, чтобы не зависеть от потока
            QtCore.QTimer.singleShot(0, lambda m=msg: self.callback(m))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Worker: запуск одного OSINT-запроса
# ---------------------------------------------------------------------------
class SearchWorker(QtCore.QObject):
    """Запускает OSINT-сборку в отдельном потоке.

    Сигналы:
        started(query)
        collector_started(name, query)
        collector_finished(name, stats)
        progress(current, total, message)
        log_message(message)
        finished(report, output_paths)
        error(message)
    """

    started = QtCore.Signal(str)
    collector_started = QtCore.Signal(str, str)
    collector_finished = QtCore.Signal(str, dict)
    progress = QtCore.Signal(int, int, str)
    log_message = QtCore.Signal(str)
    finished = QtCore.Signal(dict, dict)
    error = QtCore.Signal(str)

    def __init__(
        self,
        query: str,
        deep: bool = True,
        fetch_site: bool = True,
        enable_playwright: bool = True,
        use_cache: bool = True,
        output_dir: str = "",
    ):
        super().__init__()
        self.query = query
        self.deep = deep
        self.fetch_site = fetch_site
        self.enable_playwright = enable_playwright and HAS_PLAYWRIGHT
        self.use_cache = use_cache
        self.output_dir = output_dir or str(Path.cwd() / "output")
        self._stop_flag = False

    def stop(self):
        """Устанавливает флаг остановки. Реальная остановка происходит между коллекторами."""
        self._stop_flag = True

    @QtCore.Slot()
    def run(self):
        """Главный метод — запускается в отдельном потоке."""
        try:
            self.started.emit(self.query)
            self.log_message.emit(f"Запуск OSINT-сбора для: {self.query}")

            # Настроим логирование в GUI
            gui_handler = QtLogHandler(self.log_message.emit)
            gui_handler.setLevel(logging.INFO)
            gui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
            root_logger = logging.getLogger()
            root_logger.addHandler(gui_handler)

            try:
                report = self._run_orchestration()
            finally:
                root_logger.removeHandler(gui_handler)

            if self._stop_flag:
                self.error.emit("Сбор остановлен пользователем")
                return

            output_paths = self._save_reports(report)
            self.finished.emit(report, output_paths)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.error.emit(f"{e}\n\n{tb}")

    def _run_orchestration(self) -> dict:
        """Запускает все коллекторы по очереди, шлёт прогресс-сигналы."""
        import re
        import time as _time
        from utils import looks_like_inn, okved_to_industry

        http = HttpClient(
            use_cache=self.use_cache,
            enable_playwright=self.enable_playwright,
        )

        query = self.query
        is_inn = looks_like_inn(query)

        report = {
            "company_input": query,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "company": {},
            "market": {},
            "company_site": {},
            "sources_used": [],
            "errors": [],
            "collector_stats": {},
        }

        # Коллекторы (порядок важен)
        collectors: list[BaseCollector] = [
            NalogEGRULCollector(http),
            RusprofileCollector(http),
            ZacheBiznesCollector(http),
            ListOrgCollector(http),
            FindCompanyCollector(http),
        ]
        egrul_pdf_collector = NalogEgrulPdfCollector(http)
        market_collector = MarketSearchCollector(http)
        rosstat_collector = RosstatCollector(http)
        site_collector = CompanySiteCollector(http)

        # Всего шагов: 5 collectors + 1 EGRUL-PDF + 2 market/rosstat + 1 site = 9
        total_steps = 5 + (1 if self.deep else 0) + 2 + (1 if self.fetch_site else 0)
        current_step = 0

        best_match = None
        secondary_query = query

        for collector in collectors:
            if self._stop_flag:
                break
            self.collector_started.emit(collector.name, secondary_query)
            self.progress.emit(current_step, total_steps, f"→ {collector.name}")
            t0 = _time.time()
            try:
                res: CollectorResult = collector.collect(secondary_query)
            except Exception as e:
                self.log_message.emit(f"❌ {collector.name} упал: {e}")
                report["errors"].append(f"{collector.name}: exception {e}")
                continue
            dt = _time.time() - t0
            stats = {
                "duration_sec": round(dt, 2),
                "fields": len(res.data),
                "urls": len(res.urls),
                "errors": len(res.errors),
            }
            report["collector_stats"][collector.name] = stats
            report["sources_used"].extend(res.urls)
            report["errors"].extend(f"{collector.name}: {e}" for e in res.errors)
            self.collector_finished.emit(collector.name, stats)
            current_step += 1

            # EGRUL — выбираем лучшее совпадение
            if collector.name == "egrul_nalog":
                matches = res.data.get("matches") or []
                if matches:
                    if is_inn:
                        clean_inn = re.sub(r"\D", "", query)
                        best_match = next(
                            (m for m in matches if m.get("inn") == clean_inn),
                            matches[0],
                        )
                    else:
                        ql = query.lower()
                        def score(m):
                            n = (m.get("full_name") or "").lower()
                            return sum(1 for w in ql.split() if w in n)
                        best_match = max(matches, key=score) if matches else None
                        if best_match is None or score(best_match) == 0:
                            best_match = matches[0]

                    for k, v in best_match.items():
                        if k in ("raw", "extract_token"):
                            continue
                        if v and not report["company"].get(k):
                            report["company"][k] = v
                    report["company"]["all_matches"] = matches[:5]

                    if best_match.get("inn") and not is_inn:
                        secondary_query = best_match["inn"]
                        self.log_message.emit(f"ИНН определён: {secondary_query}")

                    # Deep — скачать PDF выписку
                    if self.deep and best_match.get("extract_token"):
                        self.collector_started.emit("egrul_pdf", best_match.get("inn", ""))
                        self.progress.emit(current_step, total_steps, "→ egrul_pdf (выписка)")
                        t0p = _time.time()
                        try:
                            pres = egrul_pdf_collector.collect_by_token(
                                best_match["extract_token"], best_match.get("inn", "")
                            )
                            dt = _time.time() - t0p
                            stats = {
                                "duration_sec": round(dt, 2),
                                "fields": len(pres.data),
                                "urls": len(pres.urls),
                                "errors": len(pres.errors),
                            }
                            report["collector_stats"]["egrul_nalog_pdf"] = stats
                            report["sources_used"].extend(pres.urls)
                            report["errors"].extend(f"egrul_pdf: {e}" for e in pres.errors)
                            pres.merge_into(report, key="company")
                            self.collector_finished.emit("egrul_pdf", stats)
                        except Exception as e:
                            self.log_message.emit(f"❌ EGRUL PDF упал: {e}")
                            report["errors"].append(f"egrul_pdf: exception {e}")
                        current_step += 1
                continue

            res.merge_into(report, key="company")

        # Определяем отрасль
        okved_main = report["company"].get("okved_main") or ""
        okved_code_match = re.search(r"(\d{2}(?:\.\d{1,3})?)", okved_main)
        okved_code = okved_code_match.group(1) if okved_code_match else ""
        industry = okved_to_industry(okved_code) if okved_code else ""
        if industry:
            report["company"]["industry"] = industry
            report["company"]["okved_code"] = okved_code
            self.log_message.emit(f"Отрасль: {industry} (ОКВЭД {okved_code})")

        # Поиск рынка
        if industry or report["company"].get("full_name"):
            if not self._stop_flag:
                company_name_for_search = (
                    report["company"].get("short_name")
                    or report["company"].get("full_name")
                    or query
                )
                company_short = re.sub(r"^(ООО|АО|ЗАО|ПАО|ИП|ОП)\s+", "", company_name_for_search).strip()

                self.collector_started.emit("market_search", industry)
                self.progress.emit(current_step, total_steps, "→ market_search")
                t0 = _time.time()
                mres = market_collector.collect(company_short, industry_hint=industry, okved_code=okved_code)
                stats = {
                    "duration_sec": round(_time.time() - t0, 2),
                    "fields": len(mres.data),
                    "urls": len(mres.urls),
                    "errors": len(mres.errors),
                }
                report["collector_stats"]["market_search"] = stats
                report["sources_used"].extend(mres.urls)
                report["errors"].extend(f"market: {e}" for e in mres.errors)
                report["market"] = mres.data
                self.collector_finished.emit("market_search", stats)
                current_step += 1

            if not self._stop_flag:
                self.collector_started.emit("rosstat", industry)
                self.progress.emit(current_step, total_steps, "→ rosstat")
                t0 = _time.time()
                rres = rosstat_collector.collect(company_short, industry_hint=industry)
                stats = {
                    "duration_sec": round(_time.time() - t0, 2),
                    "fields": len(rres.data),
                    "urls": len(rres.urls),
                    "errors": len(rres.errors),
                }
                report["collector_stats"]["rosstat"] = stats
                report["sources_used"].extend(rres.urls)
                report["errors"].extend(f"rosstat: {e}" for e in rres.errors)
                if rres.data.get("snippets"):
                    report["market"].setdefault("rosstat_snippets", rres.data["snippets"])
                    report["sources_used"].extend(s.get("url", "") for s in rres.data["snippets"] if s.get("url"))
                self.collector_finished.emit("rosstat", stats)
                current_step += 1

        # Скрапинг сайта
        if self.fetch_site and not self._stop_flag and (report["company"].get("full_name") or query):
            self.collector_started.emit("company_site", "")
            self.progress.emit(current_step, total_steps, "→ company_site")
            t0 = _time.time()
            company_name_for_site = (
                report["company"].get("short_name")
                or report["company"].get("full_name")
                or query
            )
            company_name_for_site = re.sub(
                r"^(ООО|АО|ЗАО|ПАО|ИП|ОП|НКО)\s+", "", company_name_for_site
            ).strip()
            company_name_for_site = " ".join(company_name_for_site.split()[:3])
            try:
                sres = site_collector.collect(query, company_name=company_name_for_site)
                stats = {
                    "duration_sec": round(_time.time() - t0, 2),
                    "fields": len(sres.data),
                    "urls": len(sres.urls),
                    "errors": len(sres.errors),
                }
                report["collector_stats"]["company_site"] = stats
                report["sources_used"].extend(sres.urls)
                report["errors"].extend(f"company_site: {e}" for e in sres.errors)
                if sres.data:
                    report["company_site"] = sres.data
                self.collector_finished.emit("company_site", stats)
            except Exception as e:
                self.log_message.emit(f"❌ company_site упал: {e}")
                report["errors"].append(f"company_site: exception {e}")
            current_step += 1

        # Финансовая пометка
        if any(report["company"].get(k) for k in ("revenue", "profit", "assets", "employees")):
            report["company"].setdefault(
                "finance_caveat",
                "Данные могут быть неполными из-за сложной структуры холдинга. "
                "Рекомендуется проверить аффилированные юрлица.",
            )

        self.progress.emit(total_steps, total_steps, "Готово")
        http.close()
        return report

    def _save_reports(self, report: dict) -> dict:
        """Сохраняет MD/XLSX/JSON и возвращает пути."""
        from utils import slugify
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(self.query)[:50] or "company"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = out_dir / f"{slug}_{ts}"

        paths = {}
        # JSON
        json_path = base.with_suffix(".json")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["json"] = str(json_path)

        # Markdown
        md_path = base.with_suffix(".md")
        md_path.write_text(MarkdownReporter().render(report), encoding="utf-8")
        paths["md"] = str(md_path)

        # Excel
        xlsx_path = base.with_suffix(".xlsx")
        wb = ExcelReporter().render(report)
        wb.save(xlsx_path)
        paths["xlsx"] = str(xlsx_path)

        self.log_message.emit(f"Отчёты сохранены: {base}")
        return paths
