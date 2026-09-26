# Things that look like bugs

Behavior that reads as broken but is deliberate. If you came here after hitting
something surprising, it may be listed below.

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
