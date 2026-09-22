# page_call2.py — быстрый CDP-клиент копий Chrome (без Selenium)

Канонический инструмент «хождения по страницам» копий. Демон не нужен:
подключение по WebSocket стоит миллисекунды, соединяемся на каждый вызов.

```bash
python scripts/page_call2.py --account 1 eval 'document.title'
python scripts/page_call2.py --account 1 oneshot '{"cmd":"body","max":3000}'
python scripts/page_call2.py --account 1 oneshot-many '[{"cmd":"body"},{"cmd":"links","filter":"login"}]'
python scripts/page_call2.py --account 1 snapshot 3000      # текст страницы из AX-дерева
python scripts/page_call2.py --account 1 --tab docs eval 'location.href'  # выбор вкладки по подстроке
python scripts/page_call2.py --account 1 bench
```

- Набор команд: `get`, `body`, `links`, `controls`, `js`,
  `click`, `fill`, `tabs`, `switch` (с активацией вкладки Target.activateTarget),
  `gmail_code`; `js` принимает и голые выражения (bare `return` оборачивается сам).
- `snapshot` — снимок Accessibility.getFullAXTree, лучшая «читалка страницы»:
  текст без стилей, ~0.45 с внутри процесса.
- Замеры 2026-09-12 (медиана трёх прогонов, вызов из шелла): один вызов eval/body/links
  **0.42–0.43 с** против **3.5–5.9 с** у Selenium-attach-цикла (×8–14); snapshot 0.85 с
  (аналога в Selenium не было). Лимит одной команды — старт Python (~0.4 с), канал 1.3 мс/eval.
