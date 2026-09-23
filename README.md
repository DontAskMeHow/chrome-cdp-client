# chrome-cdp-client

Управление собственными «копиями» Chrome из Python. **Копия** — браузер с
отдельным каталогом профиля (`--user-data-dir`) и постоянным
`--remote-debugging-port`. Сессии сайтов (логины) живут в профиле, поэтому
«запустить браузер залогиненным как X» = «запустить копию с каталогом X».

Два канала работы:

- **Чистый CDP через WebSocket** (`scripts/page_call2.py`) — без демона и
  Selenium. Каждый вызов подключается на несколько миллисекунд
  (~1.3 мс/eval), поэтому скрипт работает как обычный инструмент командной
  строки.
- **Подключение Selenium** (`scripts/browser_control.py`) — через
  `debugger_address` к уже запущенной копии. При выходе останавливается
  только chromedriver; окно браузера остаётся открытым.

## Структура

```
scripts/browser_control.py     запуск/статус/остановка копий + подключение Selenium
scripts/page_call2.py          быстрый CDP-клиент (eval, body, links, click, ...)
scripts/open_browser.py        CLI: открыть копию, показать статус
scripts/browsers.example.json  шаблон конфигурации -> скопировать в scripts/browsers.json
docs/                          справочник и решение проблем
```

## Установка

```bash
pip install -r requirements.txt        # websocket-client, selenium
copy scripts\browsers.example.json scripts\browsers.json
# укажите каждому «профилю» реальный каталог профиля; выбирайте свободные порты
```

## page_call2.py — команды

```bash
python scripts/page_call2.py --account 1 eval 'document.title'
python scripts/page_call2.py --account 1 --tab docs eval 'location.href'
python scripts/page_call2.py --account 1 oneshot '{"cmd":"body","max":3000}'
python scripts/page_call2.py --account 1 oneshot '{"cmd":"click","by":"css","finder":"button[type=submit]"}'
python scripts/page_call2.py --account 1 snapshot 3000      # текст страницы из AX-дерева
python scripts/page_call2.py --account 1 tabs               # список окон
python scripts/page_call2.py --account 1 bench              # замер канала
```

Команды `oneshot`: `get`, `body`, `links`, `controls`, `js`, `click`, `fill`,
`tabs`, `switch`, `gmail_code` (извлекает одноразовый код из результатов
поиска Gmail; передайте `"query"` с поисковыми операторами Gmail).

## Подключение Selenium к открытому браузеру

```python
import browser_control as bc

copy = bc.get_copy("1")
bc.ensure_browser(copy)            # запустит копию, если её порт закрыт
driver = bc.attach_driver(copy)    # 3 попытки; окно после выхода останется открытым
handle = bc.ensure_tab(driver, ("https://mail.google.com",))
# ... работа с driver ...
bc.release_driver(driver)          # остановит только chromedriver
```

## open_browser.py

```bash
python scripts/open_browser.py --status
python scripts/open_browser.py --copy 1
python scripts/open_browser.py --copy all --url https://example.com
```

Вопросы портов, DevTools и ошибок WS-403 — `docs/troubleshooting.md`.
