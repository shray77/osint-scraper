#!/usr/bin/env python3
"""
osint_scraper.py — универсальный OSINT-скраппер для российских компаний.

Назначение:
    По названию или ИНН компании собрать профиль (идентификация, базовые
    финансы) и контекст рынка (объём, динамика, топ-игроки).

Источники (v1):
    1. EGRUL — https://egrul.nalog.ru (официальный API ФНС)
    2. Rusprofile — https://www.rusprofile.ru
    3. За честный бизнес — https://zachestnyibiznes.ru
    4. FindCompany — https://www.findcompany.pro
    5. Поиск рыночных данных — DuckDuckGo + парсинг сниппетов
    6. Росстат — поиск по сайту rosstat.gov.ru

Движок:
    requests primary + Playwright fallback (для сайтов с Cloudflare/JS).

Вход:
    --query "Название или ИНН компании"
    Можно несколько: --query "Истринская сыроварня" --query "7710000000000"

Вывод (в /home/z/my-project/download/osint_scraper/output/):
    <slug>_<timestamp>.md   — человекочитаемый отчёт
    <slug>_<timestamp>.xlsx — многолистовая Excel-таблица
    <slug>_<timestamp>.json — сырой JSON (для отладки / интеграции)

Пример:
    python osint_scraper.py --query "Истринская сыроварня"
    python osint_scraper.py --query "5024001844" --enable-playwright
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Импорты из той же папки
from utils import (
    HttpClient,
    looks_like_inn,
    okved_to_industry,
    slugify,
    validate_inn,
    validate_ogrn,
    HAS_PLAYWRIGHT,
)
from collectors import (
    BaseCollector,
    CollectorResult,
    CompanySiteCollector,
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

# Логи
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("osint.main")

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class OSINTOrchestrator:
    """Связывает коллекторы, нормализует данные, готовит отчёт."""

    def __init__(self, http: HttpClient, deep: bool = False, fetch_site: bool = True):
        self.http = http
        self.deep = deep
        self.fetch_site = fetch_site
        # Порядок имеет значение: сначала EGRUL (точный ИНН),
        # потом PDF выписка (если deep) — даёт ОКВЭД/адрес/учредителей,
        # потом агрегаторы (дополняют фин. данные).
        self.collectors: list[BaseCollector] = [
            NalogEGRULCollector(http),
            RusprofileCollector(http),
            ZacheBiznesCollector(http),
            ListOrgCollector(http),
            FindCompanyCollector(http),  # legacy (domain down) — оставлен для совместимости
        ]
        self.egrul_pdf_collector = NalogEgrulPdfCollector(http)
        self.market_collector = MarketSearchCollector(http)
        self.rosstat_collector = RosstatCollector(http)
        self.site_collector = CompanySiteCollector(http)

    def run(self, query: str) -> dict:
        report = {
            "company_input": query,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "company": {},
            "market": {},
            "sources_used": [],
            "errors": [],
            "collector_stats": {},
        }

        is_inn = looks_like_inn(query)
        logger.info("Запрос: %s (is_inn=%s)", query, is_inn)

        # 1. EGRUL идёт первым — даёт authoritative ИНН/ОГРН
        best_match = None
        secondary_query = query  # для последующих коллекторов

        for collector in self.collectors:
            logger.info("→ %s (query=%s)", collector.name, secondary_query)
            t0 = time.time()
            try:
                res: CollectorResult = collector.collect(secondary_query)
            except Exception as e:
                logger.exception("collector %s failed", collector.name)
                report["errors"].append(f"{collector.name}: exception {e}")
                continue
            dt = time.time() - t0
            report["collector_stats"][collector.name] = {
                "duration_sec": round(dt, 2),
                "fields": len(res.data),
                "urls": len(res.urls),
                "errors": len(res.errors),
            }
            report["sources_used"].extend(res.urls)
            report["errors"].extend(f"{collector.name}: {e}" for e in res.errors)

            # EGRUL — даёт список matches, выбираем лучшего
            if collector.name == "egrul_nalog":
                matches = res.data.get("matches") or []
                if matches:
                    # Если ввели ИНН — точное совпадение по ИНН; иначе первый
                    if is_inn:
                        clean_inn = re.sub(r"\D", "", query)
                        best_match = next(
                            (m for m in matches if m.get("inn") == clean_inn),
                            matches[0],
                        )
                    else:
                        # Если ввели название — выбираем наиболее релевантный матч
                        # по совпадению слов запроса в полном имени
                        ql = query.lower()
                        def score(m):
                            n = (m.get("full_name") or "").lower()
                            return sum(1 for w in ql.split() if w in n)
                        best_match = max(matches, key=score) if matches else None
                        # Если лучший скоринг 0 — берём первого (возможно, не нашлось)
                        if best_match is None or score(best_match) == 0:
                            best_match = matches[0]

                    # Заполняем базовый профиль
                    for k, v in best_match.items():
                        if k in ("raw", "extract_token"):
                            continue
                        if v and not report["company"].get(k):
                            report["company"][k] = v
                    # Сохраняем все совпадения — пригодится для disambiguation
                    report["company"]["all_matches"] = matches[:5]

                    # Если у нас появился ИНН — последующие коллекторы пойдут по ИНН (точнее)
                    if best_match.get("inn") and not is_inn:
                        secondary_query = best_match["inn"]
                        logger.info("EGRUL дал ИНН=%s — переключаемся на поиск по ИНН", secondary_query)

                    # Deep-режим: скачать PDF выписку и распарсить ОКВЭД/адрес/учредителей
                    if self.deep and best_match.get("extract_token"):
                        logger.info("→ egrul_pdf (скачиваем выписку)")
                        t0p = time.time()
                        try:
                            pres = self.egrul_pdf_collector.collect_by_token(
                                best_match["extract_token"], best_match.get("inn", "")
                            )
                            dt = time.time() - t0p
                            report["collector_stats"]["egrul_nalog_pdf"] = {
                                "duration_sec": round(dt, 2),
                                "fields": len(pres.data),
                                "urls": len(pres.urls),
                                "errors": len(pres.errors),
                            }
                            report["sources_used"].extend(pres.urls)
                            report["errors"].extend(f"egrul_pdf: {e}" for e in pres.errors)
                            pres.merge_into(report, key="company")
                        except Exception as e:
                            logger.exception("EGRUL PDF failed")
                            report["errors"].append(f"egrul_pdf: exception {e}")
                continue

            # Прочие коллекторы — мёрджим данные
            res.merge_into(report, key="company")

        # 2. Определяем отрасль по ОКВЭД
        okved_main = report["company"].get("okved_main") or ""
        # Убираем числовую часть ОКВЭД, если она отдельно
        okved_code_match = re.search(r"(\d{2}(?:\.\d{1,3})?)", okved_main)
        okved_code = okved_code_match.group(1) if okved_code_match else ""
        industry = okved_to_industry(okved_code) if okved_code else ""
        if industry:
            report["company"]["industry"] = industry
            report["company"]["okved_code"] = okved_code
            logger.info("Отрасль определена: %s (по ОКВЭД %s)", industry, okved_code)
        else:
            # Если ОКВЭД не удалось извлечь — спросим пользователя
            logger.warning("Не удалось определить отрасль по ОКВЭД — поиск рынка будет общий")

        # 3. Поиск рыночных данных
        if industry or report["company"].get("full_name"):
            company_name_for_search = (
                report["company"].get("short_name")
                or report["company"].get("full_name")
                or query
            )
            # Только название без форм (ООО/АО), чтобы поиск был чище
            company_short = re.sub(r"^(ООО|АО|ЗАО|ПАО|ИП|ОП)\s+", "", company_name_for_search).strip()

            logger.info("→ market_search (industry=%s)", industry)
            t0 = time.time()
            okved_code = report["company"].get("okved_code", "")
            mres = self.market_collector.collect(company_short, industry_hint=industry, okved_code=okved_code)
            report["collector_stats"]["market_search"] = {
                "duration_sec": round(time.time() - t0, 2),
                "fields": len(mres.data),
                "urls": len(mres.urls),
                "errors": len(mres.errors),
            }
            report["sources_used"].extend(mres.urls)
            report["errors"].extend(f"market: {e}" for e in mres.errors)
            report["market"] = mres.data

            logger.info("→ rosstat")
            t0 = time.time()
            rres = self.rosstat_collector.collect(company_short, industry_hint=industry)
            report["collector_stats"]["rosstat"] = {
                "duration_sec": round(time.time() - t0, 2),
                "fields": len(rres.data),
                "urls": len(rres.urls),
                "errors": len(rres.errors),
            }
            report["sources_used"].extend(rres.urls)
            report["errors"].extend(f"rosstat: {e}" for e in rres.errors)
            # Добавляем сниппеты росстата в market.rosstat_snippets
            if rres.data.get("snippets"):
                report["market"].setdefault("rosstat_snippets", rres.data["snippets"])
                report["sources_used"].extend(s.get("url", "") for s in rres.data["snippets"] if s.get("url"))

        # 4. Скрапинг сайта компании (если включён)
        if self.fetch_site and (report["company"].get("full_name") or query):
            logger.info("→ company_site")
            t0 = time.time()
            company_name_for_site = (
                report["company"].get("short_name")
                or report["company"].get("full_name")
                or query
            )
            # Уберём формы собственности
            company_name_for_site = re.sub(
                r"^(ООО|АО|ЗАО|ПАО|ИП|ОП|НКО)\s+", "", company_name_for_site
            ).strip()
            # Возьмём только первые 2-3 слова, чтобы поиск был точнее
            company_name_for_site = " ".join(company_name_for_site.split()[:3])

            try:
                sres = self.site_collector.collect(query, company_name=company_name_for_site)
                report["collector_stats"]["company_site"] = {
                    "duration_sec": round(time.time() - t0, 2),
                    "fields": len(sres.data),
                    "urls": len(sres.urls),
                    "errors": len(sres.errors),
                }
                report["sources_used"].extend(sres.urls)
                report["errors"].extend(f"company_site: {e}" for e in sres.errors)
                if sres.data:
                    report["company_site"] = sres.data
            except Exception as e:
                logger.exception("CompanySite failed")
                report["errors"].append(f"company_site: exception {e}")

        # 4. Финансовая пометка (если есть хоть какие-то финансы)
        if any(report["company"].get(k) for k in ("revenue", "profit", "assets", "employees")):
            report["company"].setdefault(
                "finance_caveat",
                "Данные могут быть неполными из-за сложной структуры холдинга. Рекомендуется проверить аффилированные юрлица.",
            )

        return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Универсальный OSINT-скраппер для российских компаний",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--query", "-q", action="append", required=True,
                   help="Название компании или ИНН (можно несколько раз)")
    p.add_argument("--output-dir", "-o", default=str(OUTPUT_DIR),
                   help=f"Каталог для выходных файлов (по умолчанию {OUTPUT_DIR})")
    p.add_argument("--enable-playwright", action="store_true", default=True,
                   help="Включить Playwright fallback для JS/Cloudflare-сайтов")
    p.add_argument("--no-playwright", dest="enable_playwright", action="store_false",
                   help="Отключить Playwright (только requests)")
    p.add_argument("--no-cache", action="store_true",
                   help="Отключить файловое кэширование")
    p.add_argument("--deep", action="store_true",
                   help="Скачивать PDF-выписку из ЕГРЮЛ (даёт ОКВЭД, адрес, учредителей, "
                        "уставный капитал) — медленнее, но полнее. Требует pdftotext.")
    p.add_argument("--no-site", dest="fetch_site", action="store_false", default=True,
                   help="Не скрапить сайт компании (иначе ищется через Bing и тянется главная)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Подробное логирование (DEBUG)")
    return p.parse_args()


def main():
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.enable_playwright and not HAS_PLAYWRIGHT:
        logger.warning(
            "Playwright не установлен. Установите: pip install playwright && playwright install chromium"
        )

    http = HttpClient(
        use_cache=not args.no_cache,
        enable_playwright=args.enable_playwright,
    )

    orchestrator = OSINTOrchestrator(http, deep=args.deep, fetch_site=args.fetch_site)

    md_reporter = MarkdownReporter()
    xl_reporter = ExcelReporter()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for query in args.query:
        logger.info("=" * 60)
        logger.info("Обрабатываем: %s", query)
        logger.info("=" * 60)
        report = orchestrator.run(query)

        slug = slugify(query)[:50] or "company"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = out_dir / f"{slug}_{ts}"

        # JSON (сырой)
        json_path = base.with_suffix(".json")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("JSON: %s", json_path)

        # Markdown
        md_path = base.with_suffix(".md")
        md_path.write_text(md_reporter.render(report), encoding="utf-8")
        logger.info("Markdown: %s", md_path)

        # Excel
        xlsx_path = base.with_suffix(".xlsx")
        wb = xl_reporter.render(report)
        wb.save(xlsx_path)
        logger.info("Excel: %s", xlsx_path)

        # Краткий stdout-вывод
        print()
        print("=" * 60)
        print(f"  Запрос: {query}")
        print("=" * 60)
        c = report.get("company", {})
        if c.get("full_name"):
            print(f"  Компания:     {c['full_name']}")
        if c.get("inn"):
            print(f"  ИНН:          {c['inn']}")
            print(f"  ОГРН:         {c.get('ogrn', '—')}")
        if c.get("registration_date"):
            print(f"  Регистрация:  {c['registration_date']}")
        if c.get("okved_main"):
            print(f"  ОКВЭД:        {c['okved_main']}")
        if c.get("industry"):
            print(f"  Отрасль:      {c['industry']}")
        m = report.get("market", {})
        if m.get("market_size_candidates"):
            print(f"  Рынок:        найдено {len(m['market_size_candidates'])} оценок объёма")
        else:
            print("  Рынок:        оценки объёма не найдены")
        print(f"  Источники:    {len(report.get('sources_used', []))} URL")
        print(f"  Ошибки:       {len(report.get('errors', []))}")
        print()
        print(f"  → {md_path}")
        print(f"  → {xlsx_path}")
        print(f"  → {json_path}")
        print()

    http.close()


if __name__ == "__main__":
    main()
