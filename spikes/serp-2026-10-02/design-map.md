# Free SERP + scrape for serp-axi: design map

Status: **design in progress**. Nothing implemented. Last updated 2026-10-02.

## Goal

A $0 search and page-scrape path for personal agent use, small scale (tens of queries a day, one machine), inside the existing `serp-axi` CLI. The paid providers (Serper, Bright Data, Kagi) keep failing on credits or 429s, and agents fail over badly when they do.

## Settled decisions

- **One tool.** Everything lives in serp-axi behind a strategy pattern. No second search CLI for agents to pick between.
- **A daemon is fine.** A local SearXNG (and optionally a `ddgs api`) service is acceptable.
- **Engines:** Startpage, Marginalia, Bing, Yandex, Mojeek, Brave.
- **Query strategy:** query all of them and merge (dedupe by URL).
- **Scrape is in scope.** It uses a persistent Playwright browser profile with cookies.
- **Two separate problems, both needed:** getting SERP results (HTTP metasearch) and fetching pages behind the links (a real browser).
- **Anti-blocking:** layers L1 through L6 below, stacked. No L7 (paid proxies).
- **Fail fast.** A blocked engine or challenge page is reported as *blocked*, never as zero results or as page content.

## Verified facts

Checked against source on 2026-10-02: ddgs 9.16.0, SearXNG `19ffbcd`, serp-axi `97a763f`.

**serp-axi**
- TypeScript with one runtime dep (`@toon-format/toon` 4.1.1). Providers are switched by name in `src/commands/search.ts:106-120`, and `--provider` takes `serper | brightdata | kagi`. Each provider is a plain HTTP call through an injected `fetchImpl`.

**ddgs**
- HTTP via `primp` with `impersonate="random"`, `impersonate_os="random"` (`http_client.py:56-57`). TLS, HTTP/2 and UA all match a random real browser.
- No captcha detection and no back-off. Failures surface as `RatelimitException` or a generic error.
- One `proxy` setting; `"tb"` expands to Tor at `socks5h://127.0.0.1:9150` (`utils.py:70`).
- Backends include bing, brave, mojeek, startpage, yandex. **No Marginalia.**
- Ships an HTTP server (`ddgs api`, `GET /search/text` at `api_server/api.py:169`), so serp-axi can call it over HTTP with no Python in the CLI.
- `extract()` (`ddgs.py:245`) is a single GET that throws on any non-200. Fine for static pages, useless against JS or challenge pages.

**SearXNG**
- HTTP via `curl_cffi`, `DEFAULT_IMPERSONATE = "chrome"` (`searx/network/client.py:19`). Random UA from `gen_useragent()` (`searx/utils.py:74`).
- Captcha detection per engine, e.g. Startpage raises `SearxEngineCaptchaException` on the `/sp/captcha` redirect and solves an Anubis proof-of-work challenge (`searx/engines/startpage.py:2, 254, 278`).
- **Suspends blocked engines** (`searx/settings.yml:69-82`): captcha 1 h, 403 or 429 3 min, Cloudflare captcha 15 days, Cloudflare access denied 1 day, reCAPTCHA 7 days.
- Outgoing proxy pool, `source_ips` rotation and `using_tor_proxy` (`settings.yml` `outgoing:`).
- Marginalia **requires an API key** and ships disabled (`settings.yml:1652-1659`). Yandex and Mojeek ship disabled or inactive and need enabling.
- **No search-result cache.** `searx/cache.py` is an expiring key-value store engines use for their own state (tokens, codes). Caching is ours to build if we want it.

## SearXNG vs ddgs, bot detection

| | ddgs | SearXNG |
|---|---|---|
| Fingerprint | Random browser (primp) | Chrome (curl_cffi) |
| Per-engine workarounds | Thin | Deep (e.g. Startpage Anubis PoW) |
| Captcha detection | None | Explicit |
| Back-off on block | None | Engine suspension, tiered by block type |
| IP spreading | One proxy or Tor | Proxy pool, source IPs, Tor |
| Covers all six engines | No (no Marginalia) | Yes (Marginalia needs a key) |

