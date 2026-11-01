# Changelog

## 0.2.0 (2026-11-01)

First public release. The package name `serp-axi` and this version are the
first artifacts published to npm.

### Search

- SearXNG provider, now the default: free search against a local instance,
  with per-engine counts, a `status` field, and a documented precedence chain
  for endpoint, engines, and timeout (`--searxng-url`, then
  `SERP_AXI_SEARXNG_URL`, then the config file, then the default).
- Serper provider for Google Search results.
- Bright Data provider for search, and for batch scraping with NDJSON
  response parsing checked against a golden fixture.
- Kagi provider: session-token authentication against the server-rendered
  HTML endpoint, with a saved-SERP test fixture.

### Scrape and the fetch escalation ladder

- `scrape` with `--ladder` sends the full ladder request schema and escalates
  only as far as a page requires.
- Ladder rungs 1 to 4 are live: HTTP, Camoufox, zendriver with Cloudflare
  handling, and headed zendriver. Rung 5's audio solve is not wired.
- Rung 1 keeps its own Netscape session jars, separate from the filtered
  browser cookie jars used by the zendriver rungs. Jar filtering refuses a
  cookie scope it cannot determine and stops a public suffix from being
  treated as a base domain.
- Extracted text is whitespace-normalized, and page links come back in
  document order with their anchor text, capped at 200.
- `LADDER_ZENDRIVER_SANDBOX=0` opts the CDP rungs out of Chrome's sandbox.

### Output and CLI

- TOON 4.1.1 output, with `--fields` projection and a decode one-liner in
  help text.
- Structured errors with stable exit codes, and a config file read from
  `$XDG_CONFIG_HOME/serp-axi/config.json`.

### Build and CI

- mise pins Node, Python, and uv; npm scripts cover typecheck, Node tests,
  Python tests, and a named mutation gate.
- The mutation gate runs behind Bubblewrap, and CI installs Bubblewrap and
  relaxes the AppArmor setting that blocks unprivileged user namespaces.

### Release

- release-please workflow with an npm publish job using trusted publishing
  (OIDC). 0.2.0 was published manually from an authenticated local session
  because the release-please credential was invalid. See the README's
  Publishing section.
