# Check class/pitch invariants and remaining extras in the song map.
import json
import sys
from collections import Counter

which = sys.argv[1]
sm = json.load(open(rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json", encoding="utf-8"))
notes = sm["notes"]
print(f"{len(notes)} notes")
for cls in ("main", "high", "low"):
    ns = [n for n in notes if n["cls"] == cls]
    ks = Counter(n["k"] for n in ns)
    print(f"{cls}: {len(ns)} notes, k distribution: {dict(sorted(ks.items()))}")
kall = Counter(n["k"] for n in notes)
print("all k:", dict(sorted(kall.items())))
# duration sanity
durs = sorted(n["t_end"] - n["t_start"] for n in notes)
print(f"dur: min={durs[0]:.2f} p50={durs[len(durs)//2]:.2f} max={durs[-1]:.2f}")
# suspicious short-height or short-dur notes by time
sus = [n for n in notes if n["t_end"] - n["t_start"] < 0.06]
print(f"very short (<60ms): {len(sus)}")
for n in sus[:10]:
    print("  ", n)
