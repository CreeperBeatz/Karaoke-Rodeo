# Hunt for duplicate/split/junk tracks among kept notes.
import numpy as np
import pickle
import sys
from verify import load

which = sys.argv[1]
d, notes = load(which)
fps = d["fps"]
a, ph0 = d["lattice"]

for i, n in enumerate(notes):
    n["i"] = i
    n["res"] = abs((n["cy"] - ph0 + a / 2) % a - a / 2)

# 1. lattice outliers
outl = [n for n in notes if n["res"] > 1.8]
print(f"--- lattice outliers: {len(outl)}")
for n in outl[:15]:
    print(f"  f={n['first_f']}-{n['last_f']} t={n['first_f']/fps:6.1f}s x={n['x0']}-{n['x1']} "
          f"cy={n['cy']:.1f} h={n['h']} cls={n['cls']} res={n['res']:.2f}")

# 2. same-row near-duplicates (overlapping x and time)
dups = []
notes_s = sorted(notes, key=lambda n: (round(n["cy"] / 3), n["first_f"]))
for p, q in zip(notes_s[:-1], notes_s[1:]):
    if abs(p["cy"] - q["cy"]) < 4:
        ov_x = min(p["x1"], q["x1"]) - max(p["x0"], q["x0"])
        ov_t = min(p["last_f"], q["last_f"]) - max(p["first_f"], q["first_f"])
        if ov_x > 5 and ov_t > -10:
            dups.append((p, q, ov_x, ov_t))
print(f"--- near-duplicate pairs: {len(dups)}")
for p, q, ox, ot in dups[:15]:
    print(f"  A f={p['first_f']}-{p['last_f']} x={p['x0']}-{p['x1']} cy={p['cy']:.1f} cls={p['cls']} | "
          f"B f={q['first_f']}-{q['last_f']} x={q['x0']}-{q['x1']} cy={q['cy']:.1f} cls={q['cls']} ovx={ox} ovt={ot}")

# 3. long-lifetime tracks
longs = [n for n in notes if (n["last_f"] - n["first_f"]) / fps > 6]
print(f"--- lifetime>6s: {len(longs)}")
for n in longs[:15]:
    print(f"  f={n['first_f']}-{n['last_f']} t={n['first_f']/fps:.1f}s x={n['x0']}-{n['x1']} cy={n['cy']:.1f} h={n['h']} cls={n['cls']}")

# 4. zero-growth-duration but wide
zg = [n for n in notes if n["growth"][-1][0] == n["first_f"] and (n["x1"] - n["x0"]) > 30]
print(f"--- instant-wide (no growth, w>30): {len(zg)}")
for n in zg[:10]:
    print(f"  f={n['first_f']}-{n['last_f']} t={n['first_f']/fps:.1f}s x={n['x0']}-{n['x1']} cy={n['cy']:.1f} cls={n['cls']}")

# 5. distribution of first_w relative to final width
fw = np.array([n["first_w"] / max(n["x1"] - n["x0"], 1) for n in notes])
print(f"--- first_w/width: p50={np.percentile(fw,50):.2f} p90={np.percentile(fw,90):.2f} frac(>0.9)={np.mean(fw>0.9):.2%}")
