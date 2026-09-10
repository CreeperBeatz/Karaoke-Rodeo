import json
import sys

which = sys.argv[1] if len(sys.argv) > 1 else "v1"
t_lo = float(sys.argv[2]) if len(sys.argv) > 2 else 40
t_hi = float(sys.argv[3]) if len(sys.argv) > 3 else 285
sm = json.load(open(rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json", encoding="utf-8"))
ns = [n for n in sm["notes"] if n["t_start"] < t_lo]
print(f"before {t_lo}s: {len(ns)}")
for n in ns[:20]:
    print(f"  t={n['t_start']:6.2f}-{n['t_end']:6.2f} k={n['k']:4d} x={n['x0']}-{n['x1']} cy={n['cy']} cls={n['cls']} f={n['first_f']}-{n['last_f']}")
ns2 = [n for n in sm["notes"] if n["t_start"] > t_hi]
print(f"after {t_hi}s: {len(ns2)}")
for n in ns2[:25]:
    print(f"  t={n['t_start']:6.2f}-{n['t_end']:6.2f} k={n['k']:4d} x={n['x0']}-{n['x1']} cy={n['cy']} cls={n['cls']} f={n['first_f']}-{n['last_f']}")
