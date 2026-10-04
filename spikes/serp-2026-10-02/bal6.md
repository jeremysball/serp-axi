## Findings (2026-10-02, home IP, SearXNG 19ffbcd, 20 queries, 6s gaps)

| Engine | SearXNG | ddgs 9.16.0 |
|---|---|---|
| bing | 20/20 | 16/20 |
| startpage | 20/20 | 0/20 |
| yandex | 20/20 | 11/20 |
| mojeek | 10/10 on a clean rerun (SearXNG only, 15s gaps) | 0/20 |
| brave | 0/20, 429 on the first request in 3 fresh processes | 0/20 |
| marginalia | not run, waiting on BAL-5 | not supported |

- SearXNG p50 640ms, max 1763ms.
- Mojeek's first run was blocked (3/20, then 403 and suspended) because ddgs traffic was interleaved from the same IP. The clean rerun fixed it, so that was a test-harness problem, not a Mojeek limit.
- Brave blocks SearXNG's HTTP client outright. Still untested: Brave through a real browser.
- ddgs is dropped. It reports 403, 429 and Anubis challenge pages as "No results found", so a block looks like an empty result.
- SearXNG silently ignores an unknown or inactive engine in `engines=` and answers from the others. serp-axi has to check which engines actually returned results, not trust what it asked for.
- SearXNG has no query-result cache (`searx/cache.py` is a per-engine KV store). Caching is back on the open-questions list.
- Startpage, Yandex and Mojeek ship disabled or inactive and need `inactive: false` in settings.

Remaining: rerun with Marginalia once BAL-5 is done.
