# Harness ledger: challenge-solver spike (2026-10-03)

## H1. "Headed Chrome under Xvfb never opens CDP" (carried from 2026-10-02)

- **Observed:** headed `/usr/bin/chromium --remote-debugging-port=9333` under `xvfb-run`: no
  `/json/version` after 12s, empty log. Bare `Xvfb :150` with no Chrome: `xprop -root` timed
  out (exit 124).
- **Hypothesis:** harness defect in the X server, not Chrome.
- **Test:** `strace -f Xvfb :151` ends in `futex(..., FUTEX_WAIT_PRIVATE, 2, NULL` right after
  library load. gdb backtrace: `pthread_mutex_lock` <- `libGLESv2.so` <- `EGL_GetProcAddress`
  <- `eglGetError (libEGL.so.1)` <- ld.so init. A library constructor self-deadlocks.
- **Verdict:** harness defect (environment). `pacman -Qkk libglvnd` reports checksum and size
  mismatch on `/usr/lib/libEGL.so.1.1.0` and `/usr/lib/libGLESv2.so.2.1.0`. Both are byte
  identical (sha256 prefix 5f9408ab4a91 / a624033fbff2) to unowned ANGLE builds in
  `/usr/local/lib/` (dropped 2026-09-06 15:23 with a `libffmpeg.so`, an Electron/CEF bundle
  tell), and were copied over glvnd at 15:36. Fix: `sudo pacman -S libglvnd`. Not yet applied.

## H2. Probe reports SO "blocked http 403" with the real question title (camoufox)

- **Observed:** `camoufox blocked https://stackoverflow.com/questions/231767 | http 403 |
  iterator - What does the "yield" keyword do in Pyt`
- **Hypothesis:** harness defect. `status` is the first response (the CF challenge 403); the
  page then cleared and navigated. The verdict reads the stale status.
- **Test:** pending: record the final document's status / rely on end-state markers.

## H3. Cookie list is profile-wide, not per-site

- **Observed:** `cf_clearance`, `datadome` listed for x.com and linkedin after earlier sites.
- **Hypothesis:** harness defect. `ctx.cookies()` returns every cookie in the persistent
  profile. Filter by the target's domain.

## H4. Seven consecutive camoufox hangs after the first (indeed -> bloomberg)

- **Observed:** `camoufox hang https://www.indeed.com/...  >75s, killed` then the same for the
  next 6 URLs; `profiles/camoufox/lock` still present afterwards.
- **Hypothesis:** harness defect: SIGKILL leaves a profile lock, every later launch stalls.
  Alternative: real limit (those sites hang Firefox).
- **Test:** pending: rerun one of the later URLs alone with a fresh profile. Prediction: loads.

## H5. cf_clearance "does not survive restart" after 3 minutes (zendriver)

- **Observed:** reused solved profile, no click: `zendriver blocked ... Just a moment... | []`;
  `sqlite3 profiles/zendriver_cf/Default/Cookies "select count(*) from cookies"` -> `0`.
- **Hypothesis:** harness defect: Chrome flushes cookies lazily and `browser.stop()` kills it
  before the flush. Not a Cloudflare expiry.
- **Test:** carry cookies via `browser.cookies.save/load` jar. Prediction: restart passes at
  +1 min.

## Q2 control (isolating the click)

- verify_cf, fresh profile: 6/6 cleared (indeed 3/3, glassdoor 3/3), ~13-15s.
- No click, fresh profile: 0/6, "Just a moment" for the full 25s on every run.
- indeed's `verify_cf` raised "No node with given id found" after the click navigated the page
  away. Cosmetic; the solve worked.

## H6. Regex baseline scored 0.534, below the majority class

- **Observed:** `regex classify()  coarse 0.534` vs `majority (none) coarse 0.644`.
- **Hypothesis:** harness defect: the scorer re-ran `classify()` on the 240-char `head`, so
  every browser row with real content fell under the 300-char "thin" cutoff.
- **Test:** use the verdict recorded at fetch time (full page text). Result: `regex (recorded)
  coarse 0.977`. Harness defect. A broken baseline would have flattered Jev by 45 points.

## Q4. Press-and-hold denied 4/4 (stealth_new patchright, zillow)

- **Observed:** `"challenged": true, "hold_ms": 11719, "final_title": "Access to this page has
  been denied"` on 4 of 4 tries (3 scored, 1 diagnostic).
- **Hypothesis:** harness defect (hold pressed the 530x100 `#px-captcha` container centre, maybe
  missing the button) vs real limit.
- **Test:** screenshots before and 5s into the hold (`q4_before.png`, `q4_mid.png`). Mid-hold
  the button is filled with PX's verifying spinner: the press landed and was accepted as input.
