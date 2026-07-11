# OSINT Scraper v1.1.0 — QUICK START

## Что это

Desktop-приложение для OSINT-аналитики российских компаний. По названию или ИНН
собирает данные из открытых реестров (ФНС, агрегаторы, Bing, Росстат) и формирует
полный отчёт.

## Установка (Linux x64)

### Вариант 1: Готовый standalone-бинарник (без зависимостей)

1. Скачайте `OSINTScraper-1.1.0-linux-x64.zip` (227 МБ)
2. Распакуйте:
   ```bash
   unzip OSINTScraper-1.1.0-linux-x64.zip
   ```
3. Запустите:
   ```bash
   cd OSINTScraper
   ./OSINTScraper
   ```

**Системные требования:**
- Linux x86_64 (Ubuntu 20.04+, Debian 11+, Fedora 35+, Arch)
- Библиотеки Qt (обычно уже есть): `libEGL`, `libOpenGL`, `libGL`, `libfontconfig`, `libdbus-1-3`, `libxkbcommon0`
  - Если нет: `sudo apt install libegl1 libopengl0 libgl1 libfontconfig1 libdbus-1-3 libxkbcommon0`
- `pdftotext` для deep-режима (парсинг PDF-выписки ЕГРЮЛ):
  - `sudo apt install poppler-utils`

### Вариант 2: Из исходников (для разработки)

```bash
git clone https://github.com/shray77/osint-scraper.git
cd osint-scraper
pip install -r requirements.txt
python osint_app.py
```

Опционально (для Cloudflare-сайтов Rusprofile/Zache):
```bash
pip install playwright
playwright install chromium
```

## Использование

### GUI

```bash
./OSINTScraper
# или из исходников:
python osint_app.py
```

В главном окне:
1. Введите название или ИНН компании в поле поиска
2. Опционально включите галочки:
   - **Deep-режим** — скачивает PDF-выписку ЕГРЮЛ (даёт ОКВЭД, адрес, учредителей). Медленнее, но полнее.
   - **Скрапить сайт компании** — ищет сайт через Bing и собирает контакты/соцсети
3. Нажмите «🔍 Найти»
4. Ждите 30-60 секунд, наблюдаете за прогрессом в табе «Поиск» и логами в табе «Логи»
5. Результаты в табах:
   - **Профиль** — все поля компании + 6 карточек с ключевыми метриками
   - **Совпадения** — все юрлица с похожим названием (важно для холдингов!)
   - **Рынок** — кандидаты на объём/динамику/топ-игроков
   - **Сайт** — контакты, соцсети, ключевые страницы
   - **Источники** — все URL
6. Кнопки экспорта: 📄 Markdown / 📊 Excel / ⚙ JSON

### CLI

```bash
python osint_scraper.py --query "Истринская сыроварня" --deep
python osint_scraper.py --query 5017127406 --deep --no-site
python osint_scraper.py --query "Компания 1" --query "Компания 2"  # batch
```

Флаги:
- `--deep` — PDF-выписка ЕГРЮЛ (ОКВЭД, адрес, учредители)
- `--no-site` — не скрапить сайт компании
- `--no-playwright` — только requests (быстрее, но Rusprofile/Zache не сработают)
- `--no-cache` — отключить кэширование HTTP
- `-v` — подробное логирование

## Пример: «Истринская сыроварня»

```
Ввод: «Истринская сыроварня»
Найдено 2 юрлица:
  1. АО «Истринская сыроварня» (ИНН 5017127406)
     ОКВЭД: 69.20.2 — бухгалтерский учёт (управляющая компания)
  2. ООО «Истринская сыроварня» (ИНН 5024171100)
     ОКВЭД: 47.29.11 — розничная торговля молочными (розница)
```

В табе «Совпадения» можно двойным кликом по строке запустить новый поиск по
этому ИНН — удобно для проверки холдинговой структуры.

## Известные ограничения v1.1

1. **Rusprofile/ZacheBiznes** — за Cloudflare/DDoS-Guard. Без Playwright не сработают.
   В standalone-сборке Playwright убран для уменьшения размера. Если нужны эти
   источники — соберите из исходников с Playwright.

2. **Bing-поиск рынка** — гео-зависимый. На сервере в России/Европе результаты
   будут релевантнее, чем на азиатском IP.

3. **MSI-сборка** — требует Windows + WiX Toolset. Все файлы готовы в `packaging/`,
   но собрать MSI можно только на Windows.

4. **Финансы** — данные могут быть неполными из-за сложной холдинговой структуры.
   В v1.2 планируется bo.nalog.ru (официальная фин. отчётность от ФНС).

## Дорожная карта v1.2

- [ ] bo.nalog.ru — официальная фин. отчётность от ФНС
- [ ] Yandex Maps / 2GIS — география точек, отзывы
- [ ] Ozon / Wildberries — SKU, рейтинг продавца
- [ ] VK / Telegram API — подписчики, активность
- [ ] Новости и СМИ — упоминания, ключевые темы
- [ ] Playwright-stealth для обхода Cloudflare на Rusprofile
- [ ] Batch-режим с CSV-входом
- [ ] Авто-обновление через GitHub Releases

## Лицензия

MIT — используйте свободно.

## Ссылки

- Репозиторий: https://github.com/shray77/osint-scraper
- Релизы: https://github.com/shray77/osint-scraper/releases
- Issues: https://github.com/shray77/osint-scraper/issues
