"""Fetch a URL by climbing the challenge ladder (03-ladder.md). One rung per subprocess, SIGKILL at 90s.

Usage: ../spike-2026-10-03/.venv/bin/python ladder.py <out.jsonl> url...   (child: ladder.py --rung <rung> <url>)
Rung 1 uses a site API where one exists (reddit .json, HN Algolia), else primp. Full text goes to pages/.
"""
import asyncio, hashlib, json, os, re, signal, subprocess, sys, time, urllib.parse

RUNGS = ["http", "camoufox", "zendriver_cf", "zendriver_headed_cf"]
CHALLENGE = re.compile(r"just a moment|attention required|checking your browser|press & hold|verify you are human|"
                       r"prove your humanity|robot or human|access denied|blocked by network security|"
                       r"enable javascript and cookies", re.I)
JS_SHELL = re.compile(r"\bloading(\.\.\.|…| the )", re.I)
STRIP = "() => { document.querySelectorAll('script,style,noscript').forEach(e => e.remove()); return [document.title, document.body.innerText] }"


def api_url(url):
    u = urllib.parse.urlparse(url)
    if u.netloc.endswith("reddit.com") and "/comments/" in u.path:
        return "https://www.reddit.com" + u.path.rstrip("/") + ".json?limit=200"
    if u.netloc == "news.ycombinator.com" and "id=" in u.query:
        return "https://hn.algolia.com/api/v1/items/" + urllib.parse.parse_qs(u.query)["id"][0]
    return None


def flatten_api(url, data):
    out = []
    def walk(x):
        if isinstance(x, dict):
            for k in ("title", "selftext", "body", "text"):
                if isinstance(x.get(k), str) and x[k].strip():
                    who = x.get("author") or ""
                    pts = x.get("score", x.get("points"))
                    out.append(f"[{who} {pts}] {re.sub(r'<[^>]+>', ' ', x[k])}")
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(data)
    return "\n\n".join(out)


def rung_http(url):
    import primp
    for _ in range(5):  # H-sample: "random" can pick a profile this primp build rejects (BuilderError chrome_133)
        try:
            c = primp.Client(impersonate="random", impersonate_os="random", follow_redirects=True, timeout=30)
            break
        except Exception as ex:
            if "Invalid impersonate" not in str(ex): raise
    else:
        c = primp.Client(impersonate="chrome", follow_redirects=True, timeout=30)
    api = api_url(url)
    r = c.get(api or url, headers={"User-Agent": "serp-axi-research/0.1"} if api else None)
    if api and r.status_code == 200:
        return "api", flatten_api(url, r.json()), r.status_code
    text = r.text
    title = (re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I) or [None, ""])[1]
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    return title.strip(), re.sub(r"[ \t]+", " ", body), r.status_code


def rung_camoufox(url):
    from camoufox.sync_api import Camoufox
    with Camoufox(headless=True, humanize=True) as b:
        p = b.new_page()
        resp = p.goto(url, wait_until="domcontentloaded", timeout=30000)
        p.wait_for_timeout(12000)
        title, text = p.evaluate(STRIP)
        return title, text, resp.status if resp else None


async def rung_zendriver(url, headed):
    import zendriver as zd
    browser = await zd.start(headless=not headed, user_data_dir=os.path.abspath(f"profiles/zd{'_headed' if headed else ''}"),
                             browser_connection_max_tries=80)  # H11
    try:
        tab = await browser.get(url)
        await tab.sleep(6)
        try:
            await tab.verify_cf(click_delay=3, timeout=20)
        except Exception:
            pass
        await tab.sleep(6)
        title, text = await tab.evaluate(f"({STRIP})()")  # H12: zendriver evaluates the expression; an arrow fn comes back uncalled as {}
        return title, text, None
    finally:
        await browser.stop()


