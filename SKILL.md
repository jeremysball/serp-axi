---
name: searching-the-web
description: Use when a live Google web search or readable text extraction from a public web page is needed. Mandatory, not just preferred, whenever the driving model isn't Claude — native WebSearch is confirmed broken there.
---

# serp-axi

`serp-axi` is a CLI that runs **real Google Search** queries and page
scrapes for agents, via Serper's Google Search API (`google.serper.dev`) or
Bright Data's SERP API (`api.brightdata.com`). Make no mistake: this is
Google search, not a synthetic or local index. It requires `SERPER_API_KEY`
and/or `BRIGHTDATA_API_KEY` to be set in the environment (whichever
provider you use) and the package installed locally (this tool is not
published to npm — install via `git pull && npm run build && npm install -g .`
in its repo).

## If the driving model isn't Claude, native `WebSearch` doesn't work — use this instead

Check `message.model` (or however your harness exposes the active model) before
reaching for the native `WebSearch` tool. When the driving model is not a
Claude model, native `WebSearch` returns an **empty result set** — no titles,
no URLs, no snippets, just the boilerplate wrapper text — every time, not
intermittently. Native `WebFetch` (fetching a URL you already have) still
works fine for non-Claude models; it's specifically `WebSearch` that's
broken. Don't retry the query, rephrase it, or treat an empty result as "no
matches" — that's a broken tool, not a real answer. Reach for `serp-axi
search` instead, immediately, the first time you'd otherwise call
`WebSearch` under a non-Claude driving model.

**Confidence: high.** Confirmed across 3 independent Claude Code sessions,
10/10 `WebSearch` calls, all driven by `deepseek-v4-flash:0731`, all
returning zero results:

- `-workspace-serper-axi/6bbd4cc7-...jsonl` — 3 deliberate diagnostic
  queries, all empty.
- `-workspace-taskferry/a2e55adc-...jsonl` — Kagi rate-limited (429), fell
  back to `WebSearch` for 5 queries, all empty, then ground through
  `WebFetch` guesses instead.
- `-home-jeremy--claude-skills-unshackling-models/a64b58de-...jsonl` — Kagi
  429, `WebSearch` empty twice, so the model **guessed arXiv paper IDs from
  memory and fetched the wrong papers**, then `WebSearch` empty twice more
  before it self-corrected via a raw `curl` against the arXiv API. This is
  the concrete cost of not catching the empty result immediately: a wrong
  answer shipped before the workaround was found.

If you're a Claude model and native `WebSearch` is working, you don't need
this section — nothing here says stop using native tools when they work. And
if you can't tell which model is driving, don't guess: an empty `WebSearch`
result (the boilerplate wrapper with nothing above it) is itself the
signal — treat it as broken tooling and switch to `serp-axi search`,
whatever the model.

## Search

```
serp-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>] [--provider <name>] [--zone <name>]
```

Defaults: `--region us --lang en --num 10 --provider serper`. Results include
`position`, `title`, `link`, and a 200-character `snippet`. Pass `--fields
date,sitelinks` to include either of those two extra fields when present
(Serper only). Pass `--provider brightdata` to query Bright Data's SERP API
instead of Serper; it uses the Bright Data zone `serp_api1` by default,
overridable via `--zone` or `BRIGHTDATA_ZONE` (`--zone` wins if both are set).

## Scrape

```
serp-axi scrape <url> [--full]
```

Fetches a page's readable text (from Serper's scrape endpoint), truncated to
1,200 characters by default. `--full` returns up to 50,000 characters.

## Notes

- `SERPER_API_KEY` (default `--provider serper`) or `BRIGHTDATA_API_KEY`
  (`--provider brightdata`) must be exported in the environment before
  running; serp-axi checks for the relevant one before making any network
  call. `scrape` always uses Serper.
- Both commands reject invalid input (bad `--num`, non-http(s) scrape URLs,
  loopback/private hosts) with exit code 2, before any network call.
- Run `serp-axi <command> --help` for the full flag reference.
