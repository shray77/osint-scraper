"""
utils.py — вспомогательные функции OSINT-скраппера.

Содержит:
- HttpClient: HTTP-клиент с requests + автоматическим Playwright fallback
- validate_inn / validate_ogrn: проверка контрольных сумм
- inn_search_hint: подсказки по нормализации названия компании
- OKVED_INDUSTRY_MAP: маппинг ОКВЭД → отрасль для поиска рыночных данных
- parse_money / parse_date / parse_int: безопасные парсеры
- slugify: для формирования имён файлов
"""
from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# Playwright — опциональная зависимость (fallback для JS/Cloudflare-сайтов)
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    PWTimeout = Exception

logger = logging.getLogger("osint.utils")

# Пул User-Agent'ов для ротации — снижает шанс бана
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

DEFAULT_HEADERS = {
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# Cache: простое файловое кэширование GET-ответов по URL-hash
# ---------------------------------------------------------------------------
def _default_cache_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OSINTScraper" / "cache"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "OSINTScraper"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "osint-scraper"
    return base

def _default_log_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OSINTScraper" / "logs"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs" / "OSINTScraper"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "osint-scraper"
    return base

CACHE_DIR = Path(os.environ.get("OSINT_CACHE_DIR", _default_cache_dir()))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
PDF_CACHE_DIR = CACHE_DIR / "egrul_pdf"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = _default_log_dir()
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(url: str, method: str = "GET") -> Path:
    h = hashlib.sha256(f"{method}|{url}".encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{h}.txt"


def cache_get(url: str, method: str = "GET") -> Optional[str]:
    p = _cache_key(url, method)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def cache_put(url: str, body: str, method: str = "GET") -> None:
    p = _cache_key(url, method)
    try:
        p.write_text(body, encoding="utf-8")
    except Exception as e:
        logger.debug("cache_put failed: %s", e)


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
@dataclass
class HttpResponse:
    url: str
    status: int
    text: str
    final_url: str
    via: str  # "requests" | "playwright" | "cache"
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and not self.error

    def soup(self) -> BeautifulSoup:
        return BeautifulSoup(self.text or "", "lxml")


class HttpClient:
    """HTTP-клиент с requests primary + Playwright fallback.

    Правила fallback:
    - status >= 403 (Cloudflare/bot block) → пробуем Playwright
    - пустой HTML/явные признаки JS-only (только <noscript>) → Playwright
    - timeout/connection error → Playwright
    """

    def __init__(
        self,
        timeout: int = 20,
        delay_range: tuple = (1.0, 2.5),
        use_cache: bool = True,
        enable_playwright: bool = True,
    ):
        self.timeout = timeout
        self.delay_range = delay_range
        self.use_cache = use_cache
        self.enable_playwright = enable_playwright and HAS_PLAYWRIGHT
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._pw = None
        self._browser = None

    def _polite_sleep(self):
        time.sleep(random.uniform(*self.delay_range))

    def _get_requests(self, url: str, headers: Optional[dict] = None) -> HttpResponse:
        h = {"User-Agent": random.choice(USER_AGENTS)}
        if headers:
            h.update(headers)
        try:
            r = self.session.get(url, headers=h, timeout=self.timeout, allow_redirects=True)
            return HttpResponse(
                url=url,
                status=r.status_code,
                text=r.text,
                final_url=r.url,
                via="requests",
            )
        except Exception as e:
            return HttpResponse(url=url, status=0, text="", final_url=url, via="requests", error=str(e))

    def _post_requests(self, url: str, data=None, json_body=None, headers: Optional[dict] = None) -> HttpResponse:
        h = {"User-Agent": random.choice(USER_AGENTS)}
        if headers:
            h.update(headers)
        try:
            if json_body is not None:
                r = self.session.post(url, json=json_body, headers=h, timeout=self.timeout, allow_redirects=True)
            else:
                r = self.session.post(url, data=data, headers=h, timeout=self.timeout, allow_redirects=True)
            return HttpResponse(
                url=url, status=r.status_code, text=r.text, final_url=r.url, via="requests"
            )
        except Exception as e:
            return HttpResponse(url=url, status=0, text="", final_url=url, via="requests", error=str(e))

    def _ensure_browser(self):
        if not self.enable_playwright:
            return False
        if self._browser is None:
            try:
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=True)
            except Exception as e:
                logger.warning("Playwright не запустился: %s", e)
                self.enable_playwright = False
                return False
        return True

    def _get_playwright(self, url: str, headers: Optional[dict] = None) -> HttpResponse:
        if not self._ensure_browser():
            return HttpResponse(url=url, status=0, text="", final_url=url, via="playwright", error="playwright_unavailable")
        try:
            ctx = self._browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="ru-RU",
                viewport={"width": 1280, "height": 800},
            )
            if headers:
                ctx.set_extra_http_headers(headers)
            page = ctx.new_page()
            page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
            # подождать network-idle 3 сек максимум — для подгрузки JS-контента
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except PWTimeout:
                pass
            html = page.content()
            final_url = page.url
            ctx.close()
            return HttpResponse(url=url, status=200, text=html, final_url=final_url, via="playwright")
        except Exception as e:
            return HttpResponse(url=url, status=0, text="", final_url=url, via="playwright", error=str(e))

    def get(self, url: str, headers: Optional[dict] = None, force_playwright: bool = False) -> HttpResponse:
        # 1. Cache
        if self.use_cache:
            cached = cache_get(url, "GET")
            if cached is not None:
                return HttpResponse(url=url, status=200, text=cached, final_url=url, via="cache")

        # 2. requests first (unless explicitly forced)
        if not force_playwright:
            r = self._get_requests(url, headers=headers)
            # Если бот-блок или явный JS-only → fallback
            looks_js_only = (r.ok and len(r.text) < 2000 and "<noscript>" in r.text.lower())
            if (r.status in (403, 429, 503) or looks_js_only) and self.enable_playwright:
                logger.info("requests fallback → playwright (%s, status=%s)", url, r.status)
                pw = self._get_playwright(url, headers=headers)
                if pw.ok:
                    if self.use_cache:
                        cache_put(url, pw.text, "GET")
                    self._polite_sleep()
                    return pw
            if r.ok and self.use_cache:
                cache_put(url, r.text, "GET")
            self._polite_sleep()
            return r

        # 3. Force playwright
        pw = self._get_playwright(url, headers=headers)
        if pw.ok and self.use_cache:
            cache_put(url, pw.text, "GET")
        self._polite_sleep()
        return pw

    def post(self, url: str, data=None, json_body=None, headers: Optional[dict] = None) -> HttpResponse:
        # Кэш POST — по url+payload
        cache_key_url = url + "|" + (json.dumps(json_body, ensure_ascii=False) if json_body else (str(data) if data else ""))
        if self.use_cache:
            cached = cache_get(cache_key_url, "POST")
            if cached is not None:
                return HttpResponse(url=url, status=200, text=cached, final_url=url, via="cache")
        r = self._post_requests(url, data=data, json_body=json_body, headers=headers)
        if r.ok and self.use_cache:
            cache_put(cache_key_url, r.text, "POST")
        self._polite_sleep()
        return r

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# INN / OGRN validation
# ---------------------------------------------------------------------------
def validate_inn(inn: str) -> bool:
    """Проверка ИНН по контрольной сумме (10 или 12 цифр)."""
    inn = re.sub(r"\D", "", inn or "")
    if len(inn) == 10:
        weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        s = sum(int(inn[i]) * weights[i] for i in range(9))
        return int(inn[9]) == s % 11 % 10
    if len(inn) == 12:
        w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        s1 = sum(int(inn[i]) * w1[i] for i in range(10))
        if int(inn[10]) != s1 % 11 % 10:
            return False
        w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        s2 = sum(int(inn[i]) * w2[i] for i in range(11))
        return int(inn[11]) == s2 % 11 % 10
    return False


