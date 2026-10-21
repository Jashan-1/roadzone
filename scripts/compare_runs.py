"""Per-cell before/after: share of comparable cells whose distance band, time band or corridor changed.

Usage: uv run python -m scripts.compare_runs runs/OLD:runs/NEW [...]
"""
import json, statistics, sys

def load(run):
    out = {}
    for line in open(f"{run}/probes.jsonl"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r["kind"] == "cell" and r.get("m_dist") is not None:
            out[r["id"]] = r
    return out

print("| site | cells | distance band changed | time band changed | corridor changed | median Δ miles | median Δ minutes |")
print("|---|---|---|---|---|---|---|")
for pair in sys.argv[1:]:
    a, b = pair.split(":")
    A, B = load(a), load(b)
    both = [c for c in A if c in B]
    fam = lambda r: tuple((r.get("corridor") or {}).get("family_key") or ())
    n = len(both)
    db = sum(A[c]["band"] != B[c]["band"] for c in both)
    tb = sum(A[c]["band_time"] != B[c]["band_time"] for c in both)
    cf = sum(fam(A[c]) != fam(B[c]) for c in both if A[c]["band"] and B[c]["band"])
    dm = statistics.median((B[c]["m_dist"] - A[c]["m_dist"]) / 1609.344 for c in both)
    dt = statistics.median((B[c]["m_time"] - A[c]["m_time"]) / 60 for c in both)
    name = open(f"{b}/name.txt").read().strip().removeprefix("Test: ").split(" (")[0] if "custom" in b else "Stevens Creek"
    print(f"| {name} | {n} | {db/n:.1%} | {tb/n:.1%} | {cf/n:.1%} | {dm:+.2f} | {dt:+.1f} |")
