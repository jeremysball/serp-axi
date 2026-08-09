# serper-axi design

Date: 2026-08-09

## Purpose

An AXI-compliant CLI that lets agents run Serper (Google search API) queries
and page scrapes via shell execution, with token-efficient TOON output,
structured errors, and no interactive prompts.

## Architecture

Standalone TypeScript package at `/workspace/serper-axi`, npm-private (not
published), mirroring the layout of `gh-axi`/`tasks-axi`.

```
serper-axi/
  src/
    generated/
      serper-client.ts   <- regenerated only, via `npm run generate`
    commands/
      search.ts           <- hand-written; calls generated client
      scrape.ts
    bin/
      serper-axi.ts        <- runAxiCli() entrypoint
  mcporter.json             <- dev-time only; server def for generation
  package.json
```

- `mcporter.json` defines the `serper` stdio server: command
  `npx -y mcp-server-serper`, env `SERPER_API_KEY: "${SERPER_API_KEY}"`
  (placeholder only — mcporter resolves it from the process environment at
  generation time and at no point writes the literal key to disk). Safe to
  commit.
- `npm run generate` runs `mcporter generate-cli --server serper --output
  src/generated/serper-client.ts` to (re)produce typed bindings for the two
  tools the `mcp-server-serper` package exposes: `google_search` and
  `scrape`. This file is canonical/generated — never hand-edited; re-run the
  script and diff instead.
- `src/commands/*.ts` hand-written command handlers import the generated
  client, call the tool, and reshape the result into AXI output.
- `src/bin/serper-axi.ts` wires everything through `axi-sdk-js`'s
  `runAxiCli()`, which supplies command-first dispatch, bare `--help`/
  `--version`, TOON serialization, structured `AxiError` handling, and a
  free `serper-axi update` self-update command.
- Runtime dependencies: `axi-sdk-js`, `@modelcontextprotocol/sdk` (pulled in
  by the generated client code). `mcporter` is a devDependency only —
  nothing shells out to it at runtime; the compiled CLI talks to the
  `mcp-server-serper` MCP process directly.
- Install: `npm run build && npm install -g .`, landing `serper-axi` on
  `PATH` via the existing npm prefix (`~/.local/share/npm-global`).

## Commands

### `serper-axi search "<query>" [--region <cc>] [--lang <code>] [--num <n>]`

- Defaults: `--region us`, `--lang en`, `--num 10`.
- Output (TOON): `count`, an `answerBox` line when Serper returns one, and a
  `results` array with default schema `position,title,link,snippet`
  (snippet truncated to ~200 chars). Snippet stays in the default schema —
  without it an agent can't judge relevance without a follow-up scrape.
- Zero results: explicit `results: 0 results found for query "<query>"`, not
  an empty array with no context.
- Contextual disclosure: suggest `serper-axi scrape "<link>"` against one of
  the returned links (parameterized, not a guessed concrete URL beyond
  what's already in the result).

### `serper-axi scrape <url> [--full]`

- Output (TOON): `url`, `title`, `text` (truncated to ~1200 chars with a
  total-length note when truncated).
- `--full` returns the untruncated text; only suggested in output when
  content was actually truncated.

### No-args home view

This is a stateless action tool — there's no list of "things" to show
ambiently the way `gh-axi issue list` or `tasks-axi` can. The home view
shows `bin` (path, `~`-collapsed), a one-line description, and both
commands as usage examples with placeholder args. No manufactured "state."

## Errors

All errors surface on stdout as structured `error:`/`help:` pairs via
`AxiError`, never a raw stack trace, HTTP body, or MCP transport error:

- Missing `SERPER_API_KEY` in the environment → actionable message naming
  the env var, checked before any MCP call.
- Serper API failures (401/403 invalid key, 429 rate limit, 5xx) →
  translated to a concise `error` + `help` pair; the underlying dependency
  name (`mcp-server-serper`, Serper's own API) is never referenced in the
  suggestion, only `serper-axi`'s own commands/flags.
- Unknown flags/positional args → rejected by name, exit code 2, valid
  flags for that subcommand listed inline.
- Exit codes: 0 success (including a legitimate zero-results search), 1
  error, 2 usage error.

## Explicitly out of scope for v1

- **SessionStart hook / ambient session integration.** Nothing stateful
  exists for this tool to surface at session start (unlike an issue tracker
  or task list), so a hook would cost tokens on every session with no
  payoff. Skipped for v1; revisit if a use case for ambient context emerges.
- **Installable skill (`SKILL.md`).** Still planned as the discovery path
  (per AXI's secondary recommendation), generated from the same home-view
  content, with a `--check` step to catch drift. Included in the
  implementation plan.
- Publishing to the npm registry — stays a local, globally-linked install
  unless that changes later.
