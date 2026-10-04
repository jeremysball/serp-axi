# Spike data

Measured datasets backing the free-SERP and page-scrape work. Each directory is
one spike run, with the machine-readable output that the findings in Linear are
derived from.

The findings themselves are **not** in this directory. They live in Linear as
prose, one issue per spike, and this repo holds only the data those reports cite.
That split is deliberate: Linear is the human-readable record, git is the data.

| Spike | Linear issue | What it measured |
| --- | --- | --- |
| `serp-2026-10-02` | BAL-6, BAL-7 | Block rate per free engine through SearXNG; scrape A/B across five browser variants |
| `scrape-2026-10-03` | BAL-40 | The escalation ladder against 16 hostile targets, plus a 219-row page-kind classifier evaluation |
| `sample100-2026-10-03` | BAL-40 (Q7) | The same ladder against 100 random Tranco top-1M domains |

## serp-2026-10-02

`serp_probe.jsonl` is 20 queries against SearXNG and `ddgs` on the same terms.
Each row carries per-engine result counts, the engines that failed outright, and
the `ddgs` error per engine. `ddgs` reported 403, 429 and Anubis challenge pages
as "no results found", which is why it was dropped rather than kept as a second
strategy.

`serp_probe.py` reproduces the run. It expects a SearXNG instance on
`127.0.0.1:8888` with the engines named in `searxng-settings.yml`.

The scrape A/B rows are `scrape_probe.py` and `scrape_driver.py`, which ran ~15
hostile URLs through headless shell, headless new, persistent, patchright and
stealth variants.

## scrape-2026-10-03

One JSONL row per fetch attempt. `q0` through `q6` map to the questions in
BAL-40: headed Chrome under Xvfb, fingerprint unassisted, the Turnstile click
with its control arm, clearance persistence, PerimeterX hold, local Whisper
reCAPTCHA, and page-kind classification. `etsy_*.jsonl` are the Etsy pacing
runs, where `etsy_rate.jsonl` holds every fetch of the speed run and
`etsy_after.jsonl` the follow-up.

`q6_rows.jsonl` is the fetch baseline: 219 rows over 77 targets, carrying the
status, the title, the extracted character count, the first 150 rows' leading
page text, and the verdict the ladder reached. A reimplementation of the fetch
path must be scored against these rows by `harness/q6_score.py`, which is the
script that produced the coarse and 9-way accuracy figures in BAL-40.

`harness/` holds the ten driver scripts the runs used. They are throwaway
code kept for reproducibility; they are not part of the shipped CLI and nothing
in `src/` imports them.

`q4_before.png` and `q4_mid.png` are the PerimeterX press-and-hold frames. The
run failed 0 of 4 there, and these are the evidence that the button accepted the
hold while PerimeterX still denied access.

## sample100-2026-10-03

100 random domains from the Tranco top-1M list through the full ladder.

`final.jsonl` is the accepted run, one row per domain, each row recording every
rung tried and the verdict at each. `results.jsonl` is the first full pass and
`retest.jsonl` plus `retest-2026-10-04.jsonl` re-check individual domains whose
first result looked like a harness fault rather than a real verdict.

The 100 domains split 57 stopping at the HTTP rung, 27 dead, 10 recovered by
Camoufox, 1 by headed Chromium, and 5 blocked on every rung. The last rung tried
per domain was the HTTP rung 80 times, Camoufox 12, `zendriver` with the
Cloudflare click 8; the final verdict was ok 68, dead 27, blocked 5.

`pages/` holds the saved text per rung for the domains that were fetched, which
is what makes a `dead` or `ok` verdict auditable after the fact.

`ladder.py` is the ladder as it stood at the end of the run. It is the reference
implementation for the strategy refactor in BAL-8.

## Reproducing

These scripts are not wired into `npm run check` and are not expected to run on
a clean checkout. They need a SearXNG daemon, browser profiles, a Camoufox
install, and a residential IP that is not already rate limited. Treat them as the
record of what was run, not as a test suite.
