# Things that look like bugs

Behavior that reads as broken but is deliberate. If you came here after hitting
something surprising, it may be listed below.

## A killed mutation gate can leave a scratch directory

**What you see:** after forcibly killing `npm run test:mutations`, a
`serp-axi-mutation-*` directory can remain in the system temporary directory.

**Why:** the mutation gate runs mutants in disposable copies, reusing the
installed Python environment without synchronizing it from those copies. A
forced kill can leave a scratch directory behind; it does not strand a mutant
in the checkout. Normal completion removes the copy.

**When this becomes a real bug:** if a run changes checkout source, reads a
browser profile into its copy, or synchronizes the shared environment from a
temporary project.

## `search --provider kagi` ignores `--region` and `--lang`

**What you see:** `--region uk --lang de` changes nothing about Kagi results,
while the same flags visibly change Serper and Bright Data results.

**Why:** Kagi's `/html/search` takes region and language from the signed-in
account's own settings, not from the query string. There is no per-request
override to forward them to. Rejecting the flags outright would mean a caller
could not use one command line across providers, so they are accepted and
documented as having no effect here instead.

**When this becomes a real bug:** if Kagi adds query parameters for region and
language, `searchKagi` should start sending `params.gl` and `params.hl` and this
entry should be deleted.

## An expired Kagi token produces "returned no results", not an auth error

**What you see:** a stale `KAGI_SESSION_TOKEN` fails with `Kagi returned no
results` rather than something naming authentication. The help text mentions an
expired token, which looks like a guess.

**Why:** Kagi answers an unauthenticated `/html/search` with HTTP 200 and a
sign-in page, not a 401 or 403. From the client there is no status code to key
on, so an empty parse is the only available signal, and it genuinely is
ambiguous: a real query with zero results looks identical. The error names both
possibilities rather than asserting the one it cannot verify.

**When this becomes a real bug:** if Kagi starts returning a 401/403 for an
expired session, the existing status branch in `src/kagi.ts` already handles it,
and this entry should be deleted.

## The Kagi provider parses HTML instead of calling an API

**What you see:** `src/kagi.ts` contains regex-based HTML extraction, unlike
every other provider in this repo, which parses JSON.

**Why:** Kagi ships no public search API on an ordinary subscription. The
alternatives were a browser automation dependency or shelling out to a
third-party CLI that parses the same HTML anyway. Both add an install step
without removing the parsing. `src/kagi.test.ts` pins the parser against a saved
real SERP so a Kagi redesign surfaces as a test failure.

**When this becomes a real bug:** if Kagi ships a subscription-accessible search
API, this provider should move to it and this entry should be deleted.

## A `--ladder` timeout does not mean `dead`

**What you see:** a rung that exceeds its 90-second subprocess budget reports
`error` and escalation continues. Exhaustion reports `error` only if the final
rung malfunctioned. A domain that does not resolve reports `dead` immediately.

**Why:** `dead` is terminal on purpose: no browser revives a domain that does not
resolve, so the climb stops. A timeout is our own 90-second budget firing, which
says nothing at all about the page, so it climbs instead. Reporting both as
`dead` would let a blown budget look like a decision about the site.

**When this becomes a real bug:** if a timeout is classified as proof that the
page or domain does not exist, terminating escalation.

## The request cap can interrupt escalation

**What you see:** the parent can raise a request-timeout error before all four
rungs finish, even though each rung has its own 90-second budget.

**Why:** the parent's independent 120-second cap limits the whole request.
It is not a promise of 90 seconds for every rung. On expiry the parent resets
the child so a late reply cannot answer a later request.

**When this becomes a real bug:** if a reply from the abandoned request is
delivered to another request, or a documented whole-climb guarantee replaces
this independent cap without changing its enforcement.

## Ceiling 5 stops at rung 4

**What you see:** `--rung-ceiling 5` can report `rungReached: 4`.

**Why:** the protocol retains ceiling 5, but the live registry contains only
rungs 1-4. Audio transcription helpers exist; browser/audio integration is
deferred. A second headed fetch would add no audio solve, so it is not attempted.
Every live rung keeps the killable subprocess budget.

**When this becomes a real bug:** if audio integration ships without adding a
live rung, or the response claims rung 5 ran when only rung 4 was attempted.

## Old working-directory profiles are not picked up automatically

**What you see:** after upgrading, an existing `profiles/` folder beside the
CLI remains on disk, but the browser starts without that folder's warm state.

