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
reported as itself, ahead of the file error.

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

## Bright Data gets the character cap as `limit_per_input`

**What you see:** the Bright Data request body is
`{"input": [...], "limit_per_input": <cap>}` with the character cap (1200,
50000, or the configured value) in `limit_per_input`, and the response is cut to
the same cap again on our side.

**Why:** the field was sent with the character limit before the caps became
configurable, and this change passes the resolved cap through unchanged. Bright
Data documents `limit_per_input` as a record count for discovery collections.
Whether `/datasets/v3/scrape` reads it as a character count is unverified: no
Bright Data document says so, and a live check needs a funded account. The local
cut is what guarantees the cap.

**When this becomes a real bug:** if a live request shows Bright Data rejecting
the field, or reading it as a record count so that the cap changes how many
records come back.

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