def validate_ogrn(ogrn: str) -> bool:
    """Проверка ОГРН (13 цифр) по контрольной сумме."""
    ogrn = re.sub(r"\D", "", ogrn or "")
    if len(ogrn) != 13:
        return False
    s = int(ogrn[:-1]) % 11
    return int(ogrn[-1]) == s % 10


def looks_like_inn(s: str) -> bool:
    s = re.sub(r"\D", "", s or "")
    return len(s) in (10, 12)


# ---------------------------------------------------------------------------
# OKVED → industry mapping (для поиска рыночных данных)
# ---------------------------------------------------------------------------
# Ключи — префикс ОКВЭД (первые 2-4 цифры). Значения — описание отрасли для
# поискового запроса рыночных данных.
OKVED_INDUSTRY_MAP = {
    "01": "сельское хозяйство",
    "01.1": "выращивание однолетних культур",
    "01.2": "выращивание многолетних культур",
    "01.3": "выращивание рассады",
    "01.4": "животноводство",
    "01.41": "молочное скотоводство",
    "01.45": "разведение овец и коз",
    "01.46": "разведение свиней",
    "01.47": "птицеводство",
    "01.49": "разведение прочих животных",
    "02": "лесное хозяйство и лесозаготовки",
    "03": "рыболовство и рыбоводство",
    "05": "добыча угля",
    "06": "добыча сырой нефти и природного газа",
    "07": "добыча металлических руд",
    "08": "добыча прочих полезных ископаемых",
    "09": "вспомогательная деятельность в области добычи",
    "10": "производство пищевых продуктов",
    "10.1": "переработка мяса",
    "10.2": "переработка рыбы",
    "10.3": "переработка фруктов и овощей",
    "10.4": "производство растительных и животных масел",
    "10.5": "производство молочных продуктов",
    "10.51": "производство сыра",
    "10.52": "производство мороженого",
    "10.6": "производство продуктов мукомольно-крупяной промышленности",
    "10.7": "производство хлеба и кондитерских изделий",
    "10.8": "производство прочих пищевых продуктов",
    "10.9": "производство готовых кормов для животных",
    "11": "производство напитков",
    "12": "производство табачных изделий",
    "13": "производство текстильных изделий",
    "14": "производство одежды",
    "15": "производство кожи и обуви",
    "16": "обработка древесины и изделий из дерева",
    "17": "производство бумаги и картона",
    "18": "деятельность полиграфическая и копирование носителей",
    "19": "производство кокса и нефтепродуктов",
    "20": "производство химических веществ",
    "21": "производство лекарств и материалов для медицины",
    "22": "производство резиновых и пластмассовых изделий",
    "23": "производство прочей неметаллической минеральной продукции",
    "24": "производство основной металлургии",
    "25": "производство готовых металлических изделий",
    "26": "производство компьютеров и электронной техники",
    "27": "производство электрического оборудования",
    "28": "производство машин и оборудования",
    "29": "производство автомобилей",
    "30": "производство прочих транспортных средств",
    "31": "производство мебели",
    "32": "производство прочих готовых изделий",
    "33": "ремонт и монтаж машин и оборудования",
    "35": "электроэнергетика, газ и пар",
    "36": "забор и очистка воды",
    "37": "сбор и обработка сточных вод",
    "38": "сбор и обработка отходов",
    "41": "строительство зданий",
    "42": "строительство инженерных сооружений",
    "43": "специализированные строительные работы",
    "45": "торговля оптовая и розничная автотранспортом",
    "46": "торговля оптовая",
    "47": "торговля розничная",
    "49": "деятельность сухопутного транспорта",
    "50": "деятельность водного транспорта",
    "51": "деятельность воздушного транспорта",
    "52": "складирование и вспомогательная транспортная деятельность",
    "53": "деятельность почтовой связи и курьерская",
    "55": "деятельность по предоставлению мест проживания",
    "56": "деятельность по предоставлению питания",
    "58": "производство программного обеспечения",
    "60": "деятельность в области телевизионного и радиовещания",
    "61": "деятельность в области связи на основе беспроводных технологий",
    "62": "разработка компьютерного ПО",
    "63": "деятельность в области информационных услуг",
    "64": "деятельность по предоставлению финансовых услуг",
    "65": "страхование",
    "66": "вспомогательная деятельность в сфере финансовых услуг",
    "68": "операции с недвижимым имуществом",
    "69": "деятельность в области права и бухгалтерского учёта",
    "70": "деятельность головных офисов",
    "71": "деятельность в области инженерных изысканий",
    "72": "научные исследования и разработки",
    "73": "реклама",
    "74": "профессиональная научно-техническая деятельность",
    "75": "ветеринарная деятельность",
    "77": "аренда и лизинг",
    "78": "деятельность по трудоустройству",
    "79": "деятельность туристических агентств",
    "80": "деятельность по охране и безопасности",
    "81": "деятельность по комплексному обслуживанию помещений",
    "82": "деятельность административно-хозяйственная",
    "84": "государственное управление",
    "85": "образование",
    "86": "деятельность в области медицины",
    "87": "деятельность по уходу с обеспечением проживания",
    "88": "предоставление социальных услуг без проживания",
    "90": "деятельность творческая и зрелищная",
    "91": "деятельность библиотек и музеев",
    "93": "деятельность в области спорта",
    "94": "деятельность общественных организаций",
    "95": "ремонт компьютеров и предметов личного потребления",
    "96": "деятельность по предоставлению прочих персональных услуг",
}


