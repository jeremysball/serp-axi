# serp-axi

An [AXI](https://github.com/kunchenguid/axi)-compliant CLI for real Google
Search results and page-scrape text extraction, built for agents that call
tools through shell execution rather than a browser.

## Install

```
npm install -g serp-axi
```

Until the first release has actually published (see "Publishing" below),
this package doesn't exist on the npm registry yet and the install above
404s.

Confirms it's on `PATH`:

```
serp-axi --version
```

## Quickstart

Search for free through a SearXNG instance. No API key, no provider flag:

```
serp-axi search "site:example.com pricing"
```

The default endpoint is `http://127.0.0.1:8888`; override it with
`--searxng-url` or `SERP_AXI_SEARXNG_URL`.

Search Google directly, or read a result in full, through a paid provider:

```
export SERPER_API_KEY=<your key>
serp-axi search "climate policy" --provider serper
serp-axi scrape https://example.com/article
```

## Commands

### `search`

Runs a free search query via SearXNG by default (no API key; see below),
or a Google Search query via [Serper](https://serper.dev) or
[Bright Data](https://brightdata.com). Pass `--provider serper` for Serper
or `--provider brightdata` for Bright Data (requires `BRIGHTDATA_API_KEY`
and, optionally, `--zone`/`BRIGHTDATA_ZONE`).

`--provider kagi` searches [Kagi](https://kagi.com) instead of Google, against
your own subscription. It needs `KAGI_SESSION_TOKEN`; see
[Using the Kagi provider](#using-the-kagi-provider) below.

`--provider searxng` runs a free search against a SearXNG instance you run
locally; no API key. Endpoint, engines, and timeout come from flags, then
`SERP_AXI_SEARXNG_URL` / `SERP_AXI_SEARXNG_ENGINES` /
`SERP_AXI_SEARCH_TIMEOUT_MS`, then `searxngUrl` / `searxngEngines` /
`searchTimeoutMs` in `$XDG_CONFIG_HOME/serp-axi/config.json` (default
`~/.config/serp-axi/config.json`), then built-in defaults. The default
endpoint is `http://127.0.0.1:8888`. SearXNG output adds `provider: searxng`,
a `status` field (`ok`, `partial`, `blocked`, `unavailable`), and per-engine
counts. Runs with no usable results exit 1 rather than claiming zero
results: unresponsive-engine failures carry per-engine details, while an
HTTP 403/429 at the SearXNG endpoint itself surfaces `blocked` with no
engine breakdown, and 401/5xx/network/timeout errors surface a plain
runtime error.

```
serp-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>] [--provider <name>] [--zone <name>] [--searxng-url <url>] [--engines <a,b>] [--search-timeout-ms <ms>]
```

| Flag | Default | Notes |
|---|---|---|
| `--region <cc>` | `us` | Lowercase region code; ignored by `kagi` |
| `--lang <code>` | `en` | Language code; ignored by `kagi` |
| `--num <n>` | `10` | 1–100 results |
| `--fields <a,b,c>` | — | `date`, `sitelinks` (Serper only) |
| `--provider <name>` | `searxng` | `searxng` (free), `serper`, `brightdata`, or `kagi` |
| `--zone <name>` | account default | Bright Data zone; `--provider brightdata` only |
| `--searxng-url <url>` | `http://127.0.0.1:8888` | SearXNG base URL; `--provider searxng` only |
| `--engines <a,b>` | server's engines | SearXNG engine selection; `--provider searxng` only |
| `--search-timeout-ms <ms>` | `30000` | SearXNG request timeout; `--provider searxng` only |

### `scrape`

Fetches one or more URLs and extracts readable text via Serper or Bright Data.
Serper is the default and accepts one URL. Bright Data accepts multiple URLs
in one batched request and requires `BRIGHTDATA_API_KEY`.

```
serp-axi scrape <url> [--full]
serp-axi scrape <url> [<url2> ...] --provider brightdata [--full] [--dataset-id <id>]
```

Bright Data uses dataset `gd_m6gjtfmeh43we6cqc` by default. Override it with
`--dataset-id` or `BRIGHTDATA_DATASET_ID`. `--full` returns up to 50,000
characters per page instead of the default 1,200. Bright Data returns a
batched object with `provider`, `datasetId`, and dataset-specific `results`.
Truncated result fields include a `<field>TruncatedFrom` count and a `help`
hint showing how to retry with `--full`.
Loopback and private-range hosts are rejected.

### `update`

Prints the command to pull the latest published version. It doesn't hit the
npm registry itself; it's a static reminder.

```
serp-axi update
```

## Output format

Every command prints [TOON](https://toonformat.dev/) to stdout, errors
included, in the same structured shape as normal output, with an
actionable `help` field. No prompts, no interactive input: every operation
is completable with flags alone.

## Environment variables

| Variable | Required for |
|---|---|
| `SERPER_API_KEY` | `search --provider serper`, default `scrape` |
| `BRIGHTDATA_API_KEY` | `search --provider brightdata`, `scrape --provider brightdata` |
| `BRIGHTDATA_ZONE` | optional override for the Bright Data zone (`--zone` wins if both are set) |
| `BRIGHTDATA_DATASET_ID` | optional default dataset for `scrape --provider brightdata` (`--dataset-id` wins) |
| `KAGI_SESSION_TOKEN` | `search --provider kagi` |
| `SERP_AXI_SEARXNG_URL` | optional endpoint override for `search --provider searxng` |
| `SERP_AXI_SEARXNG_ENGINES` | optional engine list for `search --provider searxng` |
| `SERP_AXI_SEARCH_TIMEOUT_MS` | optional timeout override for `search --provider searxng` |

## In progress: scraping escalation ladder

The free SearXNG search path is wired in (`--provider searxng`). The escalation
ladder for fetching pages behind the links is live for rungs 1 to 4; rung 5's
audio solve is not wired yet.

`--ladder` runs the fetch through a resident `ladder-cli` child over stdio, free
and with no API key. The climb has four live rungs and escalates only as far as
it needs to:

| rung | what it does | state |
| --- | --- | --- |
| 1 | site API where one exists, else `primp` with browser impersonation | live |
| 2 | Camoufox, a patched Firefox with `humanize` | live |
| 3 | zendriver with a Turnstile click | live |
| 4 | headed Chromium under Xvfb | live |
| 5 | Whisper `base.en` on an audio reCAPTCHA | deferred; audio helpers only, not attempted |

So a page that rung 1 answers is fetched at rung 1's cost, and a page behind a
challenge is tried in a browser. Rung 5's audio solve is not wired yet, so an
audio reCAPTCHA comes back `blocked` rather than being answered.

```
serp-axi scrape https://example.com/article --ladder
```

## Ladder flags

These only work with `--ladder`, and they are rejected elsewhere so a typo is
never parsed and silently ignored. Each resolves flag, then env, then a
`--profile` bundle, then config file, then default.

The ladder response carries `links` alongside `text`: absolute, deduplicated
anchors in document order with their anchor text, capped at 200. Rung 1 reads
them from the raw HTML, resolving relative URLs against the final URL after
redirects; browser rungs read `a.href` from the live DOM. Text is whitespace-
normalized before either is returned, so source indentation and blank-line
padding do not show up as content.

| flag | values | what it sets |
| --- | --- | --- |
| `--tab-state` | `fresh` (default), `same` | reserved; not yet applied |
| `--cookie-state` | `cold` (default), `jar` | `jar` is sugar for a jar in and out on one path |
| `--cache-state` | `cold` (default), `warm` | reserved; not yet applied |
| `--fingerprint-state` | `rotate` (default), `stable` | reserved; not yet applied |
| `--rung-ceiling` | `1` to `5` (default `5`) | highest rung allowed; `5` currently stops at rung `4` |
| `--profile` | a name from `ladderProfiles` | a named bundle of the axes above |
| `--jar-in` | a path | filtered browser JSON cookie jar loaded before fetching with zendriver (rungs 3-4) |
| `--jar-out` | a path | filtered browser JSON cookie jar saved by zendriver before its browser stops |
| `--http-jar-in` | a path | full-session Netscape cookie jar loaded by HTTP rung 1 only |
| `--http-jar-out` | a path | full-session Netscape cookie jar saved after HTTP rung 1; never mirrored or converted |

`--jar-in` and `--jar-out` stay separate from `--cookie-state` on purpose.
Replay is a known-unmet goal: the measured run loaded a jar into a fresh
browser three times and every one came back a challenge page. Keeping the two
paths separate is what lets a caller find out for itself whether replay helped
that site.

Cookie jars are separate, with no automatic conversion between formats:

- `--jar-in` / `--jar-out` are reserved for filtered browser JSON jars. HTTP
  never reads or writes them. `--cookie-state jar` mirrors only these paths.
- `--http-jar-in` / `--http-jar-out` load/save full-session Netscape jars on
  HTTP rung 1 only. Neither path implies the other. Treat these files as
  credentials: they can contain authentication cookies, not just clearance.
- HTTP settings also accept `SERP_AXI_HTTP_JAR_IN` / `SERP_AXI_HTTP_JAR_OUT`,
  config keys `ladderHttpJarIn` / `ladderHttpJarOut`, and profile members
  `httpJarIn` / `httpJarOut`.

A browser jar only travels through zendriver (rungs 3-4). A climb answered by
HTTP or Camoufox (rungs 1-2) reads no browser jar in and writes no browser jar
out: rung 1 keeps its own Netscape session jars and Camoufox gets neither
format. The browser jar file is JSON, named `<name>.cookies.json` by
convention. Explicit jar paths are used as supplied; do not point them at
zendriver's `.cookies.dat` pickle files, which a JSON save would overwrite.
Each zendriver rung loads the input jar and saves its own output; when both
rungs run, the later save replaces the earlier one. Filtering uses the bundled
public/private suffix snapshot without a network refresh; unknown suffixes stay
host-scoped. Missing jars are cold starts; corrupt or unreadable jars raise
errors, including malformed cookie records. Saves replace the jar atomically
after writing a sibling temporary file; a failed write leaves the previous jar
intact. A symlink output updates its target and preserves the link. Atomic
replacement requires write access to the target's parent directory, not just to
the existing file. An export failure fails the rung even if page extraction
succeeded; the requested jar is part of that rung's result. Unicode and punycode
hostnames share one scope. The jar's base-domain filter limits which cookies may
travel; the browser still applies each cookie's own domain and path rules when
making requests.

HTTP replay checks domain, path, Secure and expiry attributes, captures cookies
on redirect hops, and preserves unrelated stored cookies when saving. Netscape
jars cannot retain SameSite. A blocked HTTP response gets one fresh-client retry;
its random fingerprint can repeat and it does not change the source IP. The
parent and child must both speak protocol 3; an older installed child fails at
the ready handshake instead of ignoring the separate HTTP fields.

Profile launches take an exclusive local lease. Cleanup removes Chromium locks
only when their recorded owner is on this host and its process no longer exists.
A live, foreign-host, or unrecognized lock is refused and left untouched.
Profiles live under `$XDG_STATE_HOME/serp-axi/profiles`, falling back to
`~/.local/state/serp-axi/profiles`. Existing working-directory `profiles/`
folders are not migrated or removed automatically.

Jar contents are filtered before they are written and again before they are
loaded, to the four defence cookies (`cf_clearance`, `_px3`, `_pxhd`,
`datadome`) scoped to the target's base domain. A warmed profile holds every
site's cookies, so only the target's own leave with the fetch.

The scored verdicts are `ok`, `dead`, `blocked`, and `error`. Exhaustion reports
`error` if the final rung malfunctioned, otherwise `blocked`. A rung that exceeds
its 90-second subprocess budget is killed and reports `error`, allowing the
next rung to run. The independent 120-second request cap can interrupt the
whole climb before every rung finishes; that cap raises a request error.

The committed datasets and harness ledger are in [`spikes/`](spikes/).
Current ladder decisions and scope live in
[the technical design](.superpowers/crispy/ladder-cli/04-tdd.md) and
[outline](.superpowers/crispy/ladder-cli/05-outline.md). Historical reports and
some excluded attachments remain in Linear; they are not the home for new findings.

## Using the Kagi provider

Kagi has no public search API on a normal subscription, so this provider signs
in the way a browser does: it sends your session token as a cookie to
`kagi.com/html/search`, the non-JavaScript endpoint that renders results
server-side, and parses that HTML.

Get the token from [kagi.com/settings?p=user_details](https://kagi.com/settings?p=user_details),
under Session Link. The link ends in `&q=%s`; the token is everything before
that.

```
export KAGI_SESSION_TOKEN=<token>
serp-axi search "postgres lateral join" --provider kagi --num 5
```

Worth knowing about it:

- The token authenticates your account. Treat it like a password, and rotate it
  from that same settings page if it leaks.
- `--region` and `--lang` are accepted but do nothing here. Kagi takes both from
  your account settings.
- `--fields` and `scrape` do not support this provider, and both say so rather
  than failing quietly.
- Parsing HTML means a Kagi redesign can break this provider where an API
  version would not. `src/kagi.test.ts` runs against a saved copy of a real
  SERP, so a breaking change shows up as a test failure.

## Tests

Run `npm run check` for typechecking, the Node/Python suites, and the named
mutation gate. Prepublish checks run the same gate. To run only the mutation
gate, use `npm run test:mutations`.

The Python mutation-safety tests and the mutation gate require Linux, Bubblewrap
(`bwrap` on `PATH`), and working unprivileged user namespaces. CI probes those
capabilities before the Python suite. A missing or unusable sandbox fails the
gate; it never runs mutants without isolation or counts a startup error as a kill.
`npm run test:mutations` first syncs the locked Python test extra in `ladder-cli`.
Before invoking `scripts/mutations.py` directly, run
`uv sync --project ladder-cli --frozen --inexact --extra test`; scratch runs stay offline
and reuse that environment without syncing it.

Serper request and error handling use mocked responses by default. To run its
live API checks, set `SERPER_API_KEY` and run:

```sh
SERP_AXI_LIVE_SERPER=1 node --test src/serper.live.test.ts
```

Live Serper checks require available account credits. Mocked tests do not
verify the live service. Bright Data tests require `SERP_AXI_LIVE_BRIGHTDATA=1`
and `BRIGHTDATA_API_KEY`; Kagi tests require `SERP_AXI_LIVE_KAGI=1` and
`KAGI_SESSION_TOKEN`. Credentials alone activate no live provider tests.
Live ladder tests require `SERP_AXI_LIVE_LADDER=1`
and an available `ladder-cli` binary.

## Publishing (maintainers)

Releases are cut by [release-please](https://github.com/googleapis/release-please):
merging its release PR tags a version and triggers a `publish` job that runs
`npm publish` under [npm trusted publishing](https://docs.npmjs.com/trusted-publishers)
(OIDC) — no long-lived npm token stored in the workflow.

Trusted publishing has to be configured on npmjs.com against a package that
already exists, so it can't cover the very first publish of a brand-new
package name. That first publish is a one-time manual step from an
authenticated local session (`npm publish`, using the `NPM_TOKEN` repo
secret's value) *before* the first release PR is merged. Every release
after that goes through OIDC only.

## Status

- `search` (all four providers, including SearXNG) and `scrape` are exercised
  against their endpoints in this repo's test suite; Serper, Bright Data,
  Kagi, and a local SearXNG were run live during development.
- The fetch escalation ladder is implemented for rungs 1 to 4 (browser rungs
  need the `browsers` extra); rung 5's browser half is pending.
  See "In progress" above.
- No npm-registry version check is implemented yet (`update` is a static
  reminder, not a live lookup).

## License

[The Unlicense](LICENSE): public domain.
