# Validation summary of all song maps vs HUD ground truth (read off frames).
import json
from collections import Counter

HUD = {  # (total notes, total pages) as shown in each video's HUD
    "v1": (598, 67),
    "v2": (503, 36),
    "v3": (774, 71),
    "v4": (379, 24),
}
for which, (hn, hp) in HUD.items():
    try:
        sm = json.load(open(rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json", encoding="utf-8"))
    except FileNotFoundError:
        print(f"{which}: missing")
        continue
    notes = sm["notes"]
    n = len(notes)
    anchor = sm.get("pitch_anchor", {})
    cls = Counter(x["cls"] for x in notes)
    names = Counter(x.get("name", "?") for x in notes)
    durs = sorted(x["t_end"] - x["t_start"] for x in notes)
    lo = min((x.get("midi", 0) for x in notes), default=0)
    hi = max((x.get("midi", 0) for x in notes), default=0)
    from meta import NOTE_NAMES_EN
    def nm(m):
        return NOTE_NAMES_EN[m % 12] + str(m // 12 - 1) if m else "?"
    print(f"{which}: {sm['meta']['title_jp']} — notes {n} (HUD {hn}, "
          f"{100*(n-hn)/hn:+.1f}%), singing pages {sm['n_pages']} (HUD total {hp})")
    print(f"    range {nm(lo)}..{nm(hi)}  cls {dict(cls)}  "
          f"anchor margin {anchor.get('score_margin')}  "
          f"dur p50 {durs[len(durs)//2]:.2f}s max {durs[-1]:.2f}s")
    print(f"    top notes: {dict(sorted(names.items(), key=lambda kv: -kv[1])[:6])}")
    print(f"    lyrics lines: {len(sm.get('lyrics', []))}")
