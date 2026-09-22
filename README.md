# chrome-cdp-client

Drive your own Chrome "copies" from Python. A **copy** is a browser with a
dedicated profile directory (`--user-data-dir`) and a persistent
`--remote-debugging-port`. Site sessions (logins) live in the profile, so
"start a browser logged in as X" = "start the copy that uses X's directory".

Two channels are provided:

- **Raw CDP over WebSocket** (`scripts/page_call2.py`) — no daemon, no
  Selenium. Each call connects for a few milliseconds (~1.3 ms/eval), so the
  script works as a plain command-line tool.
- **Selenium attach** (`scripts/browser_control.py`) — connects through
  `debugger_address` to an already-running copy. On exit only chromedriver is
  stopped; the browser window stays open.

## Layout

```
scripts/browser_control.py     copy launch/status/stop + Selenium attach
scripts/page_call2.py          fast CDP client (eval, body, links, click, ...)
scripts/open_browser.py        CLI: open a copy, show status
scripts/browsers.example.json  config template -> copy to scripts/browsers.json
docs/                          reference & troubleshooting
```

## Setup

```bash
pip install -r requirements.txt        # websocket-client, selenium
copy scripts\browsers.example.json scripts\browsers.json
# point each "profile" at a real profile directory; pick free ports
```

## page_call2.py — commands

```bash
python scripts/page_call2.py --account 1 eval 'document.title'
python scripts/page_call2.py --account 1 --tab docs eval 'location.href'
python scripts/page_call2.py --account 1 oneshot '{"cmd":"body","max":3000}'
python scripts/page_call2.py --account 1 oneshot '{"cmd":"click","by":"css","finder":"button[type=submit]"}'
python scripts/page_call2.py --account 1 snapshot 3000      # page text from the AX tree
python scripts/page_call2.py --account 1 tabs               # list windows
python scripts/page_call2.py --account 1 bench              # channel timing
```

`oneshot` commands: `get`, `body`, `links`, `controls`, `js`, `click`, `fill`,
`tabs`, `switch`, `gmail_code` (extracts a one-time code from Gmail search
results; pass `"query"` with Gmail search operators).

## Selenium attach to an open browser

```python
import browser_control as bc

copy = bc.get_copy("1")
bc.ensure_browser(copy)            # start the copy if its port is closed
driver = bc.attach_driver(copy)    # 3 attempts; window stays open after
handle = bc.ensure_tab(driver, ("https://mail.google.com",))
# ... use driver ...
bc.release_driver(driver)          # stops only chromedriver
```

## open_browser.py

```bash
python scripts/open_browser.py --status
python scripts/open_browser.py --copy 1
python scripts/open_browser.py --copy all --url https://example.com
```

See `docs/troubleshooting.md` for port, DevTools and WS-403 issues.
