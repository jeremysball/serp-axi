#!/usr/bin/env bash
# Repeat the headed DataDome pass on etsy: persistent profile arm, then fresh-profile arm. >=60s between fetches.
cd "$(dirname "$0")"
qs=(mug lamp candle poster blanket)
for q in "${qs[@]}"; do
  .venv/bin/python solver_probe.py etsy_repeat.jsonl zendriver_headed "https://www.etsy.com/search?q=$q"; sleep 60
done
for q in "${qs[@]}"; do
  d=$(mktemp -d /tmp/etsy-fresh.XXXX)
  PROBE_PROFILES=$d .venv/bin/python solver_probe.py etsy_repeat_fresh.jsonl zendriver_headed "https://www.etsy.com/search?q=$q"; sleep 60
done
echo ALL DONE
