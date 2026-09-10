# Pass 2: read note-name labels (katakana) above bars and anchor the pitch
# lattice to absolute pitch classes via a global mod-12 vote.
import cv2
import numpy as np
import pickle
import json
import os
import sys
from PIL import Image, ImageDraw, ImageFont
from extract import VIDEOS, W, H, Profile
from meta import NOTE_NAMES_JP, NOTE_PC, NOTE_NAMES_EN

scratch = r"C:\Users\dani\AppData\Local\Temp\claude\C--Users-dani-Documents-karaokejiinica\571acd04-1726-45ca-8d3b-d943a190ed63\scratchpad"
BASE_CHARS = ["ド", "レ", "ミ", "ファ", "ソ", "ラ", "シ"]
BASE_PC = {"ド": 0, "レ": 2, "ミ": 4, "ファ": 5, "ソ": 7, "ラ": 9, "シ": 11}
FONTS = [r"C:\Windows\Fonts\meiryob.ttc", r"C:\Windows\Fonts\YuGothB.ttc",
         r"C:\Windows\Fonts\msgothic.ttc"]


def render_templates():
    """Binary templates for each base char: fonts x sizes x shears."""
    out = {c: [] for c in BASE_CHARS}
    for fp in FONTS:
        try:
            font = ImageFont.truetype(fp, 26)
        except Exception:
            continue
        for c in BASE_CHARS:
            img = Image.new("L", (70, 40), 0)
            d = ImageDraw.Draw(img)
            d.text((4, 2), c, fill=255, font=font)
            arr = np.array(img)
            ys, xs = np.where(arr > 100)
            if len(xs) == 0:
                continue
            arr = arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            arr = (arr > 100).astype(np.uint8) * 255
            for shear in (0.0, 0.25):
                h, w = arr.shape
                M = np.float32([[1, shear, 0], [0, 1, 0]])
                sh = cv2.warpAffine(arr, M, (w + int(shear * h) + 1, h))
                for target_h in (14, 16, 18):
                    scale = target_h / sh.shape[0]
                    t = cv2.resize(sh, (max(4, int(sh.shape[1] * scale)), target_h))
                    out[c].append((t > 100).astype(np.uint8) * 255)
    return out


def classify_crop(crop_bgr, templates):
    """crop: BGR region above bar-left. Returns (char, score, extra_frac,
    mod_color) or None."""
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 1] < 80) & (hsv[:, :, 2] > 170)).astype(np.uint8) * 255
    n, lab, stats, cent = cv2.connectedComponentsWithStats(white, 8)
    # keep glyph-sized components only: clouds are huge, bar borders are long
    # thin lines
    mask = np.zeros_like(white)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 8 <= area <= 260 and 5 <= h <= 26 and w <= 34:
            mask[lab == i] = 255
    ys, xs = np.where(mask > 0)
    if len(xs) < 25:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    if y1 - y0 < 8 or y1 - y0 > 26:
        return None
    glyph = mask[y0:y1 + 1, x0:x1 + 1]
    gh = glyph.shape[0]
    best = (None, -1.0, 0)
    for c, tls in templates.items():
        for t in tls:
            if abs(t.shape[0] - gh) > 5:
                continue
            # pad glyph to at least template size
            H2 = max(glyph.shape[0], t.shape[0] + 2)
            W2 = max(glyph.shape[1] + 6, t.shape[1] + 2)
            g = np.zeros((H2, W2), np.uint8)
            g[:glyph.shape[0], :glyph.shape[1]] = glyph
            r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            if mx > best[1]:
                best = (c, mx, t.shape[1] + loc[0])
    char, score, used_w = best
    if char is None:
        return None
    # extra white pixels to the right of the matched base char = modifier
    extra = mask[:, x0 + used_w + 1:].sum() / 255
    total = mask.sum() / 255
    extra_frac = extra / max(total, 1)
    # colored modifier (blue flat / red sharp) anywhere in crop
    sat = hsv[:, :, 1].astype(int)
    val = hsv[:, :, 2].astype(int)
    hch = hsv[:, :, 0].astype(int)
    blue = ((sat > 120) & (val > 120) & (hch >= 95) & (hch <= 115)).sum()
    red = ((sat > 120) & (val > 120) & ((hch <= 8) | (hch >= 172))).sum()
    mod = None
    if blue > 12:
        mod = "b"
    elif red > 12:
        mod = "#"
    elif extra_frac > 0.30:
        mod = "#?"  # white modifier (family A sharp) or unknown
    return (char, score, extra_frac, mod)