Neither one *solves* captchas. Both disguise their traffic about equally well. SearXNG also stops hitting a blocked engine, which protects the IP's reputation when it runs unattended.

## Anti-blocking layers (stacked, L1-L6 adopted)

| Layer | What it does | Results side | Scrape side |
|---|---|---|---|
| L1 Coherent fingerprint | TLS, HTTP/2, headers and UA all agree with the claimed browser | Built into SearXNG and ddgs | A real browser gets this. Headless leaks some. |
| L2 Pacing | Minimum gap per engine or domain, jitter, concurrency cap | SearXNG `ban_time_on_fail`, plus our own per-engine floor | Our rate limit per domain |
| L3 Back-off on block | Detect captcha, 403 or 429 and stop hitting the target for a while | SearXNG suspension | Ours: cool-down table per domain in `XDG_STATE_HOME` |
| L4 Session continuity | Cookies and storage persist, so challenge passes get reused | Partial (SearXNG keeps Startpage's `sc` code) | Persistent browser profile |
| L5 Headed or stealth browser | Remove automation tells (`navigator.webdriver`, headless differences) | n/a | Headed Chromium under Xvfb, or a stealth fork |
| L6 Human in the loop | On a captcha, open the page headed, a human solves it once, the cookie lands in the profile | n/a | Escalation path |
| ~~L7 IP diversity~~ | Proxy pool, Tor, several source IPs | Out of scope (costs money, or Tor's reputation) | Out of scope |

A "real UA" alone does little. Modern detection checks that the UA agrees with the TLS fingerprint, HTTP/2 framing, `sec-ch-ua` client hints and JS-visible properties. A Chrome UA sent over Python's default TLS stack is a stronger bot signal than an honest one.

## Proposed shape (not yet approved)

- **Results:** a SearXNG daemon running the six engines. serp-axi gets a `searxng` strategy that is a plain HTTP provider, matching the existing `fetchImpl` pattern. A `ddgs api` daemon is an optional second strategy with a different fingerprint and code path.
- **Scrape:** a long-lived browser daemon holding a persistent profile (`launchPersistentContext`, profile under `XDG_DATA_HOME/serp-axi/profile`), which the CLI connects to over CDP. Rendered DOM, then Readability, then markdown, matching serp-axi's `scrape` output. Challenge pages are detected and reported as blocked.

## Open questions

| Question | How it gets settled |
|---|---|
| Real block rate per engine from this IP | Spike: results probe |
| Pacing floors per engine | Spike: results probe |
| Is a ddgs strategy worth carrying? | Spike: compare against SearXNG on the same queries |
| Plain Playwright vs persistent headed profile vs stealth fork (Patchright, Camoufox: **unverified** which holds up today) | Spike: scrape A/B |
| Browser process model: launch per call vs CDP daemon | Spike: scrape A/B (cold start, profile-lock behavior) |
| Result cache, and where | Can wait. SearXNG does not provide one. |
| L6 UX: how the human gets prompted to solve a captcha | Can wait |

## Spike results (2026-10-02)

Details in BAL-6 and BAL-7. What changed in the design:

- **ddgs is out.** It reports blocks as empty results. SearXNG is the only SERP backend.
- **Working engines from this IP:** bing, startpage, yandex, mojeek. Brave blocks SearXNG on the first request. Marginalia is untested (BAL-5).
- **Engine accounting.** SearXNG ignores unknown or inactive engines in `engines=`. serp-axi reports per-engine counts and `unresponsive_engines` and never treats a missing engine as "no results".
- **Scrape is a ladder, not one browser.** Rung 1: plain HTTP with browser TLS impersonation (44/50 real URLs, p50 302ms). Rung 2 on a block or thin page: stealth persistent Chromium (brings it to 47/50). Rung 3: hand the URL to a human (L6). Some sites block the browser but not HTTP, so the order matters.
- **What makes the browser rung work** is the L1 fingerprint fixes (no HeadlessChrome UA, no webdriver flag), not Patchright.
- **Headed Chrome doesn't run on this box** (no CDP under Xvfb). New headless is the default until that's solved.
- **Caching is open again.** SearXNG has no result cache.