- **Verdict:** real limit for this fingerprint: PX verifies the hold and still denies. The
  fingerprint-clean browsers (camoufox, zendriver) were never challenged on zillow, walmart or
  bloomberg, so avoidance, not solving, is the working route for PX.

## Q5. Audio reCAPTCHA via faster-whisper base.en (camoufox, Google demo page)

- **H7 observed:** `TypeError: open() got an unexpected keyword argument 'metadata_errors'`.
  Harness defect: faster-whisper 1.2.1 declares `av>=11`, resolver pulled av 19.0.1. Pinned
  `av==16.1.0`; smoke try solved. (Unpinned transitive dep, the exact CLAUDE.md failure.)
- **Result, 10 tries 30s apart (06:58-07:08):** 6 solved, 4 refused ("Your computer or network
  may be sending automated queries"), 0 wrong transcripts. Every clip that was served was
  accepted on the first round (~21s per solve). Refusals came at tries 4, 6, 7, 8: the limit is
  Google rate-limiting the IP's audio requests, not transcription.
- **Caveat:** the demo sitekey may be laxer than a production site's; 6/10 is an upper bound.

## Q3. Clearance across restart: indeed vs glassdoor

- indeed, jar save/load: rechallenged at +1, +10 min with `cf_clearance` present.
- glassdoor (`q3_profile.py`, 07:03): same-browser new tab at +60s -> "Just a moment..."; graceful
  CDP `Browser.close`, cf_clearance on disk for `.glassdoor.com` with
  `top_frame_site_key=https://glassdoor.com`; relaunch on the same profile at +1.5 min ->
  "Companies & Reviews | Glassdoor". Restart with the real profile kept clearance.
- **Verdict so far:** carrying the profile directory (with a graceful close so Chrome flushes)
  works where the zendriver jar did not; the jar likely drops the CHIPS partition key. The
  same-browser rechallenge on a new tab is unexplained (n=1).
- **Repeats (07:06, 07:09):** identical. Profile restart passes 3/3; same-browser new tab
  rechallenged 3/3.
- **H8, new-tab rechallenge.** Hypothesis: harness defect, zendriver `get(new_tab=True)` opens
  the tab without the cookie. Prediction: original tab passes at +60s, new tab fails.
  Result (07:12): `same_tab_+60s` -> "Companies & Reviews | Glassdoor"; new tab ->
  "Just a moment..." with `cf_clearance` present in `cookies.get_all()`. Prediction held on
  outcome, missed on cause: the cookie is there, so the new tab differs some other way
  (fingerprint patches applied per tab is the next guess, untested). Verdict: zendriver
  artifact, not Cloudflare expiry. Product rule: reuse one tab per host.

## H1 resolved (09:45)

- Sir ran `pacman -S libglvnd` (pacman.log `09:45:49 reinstalled libglvnd (1.7.0-3)`).
  `pacman -Qkk libglvnd` -> `0 altered files`; `Xvfb :152` answers `xprop -root`.
- Prediction (H1 harness defect): headed Chromium now opens CDP. Held: `zendriver_headed thin
  https://nowsecure.nl | 43 chars | ['cf_clearance']`, no hang. Harness defect confirmed;
  the /usr/local/lib ANGLE copies are still present and could be copied over again.
- **Headed hostile-16 (`q0_headed.jsonl`):** 10/16 ok, spot-checked. New: etsy ok (16,493 chars
  of real search results, `datadome` cookie set), the first DataDome pass of the spike.
  Lost vs headless: reddit ("Prove your humanity" captcha) and SO ("Just a moment...").
  Still out: indeed, glassdoor (CF), g2 (0 chars, DataDome), nowsecure (thin).
- **Headed + verify_cf (`q0_headed_cf.jsonl`):** indeed ok, glassdoor ok, g2 thin (no CF
  checkbox; DataDome), SO `503 Service Temporarily Unavailable` after the click, most likely
  a rate limit from today's repeated SO hits (untested).

## H9: Etsy repeat ran on the wrong interpreter (2026-10-03)

- Observed: all 10 rows `verdict: error`, `ModuleNotFoundError: No module named 'zendriver'`.
- Hypothesis: harness defect. `etsy_repeat.sh` called system `python3`; zendriver is only in `.venv`.
- Test: `.venv/bin/python -c 'import zendriver'` -> ok. Script switched to `.venv/bin/python`; failed rows kept in `failed-runs/`.
- Verdict: harness defect. The rerun is the real measurement.

## Q0 follow-up: does headed Chromium's Etsy pass repeat? (2026-10-03 21:44-21:55)

- Prediction written first: kept profile passes (saved `datadome` cookie); fresh profiles uncertain.
- Kept profile (`etsy_repeat.jsonl`): 5/5 ok, 15,594-18,495 chars, titles "<Query> - Etsy", query-specific filters in page head.
- Fresh profile per fetch (`etsy_repeat_fresh.jsonl`): 5/5 ok, 14,807-17,742 chars. Every final URL carries `&dd_referrer=`, so DataDome redirected each fresh browser and let it through with no interaction.
- Verdict: the n=1 pass repeats (10/10). It does not depend on a saved cookie. One IP, ~60s spacing, one evening; Etsy can change this without notice.

## Etsy rate run 1 + H10 (2026-10-03 22:06-22:29)

- Run 1 (`etsy_rate.run1.jsonl`): one headed tab, gaps 30/15/8/4/2/0 s, 35/35 ok, fetch 2.2-4.6 s (first 6.1 s). No block at gap 0 (5 fetches).
- H10 observed: fetch 36 never returned; Chromium stopped answering even `/json` on its debug port for 15+ min.
- Hypothesis: harness defect (no timeout on any CDP await), cause of the browser hang itself unknown (Etsy or Chromium).
- Fix: every await capped (nav 20 s, eval 5 s, fetch 40 s, stop 15 s, then kill), whole run under `timeout -k 10 900`. Run 2 extends gap 0 to 30 fetches.

## Etsy rate run 2 + H11 (2026-10-03 22:36-22:44)

- Run 2 (`etsy_rate.jsonl`, all awaits capped): gaps 30/15/8/4/2 s 30/30 ok; gap 0 22/23 ok over 111 s (~12 fetches/min sustained). Fetch median 2.8-3.9 s by phase.
- Fetch 53 (gap 0, `apron&page=2`): empty title and body for the whole 25 s settle, no challenge marker. Two paced fetches of the same URL at 22:44 were ok ("Apron - Etsy - Page 2"), so no lasting block. Throttle or render glitch: not distinguishable from n=1.
- H11 observed: two launches straight after a closed browser failed, "Failed to connect to browser". Manual Chromium launch on the same profile worked.
- Hypothesis: zendriver's connect budget (`browser_connection_max_tries=10` x 0.25 s = 2.5 s) is too short for the 303 MB headed profile.
- Test: raised to 80 tries (20 s) in solver_probe.py and etsy_rate.py; prediction "both launches succeed". Held: 2/2 ok.
- Verdict: harness defect. The serp-axi daemon needs a connect budget well above 2.5 s.

## Sample100 run 1 + H12 (2026-10-03 22:46-23:05)

- Observed: every zendriver rung in sample100/ladder.py returned "ValueError: not enough values to unpack (expected 2, got 0)", 21/21 stopped sites.
- Hypothesis: `tab.evaluate(STRIP)` evaluates the arrow function as an expression and returns it uncalled.
- Test: tailwindcss.com, predicted as-is {} and called [title, text]. Held: as-is `{}`, `(STRIP)()` gave a 2-item list. Harness defect, fixed.
- Run 1 stopped and discarded (its out*.jsonl deleted; w?.log kept in prior-run/). Also observed: dead domains (DNS error, connect error, 523) climbed all four rungs.
- Change: rung-1 network errors and status 404/410/521-530 now stop as "dead". Pages with text get a Jev choice (content / loading_shell / challenge / dead); the regex verdict is kept per rung as the baseline row.

## Sample100 run 2 + H13 (2026-10-03 23:10-23:58)

- Run 2 (`sample100/results.jsonl`, 86 Jev calls, 0 fallbacks): 63 ok at rung 1, 31 dead, 5 stopped, 1 headed.
- H13 observed: on near-empty rung-1 pages Jev answered confidently. tether.to (32 chars, title only) "content 0.74"; t77772.com (70) "content 0.92"; nict.go.jp redirect stub (127) "content 0.36"; four 0-char pages "dead". The ladder stopped on all of them.
- Hypothesis: a bare title looks like a real site to Jev; at rung 1 there is not enough text to judge.
- Test: rung-1 floor of 300 chars beyond the title, below it escalate without asking Jev. Reran the 12 affected sites (12 more Jev calls). Predicted most recover in a browser. Held: 10 ok at camoufox, 5 with real content (tether 6,562; burgerkingrus 8,636; nict 7,856; t77772 6,924; thelifeerotic 3,342); rudcx9 still empty and hayalsohbet a GoDaddy for-sale page, both dead.
- Verdict: harness defect. Jev judges kind well when there is text; the floor decides when there is not.
- Merged (`final.jsonl`): 57 rung 1, 10 camoufox, 1 headed zendriver, 27 dead, 5 stopped. Dead: 9 TLS certificate/handshake failures, 7 DNS, 4 timeouts, 2 connect, 1 x 404, 1 x 523, 3 by Jev on page text.
- Jev vs regex: regex called fassmotorsports.com (18,102 chars) a JS shell; Jev said content. Jev called a Cloudflare 1014 "CNAME cross-user banned" page a challenge; it is a dead config.
- Open: rung-1 text keeps HTML entities (&amp;); TLS-failure sites might serve on http://.
