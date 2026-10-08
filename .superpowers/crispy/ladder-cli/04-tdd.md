---
system_approved: true
program_approved: true
---

# TDD: resident ladder CLI for scraping at home

Adopts the settled design in Linear ("serp-axi: the free scrape ladder, end to
end", doc `925b67cf-76be-474c-99d4-78eb7f0fd77e`) into a buildable contract.
Evidence underneath it: `spikes/sample100-2026-10-03/` (100-domain ladder run:
68 ok / 27 dead / 5 blocked, 80 never needing a browser), the
`spikes/scrape-2026-10-03/harness/` probes (q3 same-tab rule, q3_restart 3/3
jar-replay blocked, Etsy warm-profile medians 6.8s vs 9.1s fresh), and the
harness ledger at `spikes/scrape-2026-10-03/flywheel.md` (H1/H12: fixtures that
pass green while hiding harness faults).

Scope boundary, from the design doc: the ladder CLI fetches pages behind links.
Search stays TypeScript (strategy registry, searxng strategy, verdict rules —
already shipped as `e12b6ca`). No external supervisor: the CLI is the
long-lived process and supervises itself (BAL-45 narrowed).

## 1. System design

Approval: approved 2026-10-07

### 1.1 Process contract

serp-axi (TypeScript) spawns exactly one `ladder-cli` (Python) child on the
first scrape request and tears it down when idle. Transport is stdin/stdout
with NDJSON: one JSON request object per line, one JSON response object per
line. No sockets, no ports, no supervision beyond the parent holding the child
handle. A supervised-process failure surfaces as a failed request, never a
hang: every rung keeps the spike's 90s SIGKILL budget, and the parent applies
its own overall timeout on top.

Readiness is signalled explicitly. The child prints a single
`{"ready": true, ...}` line once its event loop is up and before it reads its
first request, so no caller sleeps a fixed interval and hopes. The parent
treats any stdout line before `ready` as a startup log, and a child that exits
before `ready` as a failed request with the stderr tail attached.

Why stdio and not a socket: one child per serp-axi invocation means no port
allocation, no leftover listeners, and the OS reaps everything on parent
exit. The falsifier is concurrent scrapes from one parent outgrowing a single
stdio pipe; if that is ever measured, the contract gains a worker count, not a
new transport.

### 1.2 Request schema

```json
{
  "url": "https://example.com/article",
  "tabState": "fresh",
  "cookieState": "cold",
  "cacheState": "cold",
  "fingerprintState": "rotate",
  "rungCeiling": 5,
  "profile": null,
  "jarIn": null,
  "jarOut": null
}
```

Six axes ride as named fields with the settled defaults (`fresh / cold /
cold / rotate / 5 / none`), flag > env > config > default resolved in
TypeScript before the request is built, so the CLI never reads env or config
itself. `--cookie-state jar` is sugar the parent expands to `jarIn` plus
`jarOut` on the same path; `jar-in` and `jar-out` stay separate fields
because replay is a known-unmet goal (q3_restart 3/3 blocked) and a single
boolean cannot express intent that has already failed. `--profile` names a
bundle resolved parent-side into the six fields, so profiles live in the
existing config file and the CLI schema never grows a seventh axis.

`rungCeiling` 1–5 caps escalation; a run that hits the ceiling without a
verdict reports `blocked`, honestly, instead of climbing.

### 1.3 Response schema

```json
{
  "verdict": "ok",
  "rungReached": 2,
  "title": "Example",
  "text": "readable text...",
  "engines": ["bing"],
  "elapsedMs": 6800,
  "warning": null
}
```

`verdict` is `ok`, `dead`, or `blocked` — the same three words as the spike
ledger, so fixture rows stay comparable. `dead` means the page does not exist
or never renders; `blocked` means a defence won. An empty result with no
failure is a schema violation, not a verdict: the parent rejects it the way
search rejects untyped empties. `warning` carries partial-state notes (for
example, a rung that produced text but lost its clearance mid-run); it never
replaces `verdict`.

### 1.4 Laziness and residency

Everything loads on first need and stays resident after. A rung's browser or
model constructs once: the failure this fixes is `q5_audio.py` building
`WhisperModel("base.en", ...)` per URL (verified at
`spikes/scrape-2026-10-03/harness/q5_audio.py:44`) against medians of 21.1s
per fetch. The 80-in-100 rung-1-only case pays exactly today's cold cost;
nothing loads at startup, so a single-URL scrape launches no browser and no
model.

Rung order is fixed: HTTP (`primp`, browser impersonation), Camoufox 0.5.6
(`humanize=True`, verified at
`spikes/sample100-2026-10-03/ladder.py:69`), zendriver 0.17.1 with Turnstile
click, headed Chromium under Xvfb, Whisper `base.en` on audio reCAPTCHA as
the rung-4 fallback. Python stays Python for exactly these three rungs plus
Whisper: no Node implementation exists for Camoufox's patched build,
zendriver's CDP client, or faster-whisper's native binary, and a TypeScript
port would shell out to Python for the hard parts.

### 1.5 Stores (on disk, all of them)

- Warmed browser profiles, one directory per profile, reused across requests
  for the CLI's whole life.
- Cookie jars (`<name>.cookies.dat`), written because Chrome flushes lazily
  and `stop()` kills first (verified comment at
  `spikes/scrape-2026-10-03/harness/solver_probe.py:85`). Jar contents stay
  filtered to the target's base domain against the `cf_clearance / _px3 /
  _pxhd / datadome` allowlist (verified at `solver_probe.py:27-33`), which is
  why there is no per-host scoping knob: the leakage it would prevent is not
  reachable, and per-host persistence reintroduces the same-tab failure.
- The Whisper model weights, loaded once per CLI life.
- No database, no queue, no cache service. There are no stored-data queries
  to index; this section exists to say so explicitly.

### 1.6 Same-tab rule, as contract

New tabs in a resident browser lose clearances that same-tab refreshes keep
(Glassdoor 2/3 revisits, `q3_profile.out`). So `tabState: same` reuses one tab
for the whole request including escalation, and `fresh` opens exactly one new
tab per request — never one tab per rung. Fingerprint defaults to `rotate`
because it reproduces `final.jsonl`, not because cross-host rotate-vs-stable
was measured: that comparison is unrun and stays listed as unmeasured.

### 1.7 Guides and their sensors

Every guide gets a sensor; a guide without one does not ship.

| Guide | Sensor |
|---|---|
| Laziness: nothing loads before first need | Startup test asserting zero browser/model constructions on an empty request log |
| Verdict honesty: `blocked` vs `dead` vs empty never confused | Fixture replay of `final.jsonl` verdicts plus `q6_rows.jsonl` classifier rows; thresholds from the spike, not re-picked |
| Thresholds travel with fixtures | Harness-ledger entries (H1/H12 pattern) fail the suite if the ledger file is missing: the suite reads `flywheel.md` and asserts its entry count, so the blindness it documents cannot silently detach |
| Axis orthogonality: six knobs, no hidden coupling | Pairwise test: each axis varies while the other five hold defaults, asserting only its field changes the request |
| Per-URL cost stays at rung-1 cold cost | Timing assertion on the rung-1 path against the spike medians with headroom, not equality |

### 1.8 Open questions that would change this contract

- stdio throughput under concurrent scrapes from one parent (falsifier in
  1.1): measured, not argued, when batch scraping exists.
- Whether anything rescues jar replay (want 4): undetermined; the separate
  `jarIn`/`jarOut` fields are what let a caller find out.
- `primp` vs Node `fetch` for rung 1: untested; the only rung-1 choice not
  forced by a missing library.
- Cache `cold` vs `warm`: untested; the axis exists because warm cache is a
  fingerprint, not because the comparison ran.

## 2. Program design

Approval: approved 2026-10-07

Three rulings recorded at approval, because Phase 1 had already shipped narrower
than this section reads and the gap was found by diffing §2 against the merged
code rather than against the summary:

1. Axis resolution, the nine-field request schema, and `protocol: 1`
   negotiation move forward from outline Phase 4 into **Phase 2**. They are
   inseparable from the Python `LadderRequest` dataclass, which §2.3 specifies
   rejects unknown fields: a parent that still sends only `{url}` fails every
   request the moment the child exists.
2. §1.3's honest-empty rule is enforced in **Phase 2**, parent-side, not
   deferred to Phase 5: `verdict: "ok"` with empty text is a schema violation.
3. Binary resolution keeps sibling-of-package as specified in §2.2, even though
   Phase 1 shipped only `SERP_AXI_LADDER_BIN ?? "ladder-cli"`. It is Phase 2 work.

Below, the call path and signatures are aligned to the names Phase 1 actually
shipped (`LadderClient`, `fetchViaLadder`) rather than the drafted `resolveLadder`.

### 2.1 Call paths

TypeScript side (new code, all inside `src/`):

```
scrape command (src/commands/scrape.ts)
  -> fetchViaLadder (src/commands/scrape.ts) -> LadderClient (src/ladder.ts)
       resolve axes: flags > env > config > default; expand --profile; expand jar sugar
       resolve binary: SERP_AXI_LADDER_BIN > sibling-of-package > PATH
       spawn child on first use: ladder-cli; wait for {"ready": true, "protocol": 1}
     -> writeRequest: NDJSON line carrying all nine fields + protocol: 1
     -> readResponse: first stdout line; parse + validate against LadderResponse
     -> honest-empty: verdict ok with empty text is a schema violation, not a success
     -> verdict mapping: ok -> rows; dead/blocked -> typed SerpAxiError (blocked exits 1)
     -> idle teardown: last-resort timer closes stdin after N ms with no in-flight request
```

`LadderClient` (the class shipped in Phase 1) owns the whole child lifecycle:
exactly one child per process, one in-flight request at a time (a second
concurrent scrape queues behind the first; the falsifier in 1.1 is measured here,
not designed for). A child that dies mid-request surfaces its stderr tail as the
request error. SIGKILL per rung stays inside the child; the parent's overall
timeout races the response read.

Python side (new `ladder-cli/` tree at repo root, so the Python package never
nests inside the npm layout):

```
__main__ / cli.py
  -> handshake: print({"ready": True}) ; loop: read line -> dispatch -> print response
  -> dispatch(request: LadderRequest)
       build browser context for axes (profile dir, jar-in load, cache/fp/tab policy)
       for rung in rungs[:ceiling]:
         run with 90s SIGKILL budget
         ok -> finish(response); dead/blocked are rung-local signals, keep climbing
       ceiling hit or all rungs exhausted -> blocked (never empty-ok)
  rungs/http.py, rungs/camoufox.py, rungs/zendriver.py, rungs/headed.py, rungs/whisper.py
  state/jars.py (allowlist-filtered load/save), state/profiles.py (dir layout)
```

`ladder.py` in `spikes/` is not imported and not moved: it stays as the
executable statement of the measured thresholds. Rung implementations are
rewritten against this contract, porting the measured constants (timeouts,
allowlist, humanize flag) with the spike file cited in a comment at each use.

### 2.2 Files

```
src/ladder.ts            parent-side lifecycle: spawn, ready, write, read, teardown, verdict mapping
src/ladder.test.ts       contract tests against a stub child (a 20-line node script, not Python)
src/commands/scrape.ts   route --ladder through fetchViaLadder (new flag; serper stays default for scrape)
ladder-cli/pyproject.toml  pinned deps: camoufox==0.5.6, zendriver==0.17.1, faster-whisper==1.2.1,
                           primp==2.0.1, browserforge==1.2.4 (versions from the measured spikes)
ladder-cli/cli.py        handshake + NDJSON loop + dispatch + rung ceiling
ladder-cli/rungs/*.py   one module per rung, each exposing run(url, ctx) -> RungOutcome
ladder-cli/state/*.py   jars.py, profiles.py
ladder-cli/tests/        rung unit tests + fixture replay (final.jsonl, q6_rows.jsonl) + ledger-presence test
```

How the TS dist finds the child: `SERP_AXI_LADDER_BIN` is an exact binary path
and always wins (dev and sandboxes). Otherwise the first existing candidate is
taken, in order: `<package>/ladder-cli/ladder-cli` (the repo checkout, and a
published package if `ladder-cli` ships with it), then `<package>/../ladder-cli`
(a sibling install), then whatever `PATH` offers. Candidates are checked for
existence so an absent one never hides a working `PATH` entry. The npm
`postinstall` does not fetch Python; if the binary is missing at first scrape,
the error names the env var and the docs page, and exits 1 as a failed request.

### 2.3 Types and signatures

```ts
// src/ladder.ts
interface LadderRequest {
  protocol: 1;                        // rides on every request; see the versioning note below
  url: string; tabState: "fresh" | "same";
  cookieState: "cold" | "jar"; cacheState: "cold" | "warm";
  fingerprintState: "rotate" | "stable"; rungCeiling: 1 | 2 | 3 | 4 | 5;
  profile: string | null; jarIn: string | null; jarOut: string | null;
}
interface LadderResponse {
  verdict: "ok" | "dead" | "blocked"; rungReached: number;
  title: string; text: string; engines: string[];
  elapsedMs: number; warning: string | null;
}
async function fetchViaLadder(url: string, options: LadderClientOptions): Promise<LadderResponse>
```

```python
# ladder-cli/cli.py
@dataclass
class LadderRequest: ...   # same fields, same literals, validated on parse; unknown fields rejected
@dataclass
class LadderResponse: ...  # verdict required; empty text with verdict ok is a bug, asserted
class RungOutcome(Enum): OK, DEAD, BLOCKED, ERROR  # ERROR is rung-local, never leaves the child
def run_rung(name: str, url: str, ctx: BrowserCtx) -> RungOutcome: ...
```

The two schemas are versioned together: a `protocol: 1` field rides on every
request, and a mismatch fails fast with a message naming both sides, so a
stale installed `ladder-cli` can never silently misparse.

### 2.4 Test boundaries

- TypeScript owns the contract: `ladder.test.ts` spawns a stub child script
  that replays canned NDJSON (ready line, one ok, one blocked, one malformed,
  one pre-ready exit) and asserts spawn-once, ready-wait, timeout race,
  verdict mapping, and stderr-tail errors. No Python involved.
- Three assertions carry the approval rulings above, each a sensor on a gap
  that shipped absent from Phase 1:
  - the stub advertises `protocol: 1` on its ready line and the parent rejects
    a mismatched `protocol` with a message naming both sides;
  - the stub returns `verdict: "ok"` with empty `text` and `parseResponse`
    throws instead of returning a successful empty scrape;
  - binary resolution is exercised for all three legs (env override,
    sibling-of-package, PATH fallback).
- Python owns the rungs: each `rungs/*.py` gets unit tests with recorded
  fixtures; the fixture replay suite asserts `final.jsonl` verdicts and
  `q6_rows.jsonl` classifier thresholds bit-for-bit against the spike
  numbers, and fails if `spikes/scrape-2026-10-03/flywheel.md` is missing or
  has fewer entries than the count the suite records.
- Axis orthogonality pairs live TypeScript-side (request building), one test
  per axis varying alone; they land with Phase 2 alongside the schema they
  exercise.
- Live-engine tests stay quarantined exactly like today's `*.live.test.ts`:
  never in `npm run check`, named `.live`, run by hand.
