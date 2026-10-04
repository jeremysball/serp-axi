# Spike data

Measured datasets backing the free-SERP and page-scrape work. Each directory is
one spike run, with the machine-readable output and the scripts that produced
it. The findings derived from this data are **not** here. They live in Linear as
prose, one issue per spike, and this repo holds the data those reports cite.

That split is deliberate: Linear is the human-readable record, git is the data
and the code that produced it. Where a harness ledger exists it stays here,
because a debugging record is only useful next to the runs it explains.

Two things are deliberately absent and are Linear attachments on BAL-40 instead:
the screenshots, because a picture nobody diffs does not belong in git, and the
JSONL files and page dumps that embed verbatim scraped third-party page text.
Browser profiles, the Python venv and `__pycache__` are excluded from both, being
regenerable bulk that carries no findings; so are the per-shard logs, output files
and saved page directories a re-run produces. All of those are named in the root
`.gitignore`.

The scripts here are a snapshot, not a working install. None of them are wired
into `npm run check` and none have their dependencies checked in. `run.sh` takes
its interpreter from `$PY` and its domain list from `sample.txt`, neither of which
is committed, so a re-run needs both supplied. `harness/etsy_repeat.sh` still
carries the one interpreter path that was not fixed, `.venv/bin/python` relative
to its own directory, which does not exist in the repo; it also writes its
`etsy_*.jsonl` output into `harness/` rather than the spike root where the
committed copies live. The scripts are kept so the measured thresholds stay
readable and so the JSONL rows can be traced back to the code that produced them.

| Spike | Linear issue | What it measured |
| --- | --- | --- |
| `serp-2026-10-02` | BAL-6, BAL-7 | Block rate per free engine through SearXNG; scrape A/B across five browser variants |
| `scrape-2026-10-03` | BAL-40 | The escalation ladder against 16 hostile targets, plus the page-kind classifier evaluation |
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

Neither run's `scrape_*.jsonl` output is in git, for the reason the other two
spikes have: both scripts record a `head` field holding the first 240 characters
of the page body, so the rows embed verbatim third-party text. Those files are
part of BAL-6 and BAL-7's evidence and are Linear attachments alongside it. The
committed `serp_probe.jsonl` is the exception that proves the rule worth naming:
it holds per-engine result counts and error strings, no page text, so it stays.

## scrape-2026-10-03

One JSONL row per fetch attempt. `q0` through `q6` map to the questions in
BAL-40: headed Chrome under Xvfb, fingerprint unassisted, the Turnstile click
with its control arm, clearance persistence, PerimeterX hold, local Whisper
reCAPTCHA, and page-kind classification. `etsy_*.jsonl` are the Etsy pacing
runs, where `etsy_rate.jsonl` holds every fetch of the speed run and
`etsy_after.jsonl` the follow-up.

`q1.jsonl` and `q6_rows.jsonl` are **not** in git. Both embed scraped third-party
page text verbatim, and the em-dash gate on commit correctly refuses them. They
are archived as Linear attachments on BAL-40, next to the report that cites them.
`q6_rows.jsonl` is the fetch baseline: 219 rows over 64 distinct targets, each
target fetched under more than one browser variant, carrying status, title,
extracted character count, leading page text, and the verdict the ladder reached.
The row count and the target count are both recomputable from the five
`q6_*.jsonl` files here, which carry one row per input row with `target` copied
through as `url`; `219 rows over 77 targets` appeared in an earlier draft of this
file and the target count was wrong. `harness/q6_score.py` is the script that
produced the accuracy figures in BAL-40. It needs `q6_rows.jsonl` in the working
directory, and reads its argument paths relative to the current directory, so run
it from this one.

`harness/` holds the nine Python driver scripts the runs used, plus
`etsy_repeat.sh`, the shell wrapper that drove `solver_probe.py` twice through
the two Etsy arms. They are throwaway
code kept for reproducibility; they are not part of the shipped CLI and nothing
in `src/` imports them.

`flywheel.md` is the harness ledger: every hypothesis that turned out to be a
defect in this harness rather than a result, with the test that settled it. H1
(headed Chrome deadlocking under Xvfb) and H12 (every zendriver rung crashing on
one unevaluated arrow function) are the two that cost real time, and both read as
findings in the JSONL if you do not have the ledger.

`q4_hold.py` in `harness/` drives the PerimeterX press-and-hold. The run failed 0
of 4, and the two screenshots attached to BAL-40 are the evidence that the button
accepted the hold while PerimeterX still denied access.

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

The saved page text per rung, which is what makes a `dead` or `ok` verdict
auditable after the fact, is **not** in git for the same reason as `q1.jsonl`: it
is verbatim third-party page content. It is archived as a Linear attachment on
BAL-40.

`ladder.py` is the ladder as it stood at the end of the run. It is the reference
implementation for the strategy refactor in BAL-8, and the executable statement
of the thresholds the rungs were tuned to. The design it feeds is written up in
[serp-axi: the free scrape ladder, end to end](https://linear.app/ball-master/document/serp-axi-the-free-scrape-ladder-end-to-end-f403a7925b23).

## Reproducing

These scripts are not wired into `npm run check` and are not expected to run on
a clean checkout. They need a SearXNG daemon, browser profiles, a Camoufox
install, and a residential IP that is not already rate limited. Treat them as the
record of what was run, not as a test suite.
