# Challenge-solver spike report (2026-10-03)

Scope: one residential IP, paced (>=15s per host), no paid proxies or solvers. Data and the
harness ledger (H1-H8) are in this directory; `flywheel.md` has every observed line quoted.

| Q | Question | Verdict | Falsifier fired? |
|---|---|---|---|
| Q0 | Is headed Chrome under Xvfb broken by the harness or by Chrome? | Harness (environment): `/usr/lib/libEGL.so.1.1.0` and `libGLESv2.so.2.1.0` overwritten by ANGLE builds from `/usr/local/lib`; Xvfb deadlocked in a library constructor. Fixed 09:45 by `pacman -S libglvnd`; headed Chromium now works. Headed: 10/16, first DataDome pass (etsy), but reddit and SO challenge it where headless passed. | n/a |
| Q1 | Does a fingerprint-clean browser pass CF managed challenges with no interaction? | Camoufox yes (SO, glassdoor; indeed no). zendriver no (SO only). | Camoufox no (1/3 blocked); zendriver yes (2/3) |
| Q2 | Does a checkbox click (zendriver `verify_cf`) clear what Q1 didn't? | Yes, causal: click 6/6 (indeed 3, glassdoor 3, ~13-15s), no-click control 0/6. | No |
| Q3 | Does clearance survive a browser restart? | Site-dependent. glassdoor: same tab at +60s and same-profile restart pass 4/4. indeed: rechallenged at +60s even in the same tab, and after restart (real limit). zendriver cookie jar: rechallenged at +1, +10, +30 min (+60 check stopped). zendriver new tabs are always rechallenged with the cookie present (H8). | glassdoor: no. indeed: yes |
| Q4 | Can a scripted press-and-hold beat PerimeterX? | No, 0/4 on zillow (stealth_new Chromium). The hold registers (spinner screenshot) and is still denied. Clean browsers were never challenged on zillow/walmart/bloomberg. | Yes |
| Q5 | Can local Whisper solve reCAPTCHA v2 audio? | 6/10 solved, 4/10 refused by Google ("automated queries"), 0 wrong transcripts. Limit is IP rate, not ASR. | No (60% >= 50%) |
| Q6 | Can Jev label challenge pages better than regex? | Coarse 0.982 vs regex 0.977 (~1 row); fine 9-way 0.913. Passes mutations (shuffle no change, blank collapses, no-title drops fine to 0.840). Gold is rule-made; no held-out states yet. | No, but the margin is noise-level |

## Hostile-16 pass rates (spot-checked against page text)

- Camoufox 12/16. Blocked: indeed, g2, etsy (DataDome empty 403), nowsecure (thin).
- zendriver 12/16. Blocked: indeed, glassdoor, g2, etsy.
- zendriver + verify_cf clears indeed and glassdoor. With headed's etsy pass, the union of
  Camoufox, zendriver_cf and headed covers 14/16; g2 (DataDome) and nowsecure stay out.
- zendriver headed (Xvfb) 10/16; + verify_cf clears indeed and glassdoor. Only browser to pass
  etsy (DataDome). Loses reddit (captcha) and SO.
- Yesterday's best (stealth_new Chromium): 6/16.

## Proposed BAL-8 ladder

1. API / plain HTTP (`primp`), with a "don't solve" rule: an API-backed source never escalates.
2. Camoufox headless, persistent profile, graceful close. On a DataDome empty 403, retry
   with headed zendriver (passed etsy once).
3. zendriver + `verify_cf` for a CF checkbox Camoufox didn't clear; keep the profile dir (not
   the cookie jar), close via CDP `Browser.close`, reuse one tab per host. Sites like indeed
   that rechallenge within a minute cost one click per fetch.
4. Audio reCAPTCHA via local faster-whisper, budget a few per hour per IP.
5. Stop: PerimeterX hold, DataDome empty 403, CF hard block. Report the block type (regex is
   enough; Jev adds nothing measurable here) and hand to a human.

## Open

- Unknown what installed the ANGLE libs in /usr/local/lib; they could overwrite glvnd again.
- Whether headed's etsy pass repeats (n=1), and SO's 503 after the click (rate limit?).
- H8: why zendriver new tabs are rechallenged with the cookie present (per-tab patches is a guess).
- Q6 held-out evaluation on unseen states.
