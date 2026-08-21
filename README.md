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
| `SERPER_API_KEY` | `search` (default provider), default `scrape` |
| `BRIGHTDATA_API_KEY` | `search --provider brightdata`, `scrape --provider brightdata` |
| `BRIGHTDATA_ZONE` | optional override for the Bright Data zone (`--zone` wins if both are set) |
| `BRIGHTDATA_DATASET_ID` | optional default dataset for `scrape --provider brightdata` (`--dataset-id` wins) |

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

- `search` (both providers) and `scrape` are exercised against their live
  APIs in this repo's test suite and were run manually against real Serper
  and Bright Data endpoints during development.
- No npm-registry version check is implemented yet (`update` is a static
  reminder, not a live lookup).

## License

[The Unlicense](LICENSE): public domain.
