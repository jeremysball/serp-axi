"""Spike (throwaway): Q6, can Jev classify challenge pages? Baselines + harness mutations.

Usage: .venv/bin/python q6_jev.py <rows.jsonl> <out.jsonl> <mutation>
Mutations: none, shuffle (option order), neutral (option names a1..), blank (state = ""), no_title
"""

import json
import os
import random
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "spike-2026-10-02"))
from scrape_probe import classify  # noqa: E402  (the regex baseline)

# Hand labels by page state, written from reading every distinct (status, title, head) cluster.
# First match wins. Order matters: specific block pages before generic ones.
LABEL_RULES = [
    ("cf_challenge", r"just a moment|checking your browser|performing security verification"),
    ("cf_block", r"attention required! \| cloudflare|sorry, you have been blocked|additional verification required"),
    ("px_challenge", r"press & hold|robot or human\?|activate and hold|bloomberg - are you a robot"),
    ("captcha", r"prove your humanity"),
    ("hard_block", r"blocked - indeed|you've been blocked by network security|service unavailable"),
    ("login_wall", r"^999\t"),
]
LABELS = {
    "none": "Real page content is shown; no challenge or block.",
    "cf_challenge": "Cloudflare interstitial that may clear by itself or with a checkbox (\"Just a moment\", \"Checking your browser\").",
    "cf_block": "Cloudflare hard block (\"Sorry, you have been blocked\", Ray ID, no way through).",
    "px_challenge": "PerimeterX / HUMAN press-and-hold or \"Are you a robot\" page.",
    "datadome": "DataDome protected site returning an empty 403 body.",
    "captcha": "An image/checkbox captcha page asking the user to prove they are human.",
    "hard_block": "Other site-level block or error page, with no challenge to solve.",
    "login_wall": "A login or signup wall instead of the content.",
    "thin_js": "Page loaded but has almost no text (JS app not rendered, or empty shell).",
}
DATADOME_HOSTS = ("g2.com", "etsy.com", "nytimes.com")


def label(r):
    hay = f"{r.get('status')}\t{r.get('title', '')}\n{r.get('head', '')}".lower()
    for name, pat in LABEL_RULES:
        if re.search(pat, hay):
            return name
    if r.get("status") == 403 and r.get("chars", 0) < 50:
        return "datadome" if r.get("title", "") in DATADOME_HOSTS else "hard_block"
    if r.get("chars", 0) < 300:
        return "thin_js"
    return "none"


def state(r, mutation):
    if mutation == "blank":
        return ""
    title = "" if mutation == "no_title" else r.get("title", "")
    return (f"HTTP status: {r.get('status')}\nPage title: {title}\nVisible text length: {r.get('chars')} chars\n"
            f"Visible text excerpt: {r.get('head') or '(not captured)'}")


def jev(state_text, criteria, key):
    body = json.dumps({"model": "typesafe/jev-latest", "state": state_text, "questions": {"page": {
        "type": "choice", "criteria": criteria,
        "instructions": "A scraper fetched this web page. Which kind of page is it?"}}}).encode()
    for attempt in range(5):
        req = urllib.request.Request("https://nano-gpt.com/api/v1/systemone", data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)["answers"]["page"]
        except urllib.error.HTTPError as ex:
            if ex.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise


def main(rows_path, out_path, mutation):
    key_file = os.environ.get("NANOGPT_KEY_FILE") or os.path.join(os.environ["XDG_RUNTIME_DIR"], "nanogpt.key")
    key = open(key_file).read().strip()
    rng = random.Random(7)
    rows = [json.loads(l) for l in open(rows_path)]
    calls = 0
    with open(out_path, "w") as out:
        for r in rows:
            names = list(LABELS)
            if mutation in ("shuffle", "neutral"):
                rng.shuffle(names)
            alias = {n: (f"a{i}" if mutation == "neutral" else n) for i, n in enumerate(names)}
            criteria = {alias[n]: LABELS[n] for n in names}
            ans = jev(state(r, mutation), criteria, key)
            calls += 1
            back = {v: k for k, v in alias.items()}
            pred = back[ans["choice"]]
            regex_verdict, _ = classify(r.get("status"), r.get("title", ""), r.get("head", "") or "x" * r.get("chars", 0))
            out.write(json.dumps({"url": r["target"], "variant": r["variant"], "gold": label(r), "pred": pred,
                                  "confidence": ans.get("confidence"), "regex": regex_verdict,
                                  "mutation": mutation}) + "\n")
    print(f"{mutation}: {calls} Jev calls")


if __name__ == "__main__":
    main(*sys.argv[1:])