**Why:** profile storage now uses `$XDG_STATE_HOME/serp-axi/profiles`, with
`~/.local/state/serp-axi/profiles` as the fallback. State is independent of the
launch directory. Old folders are neither imported nor deleted automatically.

**When this becomes a real bug:** if changing the launch directory changes the
profile root without changing `XDG_STATE_HOME`, or an upgrade deletes old state.

## Jar flags do nothing when HTTP or Camoufox answers

**What you see:** a successful scrape through rung 1 or 2 leaves `--jar-out`
unwritten, even when `--cookie-state jar` is set.

**Why:** only zendriver rungs 3 and 4 load and save the filtered jar. Success at
an earlier rung ends escalation; jar flags do not force a later browser launch.

**When this becomes a real bug:** if zendriver succeeds with `jarOut` set but
neither saves the jar nor reports a write error.

## Each zendriver rung loads and saves its own jar

**What you see:** when escalation reaches both zendriver rungs, each reads
`jarIn` before navigation and writes `jarOut` before shutdown. The later save
replaces the earlier one. Explicit paths are not renamed to `.cookies.json`.

**Why:** the rungs run in separate processes with separate browser profiles.
The jar paths are per-request inputs and outputs, not a shared browser context.
Use distinct JSON paths from zendriver's `.cookies.dat` pickle files; an
explicit output path is overwritten as supplied.

**When this becomes a real bug:** if the documented contract changes to carry
the previous rung's output forward automatically, or a rung writes outside
the supplied output path.

## Jar export can fail after page extraction succeeds

**What you see:** a zendriver rung reports an error after extracting a page when
its requested `jarOut` cannot be saved.

**Why:** the requested export is part of the result. Returning success would
hide a missing or stale jar from the caller. Atomic replacement also requires
write access to the target's parent directory, even when the old file is writable.
A symlink output keeps the link and replaces its resolved target.

**When this becomes a real bug:** if the rung reports success without completing
the requested export, destroys the old jar on a failed write, or replaces the
symlink itself.

## `--include-markup` does almost nothing for Serper and `--ladder`

**What you see:** `serp-axi scrape <url> --include-markup` and the same command
without the flag print the same record, apart from the rerun command in `help`,
which carries the flag whenever it is on.

**Why:** both paths build a record with no raw-HTML field. Serper's record is
`url`, `title`, and `text`, taken from the response by name in
`src/commands/scrape.ts`, so nothing else in the response reaches the output.
Ladder rung 1 strips tags and then decodes entities (`extract_html` in
`ladder-cli/ladder_cli/rungs/http.py`), and the browser rungs read
`document.body.innerText`. The one field the flag can change is `title`, when it
is itself a whole HTML document. The flag is accepted everywhere so one command
line works across providers, and every provider goes through
`shapeScrapeRecord`.

**When this becomes a real bug:** if Serper or ladder starts returning a field
whose name ends in `html`, and it shows up in the output without
`--include-markup`, or if `--include-markup` is rejected under one provider.

## The `includeMarkup` config key is read for Bright Data only

**What you see:** `"includeMarkup": true` in the config file keeps raw-HTML
fields in a Bright Data run, but a Serper or `--ladder` run ignores it, and a
malformed value (`"includeMarkup": "yes"`) fails a Bright Data run and passes the
other two.

**Why:** Bright Data is the one provider whose records carry raw-HTML fields of
their own, so it is the only path that asks the config what `includeMarkup`
says. Every path does open the file now, for the `maxChars` and `fullMaxChars`
keys (see "Every scrape path opens the config file, after its input checks"
below), but a Serper or `--ladder` run never looks at the `includeMarkup` key, so
a malformed one still passes there. The flag and `SERP_AXI_INCLUDE_MARKUP` are
read for every provider, and they win over the config key.

**When this becomes a real bug:** if a Bright Data run ignores the config key
when neither the flag nor the env var is set, or if a run reads the config file
before it has checked its URL and API key.

## `runSearch` with no config argument reads the real config file, and a bad file stops a flags-only searxng run

**What you see:** a test or script that calls `runSearch(args, fetchImpl, env)`
without the fourth argument gets the config file from `env`'s
`XDG_CONFIG_HOME`, or from the process's home directory when that is unset. It
does not get an empty config. A searxng run also reads the file before it looks
at flags, so a corrupt `config.json` fails `--provider searxng` even when
`--searxng-url`, `--engines`, and `--search-timeout-ms` are all given, and it
replaces the error for a bad `--searxng-url`. Injecting `HOME` in the env has no
effect on where the file is looked for.

