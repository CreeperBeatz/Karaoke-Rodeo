# Timing ground-truth check: at each note's t_start the playhead must sit at
# the note's x0. err = ph_x(t_start) - x0 (px). Uses median-filtered playhead.
import json, pickle, sys
import numpy as np
import __main__
from extract import Profile, Note
__main__.Profile = Profile; __main__.Note = Note
from paths import CACHE_DIR as SC  # noqa: E402

def errors(which):
    sm = json.load(open(rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json", encoding="utf-8"))
    raw = pickle.load(open(SC + f"/raw_{which}.pkl", "rb"))
    from retime import smoothed_playhead
    fps = raw["fps"]; sm_ph = smoothed_playhead(raw); n = len(sm_ph)
    errs = []
    for nt in sm["notes"]:
        f = int(round(nt["t_start"] * fps))
        if 0 <= f < n and not np.isnan(sm_ph[f]):
            errs.append((sm_ph[f] - nt["x0"], nt))
    return errs, sm

if __name__ == "__main__":
    for which in sys.argv[1:]:
        errs, sm = errors(which)
        e = np.array([x for x, _ in errs])
        ae = np.abs(e)
        print(f"{which}: {len(errs)}/{len(sm['notes'])} notes with playhead; "
              f"median err={np.median(e):+.0f}px  |err| p50={np.median(ae):.0f} p75={np.percentile(ae,75):.0f} p90={np.percentile(ae,90):.0f}  "
              f"within 25px={np.mean(ae<25):.0%}  within 60px={np.mean(ae<60):.0%}")
