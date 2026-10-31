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
