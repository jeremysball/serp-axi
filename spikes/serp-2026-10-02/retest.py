"""Spike (throwaway): unconfounded Mojeek/Brave retest. SearXNG only, no ddgs traffic, wide gaps."""

import json
import random
import time
import urllib.parse
import urllib.request

QUERIES = ["sqlite fts5 tokenizer", "how to descale a kettle", "zig comptime tutorial", "fermentation airlock types",
           "openbsd pledge unveil", "best hiking boots wide feet", "nix flakes vs channels", "how tides work",
           "rust tokio select macro", "cast iron seasoning oil"]

with open("./retest.jsonl", "w") as log:
    for i, q in enumerate(QUERIES):
        url = "http://127.0.0.1:8888/search?" + urllib.parse.urlencode(
            {"q": q, "format": "json", "engines": "mojeek,brave"})
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
        per = {}
        for res in data["results"]:
            for e in res["engines"]:
                per[e] = per.get(e, 0) + 1
        row = {"i": i, "q": q, "per_engine": per, "unresponsive": data.get("unresponsive_engines", [])}
        log.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)
        time.sleep(15 + random.uniform(0, 5))
