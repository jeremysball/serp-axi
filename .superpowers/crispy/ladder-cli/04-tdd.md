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

Phase-four implementation status: the frontmatter and dated approvals below
record historical approvals, not a fresh signoff. The approved correction
defers live rung 5; §§1.4-1.6 and the Python call path describe the narrower
implementation. Other sections retain historical intent, including protocol
examples, file listings, signatures, and sensors. Historical examples below
predate the current protocol/error response: implemented dispatch returns
`error` when the last rung malfunctions. Historical same-tab and browser/model
residency goals remain deferred. Review, integration, and live gates remain
pending; Phase 4 is not declared accepted or merged.

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
  "protocol": 3,
  "url": "https://example.com/article",
  "tabState": "fresh",
  "cookieState": "cold",
  "cacheState": "cold",
  "fingerprintState": "rotate",
  "rungCeiling": 5,
  "profile": null,
  "jarIn": null,
  "jarOut": null,
  "httpJarIn": null,
  "httpJarOut": null
}
```

Six axes ride as named fields with the settled defaults (`fresh / cold /
cold / rotate / 5 / none`), flag > env > config > default resolved in
TypeScript before the request is built. The Python CLI does not resolve these
axes from env or config; it reads `XDG_STATE_HOME` for browser profile storage.
`--cookie-state jar` is sugar the parent expands to `jarIn` plus
`jarOut` on the same path; `jar-in` and `jar-out` stay separate fields
because replay is a known-unmet goal (q3_restart 3/3 blocked) and a single
boolean cannot express intent that has already failed. `--profile` names a
bundle resolved parent-side into the six fields, so profiles live in the
existing config file and the CLI schema never grows a seventh axis.

`jarIn`/`jarOut` remain browser-only filtered JSON jars. Separate
`httpJarIn`/`httpJarOut` fields carry full-session Netscape jars for rung 1;
neither is mirrored by `cookieState`, converted, or sent to browser rungs.
Camoufox receives neither jar format. This request extension uses protocol 3.

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

Browser and model dependencies load on first need, not at startup. The
resident CLI owns the NDJSON loop, but every live rung runs in a separate
subprocess under the hard 90s SIGKILL budget. There is no inline soft
SIGALRM route and no cross-fetch browser or model residency.

Four live rungs are registered, in order: HTTP (`primp`, browser
impersonation), Camoufox 0.5.6 (`humanize=True`, verified at
`spikes/sample100-2026-10-03/ladder.py:71`), zendriver 0.17.1 with Turnstile
click, and headed zendriver CF under Xvfb. `rungCeiling: 5` remains accepted
for protocol compatibility, but runs at most these four rungs and reports
actual `rungReached: 4` on exhaustion. It does not fetch the headed page
again under an audio rung.

Live rung 5 is explicitly deferred. The unwired Whisper `base.en` helpers
load lazily and cache only within their own process. The spike already
constructed one model per subprocess and reused it across audio rounds;
a per-process memo does not improve that into cross-fetch reuse. No
end-to-end audio solve is delivered.

Python remains the implementation language for the live ladder: Camoufox's
patched build and zendriver's CDP client supply the browser paths. The
faster-whisper helpers remain Python too, but are not a live escalation step.

### 1.5 Stores (on disk, all of them)

- Warmed zendriver profile directories persist on disk for rungs 3 and 4.
  This is disk reuse, not a resident browser. Camoufox creates and tears down
  its browser per fetch and keeps no warmed profile.
- Cookie jars (`<name>.cookies.json`) route only to zendriver rungs 3 and 4.
  They load before navigation and save before browser shutdown because Chrome
  flushes lazily and `stop()` kills first (verified comment at
  `spikes/scrape-2026-10-03/harness/solver_probe.py:85`). HTTP and Camoufox do
  not read or write jars. Replay rescue remains unproven: q3_restart was
  blocked 3/3.
- Jar filtering applies on both read and write, using the `cf_clearance /
  _px3 / _pxhd / datadome` allowlist and label-boundary domain checks.
  Pinned tldextract uses its bundled public/private suffix snapshot without
  runtime network fetching; unknown suffixes stay host-scoped. URL parsing
  strips ports and userinfo; an unscopable URL admits no cookies.
- A missing jar is a cold start. Corrupt or unreadable jars raise rather than
  silently disappearing. The measured run reused zendriver's own
  `<name>.cookies.dat`, which is a pickle; this module writes JSON and recommends
  `.cookies.json`. Explicit paths are not renamed or extension-checked: callers
  must keep JSON output separate from browser pickle files. Each zendriver rung
  replays the input and saves its own output, replacing any earlier rung's save.
- Profile cleanup refuses live, foreign-host, unknown, and
  permission-uncheckable owners. Only a proven dead local owner permits
  cleanup. A nonblocking exclusive `.ladder.lock` lease protects cleanup
  across the browser fetch, including shutdown. Tests and examples use
  temporary fixture profiles, never real browser profiles.
- Whisper helpers retain a model only within their own process after first
  use. They provide no cross-fetch model residency.
- No database, no queue, no cache service. There are no stored-data queries
  to index; this section exists to say so explicitly.

### 1.6 Same-tab rule, as contract

New tabs in a resident browser lose clearances that same-tab refreshes keep
(Glassdoor 2/3 revisits, `q3_profile.out`). The historical goal was for
`tabState: same` to reuse one tab throughout a request and escalation, and
for `fresh` to open one new tab per request. Isolated live rungs do not
deliver that goal: tabs and browsers do not survive between rungs or
fetches. Same-tab/browser-residency behavior is deferred, not fulfilled by
profile or jar persistence.

Fingerprint defaults to `rotate` because it reproduces `final.jsonl`, not
because cross-host rotate-vs-stable was measured: that comparison is unrun
and stays listed as unmeasured.

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
  `jarIn`/`jarOut` fields let a caller investigate, without guaranteeing rescue.
- Live audio integration and cross-fetch model/browser residency: deferred.
  Restoring them requires a design that preserves enforceable hard budgets;
  process-local helper caching does not deliver them.
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
3. Binary resolution keeps a ladder-cli beside the package as specified in
   §2.2, and also checks inside it first, because the repo checkout keeps the
   Python tree at `<package>/ladder-cli`. It is Phase 2 work.
4. `dead` is terminal; only `blocked` climbs. §2.1's "dead/blocked are rung-local
   signals, keep climbing" would make `dead` unreachable, since exhaustion always
   reports `blocked`, contradicting §1.3 and the merged Phase 1 test that asserts
   `dead` reaches the parent distinctly. The spike already implements the
   resolution and states why, at `spikes/sample100-2026-10-03/ladder.py:196`: a
   browser cannot revive a domain that does not resolve or a page that says it is
   parked. Exhausted rungs still report `blocked`.
5. The Python tree is a proper `ladder_cli` package under `ladder-cli/`, with the
   console script `ladder-cli = ladder_cli.cli:main`. The hyphenated directory
   cannot be an import name, and flat top-level modules called `cli`, `rungs`, and
   `state` would collide with anything else sharing the venv. This departs from
   §2.2's flat file listing; §2.2's paths are updated in place.

Residency resolution for Phase 4: every live rung uses a killable subprocess
with the 90s hard budget. Long-lived per-rung workers were a possible design,
not delivered behavior. The resident CLI supervises requests and isolated
rungs; it retains neither browsers nor models across fetches. Live rung 5
and same-tab residency remain deferred.

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

Python side (`ladder-cli/ladder_cli/`, separate from the npm layout):

```
__main__ / cli.py
  -> handshake: print({"ready": True, "protocol": PROTOCOL})
  -> loop: read line -> LadderRequest.parse -> dispatch -> print encoded response
  -> dispatch(request: LadderRequest)
       build per-request RungContext(jar_in, jar_out)
       for index, rung in enumerate(RUNGS[:request.rungCeiling]):
         record actual rungReached = index + 1
         run_rung_isolated(rung, url, ctx=ctx)
           -> python -m ladder_cli --rung <rung> <url> [jar flags]
           -> new session; 90s hard budget; SIGKILL process group on timeout
           -> child: _run_rung_child -> fetch -> JSON page or stderr exception
           -> supervisor: judge page or map child failure
         empty ok -> blocked
         ok -> return; dead -> return; blocked/error -> climb
       exhaustion -> error if final rung malfunctioned, otherwise blocked
  RUNGS = ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf")
  rungs/http.py, rungs/camoufox.py: no jar reads or writes
  rungs/zendriver.py, rungs/headed.py:
    acquire nonblocking exclusive profile/.ladder.lock lease
    verify dead-local lock owner before cleanup; launch browser
    load/filter jarIn before navigation; fetch; save/filter jarOut before stop
    stop browser; release lease
  state/jars.py, state/profiles.py
  rungs/whisper.py: lazy process-local helpers, not registered or dispatched
```

Ceiling 5 slices the four-entry registry, so exhaustion reports actual
`rungReached: 4`, never a synthetic fifth attempt. No headed-page refetch
stands in for audio integration.

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
ladder-cli/ladder_cli/cli.py        handshake + NDJSON loop + dispatch + rung ceiling
ladder-cli/ladder_cli/rungs/*.py    fetch(url, ctx) -> page dict; judge(page) -> RungResult
ladder-cli/ladder_cli/state/jars.py cookie jars and stale Chromium-lock cleanup
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
