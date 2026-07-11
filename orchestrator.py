"""orchestrator.py — единая точка правды для OSINT-сбора (v1.3).

Используется CLI (osint_scraper.py) и GUI (gui/workers.py) через callback-интерфейс.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from utils import HttpClient, looks_like_inn, okved_to_industry, slugify
from collectors import (
    BaseCollector, BoNalogCollector, CheckoCollector, CollectorResult,
    CompanySiteCollector, FindCompanyCollector, ListOrgCollector,
    MarketSearchCollector, NalogEGRULCollector, NalogEgrulPdfCollector,
    RosstatCollector, RusprofileCollector, ZacheBiznesCollector,
)
from reporters import ExcelReporter, MarkdownReporter, CsvReporter

logger = logging.getLogger("osint.orchestrator")

ProgressCallback = Callable[[int, int, str], None]
LogCallback = Callable[[str], None]
CollectorStartedCallback = Callable[[str, str], None]
CollectorFinishedCallback = Callable[[str, dict], None]


class OSINTOrchestrator:
    """Связывает коллекторы, нормализует данные, готовит отчёт."""

    def __init__(
        self,
        http: HttpClient,
        deep: bool = False,
        fetch_site: bool = True,
        skip_cloudflare_blocked: bool = True,
    ):
        self.http = http
        self.deep = deep
        self.fetch_site = fetch_site
        self.skip_cloudflare_blocked = skip_cloudflare_blocked

        self.collectors: list[BaseCollector] = [NalogEGRULCollector(http)]
        if not skip_cloudflare_blocked:
            self.collectors.append(RusprofileCollector(http))
            self.collectors.append(ZacheBiznesCollector(http))
        self.collectors.append(ListOrgCollector(http))
        self.collectors.append(CheckoCollector(http))

        self.bfo_collector = BoNalogCollector(http)
        self.egrul_pdf_collector = NalogEgrulPdfCollector(http)
        self.market_collector = MarketSearchCollector(http)
        self.rosstat_collector = RosstatCollector(http)
        self.site_collector = CompanySiteCollector(http)

    def run(
        self,
        query: str,
        on_collector_started: Optional[CollectorStartedCallback] = None,
        on_collector_finished: Optional[CollectorFinishedCallback] = None,
        on_progress: Optional[ProgressCallback] = None,
        on_log: Optional[LogCallback] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ) -> dict:
        def _log(msg):
            logger.info(msg)
            if on_log:
                on_log(msg)

        def _started(name, q=""):
            if on_collector_started:
                on_collector_started(name, q)

        def _finished(name, stats):
            if on_collector_finished:
                on_collector_finished(name, stats)

        def _progress(cur, total, msg):
            if on_progress:
                on_progress(cur, total, msg)

        def _stopped():
            return stop_flag() if stop_flag else False

        is_inn = looks_like_inn(query)
        _log(f"=== Запрос: {query} (is_inn={is_inn}) ===")

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

        total_steps = len(self.collectors) + 1
        if self.deep:
            total_steps += 1
        total_steps += 2
        if self.fetch_site:
            total_steps += 1
        current_step = 0

        best_match = None
        secondary_query = query

        for collector in self.collectors:
            if _stopped():
                break
            _started(collector.name, secondary_query)
            _progress(current_step, total_steps, f"→ {collector.name}")
            t0 = time.time()
            try:
                res = collector.collect(secondary_query)
            except Exception as e:
                _log(f"❌ {collector.name} упал: {e}")
                report["errors"].append(f"{collector.name}: exception {e}")
                continue
            dt = time.time() - t0
            stats = {
                "duration_sec": round(dt, 2),
                "fields": len(res.data),
                "urls": len(res.urls),
                "errors": len(res.errors),
            }
            report["collector_stats"][collector.name] = stats
            report["sources_used"].extend(res.urls)
            report["errors"].extend(f"{collector.name}: {e}" for e in res.errors)
            _finished(collector.name, stats)
            current_step += 1

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
                        _log(f"ИНН определён: {secondary_query}")

                    if self.deep and best_match.get("extract_token"):
                        _started("egrul_pdf", best_match.get("inn", ""))
                        _progress(current_step, total_steps, "→ egrul_pdf (выписка)")
                        t0p = time.time()
                        try:
                            pres = self.egrul_pdf_collector.collect_by_token(
                                best_match["extract_token"], best_match.get("inn", "")
                            )
                            dt = time.time() - t0p
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
                            _finished("egrul_pdf", stats)
                        except Exception as e:
                            _log(f"❌ EGRUL PDF упал: {e}")
                            report["errors"].append(f"egrul_pdf: exception {e}")
                        current_step += 1
                continue

            res.merge_into(report, key="company")

        # bo.nalog.gov.ru
        if not _stopped() and secondary_query and looks_like_inn(secondary_query):
            _started("bo_nalog", secondary_query)
            _progress(current_step, total_steps, "→ bo_nalog (БФО)")
            t0 = time.time()
            try:
                bres = self.bfo_collector.collect(secondary_query)
                dt = time.time() - t0
                stats = {
                    "duration_sec": round(dt, 2),
                    "fields": len(bres.data),
                    "urls": len(bres.urls),
                    "errors": len(bres.errors),
                }
                report["collector_stats"]["bo_nalog"] = stats
                report["sources_used"].extend(bres.urls)
                report["errors"].extend(f"bo_nalog: {e}" for e in bres.errors)
                bres.merge_into(report, key="company")
                _finished("bo_nalog", stats)
            except Exception as e:
                _log(f"❌ bo_nalog упал: {e}")
                report["errors"].append(f"bo_nalog: exception {e}")
            current_step += 1

        # Отрасль по ОКВЭД
        okved_main = report["company"].get("okved_main") or ""
        okved_code_match = re.search(r"(\d{2}(?:\.\d{1,3})?)", okved_main)
        okved_code = okved_code_match.group(1) if okved_code_match else ""
        industry = okved_to_industry(okved_code) if okved_code else ""
        if industry:
            report["company"]["industry"] = industry
            report["company"]["okved_code"] = okved_code
            _log(f"Отрасль: {industry} (ОКВЭД {okved_code})")

        # Рынок
        if not _stopped() and (industry or report["company"].get("full_name")):
            company_name_for_search = (
                report["company"].get("short_name")
                or report["company"].get("full_name")
                or query
            )
            company_short = re.sub(r"^(ООО|АО|ЗАО|ПАО|ИП|ОП)\s+", "", company_name_for_search).strip()

            _started("market_search", industry)
            _progress(current_step, total_steps, "→ market_search")
            t0 = time.time()
            mres = self.market_collector.collect(company_short, industry_hint=industry, okved_code=okved_code)
            stats = {
                "duration_sec": round(time.time() - t0, 2),
                "fields": len(mres.data),
                "urls": len(mres.urls),
                "errors": len(mres.errors),
            }
            report["collector_stats"]["market_search"] = stats
            report["sources_used"].extend(mres.urls)
            report["errors"].extend(f"market: {e}" for e in mres.errors)
            report["market"] = mres.data
            _finished("market_search", stats)
            current_step += 1

            if not _stopped():
                _started("rosstat", industry)
                _progress(current_step, total_steps, "→ rosstat")
                t0 = time.time()
                rres = self.rosstat_collector.collect(company_short, industry_hint=industry)
                stats = {
                    "duration_sec": round(time.time() - t0, 2),
                    "fields": len(rres.data),
                    "urls": len(rres.urls),
                    "errors": len(rres.errors),
                }
                report["collector_stats"]["rosstat"] = stats
                report["sources_used"].extend(rres.urls)
                report["errors"].extend(f"rosstat: {e}" for e in rres.errors)
                if rres.data.get("snippets"):
                    report["market"].setdefault("rosstat_snippets", rres.data["snippets"])
                    report["sources_used"].extend(
                        s.get("url", "") for s in rres.data["snippets"] if s.get("url")
                    )
                _finished("rosstat", stats)
                current_step += 1

        # Сайт компании
        if not _stopped() and self.fetch_site and (report["company"].get("full_name") or query):
            _started("company_site", "")
            _progress(current_step, total_steps, "→ company_site")
            t0 = time.time()
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
                sres = self.site_collector.collect(query, company_name=company_name_for_site)
                stats = {
                    "duration_sec": round(time.time() - t0, 2),
                    "fields": len(sres.data),
                    "urls": len(sres.urls),
                    "errors": len(sres.errors),
                }
                report["collector_stats"]["company_site"] = stats
                report["sources_used"].extend(sres.urls)
                report["errors"].extend(f"company_site: {e}" for e in sres.errors)
                if sres.data:
                    report["company_site"] = sres.data
                _finished("company_site", stats)
            except Exception as e:
                _log(f"❌ company_site упал: {e}")
                report["errors"].append(f"company_site: exception {e}")
            current_step += 1

        if any(report["company"].get(k) for k in ("revenue", "profit", "assets", "employees")):
            report["company"].setdefault(
                "finance_caveat",
                "Данные могут быть неполными из-за сложной структуры холдинга. "
                "Финансовые показатели — из bo.nalog.gov.ru (БФО)."
            )

        _progress(total_steps, total_steps, "Готово")
        return report


def save_reports(report: dict, output_dir: str, query: str) -> dict:
    """Сохраняет MD/XLSX/CSV/JSON."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(query)[:50] or "company"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = out_dir / f"{slug}_{ts}"

    paths = {}

    json_path = base.with_suffix(".json")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    paths["json"] = str(json_path)

    md_path = base.with_suffix(".md")
    md_path.write_text(MarkdownReporter().render(report), encoding="utf-8")
    paths["md"] = str(md_path)

    xlsx_path = base.with_suffix(".xlsx")
    wb = ExcelReporter().render(report)
    wb.save(xlsx_path)
    paths["xlsx"] = str(xlsx_path)

    csv_path = base.with_suffix(".csv")
    CsvReporter().save(report, csv_path)
    paths["csv"] = str(csv_path)

    return paths