def okved_to_industry(okved: str) -> str:
    """Возвращает описание отрасли по ОКВЭД. Идёт от длинных префиксов к коротким."""
    okved = (okved or "").strip()
    if not okved:
        return ""
    for prefix_len in (5, 4, 3, 2):
        prefix = okved[:prefix_len]
        if prefix in OKVED_INDUSTRY_MAP:
            return OKVED_INDUSTRY_MAP[prefix]
    return ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def parse_int(s) -> Optional[int]:
    """Извлекает первое целое число из строки. Возвращает None если нет числа."""
    if s is None:
        return None
    m = re.search(r"-?\d[\d\s\u00a0]*", str(s))
    if not m:
        return None
    try:
        return int(re.sub(r"[\s\u00a0]", "", m.group(0)))
    except ValueError:
        return None


def parse_money(s) -> Optional[str]:
    """Извлекает сумму с единицей измерения, сохраняя читаемость: '1 234 567 ₽'."""
    if s is None:
        return None
    s = str(s).replace("\xa0", " ").strip()
    m = re.search(r"(\d[\d\s.,]*\d|\d)\s*(тыс\.?|млн|млрд|млрд\.?|руб|₽|р\.)?", s, re.IGNORECASE)
    if m:
        return m.group(0).strip()
    return None