**Why:** the CLI entry point passes no config, so the default has to be the real
file. Tests pass `{}` to opt out. Making the read lazy, or taking the home
directory from the handed env, would change what `serp-axi search` does on a
broken file, and `runScrape` has the same read (`config ?? loadStoredConfig(...)`
in `src/commands/scrape.ts`), so the two should change together. Serper,
Bright Data, and Kagi runs never open the file, and flag errors such as
`--num 0` are reported before it is opened. Both are pinned by tests in
`src/commands/search.test.ts`.

**When this becomes a real bug:** if a non-searxng run opens the config file, if
a flag error is replaced by a config error for a flag checked before the load,
or if a test that hands in a config still reads the developer's own file.

## A hint's rerun command repeats flags, not env or config settings

**What you see:** the command in `help` has `--include-markup`, `--dataset-id`,
or a ladder axis flag only if that flag was on the command line. A value that came
from `SERP_AXI_INCLUDE_MARKUP`, `BRIGHTDATA_DATASET_ID`, or the config file is
not repeated, except that `--include-markup` is added whenever markup is on,
whichever way it was turned on. The `--include-markup` hint also repeats the cap
flags as typed (`--max-chars 500`, or `--full --full-max-chars 7000`), and the
`--full` hint does not: it repeats nothing of `--max-chars`, because `--full`
refuses it. A cap that came from `SERP_AXI_MAX_CHARS`, `SERP_AXI_FULL_MAX_CHARS`,
or the config file is never repeated.

**Why:** the env and config settings apply to the rerun by themselves, in the
same shell. The hint is shorter, and a pasted command does not pin a value that
the reader may have changed. A typed cap flag is the one flag-only setting that
changes what the rerun returns without changing which record it fetches, so
dropping it from the markup hint would bring the markup back under a different
cap than the reader chose. The cap flags are repeated only after they passed the
whole-number check, so they need no shell quoting.

**When this becomes a real bug:** if the rerun fetches a different dataset, or
uses different ladder axes, than the run that printed it, with the same
environment; or if the `--include-markup` hint drops a cap flag the run was
given, or the `--full` hint carries `--max-chars`.

## Kept text fields can still contain tags, and `markdown` and `html2text` can repeat each other

**What you see:** a Bright Data record keeps both `markdown` and `html2text`,
which carry nearly the same text. A page about HTML can show a literal `<div>`
in a field that stayed.

**Why:** the omission rule looks at a field's name (ending in `html`) and at
whether its whole value is an HTML document. It does not rewrite the inside of a
field that stays. A regex tag-stripper would delete the `<div>` a page is
legitimately talking about, and ladder rung 1 decodes entities after it removes
tags, so a tag in its text is content. Dropping
`html2text` to save space would also be a guess about which field a caller reads.
The two are not copies. A live scrape of `https://example.com` on 2026-11-03
returned the same sentence in both, with `html2text` hard-wrapped at a line width
(a `\n` mid-sentence), and the recorded fixture in `src/fixtures/` differs in
markup style as well (`# Example Domain` against `EXAMPLE DOMAIN`).

**When this becomes a real bug:** if a field whose name ends in `html`, or whose
value is a whole HTML document, appears in the output without
`--include-markup`.

## A record whose only text is an HTML document keeps it

**What you see:** a Serper or ladder `text` that begins with `<!doctype html>`
comes back, cut to the character limit, with no `markupOmitted` entry. A Bright
Data record with `page_html` and nothing else textual does the same. The same
`page_html` next to a `markdown` field is left out.

**Why:** the rule is "omit markup unless it is all there is to show". When every
text field the limit applies to is markup, omitting them would turn "the page
came back as HTML" into an empty result with a hint to rerun for the thing that
was just dropped. Showing the document, bounded by the limit, is the more honest
failure. Markup outside that scope (a Serper `title`) is still omitted, because
nothing would bound it.

**When this becomes a real bug:** if a markup field is kept next to a field of
real content, or if the only text a record has is dropped.

## Prose that opens with a literal `<html>` is classed as a document

**What you see:** a Bright Data field named `summary` whose value is
`<html> is the root element` appears in `markupOmitted`, while the same text in
a field named `snippet` that begins `<div>` is kept.

**Why:** the document test looks only at how a value opens: a doctype or an
`<html` tag, after any whitespace, comments, and XML prologs. That is cheap and
cannot be fooled into a slow scan on a large page (the scan is linear; a test
pins it). It cannot tell a page from a sentence that starts with the same
characters, and a `<div>` fragment under a name that does not end in `html` is
treated as content for the same reason: nothing here parses HTML. The omission
is not silent, so `--include-markup` brings the field back.

