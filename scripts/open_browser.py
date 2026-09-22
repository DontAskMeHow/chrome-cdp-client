"""Открыть или найти копии Chrome (по конфигу browsers.json).

  python open_browser.py --copy 1            # открыть/найти копию «1»
  python open_browser.py --copy all
  python open_browser.py --copy 2 --url https://example.com   # новое окно с адресом, если копия уже работает
  python open_browser.py --status
"""

import argparse

import browser_control as bc


def main():
    bc.console_guard()
    ap = argparse.ArgumentParser(description="Копии Chrome для автоматизации")
    ap.add_argument("--copy", help="имя копии из browsers.json или all")
    ap.add_argument("--url", help="адрес для нового окна, если копия уже запущена")
    ap.add_argument("--status", action="store_true", help="показать состояние копий")
    args = ap.parse_args()

    copies = bc.load_browsers()["copies"]
    if args.status or not args.copy:
        for c in copies:
            state = "запущена" if bc.port_open(c["port"]) else "закрыта"
            print(f"{c['name']}: {state} (порт {c['port']}, профиль {c['profile']})")
        return

    names = [c["name"] for c in copies] if args.copy == "all" else [args.copy]
    for name in names:
        copy = bc.get_copy(name)
        if bc.port_open(copy["port"]):
            if args.url:
                bc.launch_copy(copy, new_window_url=args.url)
                print(f"{copy['name']}: уже запущена — открыл новое окно {args.url}")
            else:
                print(f"{copy['name']}: уже запущена (порт {copy['port']})")
        else:
            bc.launch_copy(copy, new_window_url=args.url)
            print(f"{copy['name']}: запущена (порт {copy['port']})")


if __name__ == "__main__":
    main()
