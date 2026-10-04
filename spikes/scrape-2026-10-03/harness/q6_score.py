"""Spike (throwaway): score Q6 runs against baselines. Usage: q6_score.py q6_none.jsonl [q6_<mutation>.jsonl ...]"""

import collections
import json
import sys

COARSE = {"none": "ok", "thin_js": "thin"}  # everything else is "blocked", the regex's vocabulary


def coarse(label):
    return COARSE.get(label, "blocked")


def acc(pairs):
    return sum(a == b for a, b in pairs) / len(pairs)


def per_state(rows, key):
    # one vote per distinct (url, gold) so 21 copies of "Just a moment" count once
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["url"], r["gold"])].append(key(r))
    return sum(sum(v) / len(v) for v in groups.values()) / len(groups)


def report(name, rows, pred_fine=None, pred_coarse=None):
    line = [f"{name:<22}"]
    if pred_coarse:
        line.append(f"coarse {acc([(pred_coarse(r), coarse(r['gold'])) for r in rows]):.3f}")
        line.append(f"coarse/state {per_state(rows, lambda r: pred_coarse(r) == coarse(r['gold'])):.3f}")
    if pred_fine:
        line.append(f"fine {acc([(pred_fine(r), r['gold']) for r in rows]):.3f}")
        line.append(f"fine/state {per_state(rows, lambda r: pred_fine(r) == r['gold']):.3f}")
    print("  ".join(line))


base = [json.loads(l) for l in open(sys.argv[1])]
print(f"rows={len(base)} states={len({(r['url'], r['gold']) for r in base})}")
print("gold:", dict(collections.Counter(r["gold"] for r in base)))
report("majority (none)", base, pred_fine=lambda r: "none", pred_coarse=lambda r: "ok")
# H6: re-running classify() on the 240-char excerpt marks every browser page "thin"; use the
# verdict the regex produced at fetch time on the full page text instead
recorded = [json.loads(l)["verdict"] for l in open("q6_rows.jsonl")]
for r, v in zip(base, recorded):
    r["regex_recorded"] = v
report("regex (recomputed)", base, pred_coarse=lambda r: r["regex"])
report("regex (recorded)", base, pred_coarse=lambda r: r["regex_recorded"])
for path in sys.argv[1:]:
    rows = [json.loads(l) for l in open(path)]
    report(f"jev [{rows[0]['mutation']}]", rows, pred_fine=lambda r: r["pred"], pred_coarse=lambda r: coarse(r["pred"]))
    print("    pred dist:", dict(collections.Counter(r["pred"] for r in rows)))

print("\nunmutated jev misses (gold -> pred, count):")
for (g, p), n in collections.Counter((r["gold"], r["pred"]) for r in base if r["gold"] != r["pred"]).most_common():
    print(f"  {g:>13} -> {p:<13} {n}")
