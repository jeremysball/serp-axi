"""Spike (throwaway): SearXNG vs ddgs block rate per engine. Logs every call to JSONL."""

import json
import random
import time
import urllib.parse
import urllib.request

from ddgs import DDGS

QUERIES = [
    "rust borrow checker explained", "best sourdough hydration", "linux kernel 7.1 changelog",
    "how do heat pumps work in cold climates", "python asyncio taskgroup example", "mojeek search engine index size",
    "arch linux pacman hooks", "history of the byzantine empire", "postgres vacuum full vs vacuum",
    "tailscale exit node setup", "what is a bloom filter", "emacs doom keybindings cheat sheet",
    "typescript satisfies operator", "best budget mechanical keyboard 2026", "how to read a nutrition label",
    "playwright persistent context example", "sqlite wal mode concurrency", "toddler sleep regression 18 months",
    "kubernetes pod disruption budget", "marginalia small web search",
]
ENGINES = ["bing", "brave", "mojeek", "startpage", "yandex"]
GAP_S = 6.0


def searxng(q):
    url = "http://127.0.0.1:8888/search?" + urllib.parse.urlencode({"q": q, "format": "json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    per = {e: 0 for e in ENGINES}
    for res in data["results"]:
        for e in res["engines"]:
            per[e] = per.get(e, 0) + 1
    unresp = {name: reason for name, reason in data.get("unresponsive_engines", [])}
    return {"ms": int((time.monotonic() - t0) * 1000), "per_engine": per, "unresponsive": unresp}


def ddgs_one(q, backend):
    t0 = time.monotonic()
    try:
        res = DDGS(timeout=15).text(q, backend=backend, max_results=10)
        return {"ok": True, "n": len(res), "ms": int((time.monotonic() - t0) * 1000)}
    except Exception as ex:  # spike: record the failure class, don't hide it
        return {"ok": False, "err": f"{type(ex).__name__}: {str(ex)[:160]}", "ms": int((time.monotonic() - t0) * 1000)}


with open("./serp_probe.jsonl", "w") as log:
    for i, q in enumerate(QUERIES):
        row = {"i": i, "q": q, "ts": time.time(), "searxng": searxng(q), "ddgs": {}}
        for b in random.sample(ENGINES, len(ENGINES)):
            row["ddgs"][b] = ddgs_one(q, b)
            time.sleep(1.0)
        log.write(json.dumps(row) + "\n")
        log.flush()
        print(i, q, row["searxng"]["per_engine"], list(row["searxng"]["unresponsive"]),
              {b: (r["n"] if r["ok"] else "ERR") for b, r in row["ddgs"].items()}, flush=True)
        time.sleep(GAP_S + random.uniform(0, 2))
