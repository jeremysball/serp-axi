# serp-axi

An [AXI](https://github.com/kunchenguid/axi)-compliant CLI for real Google
Search results and page-scrape text extraction, built for agents that call
tools through shell execution rather than a browser.

## Install

```
npm install -g serp-axi
```

Confirms it's on `PATH`:

```
serp-axi --version
```

## Quickstart

Set one API key, then search:

```
export SERPER_API_KEY=<your key>
serp-axi search "site:example.com pricing"
```

Read a result in full:

```
serp-axi scrape https://example.com/article
```

## Commands

### `search`

Runs a Google Search query via [Serper](https://serper.dev) or
[Bright Data](https://brightdata.com). Serper is the default; pass
`--provider brightdata` to use Bright Data instead (requires
`BRIGHTDATA_API_KEY` and, optionally, `--zone`/`BRIGHTDATA_ZONE`).

```
serp-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>] [--provider <name>] [--zone <name>]
```

| Flag | Default | Notes |
|---|---|---|
| `--region <cc>` | `us` | Two-letter region code |
| `--lang <code>` | `en` | Language code |
| `--num <n>` | `10` | 1–100 results |
| `--fields <a,b,c>` | — | `date`, `sitelinks` (Serper only) |
| `--provider <name>` | `serper` | `serper` or `brightdata` |
| `--zone <name>` | account default | Bright Data zone; `--provider brightdata` only |

### `scrape`

Fetches a URL and extracts readable text via Serper. Always uses Serper,
regardless of which provider `search` was run with.

```
serp-axi scrape <url> [--full]
```

`--full` returns up to 50,000 characters instead of the default 1,200.
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
| `SERPER_API_KEY` | `search` (default provider), `scrape` (always) |
| `BRIGHTDATA_API_KEY` | `search --provider brightdata` |
| `BRIGHTDATA_ZONE` | optional override for the Bright Data zone (`--zone` wins if both are set) |

## Status

- `search` (both providers) and `scrape` are exercised against their live
  APIs in this repo's test suite and were run manually against real Serper
  and Bright Data endpoints during development.
- No npm-registry version check is implemented yet (`update` is a static
  reminder, not a live lookup).

## License

[The Unlicense](LICENSE): public domain.
