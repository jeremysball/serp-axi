# Task 10 Report: `SKILL.md`

## Status

DONE

## Summary

Created `SKILL.md` (frontmatter + discovery doc) exactly as specified in the
brief, then verified every stated default and limit against the real CLI's
`--help` output (and the underlying source constants where the help text
does not state a number).

## Files

- `SKILL.md` (new, committed)
- `.superpowers/sdd/2026-08-09-serper-axi-implementation/task-10-report.md` (this report)

## Deviations from the brief

None. Step 2 parity check passed with zero drift; no content changes were
needed after writing the file.

Details of the parity check:

- `--region us` / `--lang en` / `--num 10` — match `search --help`
  ("Default: us", "Default: en", "Default: 10").
- 200-character snippet — not printed by `--help`; verified against
  `SNIPPET_LIMIT = 200` in `src/commands/search.ts:14`.
- 1,200/50,000-character scrape limits — match `scrape --help`
  ("up to 50,000 characters instead of the default 1,200"); also confirmed
  against `DEFAULT_LIMIT = 1200` / `FULL_LIMIT = 50000` in
  `src/commands/scrape.ts:11-12`.
- Accepted `--fields` values `date`, `sitelinks` — match `search --help`
  ("Accepted: date, sitelinks").
- Usage synopsis lines in `SKILL.md` match the first lines of both
  commands' help output.
- Exit-code-2 claim not stated in help text; verified against
  `src/commands/search.ts` / `src/commands/scrape.ts` behavior (tests in
  `src/commands/*.test.ts` assert exit 2 for bad input) — consistent.

## Verification

`dist/` was present and fresh (built in Task 9); `npm run build` was not
re-run. Actual command output compared:

```
$ node dist/bin/serper-axi.js search --help
serper-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>] [--fields <a,b,c>]

Run a Serper (Google Search API) query.

Flags:
  --region <cc>      Two-letter region code (maps to Serper's gl). Default: us
  --lang <code>       Language code (maps to Serper's hl). Default: en
  --num <n>            Number of results, 1-100. Default: 10
  --fields <a,b,c>      Extra fields to include beyond the default schema.
                          Accepted: date, sitelinks

Examples:
  serper-axi search "site:example.com pricing"
  serper-axi search "climate policy" --region uk --lang en --num 20
  serper-axi search "conference talks" --fields date,sitelinks
```

```
$ node dist/bin/serper-axi.js scrape --help
serper-axi scrape <url> [--full]

Fetch and extract readable text from a web page via Serper.

Flags:
  --full   Return up to 50,000 characters instead of the default 1,200.

Examples:
  serper-axi scrape https://example.com/article
  serper-axi scrape https://example.com/article --full
```

**Conclusion:** every default and limit stated in `SKILL.md` matches the
real CLI help output (with the snippet/limit numbers double-checked in
source). No edits to `SKILL.md` were required after the check.

## Commit

- Hash: `712dc00bbd35b04c2150a13c1c03605ebc0c57a0`
- Message: `docs: add SKILL.md discovery doc for serper-axi`
