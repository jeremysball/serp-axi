# Challenge-solver spike: questions (written 2026-10-03, before any run)

Scope chosen by Sir: Q0-Q6. Direction: Camoufox first, zendriver as comparison, own CDP glue
for clicks/holds, API "don't solve" rung, no paid solvers, no FlareSolverr.

| # | Question | Falsifier | Plan change if it fires |
|---|---|---|---|
| Q0 | Can headed Chrome work here (CDP attach to user-launched Chrome, or another build under Xvfb)? | No CDP connection after both | SeleniumBase GUI click ruled out |
| Q1 | Fingerprint-clean browser passes CF managed challenge on SO/indeed/glassdoor, no interaction? | Still "Just a moment" after 20s on 2 of 3 | Need Q2 clicking |
| Q2 | Human-like CDP click on Turnstile clears it? | No cf_clearance after 3 tries/site | CF -> not locally solvable |
| Q3 | cf_clearance lifetime; survives restart with same profile? | Rechallenged within 10 min | No cookie amortization |
| Q4 | Jittered press-and-hold passes PerimeterX on zillow? | Fails 3 of 3 | PX -> not locally solvable |
| Q5 | Audio (local Whisper) or image (local VLM) solves reCAPTCHA/hCaptcha usably? | <50% on 10 tries | No local captcha rung |
| Q6 | Jev classifies challenge pages from the logged rows? | <90% accuracy or not better than regex baseline | Keep regex classify() |

Pacing: >=15s between hits on one host. Every attempt -> JSONL. Per-URL subprocess, SIGKILL at 75s.
