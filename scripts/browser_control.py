"""Управление копиями Chrome с портом CDP-отладки.

Копия браузера = отдельный каталог профиля (--user-data-dir) и свой порт
remote-debugging. Сессии сайтов живут в каталоге профиля, поэтому «запустить
браузер с нужным аккаунтом» = запустить копию с его каталогом (сессии
восстанавливаются сами). Подключение Selenium — через debugger_address к
запущенной копии; после работы останавливается только chromedriver, окно
копии остаётся открытым.

Конфиг копий — browsers.json рядом со скриптом.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BROWSERS_JSON = ROOT / "browsers.json"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
]


def console_guard():
    """Под pythonw потоков вывода нет — подменяем, чтобы print не ронял процесс."""
    import os

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
        else:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def load_browsers():
    if not BROWSERS_JSON.exists():
        raise RuntimeError(f"Нет конфига копий браузера: {BROWSERS_JSON}")
    raw = json.loads(BROWSERS_JSON.read_text(encoding="utf-8"))
    copies = []
    for c in raw.get("copies", []):
        profile = Path(c["profile"])
        if not profile.is_absolute():
            profile = (ROOT / profile).resolve()
        copies.append({
            "name": str(c["name"]),
            "port": int(c["port"]),
            "profile": profile,
            "profile_subdir": c.get("profile_subdir"),
            "chrome_path": c.get("chrome_path") or raw.get("chrome_path"),
        })
    if not copies:
        raise RuntimeError("browsers.json: пустой список copies")
    return {"chrome_path": raw.get("chrome_path"), "copies": copies}


def get_copy(name=None):
    copies = load_browsers()["copies"]
    if name is None:
        return copies[0]
    for c in copies:
        if c["name"] == str(name):
            return c
    raise KeyError(
        "Копия браузера «%s» не описана в browsers.json. Доступны: %s"
        % (name, ", ".join(c["name"] for c in copies))
    )


def port_open(port, host="127.0.0.1", timeout=0.4):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_chrome(chrome_path=None):
    candidates = []
    if chrome_path:
        candidates.append(Path(chrome_path))
    try:
        candidates.append(Path(load_browsers()["chrome_path"]))
    except Exception:
        pass
    candidates += [Path(p) for p in _CHROME_CANDIDATES]
    for p in candidates:
        if p.is_file():
            return str(p)
    raise RuntimeError("chrome.exe не найден; укажите путь в browsers.json (chrome_path)")


def launch_copy(copy, new_window_url=None, wait_port=25):
    """Запустить копию Chrome; если уже запущена — открыть новое окно (по желанию).

    Порт отладки задаётся только при старте копии: если Chrome с этим профилем
    уже работает без порта, повторный запуск лишь открывает окно — тогда
    ensure_browser сообщит об ошибке, и копию надо перезапустить.
    """
    running = port_open(copy["port"])
    chrome = find_chrome(copy.get("chrome_path"))
    args = [chrome, f"--user-data-dir={copy['profile']}"]
    if not running:
        args += [
            f"--remote-debugging-port={copy['port']}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--restore-last-session",
            "--disable-blink-features=AutomationControlled",
            # Не качать on-device ИИ-модели Chrome (OptGuide / Gemini Nano):
            # разрастались до ГБ в профиле копии; автоматизации не нужны.
            "--disable-features=OptimizationGuideModelDownloading",
        ]
    if (not running) and copy.get("profile_subdir"):
        # В каталоге копии может лежать несколько профилей Chrome — тогда
        # холодный старт показывает окно выбора профиля, и автоматизация
        # встаёт. Открываем конкретный профиль без выбора.
        args.append(f"--profile-directory={copy['profile_subdir']}")
    if new_window_url:
        if running:
            args += ["--new-window", new_window_url]
        else:
            args.append(new_window_url)
    subprocess.Popen(args, close_fds=True)
    if running:
        return True
    deadline = time.time() + wait_port
    while time.time() < deadline:
        if port_open(copy["port"]):
            time.sleep(1)  # дать браузеру подняться
            return True
        time.sleep(0.5)
    raise RuntimeError(
        f"Копия «{copy['name']}» не открыла порт {copy['port']} за {wait_port} с. "
        "Вероятно, Chrome с этим профилем уже запущен без порта отладки — "
        "закройте его и запустите снова (open_browser.py)."
    )


def ensure_browser(copy, wait_port=25):
    if port_open(copy["port"]):
        return True
    return launch_copy(copy, wait_port=wait_port)


def devtools_alive(copy):
    """Отвечает ли копия на HTTP-запросы DevTools, а не просто держит порт.

    После сна/гибернации Chrome может держать порт, но не отвечать на
    /json/version — тогда attach даёт SessionNotCreatedException.
    """
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{copy['port']}/json/version", timeout=3
        ) as r:
            return r.status == 200
    except Exception:
        return False


def stop_copy(copy):
    """Завершить все процессы Chrome копии (по каталогу профиля).

    Нужно, когда копия «залипла» после сна/гибернации: порт открыт, но
    DevTools не отвечает. Перезапуск копии восстанавливает вкладки сессии.
    """
    ps = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -like '*{prof}*' }; "
        "foreach ($x in ($p | Sort-Object ProcessId)) "
        "{ Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }"
    ).replace("{prof}", str(copy["profile"]))
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, creationflags=NO_WINDOW,
    )


def attach_driver(copy, attempts=3):
    """Selenium-подключение к запущенной копии (копия не закрывается при завершении).

    Подключение повторяется: сразу после запуска или после сна/гибернации
    Chrome может отвечать на порт, но не пускать chromedriver — единственная
    попытка даёт SessionNotCreatedException. Лог chromedriver — в
    chromedriver.log рядом со скриптом (для диагностики).
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    last = None
    for attempt in range(attempts):
        opts = Options()
        opts.debugger_address = f"127.0.0.1:{copy['port']}"
        try:
            svc = Service(log_output=str(ROOT / "chromedriver.log"))
        except TypeError:
            svc = None
        try:
            return webdriver.Chrome(options=opts, service=svc)
        except Exception as e:
            last = e
            time.sleep(5)
    raise last


def ensure_tab(d, url_prefixes):
    """Переключиться на вкладку с URL-префиксом; такой нет — открыть новую вкладку."""
    prefixes = tuple(url_prefixes)
    for handle in d.window_handles:
        try:
            d.switch_to.window(handle)
            url = d.current_url or ""
        except Exception:
            continue
        if url.startswith(prefixes):
            return handle
    d.switch_to.new_window("tab")
    return d.current_window_handle


def release_driver(d):
    """Отключиться, не закрывая браузер: останавливается только chromedriver."""
    try:
        d.service.stop()
    except Exception:
        pass