def child(rung, url):
    if rung == "http":
        title, text, status = rung_http(url)
    elif rung == "camoufox":
        title, text, status = rung_camoufox(url)
    elif rung == "zendriver_cf":
        title, text, status = asyncio.run(rung_zendriver(url, False))
    else:
        disp = f":{200 + os.getpid() % 500}"
        x = subprocess.Popen(["Xvfb", disp, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ["DISPLAY"] = disp
        time.sleep(1.5)
        try:
            title, text, status = asyncio.run(rung_zendriver(url, True))
        finally:
            x.kill()
    text = re.sub(r"\n\s*\n+", "\n\n", text or "").strip()
    print(json.dumps({"title": title or "", "text": text, "status": status}))


def verdict(rec, rung):
    if rec.get("status") and rec["status"] >= 400 and rec["title"] != "api":
        return "blocked", f"status {rec['status']}"
    if CHALLENGE.search(rec["title"] + " " + rec["text"][:600]):
        return "blocked", "challenge marker"
    if rung == "http" and rec["title"] != "api" and JS_SHELL.search(rec["text"]):
        return "thin", "js shell (loading marker)"  # rung-1 html of a client-rendered page; content never arrived
    if len(rec["text"]) < 800:
        return "thin", f"{len(rec['text'])} chars"
    return "ok", f"{len(rec['text'])} chars"


DEAD_NET = re.compile(r"DNSError|dns error|failed to lookup|Name or service not known|ConnectError|Connection refused|"
                      r"connection reset|certificate|tls handshake|received corrupt message|ERR_SSL|TimeoutError|timed out|"
                      r"ERR_NAME_NOT_RESOLVED|ERR_CONNECTION", re.I)  # any TLS failure is dead; plain-http fallback is an open item (BAL-40)
SHELL_FLOOR = 300  # rung-1 text beyond the title; below this only a browser can say what the page is
DEAD_STATUS = {404, 410, 521, 522, 523, 525, 526, 530}  # gone, or Cloudflare saying the origin is down
KINDS = {
    "content": "a real page from a live site: articles, products, listings, docs, a company or personal homepage",
    "loading_shell": "a page skeleton waiting for JavaScript: loading text, spinner, nav or footer only, the real content has not arrived",
    "challenge": "a bot check: captcha, 'verify you are human', access denied, rate limited, or a firewall block page",
    "dead": "no live site: parked or for-sale domain, hosting default or placeholder page, suspended account, server error page, or empty",
}


def jev(url, rec):
    """Ask Jev what kind of page this is. One request, one choice question; only input tokens bill."""
    import urllib.request
    key = open(os.environ.get("NANOGPT_KEY_FILE") or os.path.join(os.environ["XDG_RUNTIME_DIR"], "nanogpt.key")).read().strip()
    state = f"URL: {url}\nHTTP status: {rec.get('status')}\nTitle: {rec['title']}\nVisible text ({len(rec['text'])} chars, first 2500):\n{rec['text'][:2500]}"
    body = {"model": "typesafe/jev-latest", "state": state, "questions": {"kind": {
        "type": "choice", "instructions": "What kind of page did this fetch return?", "criteria": KINDS}}}
    req = urllib.request.Request("https://nano-gpt.com/api/v1/systemone", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        a = json.load(r)["answers"]["kind"]
    return a["choice"], round(a["confidence"], 3)


def judge(url, rec, rung):
    """Final verdict for one rung: deterministic status rules first, then Jev on the text. Regex verdict kept as baseline."""
    base, why = verdict(rec, rung)
    if rec["title"] == "api":
        return "ok", why, base, None
    if rec.get("status") in DEAD_STATUS:
        return "dead", f"status {rec['status']}", base, None
    if rec.get("status") and rec["status"] >= 400:
        return "blocked", f"status {rec['status']}", base, None
    if rung == "http" and len(rec["text"].replace(rec["title"], "", 1).strip()) < SHELL_FLOOR:
        return "thin", f"{len(rec['text'])} chars, under rung-1 floor", base, None  # H13: Jev calls a bare title "content"
    try:
        kind, conf = jev(url, rec)
    except Exception as ex:  # no silent guess: say the judge failed and fall back to the regex verdict, labelled
        return base, f"jev failed ({type(ex).__name__}); regex: {why}", base, None
    v = {"content": "ok", "loading_shell": "thin", "challenge": "blocked", "dead": "dead"}[kind]
    return v, f"jev {kind} {conf}, {len(rec['text'])} chars", base, {"kind": kind, "confidence": conf}


def climb(url):
    tried = []
    for rung in RUNGS:
        p = subprocess.Popen([sys.executable, __file__, "--rung", rung, url], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = p.communicate(timeout=90)
            lines = [l for l in out.splitlines() if l.startswith("{")]
            rec = json.loads(lines[-1]) if lines else None
            base, j = None, None
            if rec:
                v, why, base, j = judge(url, rec, rung)
                with open(f"pages/{hashlib.sha1(url.encode()).hexdigest()[:10]}.{rung}.txt", "w") as f:
                    f.write(f"URL: {url}\nSTATUS: {rec.get('status')}\nTITLE: {rec['title']}\n\n{rec['text']}")
            else:
                why = (err.strip().splitlines() or ["?"])[-1][:160]
                v = "dead" if rung == "http" and DEAD_NET.search(err) else "error"
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); p.communicate(); rec, v, why, base, j = None, "hang", ">90s", None, None
        tried.append({"rung": rung, "verdict": v, "why": why, "regex": base, "jev": j})
        if v == "dead":  # a browser cannot revive a domain that does not resolve or a page that says it is parked
            return {"url": url, "rung": "dead", "tried": tried}
        if v == "ok":
            path = "pages/" + hashlib.sha1(url.encode()).hexdigest()[:10] + ".txt"
            with open(path, "w") as f:
                f.write(f"URL: {url}\nTITLE: {rec['title']}\n\n{rec['text']}")
            return {"url": url, "rung": rung, "page": path, "tried": tried}
    return {"url": url, "rung": "stop", "tried": tried}


if __name__ == "__main__":
    if sys.argv[1] == "--rung":
        child(sys.argv[2], sys.argv[3])
    else:
        os.makedirs("pages", exist_ok=True); os.makedirs("profiles", exist_ok=True)
        last = {}
        with open(sys.argv[1], "a") as out:
            for url in sys.argv[2:]:
                host = urllib.parse.urlparse(url).netloc
                if host in last and time.time() - last[host] < 15:
                    time.sleep(15 - (time.time() - last[host]))
                rec = climb(url)
                last[host] = time.time()
                rec["ts"] = time.strftime("%H:%M:%S")
                out.write(json.dumps(rec) + "\n"); out.flush()
                print(rec["rung"], url, [(t["rung"], t["verdict"], t["why"]) for t in rec["tried"]], flush=True)
