## Findings (2026-10-02)

### Hard set (16 bot-hostile sites)

| Variant | ok | blocked | thin/err |
|---|---|---|---|
| headless_shell | 1 | 14 | 1 |
| headless_new | 1 | 12 | 3 |
| persistent_new | 1 | 12 | 3 |
| patchright_new | 1 | 12 | 1 |
| stealth_new | 6 | 8 | 2 |

stealth_new = full Chromium new headless, persistent profile, `--disable-blink-features=AutomationControlled`, a plain Chrome UA. Fingerprint: webdriver false, 5 plugins, `window.chrome` is an object. Patchright by itself still leaks webdriver true and the HeadlessChrome UA.

Nothing got past the Cloudflare "Just a moment" check (Stack Overflow, Indeed, Glassdoor), Zillow's PerimeterX "Press & Hold", or the blocks on G2, Etsy and the NYT. Those need L4 (a warm, logged-in profile) or L6 (a human).

### Real set (top 5 SearXNG results for 10 everyday queries, 50 URLs, 45 hosts)

| Rung | ok | p50 |
|---|---|---|
| plain HTTP, primp impersonate=random | 44 | 302ms |
| headless_new | 42 | 6.3s |
| stealth_new | 45 | 6.4s |
| HTTP first, stealth_new on a miss | 47 | |

- The browser recovered TikTok, YouTube and one Stack Overflow page.
- Two sites (sourdoughsavvy, backendmesh) blocked both browsers with "Checking your browser" but served plain HTTP. So the fallback ladder goes HTTP first.
- Still missing: one Stack Overflow page, a Reddit thread, and one site that timed out on every rung (probably down).

### Cold start
Chromium launch to about:blank, 250 to 1000ms. A warm daemon matters less than expected, though it's still worth it for keeping the profile warm (L4).

### Open
- Headed Chrome under Xvfb never opens CDP on this box (Arch, kernel 7.1). Not solved; new headless is the workaround.
- One run died with FileNotFoundError on the venv python, which was present when checked afterwards. Cause unknown, and it didn't recur.
- L4 warm-profile retest (second pass on the same profile) not run.
