"""
collectors.py — сборщики данных из открытых источников.

Каждый коллектор наследуется от BaseCollector и реализует collect(input).
Возвращает dict с нормализованными полями + список использованных URL'ов.

Источники:
1. NalogEGRULCollector  — https://egrul.nalog.ru (официальный API ФНС)
2. RusprofileCollector  — https://www.rusprofile.ru
3. ZacheBiznesCollector — https://zachestnyibiznes.ru
4. FindCompanyCollector — https://www.findcompany.pro
5. MarketSearchCollector — поиск по сниппетам через DuckDuckGo + выборка ключевых метрик
6. RosstatCollector      — Росстат, отраслевые страницы (для рынка)

Все коллекторы устойчивы к ошибкам: если источник недоступен или парсинг
сломан — возвращают пустой dict, но не падают. Все ошибки логируются.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote_plus, urljoin

from utils import (
    HttpClient,
    clean_text,
    duckduckgo_search,
    looks_like_inn,
    okved_to_industry,
    parse_date,
    parse_int,
    parse_money,
    validate_inn,
)

logger = logging.getLogger("osint.collectors")


@dataclass
class CollectorResult:
    source: str
    data: dict = field(default_factory=dict)
    urls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def merge_into(self, target: dict, key: Optional[str] = None) -> None:
        """Сливает данные в target, перезаписывая только пустые поля."""
        bucket = target if key is None else target.setdefault(key, {})
        for k, v in self.data.items():
            if v is None:
                continue
            if k not in bucket or bucket[k] in (None, "", [], {}):
                bucket[k] = v


class BaseCollector:
    name: str = "base"

    def __init__(self, client: HttpClient):
        self.client = client

    def collect(self, query: str) -> CollectorResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 1. Nalog.ru EGRUL (официальный API ФНС)
# ---------------------------------------------------------------------------
# Эндпоинты (актуальны на 2025-2026):
# POST https://egrul.nalog.ru/  form-data: query, region, PreventChrome
#   -> {"t": "<token>", "captchaRequired": false}
# GET  https://egrul.nalog.ru/search-result/<token>?r=<ts>
#   -> {"rows": [{"o","i","n","b","c","k","g","r","e","rn","p","t","cnt"}]}
# Поля ответа:
#   c — краткое наименование
#   n — полное наименование
#   i — ИНН
#   o — ОГРН
#   p — КПП
#   g — должность + ФИО руководителя (например, "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР: Сирота ...")
#   r — дата регистрации
#   e — дата ликвидации (если есть; иначе компания действующая)
#   rn — регион
#   t — токен для запроса выписки PDF
#   cnt — общее количество найденных записей
class NalogEGRULCollector(BaseCollector):
    name = "egrul_nalog"

    BASE = "https://egrul.nalog.ru"

    def collect(self, query: str) -> CollectorResult:
        res = CollectorResult(source=self.name)
        try:
            # 1. POST form-data для получения токена поиска
            r = self.client.post(
                f"{self.BASE}/",
                data={"query": query, "region": "", "PreventChrome": "1"},
                headers={
                    "Referer": f"{self.BASE}/index.html",
                    "Origin": self.BASE,
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            if not r.ok:
                res.errors.append(f"token_request_failed: status={r.status}")
                return res
            try:
                token_data = json.loads(r.text)
            except json.JSONDecodeError as e:
                res.errors.append(f"token_json_decode: {e}")
                return res

            token = token_data.get("t")
            if not token:
                res.errors.append("no_token_returned (возможно капча или блок)")
                return res

            if token_data.get("captchaRequired"):
                res.errors.append("captcha_required (ФНС запросила капчу)")

            # 2. Опрос search-result/<token>
            import time as _t
            rows = None
            for attempt in range(10):
                _t.sleep(0.8 + 0.3 * attempt)
                rs = self.client.get(
                    f"{self.BASE}/search-result/{token}?r={int(_t.time() * 1000)}",
                    headers={
                        "Referer": f"{self.BASE}/index.html",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
                if not rs.ok:
                    res.errors.append(f"search_result_failed: status={rs.status}")
                    return res
                try:
                    sj = json.loads(rs.text)
                except json.JSONDecodeError:
                    res.errors.append("search_result_json_decode")
                    return res
                rows = sj.get("rows")
                if rows:
                    break

            if not rows:
                res.errors.append("no_rows_matched")
                return res

            res.urls.append(f"{self.BASE}/index.html?query={quote_plus(query)}")
            res.data["total_count"] = rows[0].get("cnt") or str(len(rows))
            res.data["matches"] = []
            for row in rows[:15]:
                director = row.get("g") or ""
                # "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР: ФИО" → разделяем
                director_role = ""
                director_name = director
                if ":" in director:
                    parts = director.split(":", 1)
                    director_role = clean_text(parts[0])
                    director_name = clean_text(parts[1])
                liquidation = parse_date(row.get("e") or "")
                match = {
                    "full_name": clean_text(row.get("n") or ""),
                    "short_name": clean_text(row.get("c") or ""),
                    "inn": row.get("i") or "",
                    "ogrn": row.get("o") or "",
                    "kpp": row.get("p") or "",
                    "region": clean_text(row.get("rn") or ""),
                    "registration_date": parse_date(row.get("r") or ""),
                    "director_role": director_role,
                    "director": director_name,
                    "liquidation_date": liquidation,
                    "status": "ликвидировано" if liquidation else "действует",
                    "extract_token": row.get("t") or "",
                }
                res.data["matches"].append(match)
            return res
        except Exception as e:
            logger.exception("NalogEGRUL error")
            res.errors.append(f"exception: {e}")
        return res


# ---------------------------------------------------------------------------
# 1b. EGRUL PDF выписка (скачивание + парсинг pdftotext)
# ---------------------------------------------------------------------------
# Если у нас есть extract_token от NalogEGRUL, можно скачать PDF выписку
# и распарсить из неё: юр. адрес, ОКВЭД, учредителей, уставный капитал.
# Это медленно (~5-10 сек на компанию), но даёт самую полную информацию.
class NalogEgrulPdfCollector(BaseCollector):
    name = "egrul_nalog_pdf"

    BASE = "https://egrul.nalog.ru"

    def collect_by_token(self, extract_token: str, query_inn: str = "") -> CollectorResult:
        """Скачивает PDF выписку по токену из EGRUL search-result и парсит её."""
        res = CollectorResult(source=self.name)
        try:
            import subprocess
            import tempfile
            from pathlib import Path

            # 1. Запросить подготовку выписки (vyp-request/<token>)
            r_req = self.client.get(
                f"{self.BASE}/vyp-request/{extract_token}?r={int(__import__('time').time() * 1000)}",
                headers={
                    "Referer": f"{self.BASE}/index.html",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            # 2. Опрос vyp-status пока не станет ready
            import time as _t
            ready = False
            for _ in range(15):
                _t.sleep(1.0)
                r_st = self.client.get(
                    f"{self.BASE}/vyp-status/{extract_token}?r={int(_t.time() * 1000)}",
                    headers={
                        "Referer": f"{self.BASE}/index.html",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
                if not r_st.ok:
                    res.errors.append(f"vyp_status_failed: {r_st.status}")
                    return res
                try:
                    sj = json.loads(r_st.text)
                except json.JSONDecodeError:
                    res.errors.append("vyp_status_json_decode")
                    return res
                if sj.get("status") == "ready":
                    ready = True
                    break

            if not ready:
                res.errors.append("vyp_status_timeout")
                return res

            # 3. Скачать PDF — это бинарный контент, используем прямой requests
            import requests as _rq
            pdf_bytes = None
            try:
                rraw = _rq.get(
                    f"{self.BASE}/vyp-download/{extract_token}",
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0",
                        "Referer": f"{self.BASE}/index.html",
                    },
                    timeout=30,
                    allow_redirects=True,
                )
                if rraw.content.startswith(b"%PDF"):
                    pdf_bytes = rraw.content
                else:
                    res.errors.append(f"pdf_not_pdf: first_bytes={rraw.content[:30]!r}")
            except Exception as e:
                pdf_bytes = None
                res.errors.append(f"pdf_download_failed: {e}")

            if not pdf_bytes:
                res.errors.append("pdf_empty")
                return res

            # 4. Сохранить во временный файл и распарсить через pdftotext
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                tf.write(pdf_bytes)
                pdf_path = tf.name
            txt_path = pdf_path.replace(".pdf", ".txt")
            try:
                subprocess.run(
                    ["pdftotext", "-layout", pdf_path, txt_path],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
            except subprocess.CalledProcessError as e:
                res.errors.append(f"pdftotext_failed: {e.stderr[:200] if e.stderr else ''}")
                return res
            except FileNotFoundError:
                res.errors.append("pdftotext_not_installed (apt install poppler-utils)")
                return res

            text = Path(txt_path).read_text(encoding="utf-8", errors="ignore")
            self._parse_extract_text(text, res)

            # Сохраняем PDF-копию в кэш для аудита
            res.data["_pdf_size"] = len(pdf_bytes)
            res.urls.append(f"{self.BASE}/vyp-download/{extract_token[:32]}...")

            # Чистим временные файлы
            try:
                Path(pdf_path).unlink()
                Path(txt_path).unlink()
            except Exception:
                pass

        except Exception as e:
            logger.exception("EgrulPdf error")
            res.errors.append(f"exception: {e}")
        return res

    def _parse_extract_text(self, text: str, res: CollectorResult):
        """Парсит текст PDF выписки ЕГРЮЛ."""
        # Юридический адрес — после "Адрес юридического лица"
        m = re.search(r"Адрес юридического лица\s*?\d+\s*?(?:ГРН.*?\n.*?\n)?\s*?((?:\d{6},)?.+?)(?=\s*\d+\s+ГРН|\s+Сведения)", text, re.DOTALL)
        if m:
            addr = clean_text(m.group(1)).replace("\n", ", ")
            # Убираем переносы в строках адреса
            addr = re.sub(r",\s*,", ",", addr)
            res.data.setdefault("legal_address", addr)

        # ОКВЭД — парсим по маркеру "Код и наименование вида деятельности"
        # Формат в PDF: "42 Код и наименование вида деятельности  69.20.2 Деятельность по оказанию услуг в\n  области бухгалтерского учета"
        # Поле 42 — основной ОКВЭД, 44/46/48/... — дополнительные
        okved_main = ""
        okved_all = []
        # Найдём все вхождения "Код и наименование вида деятельности" с последующим кодом
        for m in re.finditer(
            r"Код\s+и\s+наименование\s+вида\s+деятельности\s+(\d{2}\.\d{1,2}(?:\.\d{1,2})?)\s+(.+?)(?=\s+\d{2,3}\s+(?:ГРН|Код\s+и\s+наименование)|Сведения|Выписка\s+из\s+ЕГРЮЛ|\Z)",
            text,
            re.DOTALL,
        ):
            code = m.group(1)
            name = re.sub(r"\s+", " ", m.group(2)).strip()
            # Уберём trailing числа (номера полей)
            name = re.sub(r"\s+\d{1,3}$", "", name).strip()
            # Уберём colontitul ("Выписка из ЕГРЮЛ ..." и "Страница N из M")
            name = re.split(r"Выписка\s+из\s+ЕГРЮЛ|Страница\s+\d", name)[0].strip()
            if name and len(name) > 3:
                full = f"{code} {name}"
                if not okved_main:
                    okved_main = full
                if full not in okved_all:
                    okved_all.append(full)
        if okved_main:
            res.data.setdefault("okved_main", okved_main)
        if okved_all:
            res.data.setdefault("okved_all", okved_all[:15])

        # Уставный капитал
        m = re.search(r"Сведения о размер[ае]\s.*?уставн[а-яё]+\s*капитал[а-яё]*\s*\n.*?\n.*?(\d[\d\s.,]*\s*(?:рублей|руб\.?|₽))", text, re.IGNORECASE | re.DOTALL)
        if m:
            res.data.setdefault("authorized_capital", clean_text(m.group(1)))

        # Учредители — ищем секцию "Сведения об учредителях"
        founders = []
        fsection_match = re.search(r"Сведения об учредител[а-яё]+[\s\S]{0,5000}?(?=\s*Сведения о держателе реестра|\Z)", text)
        if fsection_match:
            fsection = fsection_match.group(0)
            # ФИО физлица или наименование юрлица
            for m in re.finditer(r"(?:Фамилия, имя, отчество|Полное наименование)\s*([^\n]+(?:\n[^\n\d]{5,80})?)", fsection):
                name = clean_text(m.group(1)).split("\n")[0]
                if name and len(name) < 200 and name not in founders:
                    founders.append(name)
        if founders:
            res.data.setdefault("founders", founders[:10])

        res.data.setdefault("finance_caveat",
            "Данные могут быть неполными из-за сложной структуры холдинга. "
            "Рекомендуется проверить аффилированные юрлица."
        )

    def collect(self, query: str) -> CollectorResult:
        """Не используется напрямую — вызывается через collect_by_token."""
        return CollectorResult(source=self.name, errors=["use collect_by_token instead"])


# ---------------------------------------------------------------------------
# 2. Rusprofile.ru
# ---------------------------------------------------------------------------
class RusprofileCollector(BaseCollector):
    name = "rusprofile"

    BASE = "https://www.rusprofile.ru"

    def collect(self, query: str) -> CollectorResult:
        res = CollectorResult(source=self.name)
        try:
            # Поиск
            search_url = f"{self.BASE}/search?query={quote_plus(query)}&type=ul"
            r = self.client.get(search_url, force_playwright=True, headers={"Referer": self.BASE})
            res.urls.append(search_url)
            if not r.ok:
                res.errors.append(f"search_request_failed: status={r.status}")
                return res

            # Cloudflare/DDoS-Guard страницы могут вернуть 200 с пустым/коротким телом
            if len(r.text) < 1500 and ("cloudflare" in r.text.lower() or "ddos-guard" in r.text.lower()):
                res.errors.append("blocked_by_waf (Cloudflare/DDoS-Guard)")
                return res

            soup = r.soup()

            # Сначала ищем прямую карточку на странице поиска
            # или ссылку на карточку первой компании
            company_card_link = None
            for a in soup.select("a"):
                href = a.get("href", "")
                if href.startswith("/id/") or re.match(r"/id/\d+", href):
                    company_card_link = urljoin(self.BASE, href)
                    break

            if company_card_link:
                # Тянем карточку
                rc = self.client.get(company_card_link, force_playwright=True, headers={"Referer": self.BASE})
                res.urls.append(company_card_link)
                if rc.ok:
                    self._parse_company_page(rc.soup(), res)
                    return res
                else:
                    res.errors.append(f"company_card_failed: {rc.status}")
                    return res

            # Если прямой ссылки нет — попробуем распарсить поиск напрямую
            self._parse_company_page(soup, res)
        except Exception as e:
            logger.exception("Rusprofile error")
            res.errors.append(f"exception: {e}")
        return res

    def _parse_company_page(self, soup, res: CollectorResult):
        # Заголовок — полное наименование
        h1 = soup.select_one("h1, .company-name, .header-name")
        if h1:
            res.data.setdefault("full_name", clean_text(h1.get_text()))

        # Базовые блоки: ИНН/ОГРН/КПП
        text = soup.get_text(" ", strip=True)
        for label, key in [
            ("ИНН", "inn"), ("ОГРН", "ogrn"), ("КПП", "kpp"),
            ("Дата регистрации", "registration_date"),
            ("Юридический адрес", "legal_address"),
            ("Руководитель", "director"), ("Директор", "director"),
            ("Учредитель", "founder"),
            ("Основной ОКВЭД", "okved_main"),
            ("Уставный капитал", "authorized_capital"),
            ("Статус", "status"),
            ("Среднесписочная численность", "employees"),
            ("Выручка", "revenue"), ("Чистая прибыль", "profit"),
            ("Стоимость активов", "assets"),
        ]:
            # Ищем паттерн вида "ИНН  1234567890"
            m = re.search(rf"{re.escape(label)}\s*[:：]?\s*([^\n\r•|]+?)(?:\s{{2,}}|$|•|\|)", text)
            if m:
                val = clean_text(m.group(1))
                if val and val.lower() not in ("—", "-", "нет данных"):
                    res.data.setdefault(key, val)

        # Список всех ОКВЭДов
        okveds = []
        for el in soup.select(".okved-item, .okveds-list li, [class*='okved']"):
            t = clean_text(el.get_text())
            if t and t not in okveds:
                okveds.append(t)
        if okveds:
            res.data.setdefault("okved_all", okveds[:20])

        # Кавернозная пометка про холдинги
        res.data.setdefault(
            "finance_caveat",
            "Данные могут быть неполными из-за сложной структуры холдинга. Рекомендуется проверить аффилированные юрлица.",
        )


# ---------------------------------------------------------------------------
# 3. Zachestnyibiznes.ru
# ---------------------------------------------------------------------------
class ZacheBiznesCollector(BaseCollector):
    name = "zachestnyibiznes"

    BASE = "https://zachestnyibiznes.ru"

    def collect(self, query: str) -> CollectorResult:
        res = CollectorResult(source=self.name)
        try:
            url = f"{self.BASE}/search?query={quote_plus(query)}"
            r = self.client.get(url, force_playwright=True, headers={"Referer": self.BASE})
            res.urls.append(url)
            if not r.ok:
                res.errors.append(f"request_failed: {r.status}")
                return res

            soup = r.soup()
            # Поиск первой ссылки на карточку компании
            card_link = None
            for a in soup.select("a"):
                href = a.get("href", "")
                if "/company/" in href:
                    card_link = urljoin(self.BASE, href)
                    break

            if card_link:
                rc = self.client.get(card_link, force_playwright=True, headers={"Referer": url})
                res.urls.append(card_link)
                if rc.ok:
                    self._parse_card(rc.soup(), res)
                    return res

            # Иначе парсим страницу поиска
            self._parse_card(soup, res)
        except Exception as e:
            logger.exception("Zache error")
            res.errors.append(f"exception: {e}")
        return res

    def _parse_card(self, soup, res: CollectorResult):
        text = soup.get_text(" ", strip=True)

        for label, key in [
            ("ИНН", "inn"), ("ОГРН", "ogrn"), ("КПП", "kpp"),
            ("Дата регистрации", "registration_date"),
            ("Юридический адрес", "legal_address"),
            ("Руководитель", "director"), ("Генеральный директор", "director"),
            ("Учредители", "founder"), ("Учредитель", "founder"),
            ("Основной ОКВЭД", "okved_main"),
            ("Статус", "status"),
            ("Выручка", "revenue"), ("Прибыль", "profit"),
            ("Численность сотрудников", "employees"),
            ("Стоимость активов", "assets"),
        ]:
            m = re.search(rf"{re.escape(label)}\s*[:：]?\s*([^\n\r•|]+?)(?:\s{{2,}}|$|•|\|)", text)
            if m:
                val = clean_text(m.group(1))
                if val and val.lower() not in ("—", "-", "нет данных"):
                    res.data.setdefault(key, val)


# ---------------------------------------------------------------------------
# 4. List-Org.com — замена мёртвому FindCompany
# ---------------------------------------------------------------------------
class ListOrgCollector(BaseCollector):
    """list-org.com — открытый каталог российских компаний.

    Хорошо индексируется поисковиками, не за Cloudflare, даёт базовые поля и
    иногда финансовые показатели. Не самый авторитетный источник, но рабочий.
    """
    name = "list_org"

    BASE = "https://www.list-org.com"

    def collect(self, query: str) -> CollectorResult:
        res = CollectorResult(source=self.name)
        try:
            # Если ИНН — ищем по нему, иначе по названию
            if looks_like_inn(query):
                # list-org принимает ИНН в URL
                url = f"{self.BASE}/search?type=inn&val={quote_plus(query)}"
            else:
                url = f"{self.BASE}/search?type=name&val={quote_plus(query)}"
            r = self.client.get(url, headers={"Referer": self.BASE})
            res.urls.append(url)
            if not r.ok:
                res.errors.append(f"search_failed: {r.status}")
                return res

            soup = r.soup()
            # Ищем ссылку на карточку компании
            card_link = None
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                if "/company/" in href:
                    card_link = urljoin(self.BASE, href)
                    break

            if card_link:
                rc = self.client.get(card_link, headers={"Referer": url})
                res.urls.append(card_link)
                if rc.ok:
                    self._parse_card(rc.soup(), res)
                    return res
                else:
                    res.errors.append(f"card_failed: {rc.status}")
        except Exception as e:
            logger.exception("ListOrg error")
            res.errors.append(f"exception: {e}")
        return res

    def _parse_card(self, soup, res: CollectorResult):
        text = soup.get_text(" ", strip=True)
        h1 = soup.select_one("h1, h2")
        if h1:
            res.data.setdefault("full_name", clean_text(h1.get_text()))

        for label, key in [
            ("ИНН", "inn"), ("ОГРН", "ogrn"), ("КПП", "kpp"),
            ("Дата регистрации", "registration_date"),
            ("Юридический адрес", "legal_address"),
            ("Директор", "director"), ("Руководитель", "director"),
            ("Учредитель", "founder"),
            ("Основной ОКВЭД", "okved_main"),
            ("Статус", "status"),
            ("Выручка", "revenue"), ("Чистая прибыль", "profit"),
            ("Сотрудники", "employees"),
        ]:
            m = re.search(rf"{re.escape(label)}\s*[:：]?\s*([^\n\r•|]+?)(?:\s{{2,}}|$|•|\|)", text)
            if m:
                val = clean_text(m.group(1))
                if val and val.lower() not in ("—", "-", "нет данных", ""):
                    res.data.setdefault(key, val)


# ---------------------------------------------------------------------------
# 4b. FindCompany — оставлен как legacy, может заработать на другой машине
# ---------------------------------------------------------------------------
class FindCompanyCollector(BaseCollector):
    name = "findcompany"
    BASE = "https://www.findcompany.pro"

    def collect(self, query: str) -> CollectorResult:
        res = CollectorResult(source=self.name)
        res.errors.append("domain_unavailable")
        return res


# ---------------------------------------------------------------------------
# 5. MarketSearchCollector — поиск по сниппетам рыночных данных
# ---------------------------------------------------------------------------
class MarketSearchCollector(BaseCollector):
    name = "market_search"

    # Паттерны для извлечения рыночных метрик из сниппетов
    MONEY_RE = re.compile(r"(\d[\d\s.,]*\d|\d)\s*(млрд|млн|тыс\.?|billion|million|bn|m)\b", re.IGNORECASE)
    YEAR_RE = re.compile(r"\b(20\d{2})\b")
    PERCENT_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE)
    TOP_RE = re.compile(r"(ТОП[-\s]?(\d+)|топ[-\s]?(\d+))", re.IGNORECASE)

    def collect(self, query: str, industry_hint: str = "", okved_code: str = "") -> CollectorResult:
        res = CollectorResult(source=self.name)
        try:
            # Если на входе ИНН/название — мы не знаем рынок.
            # Формируем несколько поисковых запросов, в т.ч. с кодом ОКВЭД
            industry = industry_hint or "рынок"
            queries = [
                f"{industry} Россия объём рынка 2024 2025",
                f"{industry} топ игроков Россия доля рынка",
                f"{industry} производство Россия динамика",
                f"{query} {industry} доля рынка позиция",
            ]
            if okved_code:
                # Запрос с кодом ОКВЭД часто даёт более точные результаты (TAdviser, BusinesStat)
                queries.insert(0, f"ОКВЭД {okved_code} Россия рынок объём")
            snippets = []
            for q in queries:
                snippets.extend(duckduckgo_search(q, self.client, max_results=6))
                res.urls.append(f"duckduckgo: {q}")

            # Анализируем сниппеты на ключевые метрики
            market_size_candidates = []
            dynamics_candidates = []
            top_players_candidates = []
            company_position_candidates = []

            for s in snippets:
                text = (s.get("snippet") or "") + " " + (s.get("title") or "")
                # Объём рынка
                if re.search(r"(объём|объем|размер)\s*(рынка)?", text, re.IGNORECASE):
                    money = self.MONEY_RE.findall(text)
                    years = self.YEAR_RE.findall(text)
                    if money:
                        market_size_candidates.append({
                            "value": " ".join(m[0] for m in money[:2]) + " " + (money[0][1] if money[0][1] else ""),
                            "year": years[0] if years else "",
                            "source": s.get("url", ""),
                            "text": text[:200],
                        })
                # Динамика
                if re.search(r"(вырос|рост|снизил|падение|динамик)", text, re.IGNORECASE):
                    percents = self.PERCENT_RE.findall(text)
                    if percents:
                        dynamics_candidates.append({
                            "value": percents[0] + "%",
                            "source": s.get("url", ""),
                            "text": text[:200],
                        })
                # Топ-игроки
                if self.TOP_RE.search(text) or re.search(r"(лидер|лидеры|крупнейш)", text, re.IGNORECASE):
                    top_players_candidates.append({
                        "text": text[:300],
                        "source": s.get("url", ""),
                    })
                # Позиция запрошенной компании
                if query.lower().split()[0] in text.lower():
                    company_position_candidates.append({
                        "text": text[:300],
                        "source": s.get("url", ""),
                    })

            res.data = {
                "industry": industry,
                "market_size_candidates": market_size_candidates[:8],
                "dynamics_candidates": dynamics_candidates[:6],
                "top_players_candidates": top_players_candidates[:5],
                "company_position_candidates": company_position_candidates[:5],
                "raw_snippets": snippets[:20],
            }
        except Exception as e:
            logger.exception("MarketSearch error")
            res.errors.append(f"exception: {e}")
        return res


# ---------------------------------------------------------------------------
# 6. RosstatCollector — Росстат (открытые данные по отраслям)
# ---------------------------------------------------------------------------
class RosstatCollector(BaseCollector):
    name = "rosstat"

    BASE = "https://rosstat.gov.ru"

    def collect(self, query: str, industry_hint: str = "") -> CollectorResult:
        res = CollectorResult(source=self.name)
        try:
            # Росстат не даёт прямого API по отраслям. Делаем поиск по сайту.
            if industry_hint:
                q = f"site:rosstat.gov.ru {industry_hint} производство"
            else:
                q = f"site:rosstat.gov.ru {query} производство"
            results = duckduckgo_search(q, self.client, max_results=5)
            res.urls.extend(r.get("url", "") for r in results if r.get("url"))
            res.data = {
                "snippets": [
                    {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", "")}
                    for r in results
                ]
            }
        except Exception as e:
            logger.exception("Rosstat error")
            res.errors.append(f"exception: {e}")
        return res


# ---------------------------------------------------------------------------
# 7. CompanySiteCollector — скрапинг сайта компании
# ---------------------------------------------------------------------------
class CompanySiteCollector(BaseCollector):
    """Пытается найти сайт компании и собрать с него:
    - телефоны, email (regex)
    - соцсети (ссылки на VK, Telegram, YouTube, Дзен)
    - адреса магазинов / офисов (поиск по тексту)
    - каталог / ключевые страницы
    """
    name = "company_site"

    SOCIAL_PATTERNS = {
        "vk": re.compile(r"vk\.com/[^\"'\s<>]+", re.IGNORECASE),
        "telegram": re.compile(r"t(?:elegram)?\.me/[^\"'\s<>]+|@[\w\d_]{5,}", re.IGNORECASE),
        "youtube": re.compile(r"youtube\.com/(?:channel|c|user)/[^\"'\s<>]+|youtu\.be/[^\"'\s<>]+", re.IGNORECASE),
        "dzen": re.compile(r"dzen\.ru/[^\"'\s<>]+", re.IGNORECASE),
        "ok": re.compile(r"ok\.ru/[^\"'\s<>]+", re.IGNORECASE),
        "instagram": re.compile(r"instagram\.com/[^\"'\s<>]+", re.IGNORECASE),
        "facebook": re.compile(r"facebook\.com/[^\"'\s<>]+", re.IGNORECASE),
    }
    PHONE_RE = re.compile(r"\+7[\s(]?-?\d{3}[\s)]?-?\d{3}[\s-]?\d{2}[\s-]?\d{2}|\+7\d{10}")
    EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    def collect(self, query: str, company_name: str = "") -> CollectorResult:
        res = CollectorResult(source=self.name)
        try:
            # 1. Ищем сайт компании через Bing
            if company_name:
                q = f"{company_name} официальный сайт"
            else:
                q = f"{query} официальный сайт"
            results = duckduckgo_search(q, self.client, max_results=5)

            # 2. Берём первый не-агрегаторский домен
            site_url = None
            bad_domains = ("list-org.com", "rusprofile.ru", "zachestnyibiznes",
                           "findcompany.pro", "nalog.ru", "rosstat.gov.ru",
                           "wikipedia.org", "youtube.com", "vk.com",
                           "audit-it.ru", "skrin.ru", "kontragent", "bing.com")
            for r in results:
                url = r.get("url", "")
                if not url:
                    continue
                if any(bd in url.lower() for bd in bad_domains):
                    continue
                if not url.startswith("http"):
                    continue
                site_url = url
                res.urls.append(url)
                break

            if not site_url:
                res.errors.append("site_not_found")
                return res

            # 3. Скачиваем главную
            r = self.client.get(site_url, force_playwright=False)
            if not r.ok:
                # Пробуем с playwright
                r = self.client.get(site_url, force_playwright=True)
                if not r.ok:
                    res.errors.append(f"site_fetch_failed: status={r.status}")
                    return res

            soup = r.soup()
            page_text = soup.get_text(" ", strip=True)

            # 4. Извлекаем контакты
            phones = list(set(self.PHONE_RE.findall(page_text)))[:5]
            emails = list(set(self.EMAIL_RE.findall(page_text)))[:5]
            socials = {}
            for name, pattern in self.SOCIAL_PATTERNS.items():
                matches = list(set(pattern.findall(page_text)))[:3]
                if matches:
                    socials[name] = matches

            # 5. Извлекаем ссылки с сайта (каталог, о компании, контакты)
            interesting_links = []
            for a in soup.select("a[href]")[:100]:
                href = a.get("href", "")
                text = clean_text(a.get_text())
                if not text:
                    continue
                # Ключевые слова в тексте ссылки
                if any(kw in text.lower() for kw in
                       ["каталог", "продукт", "магазин", "адрес", "контакт",
                        "о нас", "о компании", "прайс", "цены"]):
                    if href.startswith("/"):
                        href = urljoin(site_url, href)
                    elif not href.startswith("http"):
                        continue
                    interesting_links.append({"text": text[:60], "url": href})

            res.data = {
                "site_url": site_url,
                "site_title": clean_text(soup.title.get_text()) if soup.title else "",
                "phones": phones,
                "emails": emails,
                "socials": socials,
                "interesting_links": interesting_links[:15],
            }
        except Exception as e:
            logger.exception("CompanySite error")
            res.errors.append(f"exception: {e}")
        return res