def parse_date(s) -> Optional[str]:
    """Извлекает дату в формате ДД.ММ.ГГГГ."""
    if not s:
        return None
    m = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", str(s))
    return m.group(0) if m else None


def clean_text(s) -> str:
    """Нормализует текст: схлопывает пробелы, убирает NBSP."""
    if s is None:
        return ""
    s = str(s).replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def slugify(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "_", s)
    return s.strip("_")[:80]


# ---------------------------------------------------------------------------
# Search-engine snippet grabber (DuckDuckGo HTML, no API key required)
# ---------------------------------------------------------------------------
def duckduckgo_search(query: str, client: HttpClient, max_results: int = 8) -> list[dict]:
    """Поиск рыночных данных через Bing (HTML endpoint).

    Стратегия:
    1. requests.get на Bing с mkt=ru-RU.
    2. Парсим li.b_algo элементы.
    3. Если результаты не содержат ключевых слов запроса (гео-блок) —
       Playwright fallback через HttpClient.

    Возвращает список {title, url, snippet}.

    ВАЖНО: Bing гео-зависимый — на сервере с европейским/российским IP
    результаты будут релевантнее, чем на азиатском.
    """
    from urllib.parse import urlencode
    import requests as _rq

    qs = urlencode({"q": query, "mkt": "ru-RU", "setlang": "ru-RU", "cc": "ru"})
    url = f"https://www.bing.com/search?{qs}"

    query_keywords = [w.lower() for w in re.findall(r"[а-яёА-ЯЁa-zA-Z]{3,}", query)][:3]

    def _parse_bing_html(html_text: str) -> list[dict]:
        soup = BeautifulSoup(html_text or "", "lxml")
        out = []
        for res in soup.select("li.b_algo"):
            h2 = res.select_one("h2")
            if not h2:
                continue
            a = h2.find("a")
            if not a:
                continue
            title = clean_text(a.get_text())
            href = a.get("href", "")
            # Bing redirect: /ck/a?...&u=a1<base64-encoded-url>&...
            m = re.search(r"[?&]u=a1([^&]+)", href)
            if m:
                import base64
                try:
                    padded = m.group(1) + "=" * (-len(m.group(1)) % 4)
                    href = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
                except Exception:
                    pass
            snip_el = res.select_one(".b_caption p, .b_lineclamp4, .b_lineclamp3, .b_lineclamp2")
            snippet = clean_text(snip_el.get_text()) if snip_el else ""
            out.append({
                "title": title,
                "url": href,
                "snippet": snippet,
            })
            if len(out) >= max_results:
                break
        return out

    def _is_relevant(results: list[dict]) -> bool:
        """Хотя бы 1 результат содержит keyword из запроса."""
        if not results:
            return False
        for r in results:
            text = (r.get("title", "") + " " + r.get("snippet", "")).lower()
            if any(kw in text for kw in query_keywords):
                return True
        return False

    # --- 1. requests.get ---
    try:
        r = _rq.get(
            url,
            headers={
                "User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=12,
        )
        if r.status_code == 200:
            results = _parse_bing_html(r.text)
            if _is_relevant(results):
                return results
            logger.debug("bing requests: %d results but not relevant (geo-block?)", len(results))
    except Exception as e:
        logger.debug("bing requests failed: %s", e)

    # --- 2. Playwright fallback ---
    try:
        r2 = client.get(url, force_playwright=True,
                        headers={"Accept-Language": "ru-RU,ru;q=0.9"})
        if r2.ok:
            results = _parse_bing_html(r2.text)
            if _is_relevant(results):
                return results
            logger.debug("bing playwright: %d results but not relevant", len(results))
    except Exception as e:
        logger.debug("bing playwright failed: %s", e)

    return []

# PDF cache для выписок ЕГРЮЛ
PDF_CACHE_TTL_SECONDS = 24 * 3600

def cache_get_pdf(inn):
    p = PDF_CACHE_DIR / f"{inn}.pdf"
    if not p.exists():
        return None
    try:
        import time as _t
        if _t.time() - p.stat().st_mtime > PDF_CACHE_TTL_SECONDS:
            return None
        return p.read_bytes()
    except Exception:
        return None

def cache_put_pdf(inn, pdf_bytes):
    p = PDF_CACHE_DIR / f"{inn}.pdf"
    try:
        p.write_bytes(pdf_bytes)
    except Exception:
        pass

def setup_file_logger(level=None):
    import logging as _lg
    if level is None:
        level = _lg.INFO
    try:
        handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / "osint.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(_lg.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
        _lg.getLogger().addHandler(handler)
        return handler
    except Exception:
        return None

# Web search — алиас для duckduckgo_search (v1.2+)
def web_search(query, client, max_results=8):
    return duckduckgo_search(query, client, max_results)

