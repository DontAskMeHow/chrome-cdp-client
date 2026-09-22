# browser_control.py — Selenium-библиотека

Импорт из других скриптов:
`sys.path.insert(0, <путь к каталогу scripts>)`, затем `import browser_control as bc`.

- `load_browsers()` / `get_copy(name)` — конфиг и конкретная копия (без имени — первая).
- `port_open(port)` — запущена ли копия.
- `ensure_browser(copy)` — гарантирует, что копия запущена (запускает при необходимости).
- `attach_driver(copy)` — Selenium-драйвер через `debugger_address` (с `detach`);
  копия **не закрывается** при завершении драйвера. Подключение повторяется
  (3 попытки — Chrome после сна/гибернации отвечает не сразу); диагностика —
  `chromedriver.log` рядом со скриптом.
- `devtools_alive(copy)` — отвечает ли копия на `/json/version` (порт открыт,
  но DevTools мёртв = «залипшая» копия).
- `stop_copy(copy)` — завершить все процессы Chrome копии по каталогу профиля
  (для перезапуска залипшей копии; вкладки сессии восстановятся).
- `ensure_tab(d, url_prefixes)` — переключиться на вкладку с нужным префиксом URL,
  нет такой — открыть новую.
- `release_driver(d)` — отключение без закрытия браузера (останавливается только chromedriver).
- **Прямой CDP**: копии запускаются с `--remote-allow-origins=*`, поэтому к порту
  отладки можно ходить без Selenium — `http://127.0.0.1:<port>/json/list` даёт
  `webSocketDebuggerUrl`, по WebSocket доступны `Runtime.evaluate`, `Page.navigate`,
  `Accessibility.getFullAXTree` (задержки ~2–30 мс против ~3.5 с у attach-цикла).
- `console_guard()` — безопасный вывод при запуске под `pythonw` (без консоли).