**When this becomes a real bug:** if a field that stays contains a whole
document (starting with a doctype or `<html>`), or if an omitted field is not
named in `markupOmitted`.

## Serper and ladder `title` and `warning` are not cut to the limit

**What you see:** with the default 1,200-character limit, a Serper or ladder
record can still print a `title` (or the ladder's `warning`) longer than that,
and no `truncatedFrom` marker covers it.

**Why:** the limit is a bound on the page body. Serper and ladder each declare
one body field, `text`, and the limit applies to that field only. A title is
expected to be short, and so is the ladder's `warning`, a message the child
writes by protocol. The `warning` is attached after the record is shaped
(`src/commands/scrape.ts`, after `shapeTextRecord`), so it rides outside the
limit. Bright Data's every-string scope has
no such carve-out because its record shape is not ours to know.

**When this becomes a real bug:** if a title or warning large enough to matter
shows up in practice, since that would mean the premise (short strings) is
false and the scope needs to widen.

## A document with a comment or XML prolog before the doctype is still a document

**What you see:** a field that starts with `<!-- saved from url=... -->` or
`<?xml version="1.0"?>` and then `<!doctype html>` is omitted as markup, even
though its first characters are neither.

**Why:** saved pages and some proxies prepend those. The scan skips whitespace,
comments, and prologs before it looks for the doctype, one at a time, so a page
with many comments costs time proportional to its length.

**When this becomes a real bug:** if an unterminated comment or prolog makes the
scan run past the end of the value, or the scan's time grows faster than the
value's length.

## There is no flag to turn markup back off

**What you see:** with `"includeMarkup": true` in the config file, no CLI flag
switches it off for one run.

**Why:** the flag is presence-only like the other boolean flags in `scrape`, so
`--include-markup` can only turn it on. `SERP_AXI_INCLUDE_MARKUP=0` is the
per-run override: env outranks config.

**When this becomes a real bug:** if the env override stops beating the config
key, or `SERP_AXI_INCLUDE_MARKUP=0` is read as true.

## A bad `--full` cap fails a run that never uses `--full`, but not the other way round

**What you see:** `SERP_AXI_FULL_MAX_CHARS=abc serp-axi scrape <url>` exits with a
usage error naming `SERP_AXI_FULL_MAX_CHARS`, though the run never asked for
`--full`. The reverse is not true: `SERP_AXI_MAX_CHARS=abc serp-axi scrape <url>
--full` runs, because a `--full` run never reads the normal cap. A bad `maxChars`
in the config file is skipped the same way. Only the source that wins for each cap
is checked, so a bad env value under a flag, or a bad config value under an env
var, never fails anything.

**Why:** the rerun hint under a truncated field prints the real `--full` cap
("to see up to 8000 characters"), so a normal run has to resolve it. A hint that
printed a number nobody validated would be a wrong fact, and resolving the cap
lazily would make the failure depend on whether the page happened to be long
enough to truncate. A `--full` run prints no hint that names the normal cap, so
it has nothing to validate. That also keeps the `--full` rerun that a hint
offers working when the original run got past a bad `SERP_AXI_MAX_CHARS` with a
`--max-chars` flag.

**When this becomes a real bug:** if a value that loses to a flag or an env var
is checked and fails the run, if a malformed cap passes and a hint prints it, or
if a `--full` run fails on `SERP_AXI_MAX_CHARS` or `maxChars`.

## `--max-chars` is refused with `--full`, and the `--full` hint never offers `--max-chars`

**What you see:** `serp-axi scrape <url> --full --max-chars 500` exits with
"--max-chars cannot be combined with --full", and `--full-max-chars 500` without
`--full` exits with "--full-max-chars only applies with --full". The rerun hint
says `Run \`serp-axi scrape '<url>' --full\` to see up to N characters` and
leaves `--max-chars` off, even when the run being repeated used it. An env var or
config key for the cap that the run does not use is not a conflict:
`SERP_AXI_FULL_MAX_CHARS` on a normal run is still checked (see the entry above),
and `SERP_AXI_MAX_CHARS` on a `--full` run is not read at all.

**Why:** `--full` picks which cap applies, so `--max-chars` beside it would name
a cap the run does not use, and `--full-max-chars` alone would be read by
nothing. Accepting either and ignoring it is the silent failure the other
flag-conflict checks in `scrape` already refuse. Env and config settings are not
conflicts because they are standing defaults for both modes. The `--full` hint
omits `--max-chars` because the rerun is the `--full` run, where `--max-chars` is
an error; the `--full` cap it prints is the one that rerun will use.

**When this becomes a real bug:** if a hint suggests a command that exits with
the usage error above, or if a conflicting pair reaches the network.

## Every scrape path opens the config file, after its input checks

**What you see:** a corrupt or unreadable `config.json` now fails a Serper scrape
(it used to be read only by `--ladder`, and by Bright Data when the flag and env
var had not settled `includeMarkup`). A Bright Data run with `--include-markup`
fails on it too. A bad URL, a missing API key, or a bad cap flag is still
reported as itself, ahead of the file error. A malformed cap is checked after
the URL, provider, axis and ladder checks, so it cannot mask one of those; it is
still checked before the file is opened.

**Why:** `maxChars` and `fullMaxChars` apply to every path, so every path needs
the file. It is read once, after the URL and key checks, so a broken file never
replaces a more useful error. Unlike `includeMarkup`, these keys cannot be left
out of a path. The file is opened even when a flag or env var already settles both
caps, because skipping the read in that case would make a corrupt file fail a
run only when the settings happen to leave a cap open, which is harder to
diagnose than failing every run the same way.

**When this becomes a real bug:** if a run opens the config file before it has
checked its URL, its API key (or ladder binary), and the cap flags, or if a
path opens it twice.

## The Bright Data cap is applied after the records arrive

**What you see:** `serp-axi scrape --provider brightdata --max-chars 5` sends
Bright Data no limit of any kind (the request body is `{"input": [...]}`,
nothing else). Whatever comes back is cut afterward: every long top-level
string except `url` is cut to 5 characters. The cap shortens the output, and
nothing in the request asks Bright Data to send less.

**Why:** the only limit the `/datasets/v3/scrape` reference names is
`limit_per_input`, and it counts records per input, for discovery requests
("Maximum records returned per input", schema `minimum: 1`). It is not a
character limit. An earlier version sent the character cap in it anyway. Sent as
a record count, `--max-chars 5` would have asked a discovery dataset for five
records. The documented fields are `input`, `limit_per_input` and
`custom_output_fields`; none limits the length of a string. Source:
`https://docs.brightdata.com/api-reference/web-scraper-api/synchronous-requests`,
read 2026-11-02. The cap is applied locally in `shapeScrapeRecord`.

**What the download is bounded by instead:** the byte cap in `src/body.ts`
(`DEFAULT_MAX_RESPONSE_BYTES`, 64 MiB; `--max-response-bytes`,
`SERP_AXI_MAX_RESPONSE_BYTES` or `maxResponseBytes` to change it). The old
`limit_per_input` carried the character cap (1200 by default, 50000 with
`--full`; `DEFAULT_MAX_CHARS` and `DEFAULT_FULL_MAX_CHARS` in
`src/scrape-output.ts`), so by default it also told a discovery dataset to
return at most 1200 records per input. That was an accident of reading a record
count as a length, not a bound anyone chose. The request `scrapeBrightData`
builds has only `dataset_id`, `notify` and `include_errors` in its query string
(asserted in `src/brightdata.scrape.test.ts`), so it is not a discovery request
and the field had no records to limit. That is read from the reference, not
tested against the live endpoint. The byte cap is what keeps a large reply out of memory, and it stops
the read, not just the output.

**When this becomes a real bug:** if Bright Data adds a field-length limit to
this endpoint, the download could shrink and this entry should go. Or if a live
request shows the endpoint rejecting a body that holds only `input`; the opt-in
live test (`SERP_AXI_LIVE_BRIGHTDATA`) sends exactly that. Or if a normal scrape
starts hitting the byte cap because a dataset returns many records per URL, in
which case a record limit that is chosen on purpose, not borrowed from the
character cap, belongs in the request.

## The Bright Data cap covers top-level strings, not nested ones

**What you see:** a Bright Data record with a long string inside a nested object
or an array (`{"reviews": [{"text": "<50,000 characters>"}]}`) comes back with
that string whole, under the 1,200-character default, and no `TruncatedFrom`
marker names it. A long top-level string in the same record is cut.

**Why:** the cut walks the record's own entries and cuts each value that is a
string (`shapeScrapeRecord` in `src/scrape-output.ts`). It does not descend into
objects or arrays, because the shape of a Bright Data record depends on the
dataset and is not ours to know, and a marker such as `reviews[3].textTruncatedFrom`
has no obvious home in the output. Only `url` is exempt from the top-level cut,
so that it stays usable as a link. The cap is a bound on the fields a record is
known to hold, not a promise about its total size.

**When this becomes a real bug:** if a dataset puts its page text in a nested
field and a normal run returns it uncapped, since the cap would then fail at what
it is for. The fix is to descend, with a marker that names the path.

## A cut can come out one character short of the cap

**What you see:** `--max-chars 3` on a field that starts `ab` followed by an emoji
returns `ab` (two characters), not three, and the marker reports the real total.
With `--max-chars 1` on a field that starts with an emoji, the field comes back
empty.

**Why:** the cap counts UTF-16 code units, like JavaScript's string length, and an
emoji or other character outside the Basic Multilingual Plane takes two of them.
A cut between the halves would leave half a character, which Node writes to
stdout as the replacement character U+FFFD. `truncate` in
`src/output.ts` backs up one unit instead. The `totalChars` it reports stays in
code units, so it can exceed the number of characters a reader counts.

**When this becomes a real bug:** if a cut field ends in half of a surrogate pair,
or if backing up removes more than one unit.

## Every response read goes through body.ts

**What you see:** `npm run guard` (and CI, and the pre-commit hook) fails on a
bare `response.text()`, `.json()`, `.arrayBuffer()`, `.blob()`, `.formData()` or
`.bytes()` anywhere in `src/`, on any `.body` read (member access, subscript, or
destructuring), and on an import or re-export of `node:http`, `node:https`,
`node:http2` or `undici`. `src/body.ts` and the `*.test.ts` files are exempt. One
line in production code carries a bypass: `JSON.parse(envelope.body)` in
`src/brightdata.ts`, where `body` is a string field of Bright Data's parsed reply
and not a stream.

**Why:** the belief is that no network response is read into memory without a
byte bound. A scan of the tree before the fix (commit `4606e31`) found nine
unbounded reads across Serper, Kagi, SearXNG and Bright Data, so the fix was a
bounded reader (`readBodyText`) and a rule that makes the next unbounded read
fail the build. Three rules cover three
routes: the method names, the `.body` stream (a `for await` loop, `getReader()`,
a stream handed to another function), and a second HTTP client that would never
call `fetch` at all. A rule that reports a warning would be read once and then
ignored, so all three are errors, and `--error=unused-suppression` makes a stale
bypass an error as well.

The rules match names, not types. ast-grep cannot tell a `Response` from another
object with a `.text()` method or a `body` field, so a false positive takes a
bypass with the reason written next to it (`// ast-grep-ignore: <rule-id>
(<reason>)`, on the line above or at the end of the line). The reason sits in
parentheses because the pre-commit dash gate rejects a double hyphen, the
separator ast-grep's own examples use; ast-grep 0.44.1 reads the rule id and
ignores the rest. They also miss method reads that never name the method at the
call: `response["text"]()`, `const { text } = response`, and `const read =
response.text; read.call(response)` all pass. That is a deliberate limit. The
risk being guarded is a developer or an agent copying `response.text()` into a
new provider, and a rule written to stop a deliberate evasion would flag ordinary
code to do it. The `.body` stream is different: a subscript or a destructuring
pattern is a plausible way to reach it, so those spellings are covered.

The guard covers HTTP responses only. `src/ladder.ts` reads a local child's
stdout, not a `Response`, and bounds it by its own check: the pending line may not
pass the same cap (see "The ladder cap bounds the child's read and its reply
line" below). No ast-grep rule watches that read; `src/ladder.test.ts` does.

`src/guards.test.ts` runs each rule against code it must catch, code it must
leave alone, and the bypass forms, and it fails if a rule file has no case that
makes it fire.

**When this becomes a real bug:** if `unbounded-response-read` or
`response-body-stream-access` flags code that is not a response and the bypass
count in `src/` grows past a handful, since the rule would then be teaching people
to type the bypass. Or if a provider reads a body without a hit from any rule, or
`npm run guard` can pass on a tree that has a bare `response.text()`.

## A response over the byte cap is an error, never a partial result

**What you see:** a response larger than `--max-response-bytes` (default 64 MiB)
stops the run with `<provider> response is larger than the <n> bytes serp-axi
will read`, naming the flag, the env var and the config key, and saying that the
key is read by `scrape` and `search --provider searxng`. No results are
printed, even when the first megabyte of the body held a whole valid answer.

**Why:** a JSON document cut off at a byte boundary does not parse, and a cut-off
page of text looks complete and is wrong. The character caps (`--max-chars`)
shorten text on purpose and mark each cut with a `<field>TruncatedFrom` count;
the byte cap protects memory and has no such marker, so it refuses instead. A
`content-length` over the cap is refused before a byte is read, unless the
response is compressed: then the header counts wire bytes rather than the
decoded ones the cap measures, so only the read can decide. Without a usable
header the read stops the moment the running count passes the cap.

**When this becomes a real bug:** if an over-cap body ever produces output from
part of it, or if the error does not say how to raise the cap.

## The byte cap counts decoded bytes, and an error body is cut at 64 KiB, not refused

**What you see:** a gzip reply of 1 MiB that expands to 100 MiB is refused at the
default cap, though only 1 MiB crossed the network (`src/body.socket.test.ts`
serves exactly that over a real socket). Separately, an error response longer
than 64 KiB is not an error of its own: only its first 64 KiB is read. Kagi and
Bright Data put the start of that text in the failure message, shortened again
by `boundedDetail`. Serper reads an error body only for a status it does not map:
the mapped 403, 429, 404 and 5xx branches decide from the status alone and hang
up on the body unread. An unmapped body cut at 64 KiB no longer parses, so that
status reports `no details`. If an error body cannot be read at all, the message
says `(the response body could not be read: <reason>)` where the server's text
would have gone, and Serper's JSON parse of that sentence fails the same way.

**Why:** `fetch` undoes gzip and brotli before the stream hands over any bytes,
so the count sees the expanded size, which is what costs memory and what a
compression bomb attacks. A compressed response's `content-length` counts wire
bytes, so it is not compared with the decoded cap; the read still enforces the
cap. An error body only explains a status code the run has already failed on, so
cutting it loses little and refusing it would replace a useful failure with a
less useful one. A mapped Serper status does not need the body at all, so reading
it would delay the error and do I/O for nothing. The marker keeps a failed read
from looking like a server that said nothing. SearXNG reads no error body at all;
its errors come from the status code, and it hangs up on the body before
throwing.

**When this becomes a real bug:** if the count uses compressed bytes, if an error
body read can throw past the status-code failure it was explaining, or if the
failed-read marker is empty.

## The `maxResponseBytes` config key is read for scrape and searxng search only

**What you see:** `"maxResponseBytes": 1000` in the config file caps every
`scrape` run and every `search --provider searxng` run, but a `search --provider
serper`, `kagi` or `brightdata` run ignores it, and a malformed value
(`"maxResponseBytes": "big"`) fails the paths that read it and passes the rest.
`--max-response-bytes` and `SERP_AXI_MAX_RESPONSE_BYTES` apply to all of them.
The overflow error names the config key only for the paths that read it, so a
Serper search's advice does not send its reader to a key that cannot affect the
run.

**Why:** searxng is the one search path that opens the config file, for its URL,
engines and timeout. The other search providers are configured by flag and env
var alone, and making them open the file for one key would put a corrupt
`config.json` in the way of a Serper search that never needed it (see "`runSearch`
with no config argument reads the real config file" above). It is the same shape
as the `includeMarkup` key.

**When this becomes a real bug:** if a search provider starts opening the config
file for another reason, since the key should then apply to it too, or if a path
that does read the key lets a bad value through.

## The ladder cap bounds the child's read and its reply line

**What you see:** two different failures share the one cap.

A page whose HTTP body is over the cap stops inside the ladder child, which
reports `ladder response is larger than the <n> bytes serp-axi will read`; the
run fails with the ladder verdict `error` rather than printing part of the page.
The child did not read the whole body into memory first.

A reply line that is over the cap even though the page body was under it fails
differently: `ladder scrape failed: ladder-cli printed a line longer than <n>
bytes, which serp-axi will not read`. The same run with a larger cap succeeds.
A malformed `SERP_AXI_MAX_RESPONSE_BYTES` or `maxResponseBytes` stops a
`--ladder` run too, as it stops every other scrape.

**Why:** the child reads the network itself, so it cannot rely on the parent's
line check, which only runs after the page has been serialized. The parent sends
its resolved cap as `maxResponseBytes` on the request (protocol 4), the rung
hands it to the isolated child as `--max-bytes`, and the HTTP rung reads the
body with primp's `iter_bytes` instead of `response.text` or `response.json`.
The running byte count is checked before each chunk is kept, and the response is
closed the moment it passes, so the child holds at most the cap plus one chunk
of a runaway page.

The parent keeps its own check because the two measurements are not the same
size. The ladder CLI prints each reply as one JSON line: the text after JSON
escaping, plus the title, the links and the rung metadata. A quote or a newline
in the page costs two bytes; a non-ASCII character costs its UTF-8 width, because
the ladder CLI writes with `ensure_ascii=False` (`ladder-cli/ladder_cli/cli.py:256`).
A page can therefore fit under the body cap and still produce a line over it.
Every line in a chunk is measured before the chunk is appended, against the
bytes already pending for the line it extends, and a child over the line cap is
killed and respawned by the next fetch, because a cut-off line cannot be parsed.
Measuring every line matters when a chunk begins with a newline (a blank startup
line, or the end of the previous reply): checking only the first line would count
zero bytes and let the reply after it through. The same cap bounds the startup
output before the ready line, so a child that prints without ever ending a line
is stopped too. This is a different thing from `--max-chars`, which trims text
after it has been read.

**When this becomes a real bug:** if a body under the cap still fails with the
child's `larger than` error, or if the child returns a page after reading more
than the cap (the read lives in `_read_body` in
`ladder-cli/ladder_cli/rungs/http.py`), or if a page that fits under the cap as
plain text fails on the parent's line check and the line is not over the cap by
that count (the byte count lives in `onStdout` in `src/ladder.ts`, and
`src/ladder.test.ts` pins it at the cap and one byte under), or if a malformed
cap fails a run before the URL, the binary or the other flags have been checked.

## Test-only modules are left out of the package by name

**What you see:** `src/live.ts` and `src/fixtures.ts` are compiled into `dist/`,
and `package.json` `files` lists `!dist/live.js` and `!dist/fixtures.js` so the
published tarball has neither. A new test helper that is not added to that list
ships.

**Why:** `files` takes `dist` minus `*.test.js`, and a helper that tests import is
not named `*.test.ts`. `live.js` was shipping before this was noticed. A test in
`src/guards.test.ts` finds every non-test module that only test files reach,
following a helper through another test-only module, and fails unless `files`
excludes it, so the list cannot fall behind unnoticed.

**When this becomes a real bug:** if `npm pack --dry-run --json` lists a file
that only tests use, or if the packaging test passes with a helper missing from
`files`.

## A Bright Data hint can say "Rerun this scrape with --full" and print no command

**What you see:** most truncation hints read ``Run `serp-axi scrape '<url>'
--provider brightdata --full` to see up to 50000 characters``. For some records
the hint reads `Rerun this scrape with --full to see up to 50000 characters`
and shows no command.

**Why:** the command names the record's `url`, then the url this scrape asked for
(`input.url`, which Bright Data echoes back). A record that carries neither has no
honest url to print. The hint used to print `'<url>'` there, a command the reader
could not paste and run, so it now names the flag and leaves the command out
(`recordUrl` in `src/commands/scrape.ts`).

**When this becomes a real bug:** if a record that does carry `url` or `input.url`
gets the command-less wording, or if a `<url>` placeholder reaches any hint again.

## The shell-sensitive tests run again with poisoned settings

**What you see:** `npm run check` and CI run the full suite once as `npm test`,
then rerun only the test files that can see the shell as `npm run
test:hostile-env`. The rerun has `SERPER_API_KEY`,
`SERP_AXI_MAX_RESPONSE_BYTES`, the `SERP_AXI_LIVE_*` opt-ins and every other
variable the source reads set to `/nonexistent/serp-axi-hostile-env`, and an
empty `HOME` and `XDG_CONFIG_HOME`, so it cannot read the developer's real
config file either. The 10 live tests are skipped in both runs.

**Why:** the first run cannot see a test that reads the developer's shell or
config. A clean runner has none of those variables and no config file, so a test
that forgot to hand `runScrape` or `runSearch` its own env passes there and fails
on a machine that exports a key. That happened twice before the second run
existed: `searxng.test.ts` failed 24 of 48 tests under an exported
`SERP_AXI_MAX_RESPONSE_BYTES`, and two `scrape.test.ts` tests read the shell and
the real config file. The variable names are scanned from `src/` by
`scripts/hostile-env.mjs`, so a new setting is poisoned without an edit. The
files are found from the import graph: a test that names `process.env` or reaches
a module that does is run, and the real-socket and ast-grep suites that cannot
see the environment are not run a second time.

**When this becomes a real bug:** if the second run passes while a test still reads
the shell (a variable under a prefix the script does not scan: add the prefix to
the shared list in `scripts/env-prefixes.mjs`, which both the script and
`src/searxng.test.ts` import), if a shell-sensitive test is not selected by the
import graph, or if the script reports a clean run after finding no names or no
test files to run (it exits 2 instead).
