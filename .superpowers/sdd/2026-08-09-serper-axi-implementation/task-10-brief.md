### Task 10: `SKILL.md`

**Files:**
- Create: `SKILL.md`

**Interfaces:**
- None — static documentation. Must stay consistent with the real `--help` output produced by Task 6/7's `SEARCH_HELP`/`SCRAPE_HELP`
  text (defaults, flags, limits).

- [ ] **Step 1: Write `SKILL.md`**

```markdown
---
name: using-serper-axi
description: Use when an agent needs to run a live web search or scrape a specific page's text via Serper (Google Search API) — search results with title/link/snippet, or a page's readable text extracted from its URL.
---

# serper-axi

`serper-axi` is a CLI that runs Serper (Google Search API) queries and page
scrapes for agents. It requires `SERPER_API_KEY` to be set in the
environment and the package installed locally (this tool is not published to
npm — install via `git pull && npm run build && npm install -g .` in its
repo).

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
```

- [ ] **Step 2: Verify parity against the real CLI's help output**

Run: `node dist/bin/serper-axi.js search --help`
Run: `node dist/bin/serper-axi.js scrape --help`

Confirm by inspection that every default and limit `SKILL.md` states (`--region us`, `--lang en`, `--num 10`, 200-character snippet,
1200/50000-character scrape limits, accepted `--fields` values `date`/`sitelinks`) matches what these two commands actually print.
Fix `SKILL.md` if anything drifted.

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "docs: add SKILL.md discovery doc for serper-axi"
```

---

