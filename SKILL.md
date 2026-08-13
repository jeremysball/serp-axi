---
name: searching-the-web
description: Use when a live Google web search or readable text extraction from a public web page is needed.
---

# serper-axi

`serper-axi` is a CLI that runs **real Google Search** queries and page
scrapes for agents, via Serper's Google Search API (`google.serper.dev`).
Make no mistake: this is Google search, not a synthetic or local index. It
requires `SERPER_API_KEY` to be set in the environment and the package
installed locally (this tool is not published to npm — install via
`git pull && npm run build && npm install -g .` in its repo).

## Search

```
serper-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>]
```

Defaults: `--region us --lang en --num 10`. Results include `position`,
`title`, `link`, and a 200-character `snippet`. Pass `--fields date,sitelinks`
to include either of those two extra fields when present.

## Scrape

```
serper-axi scrape <url> [--full]
```

Fetches a page's readable text (from Serper's scrape endpoint), truncated to
1,200 characters by default. `--full` returns up to 50,000 characters.

## Notes

- `SERPER_API_KEY` must be exported in the environment before running either
  command; serper-axi checks for it before making any network call.
- Both commands reject invalid input (bad `--num`, non-http(s) scrape URLs,
  loopback/private hosts) with exit code 2, before any network call.
- Run `serper-axi <command> --help` for the full flag reference.
