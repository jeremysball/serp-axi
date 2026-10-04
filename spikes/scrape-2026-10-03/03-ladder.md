# The challenge ladder: what we tried and what held up (2026-10-03)

serp-axi's scraper is going to run into bot defenses. The question for this spike was how far a free setup can get on one home IP, going slowly, before it has to stop and ask a person. The answer is a ladder. Each rung costs more than the one below it, and the scraper only climbs when the rung below has failed.

## The ladder

1. **API or plain HTTP.** If a site has an API, use it and never escalate. This rung is a policy, not something we measured.
2. **Camoufox (patched Firefox), headless, with a persistent profile.** This is where most of the work gets done. It loaded real content on 12 of our 16 hostile sites with no interaction, including Stack Overflow and Glassdoor behind Cloudflare. The best Chromium setup from the 2026-10-02 spike managed 6.
3. **zendriver (Chromium) clicking the Cloudflare checkbox.** With the click, Indeed and Glassdoor cleared 6 times out of 6. Without it, 0 out of 6, so the click really is what clears them.
4. **Headed Chromium on a virtual display.** This is the only thing that got past DataDome (Etsy), once. It also lost Reddit and Stack Overflow, which headless passes, so it's a rung for one kind of block, not an upgrade for everything.
5. **Audio captcha through local Whisper.** On Google's reCAPTCHA demo page, 6 of 10 were solved, and every clip Whisper heard was accepted. The other 4 were refused outright for "automated queries." What limits this rung is how often Google will hand one IP an audio challenge, not transcription quality.
6. **Stop and hand off to a person.** This covers PerimeterX press-and-hold, DataDome's empty 403, and Cloudflare hard blocks. The scraper reports which kind of block it hit.

Put together, rungs 2 to 4 got real content from 14 of the 16 sites. G2 (DataDome) and nowsecure stayed out.

## What didn't work

- **Press-and-hold.** I held the PerimeterX button on Zillow for 10 to 12 seconds with a jittered mouse path, four times. A screenshot shows the button registered the hold and started verifying, and the page was denied anyway. The cleaner browsers were never shown that challenge, so avoiding it is the route that works.
- **Carrying clearance in a cookie file.** Saving cookies and loading them into a fresh browser didn't keep Cloudflare happy. Keeping the browser's own profile folder and shutting it down cleanly did, on Glassdoor. Indeed challenges again within a minute however the clearance is carried, so on Indeed every fetch costs a click.
- **A model to classify block pages.** Jev labeled pages about as well as the existing regex (0.982 against 0.977, about one row out of 219). That isn't enough to add a model call to the hot path.

## Things that looked like results and weren't

Most of the day went into the probe itself rather than the sites. Eight times a number looked like a finding and turned out to be my harness. The ones that would have changed the conclusions:

- Headed Chrome hung because two system graphics libraries had been overwritten. Reinstalling `libglvnd` fixed it.
- The probe read the first HTTP status (Cloudflare's 403) after the page had already cleared. Seven Camoufox "hangs" in a row were a stale profile lock left by my own kill.
- Chrome never wrote its cookies to disk before zendriver killed it.
- The regex baseline scored worse than always guessing "fine," because I'd fed it a 240-character excerpt instead of the page.

Each one went into a ledger with its prediction before the fix, and a number only went into this page once the fix was in.

## Caveats

This is one IP on one day, with sample sizes in single digits for several rungs. The Etsy pass happened once. Sites change their defenses without notice, so the ladder has to log every escalation and its outcome, and these numbers should be re-measured from those logs rather than trusted.

Data, scripts and the full ledger: `spikes/scrape-2026-10-03/` (`02-report.md`, `flywheel.md`).
