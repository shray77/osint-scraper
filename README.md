# OSINT Scraper v1.1 — настольное приложение

Универсальный OSINT-скраппер для российских компаний с **GUI** и **MSI-установщиком**.

По названию или ИНН компании собирает:
- Идентификацию (ИНН, ОГРН, КПП, дата регистрации, регион, директор)
- ОКВЭД (основной + дополнительные) — из PDF-выписки ЕГРЮЛ
- Юридический адрес, учредителей, уставный капитал
- Базовые финансы (если найдены в открытых реестрах)
- Контекст рынка: объём, динамика, топ-игроки
- Сайт компании: контакты, соцсети, ключевые страницы
- Список всех совпадений юрлиц — для disambiguation в холдингах

## Возможности v1.1

- ✅ **GUI на PySide6 (Qt)** — нативный, тёмный хедер, 8 табов
- ✅ **Асинхронные коллекторы** — GUI не зависает, прогресс-бар показывает статус
- ✅ **Профиль компании** — карточки с ключевыми метриками + детальные поля
- ✅ **Таб «Совпадения»** — все юрлица с похожим названием (для холдингов)
- ✅ **Таб «Рынок»** — кандидаты на объём/динамику/топ-игроков из сниппетов
- ✅ **Таб «Сайт»** — контакты, соцсети, ссылки на каталог/адреса
- ✅ **Таб «Логи»** — живой вывод логов сборки
- ✅ **Таб «Источники»** — все URL, двойной клик открывает в браузере
- ✅ **Таб «Настройки»** — deep mode, playwright, кэш, папка вывода
- ✅ **CLI-режим** — `python osint_scraper.py --query "Компания" --deep`
- ✅ **MSI-пакет** через WiX Toolset (Windows Installer)
- ✅ **EXE-установщик** через Inno Setup (альтернатива)
- ✅ **Standalone exe** через PyInstaller (без установки)

## Установка для разработки

```bash
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Установить Playwright + Chromium (для Cloudflare-сайтов)
pip install playwright
playwright install chromium

# 3. На Linux дополнительно (если нет системных Qt-библиотек):
#    apt install libegl1 libopengl0 libgl1 libfontconfig1 libdbus-1-3 libxkbcommon0

# 4. Установить pdftotext (для deep-режима — парсинг PDF-выписки ЕГРЮЛ)
#    Ubuntu/Debian: apt install poppler-utils
#    macOS: brew install poppler
#    Windows: скачать с https://github.com/oschwartz10612/poppler-windows/releases
```

## Запуск

### GUI

```bash
python osint_app.py
```

### CLI

```bash
# Поиск по названию
python osint_scraper.py --query "Истринская сыроварня" --deep

# Поиск по ИНН (точнее)
python osint_scraper.py --query "5017127406" --deep

# Без скрапинга сайта (быстрее)
python osint_scraper.py --query "Истринская сыроварня" --deep --no-site

# Несколько компаний за раз
python osint_scraper.py --query "Компания 1" --query "Компания 2"
```

## Сборка standalone приложения

### Windows — MSI через WiX

**Требования:**
1. Python 3.10+ с зависимостями (`pip install -r requirements.txt`)
2. PyInstaller: `pip install pyinstaller`
3. WiX Toolset v3.11+: https://wixtoolset.org/releases/

**Сборка:**
```cmd
packaging\build_msi.bat
```

**Результат:** `packaging\OSINTScraper-1.1.0.msi`

### Windows — EXE через Inno Setup (альтернатива)

**Требования:**
1. PyInstaller установлен
2. Inno Setup 6+: https://jrsoftware.org/isdl.php

**Сборка:**
```cmd
pyinstaller packaging\osint_scraper.spec --noconfirm
iscc packaging\installer.iss
```

**Результат:** `packaging\OSINTScraper-Setup-1.1.0.exe`

### Linux / macOS — standalone бинарник

```bash
./packaging/build_app.sh
```

**Результат:** `dist/OSINTScraper/OSINTScraper`

Для создания .dmg на macOS:
```bash
hdiutil create -volname "OSINT Scraper 1.1" \
  -srcfolder dist/OSINTScraper.app \
  -ov -format UDZO \
  dist/OSINTScraper-1.1.0.dmg
```

## Архитектура

```
osint_scraper/
├── osint_app.py             # GUI entry point
├── osint_scraper.py         # CLI entry point
├── utils.py                 # HttpClient (requests+Playwright), INN validation, OKVED→industry map, Bing search
├── collectors.py            # 7 коллекторов
├── reporters.py             # Markdown и Excel репортеры
├── gui/
│   ├── __init__.py
│   ├── main_window.py       # Главное окно с 8 табами
│   ├── workers.py           # QThread workers (async)
│   └── resources/
│       ├── icon.svg         # Исходник иконки
│       ├── icon.png         # Для Linux
│       └── icon.ico         # Для Windows
├── packaging/
│   ├── osint_scraper.spec   # PyInstaller spec
│   ├── osint_scraper.wxs    # WiX MSI-описание
│   ├── build_msi.bat        # Сборка MSI на Windows
│   ├── installer.iss        # Inno Setup EXE-установщик
│   ├── build_app.sh         # Сборка standalone на Linux/Mac
│   ├── heat-transform.xslt  # Трансформация для heat.exe
│   └── license.rtf          # Лицензия MIT для установщика
├── requirements.txt
├── README.md
└── output/                  # выходные файлы (.md, .xlsx, .json)
```

