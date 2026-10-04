#!/usr/bin/env bash
# 4 shards, each in its own dir so zendriver profiles and pages/ never collide. Hosts are all distinct.
# A re-run needs two things this repo does not carry: $PY, an interpreter with
# camoufox, zendriver, primp and browserforge installed, and sample.txt, the domain
# list to shard. Both were on this machine before the data moved into the repo.
cd "$(dirname "$0")"
PY=${PY:?set PY to the python that has camoufox/zendriver/primp/browserforge, e.g. PY=$HOME/.venvs/serp-axi/bin/python}
split -n r/4 -d sample.txt shard.
for i in 0 1 2 3; do
  mkdir -p w$i
  ( cd w$i && timeout -k 30 3h $PY ../ladder.py ../out$i.jsonl $(cat ../shard.0$i) > ../w$i.log 2>&1 ) &
done
wait
cat out0.jsonl out1.jsonl out2.jsonl out3.jsonl > results.jsonl
echo "ALL DONE $(wc -l < results.jsonl) rows"
