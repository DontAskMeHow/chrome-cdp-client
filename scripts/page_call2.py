"""page_call2.py — быстрый CDP-клиент к копиям Chrome (WebSocket, без Selenium).

Команды: get, body, links, controls, js, click, fill, tabs, switch, gmail_code,
плюс дополнительные возможности:
  - eval        — сырой JS в странице (return не обязателен)
  - snapshot    — текст страницы из accessibility-дерева (Accessibility.getFullAXTree)
  - --tab       — выбор рабочей вкладки по подстроке URL/заголовка
  - bench       — локальные замеры канала

Канал: WebSocket к remote-debugging порту копии (json/list -> webSocketDebuggerUrl).
Подключение ~5-30 мс, поэтому демон не нужен — соединяемся на каждый вызов.

Использование:
  page_call2.py --account 1 eval 'document.title'
  page_call2.py --account 1 oneshot '{"cmd":"body","max":3000}'
  page_call2.py --account 1 oneshot-many '[{"cmd":"body"},{"cmd":"links"}]'
  page_call2.py --account 1 snapshot 3000
  page_call2.py --account 1 bench
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import websocket  # noqa: E402

import browser_control as bc  # noqa: E402


def _http_json(url, timeout=10):
    return json.load(urllib.request.urlopen(url, timeout=timeout))


class CDP:
    """Одно соединение к одной вкладке копии."""

    def __init__(self, account="1", tab=None):
        self.port = int(bc.get_copy(account)["port"])
        self.tab_hint = tab
        self.ws = None
        self.rid = 0
        self.target = self._pick_target(tab)
        self.connect_ms = 0

    # ---------- транспорт ----------

    def _list(self):
        return _http_json(f"http://127.0.0.1:{self.port}/json/list")

    def _pick_target(self, hint):
        lst = dict()
        for t in self._list():
            if t.get("type") == "page":
                lst[t["id"]] = t
        if not lst:
            raise RuntimeError("нет открытых вкладок в копии")
        if hint:
            for t in lst.values():
                if hint in (t.get("url", "") + "|" + t.get("title", "")):
                    return t
        for t in lst.values():
            if t.get("url", "").startswith("http"):
                return t
        return next(iter(lst.values()))

    def connect(self):
        if self.ws:
            self.close()
        t0 = time.time()
        self.ws = websocket.create_connection(self.target["webSocketDebuggerUrl"], timeout=20)
        self.connect_ms = (time.time() - t0) * 1000

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def call(self, method, params=None):
        if not self.ws:
            self.connect()
        self.rid += 1
        rid = self.rid
        self.ws.send(json.dumps({"id": rid, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == rid:
                if "error" in m:
                    return {"__error": m["error"].get("message", str(m["error"]))[:200]}
                res = m.get("result", {})
                ed = m.get("exceptionDetails") or res.get("exceptionDetails")
                if ed:
                    desc = ed.get("exception", {}).get("description") or ed.get("text") or "exception"
                    res = dict(res)
                    res["__error"] = str(desc)[:200]
                return res

    def eval(self, expr, timeout_ok=False):
        """Выполнить JS и вернуть значение: выражение оборачивается в IIFE с return;
        верхнеуровневый `return`-стиль (как в Selenium execute_script) — без префикса."""
        if re.match(r"\s*return\b", expr):
            expr = "(function(){" + expr + "})()"
        else:
            expr = "(function(){ return (" + expr + ") })()"
        r = self.call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": True})
        if "__error" in r:
            return r
        if "exceptionDetails" in r:
            det = r["exceptionDetails"]
            desc = det.get("exception", {}).get("description") or det.get("text") or "ex"
            return {"__error": str(desc)[:200]}
        return {"value": r.get("result", {}).get("value")}

    # ---------- командный уровень ----------

    def cmd_get(self, c):
        url = c["url"]
        self.call("Page.navigate", {"url": url})
        self.ready(int(c.get("wait", 5)))
        return {"url": self.eval("location.href").get("value"),
                "title": self.eval("document.title").get("value"),
                "body": (self.eval("(document.body?document.body.innerText:'')").get("value") or "")[:int(c.get("body_max", 1200))]}

    def cmd_body(self, c):
        txt = self.eval("(document.body?document.body.innerText:'')||'__none__'").get("value") or ""
        if txt == "__none__":
            txt = ""
        mx = int(c.get("max", 3000))
        return {"body": txt[:mx] + (f" ...(всего {len(txt)} симв.)" if len(txt) > mx else ""),
                "url": self.eval("location.href").get("value")}

    def cmd_links(self, c):
        filt = (c.get("filter") or "").lower()
        raw = self.eval(
            "JSON.stringify(Array.from(document.querySelectorAll('a')).slice(0,3000).map(a=>"
            "[(a.innerText||'').trim().replace(/\\s+/g,' ').slice(0,70),a.href||'']))").get("value")
        out = []
        for t, h in json.loads(raw or "[]"):
            if filt and filt not in (t + h).lower():
                continue
            out.append({"t": t, "h": h[:150]})
            if len(out) >= int(c.get("max", 120)):
                break
        return {"links": out}

    def cmd_controls(self, c):
        kind = c.get("kind", "all")
        filt = (c.get("filter") or "").lower()
        sel = {"all": "button,input,a[href]",
               "buttons": "button",
               "inputs": "input",
               "links": "a[href]"}.get(kind, kind)
        raw = self.eval(
            "JSON.stringify(Array.from(document.querySelectorAll(%s)).slice(0,500).map(el=>{"
            "return [el.tagName,(el.innerText||'').trim().replace(/\\s+/g,' ').slice(0,60),"
            "el.type||'',el.placeholder||'',el.href||'',el.getAttribute('data-qa')||'']}))"
            % json.dumps(sel)).get("value")
        out = []
        for tag, t, typ, ph, href, qa in json.loads(raw or "[]"):
            line = f"{t} {typ} {ph} {href} {qa}".lower()
            if filt and filt not in line:
                continue
            out.append({"tag": tag.lower(), "t": t, "type": typ, "ph": ph, "href": href[:120], "qa": qa})
            if len(out) >= int(c.get("max", 80)):
                break
        return {"items": out}

    def cmd_js(self, c):
        r = self.eval(c["script"])
        if "__error" in r:
            return {"error": r["__error"]}
        return {"result": r.get("value")}

    def cmd_click(self, c):
        el, err = self._find(c)
        if err:
            return {"error": err}
        r = self.eval("%s.click()" % el)
        if "__error" in r:
            return {"error": r["__error"]}
        return {"clicked": True}

    def cmd_fill(self, c):
        el, err = self._find(c)
        if err:
            return {"error": err}
        js = ("(function(el,v){var d=Object.getOwnPropertyDescriptor("
              "Object.getPrototypeOf(el),'value').set; d.call(el,v);"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "el.dispatchEvent(new Event('change',{bubbles:true}));"
              "return el.value})(%s,%s)") % (el, json.dumps(c["value"]))
        r = self.eval(js)
        if "__error" in r:
            return {"error": r["__error"]}
        return {"filled": True, "value": r.get("value")}

    def _find(self, c):
        by = c.get("by", "css")
        finder = json.dumps(c["finder"])
        idx = int(c.get("index", 0))
        if by == "css":
            expr = "Array.from(document.querySelectorAll(%s))[%d]||null" % (finder, idx)
        elif by == "id":
            expr = "document.getElementById(%s)" % finder
        elif by == "xpath":
            expr = ("(function(){var r=document.evaluate(%s,document,null,"
                    "XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null);"
                    "return r.snapshotLength>%d?r.snapshotItem(%d):null})()" % (finder, idx, idx))
        elif by == "text":
            expr = ("(function(){var els=Array.from(document.querySelectorAll("
                    "'a,button,[role=button],[type=submit],label,span,div')).filter("
                    "e=>(e.innerText||'').trim().toLowerCase().includes(%s));"
                    "return els[%d]||null})()") % (finder.lower(), idx)
        else:
            return None, f"неизвестный by: {by}"
        r = self.eval("Boolean(%s)?1:0" % expr)
        if not r.get("value"):
            return None, f"not found: {c['finder']}"
        return expr, None

    def cmd_tabs(self, c):
        out = []
        for i, t in enumerate(self._list()):
            if t.get("type") != "page":
                continue
            out.append({"i": i, "url": (t.get("url") or "")[:140],
                        "title": (t.get("title") or "")[:60],
                        "active": t.get("id") == self.target.get("id")})
        return {"tabs": out}

    def cmd_switch(self, c):
        pages = [t for t in self._list() if t.get("type") == "page"]
        if "href_sub" in c:
            t = next((t for t in pages if c["href_sub"] in (t.get("url") or "")), None)
        else:
            idx = int(c.get("index", -1))
            t = pages[idx] if 0 <= idx < len(pages) else None
        if not t:
            return {"error": "вкладка не найдена"}
        self._activate(t["id"])
        self.target = t
        return {"switched": t.get("url")}

    def _activate(self, target_id):
        ver = _http_json(f"http://127.0.0.1:{self.port}/json/version")
        bw = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=10)
        try:
            rid = 1
            bw.send(json.dumps({"id": rid, "method": "Target.activateTarget",
                                "params": {"targetId": target_id}}))
            while True:
                m = json.loads(bw.recv())
                if m.get("id") == rid:
                    break
        finally:
            bw.close()
        time.sleep(0.3)

    def cmd_gmail_code(self, c):
        # Gmail-запрос (search-операторы); дефолт — generic-пример, задаётся в "query"
        query = c.get("query", 'subject:"code" newer_than:1d')
        pat = c.get("regex", r"\b(\d{6})\b")
        max_wait = int(c.get("max_wait", 90))
        url = "https://mail.google.com/mail/u/0/#search/" + urllib.parse.quote(query)
        ver = _http_json(f"http://127.0.0.1:{self.port}/json/version")
        bw = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=10)
        try:
            bw.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                "params": {"url": url}}))
            while True:
                m = json.loads(bw.recv())
                if m.get("id") == 1:
                    tid = m["result"]["targetId"]
                    break
        finally:
            bw.close()
        deadline = time.time() + max_wait
        while time.time() < deadline:
            time.sleep(3)
            pages = {t["id"]: t for t in self._list()}
            if tid in pages and pages[tid]["webSocketDebuggerUrl"]:
                break
        ws = websocket.create_connection(pages[tid]["webSocketDebuggerUrl"], timeout=20)
        try:
            self.ws, old_ws, old_target = ws, self.ws, self.target
            self.target = pages[tid]
            self.rid = 0
            code, body = None, ""
            while time.time() < deadline:
                time.sleep(4)
                row = self.eval("Boolean(document.querySelector('tr.zA,[role=row]'))").get("value")
                if row:
                    self.eval("document.querySelector('tr.zA,[role=row]').click()")
                    time.sleep(4)
                    body = self.eval("document.body.innerText").get("value") or ""
                    m = re.search(pat, body)
                    if m:
                        code = m.group(1)
                        break
            try:
                self._close_target(tid)
            except Exception:
                pass
            return {"code": code, "body": body[:300]}
        finally:
            self.ws, self.target = old_ws, old_target
            try:
                ws.close()
            except Exception:
                pass

    def _close_target(self, tid):
        ver = _http_json(f"http://127.0.0.1:{self.port}/json/version")
        bw = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=10)
        try:
            bw.send(json.dumps({"id": 1, "method": "Target.closeTarget",
                                "params": {"targetId": tid}}))
            while True:
                m = json.loads(bw.recv())
                if m.get("id") == 1:
                    return
        finally:
            bw.close()

    def snapshot(self, max_chars=3000):
        """Текст страницы из accessibility-дерева (AX)."""
        self.call("Accessibility.enable")
        tree = self.call("Accessibility.getFullAXTree")
        if "__error" in tree or not tree.get("nodes"):
            # запасной вариант — plain text
            txt = self.eval("document.body?document.body.innerText:''").get("value") or ""
            return {"fallback": "innerText", "text": txt[:max_chars]}
        nodes = {n["nodeId"]: n for n in tree["nodes"]}
        roots = [n for n in tree["nodes"] if not n.get("parentId")]
        lines, total = [], 0

        def walk(nid, depth):
            nonlocal total
            n = nodes[nid]
            ignored = n.get("ignored")
            if not ignored:
                role = (n.get("role") or {}).get("value", "")
                name = (n.get("name") or {}).get("value", "") or ""
                val = (n.get("value") or {}).get("value", "") or ""
                if role and (name or val):
                    line = "  " * min(depth, 6) + f"{role}: {name}" + (f" [{val}]" if val else "")
                    if total + len(line) < max_chars:
                        lines.append(line)
                        total += len(line) + 1
            for ch in n.get("childIds") or []:
                walk(ch, depth if ignored else depth + 1)

        for r in roots:
            walk(r["nodeId"], 0)
        return {"text": "\n".join(lines), "roles": len(lines)}

    def ready(self, wait=5):
        """Дождаться document.readyState (после навигации), но не дольше wait сек."""
        deadline = time.time() + wait
        while time.time() < deadline:
            st = (self.eval("document.readyState") or {}).get("value")
            if st == "complete":
                return st
            time.sleep(0.3)
        return st or "?"

    # ---------- обслуживание ----------

    def run_cmd(self, c):
        name = c.get("cmd", "")
        fn = getattr(self, "cmd_" + name, None)
        if not fn:
            return {"error": "unknown cmd: " + name}
        try:
            return fn(c)
        except Exception as e:
            return {"error": str(e)[:200]}


def bench(account):
    cdp = CDP(account)
    r = []
    t0 = time.time()
    cdp.connect()
    r.append(("connect", (time.time() - t0) * 1000))
    t0 = time.time()
    for i in range(30):
        cdp.eval("1+" + str(i))
    dt = (time.time() - t0) * 1000
    r.append(("30 eval", dt))
    r.append(("eval/each", dt / 30))
    t0 = time.time()
    title = cdp.eval("document.title").get("value")
    r.append(("title", (time.time() - t0) * 1000))
    if title:
        t0 = time.time()
        txt = cdp.eval("document.body?document.body.innerText:''").get("value") or ""
        r.append(("innerText", (time.time() - t0) * 1000))
        t0 = time.time()
        ax = cdp.snapshot(2000)
        r.append(("snapshot2000", (time.time() - t0) * 1000))
        t0 = time.time()
        links = cdp.cmd_links({"max": 50})
        r.append(("links50", (time.time() - t0) * 1000))
        r.append(("page", (title or "")[:40]))
    cdp.close()
    return r, (len(txt) if title else 0), (len(ax.get("text", "")) if title else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="1")
    ap.add_argument("--tab", default=None, help="подстрока URL/заголовка вкладки")
    ap.add_argument("command", nargs="?")
    ap.add_argument("arg", nargs="?")
    a = ap.parse_args()

    if a.command == "bench":
        for name, v in bench(a.account)[0]:
            print(f"{name}: {v:8.1f} ms" if isinstance(v, float) else f"{name}: {v}")
        return

    cdp = CDP(a.account, a.tab)
    cdp.connect()
    try:
        if a.command == "eval":
            print(json.dumps(cdp.eval(a.arg), ensure_ascii=False))
        elif a.command == "oneshot":
            print(json.dumps(cdp.run_cmd(json.loads(a.arg)), ensure_ascii=False))
        elif a.command == "oneshot-many":
            for c in json.loads(a.arg):
                print(json.dumps(cdp.run_cmd(c), ensure_ascii=False), flush=True)
        elif a.command == "snapshot":
            mx = int(a.arg) if a.arg else 3000
            print(json.dumps(cdp.snapshot(mx), ensure_ascii=False))
        elif a.command == "tabs":
            print(json.dumps(cdp.cmd_tabs({}), ensure_ascii=False))
        elif a.command is None:
            ap.print_help()
        else:
            print(json.dumps({"error": "неизвестная команда CLI"}, ensure_ascii=False))
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