def run(which):
    with open(scratch + f"\\tracks_{which}.pkl", "rb") as fh:
        d = pickle.load(fh)
    sm_path = rf"C:\Users\dani\Documents\karaokejiinica\output\song_map_{which}.json"
    sm = json.load(open(sm_path, encoding="utf-8"))
    fam = sm["family"]
    prof = Profile(fam)
    lane_y0 = prof.lane[1]
    notes = sm["notes"]
    # crop frame per note: right after fully wiped
    jobs = defaultdict_list = {}
    for i, nt in enumerate(notes):
        f = min(nt["last_f"], nt["first_f"] + int((nt["t_end"] - nt["t_start"]) * sm["fps"]) + 2)
        jobs.setdefault(f, []).append(i)
    templates = render_templates()
    cap = cv2.VideoCapture(VIDEOS[which])
    results = {}
    frames_sorted = sorted(jobs)
    f = -1
    while frames_sorted:
        target = frames_sorted[0]
        while f < target:
            ok = cap.grab()
            if not ok:
                break
            f += 1
        ok, frame = cap.retrieve()
        if not ok:
            break
        if frame.shape[1] != W:
            frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
        for i in jobs[target]:
            nt = notes[i]
            cy = nt["cy"] + lane_y0
            x0 = nt["x0"]
            crop = frame[max(0, int(cy - 40)):int(cy - 8),
                         max(0, x0 - 10):x0 + 46]
            if crop.size:
                results[i] = classify_crop(crop, templates)
        frames_sorted.pop(0)
    cap.release()

    got = {i: r for i, r in results.items() if r and r[1] > 0.45}
    print(f"labels classified: {len(got)}/{len(notes)}")
    # global offset vote using unmodified labels
    votes = np.zeros(12)
    for i, (c, s, ef, mod) in got.items():
        if mod is not None:
            continue
        k = notes[i]["k"]
        # pc = (offset + k) mod 12 should equal BASE_PC[c]
        off = (BASE_PC[c] - k) % 12
        votes[off] += s
    off = int(np.argmax(votes))
    ranked = np.sort(votes)[::-1]
    print(f"offset votes: {votes.round(1)} -> offset={off} "
          f"(margin {ranked[0]:.1f} vs {ranked[1]:.1f})")
    # agreement stats incl. modifiers
    agree = total = 0
    for i, (c, s, ef, mod) in got.items():
        pc = (off + notes[i]["k"]) % 12
        base = BASE_PC[c]
        exp = {None: base, "b": (base - 1) % 12, "#": (base + 1) % 12,
               "#?": (base + 1) % 12}[mod]
        total += 1
        agree += (pc == exp)
    print(f"label agreement: {agree}/{total} = {agree/total:.1%}")

    # octave anchor: median melody pitch into vocal range around midi 62
    ks = np.array([n["k"] for n in notes])
    med_k = float(np.median(ks))
    best_base = None
    for base in range(0, 128, 12):
        midi_med = base + off + med_k
        if best_base is None or abs(midi_med - 62) < abs(best_base + off + med_k - 62):
            best_base = base
    for n in notes:
        midi = best_base + off + n["k"]
        n["midi"] = int(midi)
        n["pc"] = int(midi % 12)
        n["name"] = NOTE_NAMES_EN[midi % 12] + str(midi // 12 - 1)
        n["name_jp"] = NOTE_NAMES_JP[midi % 12]
    sm["pitch_anchor"] = dict(offset=off, midi_base=best_base,
                              label_agreement=round(agree / max(total, 1), 3),
                              n_labels=total)
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    cnt = Counter(n["name"] for n in notes)
    print("note histogram:", dict(sorted(cnt.items(), key=lambda kv: -kv[1])))
    print(f"updated {sm_path}")


if __name__ == "__main__":
    run(sys.argv[1])