### Коллекторы

| Коллектор | Источник | Что даёт | Статус |
|-----------|----------|----------|--------|
| `NalogEGRULCollector` | egrul.nalog.ru | ИНН/ОГРН/КПП/дата/регион/директор | ✅ работает |
| `NalogEgrulPdfCollector` | PDF-выписка ЕГРЮЛ | ОКВЭД, адрес, учредители, капитал | ✅ работает (deep-режим) |
| `RusprofileCollector` | rusprofile.ru | Фин. показатели, доп.детали | ⚠️ Cloudflare (нужен Playwright) |
| `ZacheBiznesCollector` | zachestnyibiznes.ru | Фин. показатели | ⚠️ DDoS-Guard |
| `ListOrgCollector` | list-org.com | Базовые поля, иногда финансы | ✅ работает |
| `MarketSearchCollector` | Bing search | Рынок: объём, динамика, топ-игроки | ✅ работает |
| `RosstatCollector` | rosstat.gov.ru (через Bing) | Сниппеты от Росстата | ✅ работает |
| `CompanySiteCollector` | Сайт компании | Контакты, соцсети, ссылки | ✅ работает |

## GUI: табы

### 1. 🔍 Поиск
Форма ввода + переключатели (deep/site) + статусы всех коллекторов в реальном времени.

### 2. 📋 Профиль
6 карточек с ключевыми метриками (ИНН, ОГРН, дата, ОКВЭД, отрасль, директор) +
детальные поля (адрес, учредители, капитал, финансы) + список всех ОКВЭД.
Кнопки: открыть MD / Excel / JSON в системе.

### 3. 🔄 Совпадения
Таблица всех найденных юрлиц. Двойной клик по строке запускает новый поиск по ИНН
этого юрлица — удобно для проверки холдинговой структуры.

### 4. 📊 Рынок
Таблица кандидатов на объём рынка / динамику / топ-игроков / позицию компании
из поисковых сниппетов. Двойной клик открывает источник.

### 5. 🌐 Сайт
URL сайта, кнопка «Открыть», телефоны/email (regex из текста), соцсети, ключевые
страницы (каталог, контакты, о компании).

### 6. 📜 Логи
Живой вывод логов в терминальном стиле (тёмный фон, моноширинный шрифт).
Кнопка «Сохранить лог».

### 7. 🔗 Источники
Список всех URL, из которых собраны данные. Двойной клик открывает в браузере.

### 8. ⚙ Настройки
- Папка для отчётов
- Включить Playwright fallback
- Кэшировать HTTP-ответы
- О программе

## Известные ограничения v1.1

1. **Rusprofile/ZacheBiznes** — Cloudflare/DDoS-Guard блокируют даже Playwright.
   Финансы из этих источников часто пустые. Решение: платный API или bo.nalog.ru в v1.2.

2. **bo.nalog.ru** (БФО — официальный источник фин. отчётности от ФНС) — в v1.1 не
   подключён. В v1.2 можно добавить для прямой выручки/прибыли из ФНС.

3. **Bing-поиск рынка** — гео-зависимый. На сервере в России/Европе результаты будут
   релевантнее, чем на азиатском IP.

4. **MSI-сборка** — требует Windows + WiX Toolset. На Linux/Mac можно собрать только
   standalone exe через PyInstaller.

5. **Размер standalone** — из-за PySide6 + Qt + Chromium (если Playwright включён) —
   приложение занимает ~200-400 МБ. Без Playwright — ~80-120 МБ.

## Дорожная карта v1.2+

- [ ] bo.nalog.ru — официальная фин. отчётность от ФНС
- [ ] Yandex Maps / 2GIS — география точек, отзывы
- [ ] Ozon / Wildberries — SKU, рейтинг продавца
- [ ] VK / Telegram API — подписчики, активность
- [ ] Новости и СМИ — упоминания, ключевые темы
- [ ] Playwright-stealth для обхода Cloudflare на Rusprofile
- [ ] Batch-режим с CSV-входом
- [ ] Авто-обновление (через GitHub Releases)

## Пример: «Истринская сыроварня»

Запуск:
```
python osint_app.py
→ вводим «Истринская сыроварня»
→ включаем deep + site
→ ждём ~30 сек
```

Результат (в табе «Совпадения»):

| # | Название | ИНН | ОГРН | Регион | Регистрация | Статус |
|---|----------|-----|------|--------|-------------|--------|
| 1 | АО «Истринская сыроварня» | 5017127406 | 1215000130840 | Московская область | 24.12.2021 | действует |
| 2 | ООО «Истринская сыроварня» | 5024171100 | 1165024060464 | Московская область | 13.12.2016 | действует |

В табе «Профиль» выбран АО (управляющая компания холдинга) с ОКВЭД 69.20.2
(бухгалтерский учёт). Чтобы увидеть реальную деятельность (розница молочными
продуктами), нужно кликнуть по ООО в табе «Совпадения» — откроется новый поиск.

Это иллюстрирует мысль: **«бабки не всегда релевантны из-за сложной системы холдинга»**
— у одного холдинга несколько юрлиц с разными ОКВЭД, и для понимания реальной
деятельности нужно проверять все.

## Лицензия

MIT
