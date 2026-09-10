# Anchor the pitch lattice in absolute pitch using the video's own audio:
# the guide melody follows the note bars, so the correct (offset, octave)
# maximizes spectral energy at predicted note frequencies over all notes.
import numpy as np
import subprocess
import json
import sys
import os
from meta import NOTE_NAMES_EN, NOTE_NAMES_JP
from extract import VIDEOS

from paths import CACHE_DIR, map_path, ffmpeg as _ffmpeg  # noqa: E402
FF = _ffmpeg()
scratch = CACHE_DIR
SR = 22050


def load_audio(which):
    wav = os.path.join(scratch, f"audio_{which}.f32")
    if not os.path.exists(wav):
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i",
                        VIDEOS[which], "-ac", "1", "-ar", str(SR), "-f", "f32le",
                        wav], check=True)
    return np.fromfile(wav, np.float32)


def stft_logmag(x, nfft=8192, hop=1024):
    win = np.hanning(nfft).astype(np.float32)
    nf = 1 + (len(x) - nfft) // hop
    frames = np.lib.stride_tricks.as_strided(
        x, (nf, nfft), (x.strides[0] * hop, x.strides[0]), writeable=False)
    S = np.abs(np.fft.rfft(frames * win, axis=1)).astype(np.float32)
    return S, hop / SR


def semitone_energy(S, dt):
    """Energy per (frame, midi) for midi 30..96, bins within +-2.9% of f."""
    freqs = np.fft.rfftfreq(8192, 1 / SR)
    midis = np.arange(30, 97)
    fs = 440 * 2 ** ((midis - 69) / 12)
    E = np.zeros((S.shape[0], len(midis)), np.float32)
    for j, f in enumerate(fs):
        lo, hi = np.searchsorted(freqs, [f * 0.971, f * 1.03])
        if hi > lo:
            E[:, j] = S[:, lo:hi].max(axis=1)
    return E, midis


def run(which):
    sm_path = map_path(which)
    sm = json.load(open(sm_path, encoding="utf-8"))
    notes = sm["notes"]
    x = load_audio(which)
    S, dt = stft_logmag(x)
    E, midis = semitone_energy(S, dt)
    logE = np.log1p(E)
    # normalize per frame so loud sections don't dominate
    logE = logE / np.maximum(logE.mean(axis=1, keepdims=True), 1e-6)

    ks = np.array([n["k"] for n in notes])
    t0s = np.array([n["t_start"] for n in notes])
    t1s = np.array([n["t_end"] for n in notes])
    scores = {}
    for base in range(30 - ks.min() if ks.min() < 0 else 30, 97):
        mm = base + ks
        if mm.min() < 30 or mm.max() > 96:
            continue
        # vocal plausibility: the median melody note must sit in singable range
        if not 53 <= np.median(mm) <= 76:
            continue
        tot = cnt = 0.0
        for m, t0, t1 in zip(mm, t0s, t1s):
            dur = t1 - t0
            a = int((t0 + 0.15 * dur) / dt)
            b = max(a + 1, int((t1 - 0.15 * dur) / dt))
            if b > logE.shape[0]:
                break
            s = logE[a:b, m - 30].mean()
            # harmonic support (octave-up energy backs a true fundamental;
            # no sub-harmonic penalty: real bass lives an octave below)
            if m + 12 <= 96:
                s += 0.35 * logE[a:b, m + 12 - 30].mean()
            tot += s
            cnt += 1
        scores[base] = tot / max(cnt, 1)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    print("top bases:", [(b, round(s, 4)) for b, s in ranked[:6]])
    base = ranked[0][0]
    # also report offset-only (chroma) ranking for confidence
    chroma_score = {}
    for off in range(12):
        vals = [scores.get(b) for b in scores if (b - base) % 12 == (off) % 12]
    # per-pc aggregate
    pc_agg = {}
    for b, s in scores.items():
        pc_agg.setdefault(b % 12, []).append(s)
    pc_rank = sorted(((pc, max(v)) for pc, v in pc_agg.items()), key=lambda kv: -kv[1])
    print("pc ranking:", [(pc, round(s, 4)) for pc, s in pc_rank[:4]])

    for n in notes:
        midi = base + n["k"]
        n["midi"] = int(midi)
        n["pc"] = int(midi % 12)
        n["name"] = NOTE_NAMES_EN[midi % 12] + str(midi // 12 - 1)
        n["name_jp"] = NOTE_NAMES_JP[midi % 12]
    sm["pitch_anchor"] = dict(
        method="audio", midi_base=int(base),
        score_margin=round(float(ranked[0][1] - ranked[1][1]), 4),
        top=[(int(b), round(float(s), 4)) for b, s in ranked[:3]])
    json.dump(sm, open(sm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    cnt = Counter(n["name"] for n in notes)
    print("note histogram:", dict(sorted(cnt.items(), key=lambda kv: -kv[1])[:8]))
    print("wrote", sm_path)


if __name__ == "__main__":
    run(sys.argv[1])
