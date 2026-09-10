# Backend for the manual labeling tool (app/label.html), mounted by serve.py
# under /api/label/*.
#
# The tool edits a song map PAGE BY PAGE on a still frame taken just before the
# page flips (every bar of the page is coloured then, nothing moves). Timing is
# never edited directly: within a page  t = T0 + x / R  (geotime.py's model), so
# editing a bar's x-extent IS editing its time. The CV helpers here give the
# human exact geometry (static bar detection under the cursor, waist split),
# timing evidence (frame at any t with the predicted playhead, colour-flip
# strips) and page-sweep refits (from the playhead line or from bar flips).
#
# Endpoints (all GET unless noted; JSON unless noted):
#   /api/label/songs                       -> [{id, title, n_notes, hud_total}]
#   /api/label/song?v=v2                   -> full editing state (map + geometry)
#   /api/label/frame?v=v2&t=45.3[&crop=top|lane|full][&q=85]  -> image/jpeg
#   /api/label/detect?v=v2&t=45.3[&strict=1]                  -> static bars at t
#   /api/label/playhead?v=v2&t=45.3        -> playhead runs at t
#   /api/label/pagescan?v=v2               -> per page: static bar count at end frame
#   /api/label/flipstrip?v=v2&x0=&x1=&cy=&t=[&cls=]   -> image/jpeg (5 crops around t)
#   /api/label/fliptime?v=v2&x0=&x1=&cy=&cls=&t_seen= -> {t_flip}
#   /api/label/refit_playhead?v=v2&t_a=&t_b=&R=&T0=   -> {R, T0, n, med_res}
#   POST /api/label/refit_flips  {v, page:{R,T0,vis_a,t_end}, notes:[...]} -> {R, T0, n_in, n_pts}
#   POST /api/label/save         {v, pages:[...], notes:[...]}             -> {ok, n_notes, path}
import json
import os
import pickle
import shutil
import sys
import threading
import time
from collections import OrderedDict

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import __main__  # noqa: E402
from extract import VIDEOS, Profile, Note, W, H, find_legend_swatches  # noqa: E402
__main__.Profile = Profile; __main__.Note = Note  # raw_*.pkl were pickled from __main__
from pageshots import detect_bars_static  # noqa: E402
from retime import SC, colored_frac  # noqa: E402
import geotime  # noqa: E402

ROOT = os.path.dirname(HERE)
from paths import MAPS_DIR as OUT  # noqa: E402
CLSN = ["main", "high", "low"]
NOTE_NAMES_EN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_NAMES_JP = ["ド", "ド#", "レ", "レ#", "ミ", "ファ", "ファ#", "ソ", "ソ#", "ラ", "ラ#", "シ"]
# on-screen HUD totals (音数 / ノート), the count ground truth per video
HUD_TOTALS = {"v1": 598, "v2": 503, "v3": 774, "v4": 379, "v5": 786}


class Song:
    """One video + its map, with a seeking frame cache and the CV helpers."""

    def __init__(self, sid):
        self.id = sid
        self.path = VIDEOS[sid]
        self.map_path = os.path.join(OUT, f"song_map_{sid}.json")
        self.lock = threading.Lock()
        self.cap = cv2.VideoCapture(self.path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.nframes = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.pos = -1  # frame index the capture will read next
        self.cache = OrderedDict()
        self.sm = json.load(open(self.map_path, encoding="utf-8"))
        self.prof = Profile(self.sm["family"])
        self.swatches = None
        self.hue0 = None
        raw_p = os.path.join(SC, f"raw_{sid}.pkl")
        if os.path.exists(raw_p):
            try:
                raw = pickle.load(open(raw_p, "rb"))
                self.prof = raw["prof"]
                self.swatches = [tuple(map(float, s)) for s in raw["swatches"]][:3]
            except Exception as e:  # pragma: no cover
                print("raw pkl unreadable:", e)
        geo_p = os.path.join(SC, f"geo_{sid}.pkl")
        if os.path.exists(geo_p):
            try:
                self.hue0 = pickle.load(open(geo_p, "rb")).get("hue0")
            except Exception:
                pass
        if self.swatches is None:
            self.swatches = self._swatches_from_video()

    # ------------------------------------------------------------ frames
    def frame(self, f):
        """1280x720 BGR frame f (clamped). Sequential reads when the target is
        just ahead of the decoder position (a seek costs ~60 ms)."""
        f = int(max(0, min(self.nframes - 1, f)))
        with self.lock:
            fr = self.cache.get(f)
            if fr is not None:
                self.cache.move_to_end(f)
                return fr
            if not (0 <= f - self.pos <= 12):
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, f)
                self.pos = f
            while True:
                ok, fr = self.cap.read()
                if not ok:
                    return None
                got = self.pos; self.pos += 1
                if got >= f:
                    break
            if fr.shape[1] != W:
                fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
            self.cache[f] = fr
            if len(self.cache) > 300:
                self.cache.popitem(last=False)
            return fr

    def frame_at(self, t):
        return self.frame(int(round(t * self.fps)))

    def _swatches_from_video(self):
        for k in (0.5, 0.3, 0.7, 0.2, 0.8):
            fr = self.frame(int(k * self.nframes))
            if fr is None:
                continue
            sw = find_legend_swatches(fr, self.prof)[:3]
            hues = [s[0] for s in sw]
            if len(sw) == 3 and len({int(h) // 8 for h in hues}) == 3:
                return [tuple(map(float, s)) for s in sw]
        return [(100.0, 200.0, 220.0), (0.0, 200.0, 220.0), (150.0, 200.0, 220.0)]

    def playhead_hue(self):
        if self.hue0 is None:
            lx0, ly0, lx1, ly1 = self.prof.lane
            hist = np.zeros(180)
            for f in np.linspace(self.fps * 5, self.nframes - 1, 160).astype(int):
                fr = self.frame(f)
                if fr is None:
                    continue
                hsv = cv2.cvtColor(fr[ly0:ly1, lx0:lx1], cv2.COLOR_BGR2HSV)
                for (x, h, w) in geotime.playhead_runs(hsv, ly1 - ly0):
                    if h >= 0:
                        hist[h] += 1
            circ = np.array([hist[(np.arange(i - 6, i + 7)) % 180].sum() for i in range(180)])
            self.hue0 = int(np.argmax(circ)) if circ.max() > 0 else None
        return self.hue0

    # ------------------------------------------------------------ state
    def state(self):
        sm = self.sm
        a, ph0 = sm["lattice"]["px_per_semitone"], sm["lattice"]["phase"]
        pages = sm.get("pages")
        if not pages:  # pre-geotime map: derive pages from flips with unknown sweep
            flips = [0.0] + list(sm.get("page_flips", [])) + [sm["duration"]]
            pages = [dict(vis_a=flips[i], t_end=flips[i + 1], R=None, T0=None) for i in range(len(flips) - 1)]
        notes = []
        for i, p in enumerate(pages):
            p["t_show"] = self.t_show(p, [n for n in sm["notes"] if n.get("page") == i])
        for n in sm["notes"]:
            m = dict(x0=int(n["x0"]), x1=int(n["x1"]), cy=float(n["cy"]), cls=n.get("cls", "main"),
                     k=int(n["k"]) if "k" in n else -int(round((n["cy"] - ph0) / a)),
                     page=n.get("page"), src=n.get("src", "auto"), seen=n.get("seen", 0),
                     t_start=n["t_start"], t_end=n["t_end"])
            if m["page"] is None:
                m["page"] = max(0, sum(1 for p in pages if p["vis_a"] <= n["t_start"] + 0.03) - 1)
            notes.append(m)
        return dict(
            id=self.id, video=sm["video"], title=sm["meta"].get("title_jp"), family=sm["family"],
            fps=self.fps, nframes=self.nframes, duration=sm["duration"],
            lane=list(self.prof.lane), counter=list(self.prof.counter), legend=list(self.prof.legend),
            lattice=dict(a=a, phase=ph0), midi_base=(sm.get("pitch_anchor") or {}).get("midi_base"),
            swatches=self.swatches, hue0=self.hue0, hud_total=HUD_TOTALS.get(self.id),
            pages=pages, notes=notes, method=sm.get("method"),
        )

    @staticmethod
    def t_show(p, notes=()):
        """Time to SHOW a page with every bar coloured: the sweep just past the
        last bar (or x=1150). Family B draws the next page before this page's
        vis_a-based t_end, so t_end-0.1 may already be the next page."""
        if not p.get("R") or p.get("T0") is None:
            t = p["t_end"] - 0.10
            return t if t > p["vis_a"] else (p["vis_a"] + p["t_end"]) / 2
        x_ref = max(1150.0, max([n["x1"] for n in notes], default=0) + 6.0)
        t = p["T0"] + x_ref / p["R"]
        return round(max(p["vis_a"] + 0.05, min(t, p["t_end"] - 0.05)), 3)

    # ------------------------------------------------------------ CV helpers
    def jpeg(self, t, crop="top", q=85):
        fr = self.frame_at(t)
        if fr is None:
            return None
        if crop == "lane":
            lx0, ly0, lx1, ly1 = self.prof.lane
            fr = fr[ly0:ly1, lx0:lx1]
        elif crop == "top":
            fr = fr[:270]
        ok, buf = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, int(q)])
        return buf.tobytes() if ok else None

    def washed(self, fr):
        """Fraction of saturated bright lane pixels: > 0.5 means a bar-coloured
        sky/explosion where the loose detector drowns (geotime's rule)."""
        lx0, ly0, lx1, ly1 = self.prof.lane
        hsv = cv2.cvtColor(fr[ly0:ly1, lx0:lx1], cv2.COLOR_BGR2HSV)
        m = geotime.sat_mask(hsv)
        return cv2.countNonZero(m) / m.size

    def detect(self, t, strict=None, lattice=True):
        """Static bars at t. strict=None: automatic (strict swatches on washed frames)."""
        fr = self.frame_at(t)
        if fr is None:
            return []
        sw = self.swatches
        if strict is None:
            strict = self.washed(fr) > 0.5
        if strict:
            sw = [(h0, s0 + 50, v0) for (h0, s0, v0) in sw]
        lat = (self.sm["lattice"]["px_per_semitone"], self.sm["lattice"]["phase"]) if lattice else None
        return [dict(x0=int(a), x1=int(b), cy=round(float(cy), 1), h=int(h), cls=CLSN[int(cls)])
                for (a, b, cy, h, cls) in detect_bars_static(fr, self.prof, sw, lat)]

    def playhead(self, t):
        fr = self.frame_at(t)
        if fr is None:
            return []
        lx0, ly0, lx1, ly1 = self.prof.lane
        hsv = cv2.cvtColor(fr[ly0:ly1, lx0:lx1], cv2.COLOR_BGR2HSV)
        return [dict(x=int(x), hue=int(h), w=int(w)) for (x, h, w) in geotime.playhead_runs(hsv, ly1 - ly0, self.playhead_hue())]

    def pagescan(self, pages, notes=None):
        out = []
        for i, p in enumerate(pages):
            t = self.t_show(p, [n for n in (notes or []) if n.get("page") == i])
            out.append(dict(t=t, n_static=len(self.detect(t))))
        return out

    def flipstrip(self, x0, x1, cy, t, cls="main"):
        """5 crops of the bar's left end at t-0.2 .. t+0.2 (x3), stacked; the
        predicted playhead position (x0 at time t) is marked in magenta."""
        lx0, ly0, lx1, ly1 = self.prof.lane
        cy = int(round(cy)); ya, yb = max(0, cy - 14), min(ly1 - ly0, cy + 15)
        xa, xb = max(0, x0 - 60), min(lx1 - lx0, max(x1, x0 + 60) + 20)
        tiles = []
        for dt in (-0.2, -0.1, 0.0, 0.1, 0.2):
            fr = self.frame_at(t + dt)
            if fr is None:
                continue
            crop = fr[ly0 + ya:ly0 + yb, lx0 + xa:lx0 + xb].copy()
            crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
            cv2.line(crop, ((x0 - xa) * 3, 0), ((x0 - xa) * 3, crop.shape[0]), (255, 0, 255), 1)
            cv2.rectangle(crop, ((x0 - xa) * 3, (cy - ya) * 3 - 12), ((x1 - xa) * 3, (cy - ya) * 3 + 12), (0, 255, 0), 1)
            cv2.putText(crop, f"{dt:+.1f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            tiles.append(crop)
        if not tiles:
            return None
        ok, buf = cv2.imencode(".jpg", np.vstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 90])
        return buf.tobytes() if ok else None

    class _Frames:
        def __init__(self, song):
            self.song = song
        def get(self, f):
            return self.song.frame(f)

    def fliptime(self, x0, x1, cy, cls, t_seen):
        nt = dict(x0=int(x0), x1=int(x1), cy=float(cy), cls=cls)
        return geotime.flip_time(self._Frames(self), self.prof, self.swatches, nt, float(t_seen), self.fps)

    def refit_playhead(self, t_a, t_b, R, T0):
        """Detect the playhead every 0.2 s in [t_a, t_b], keep detections near the
        current line's prediction (or all if no line), Theil-Sen fit."""
        pts = []
        for t in np.arange(t_a + 0.05, t_b - 0.05, 0.2):
            runs = self.playhead(t)
            if not runs:
                continue
            if R and T0 is not None:
                pred = (t - T0) * R
                runs = [r for r in runs if abs(r["x"] - pred) <= 80]
                if not runs:
                    continue
                r = min(runs, key=lambda r: abs(r["x"] - pred))
            else:
                r = min(runs, key=lambda r: r["x"])
            pts.append((float(t), float(r["x"])))
        if len(pts) < 4:
            return dict(ok=False, n=len(pts), msg="playhead not visible enough on this page")
        fit = geotime.theil([p[0] for p in pts], [p[1] for p in pts])
        if fit is None or not (60 < fit[0] < 1200):
            return dict(ok=False, n=len(pts), msg="no consistent sweep line")
        Rn, T0n = fit
        res = [abs(x - (t - T0n) * Rn) for t, x in pts]
        return dict(ok=True, R=round(Rn, 3), T0=round(T0n, 4), n=len(pts), med_res=round(float(np.median(res)), 1))

    def refit_flips(self, page, notes):
        """Binary-search the colour-flip time of every bar on the page and RANSAC
        a sweep line through (t_flip, x0): the fix for pages whose playhead is
        hidden by a bar-coloured background."""
        pts = []
        frames = self._Frames(self)
        for n in notes:
            if n["x1"] - n["x0"] < 16:
                continue
            nt = dict(x0=int(n["x0"]), x1=int(n["x1"]), cy=float(n["cy"]), cls=n.get("cls", "main"))
            t_seen = page["t_end"] - 0.10
            tf = geotime.flip_time(frames, self.prof, self.swatches, nt, t_seen, self.fps, max_back=page["t_end"] - page["vis_a"] + 0.5)
            if tf is not None:
                pts.append((tf, float(n["x0"])))
        if len(pts) < 3:
            return dict(ok=False, n_pts=len(pts), msg="fewer than 3 bars flipped cleanly")
        best = None
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                (ti, xi), (tj, xj) = pts[i], pts[j]
                if abs(xj - xi) < 60 or abs(tj - ti) < 0.05:
                    continue
                R = (xj - xi) / (tj - ti)
                if not (60 < R < 1200):
                    continue
                T0 = ti - xi / R
                inl = [q for q in pts if abs(q[0] - (T0 + q[1] / R)) < 0.08]
                if best is None or len(inl) > len(best[2]):
                    best = (R, T0, inl)
        if best is None or len(best[2]) < 3:
            return dict(ok=False, n_pts=len(pts), msg="flips do not line up")
        fit = geotime.fit_line_pts(best[2])
        R, T0 = (fit[0], fit[1]) if fit else best[:2]
        return dict(ok=True, R=round(R, 3), T0=round(T0, 4), n_in=len(best[2]), n_pts=len(pts),
                    flips=[dict(t=round(t, 3), x0=int(x)) for t, x in pts])

    # ------------------------------------------------------------ save
    def save(self, pages, notes, dry=False):
        sm = self.sm
        a, ph0 = sm["lattice"]["px_per_semitone"], sm["lattice"]["phase"]
        base = (sm.get("pitch_anchor") or {}).get("midi_base")
        pages = sorted(pages, key=lambda p: p["vis_a"])
        for p, q in zip(pages, pages[1:]):
            p["t_end"] = q["vis_a"]
        out = []
        for n in notes:
            p = pages[int(n["page"])]
            if p.get("R") is None or p.get("T0") is None:
                ts, te = float(n["t_start"]), float(n["t_end"])  # legacy page without sweep model
            else:
                ts = p["T0"] + n["x0"] / p["R"]; te = p["T0"] + n["x1"] / p["R"]
            cy = float(n["cy"]); k = -int(round((cy - ph0) / a))
            m = dict(x0=int(n["x0"]), x1=int(n["x1"]), cy=round(cy, 1), cls=n.get("cls", "main"), k=k,
                     t_start=round(ts, 3), t_end=round(max(te, ts + 0.05), 3),
                     first_f=int(round(ts * self.fps)), last_f=int(round(te * self.fps)),
                     page=int(n["page"]), seen=int(n.get("seen", 0)), src=n.get("src", "manual"))
            if base is not None:
                midi = int(base + k)
                m.update(midi=midi, pc=midi % 12, name=NOTE_NAMES_EN[midi % 12] + str(midi // 12 - 1), name_jp=NOTE_NAMES_JP[midi % 12])
            out.append(m)
        out.sort(key=lambda n: (n["t_start"], n["t_end"]))
        for n, m in zip(out, out[1:]):
            if n["t_end"] > m["t_start"]:
                n["t_end"] = round(max(m["t_start"] - 0.01, n["t_start"] + 0.05), 3)
        if dry:  # recompute only (used for testing): nothing written
            return dict(ok=True, dry=True, n_notes=len(out), n_pages=len(pages), notes=out)
        # backups: the pre-label original once, plus a rolling previous version
        pre = self.map_path.replace(".json", ".pre_label.json")
        if not os.path.exists(pre):
            shutil.copyfile(self.map_path, pre)
        shutil.copyfile(self.map_path, self.map_path.replace(".json", ".bak.json"))
        sm["notes"] = out; sm["n_notes"] = len(out)
        sm["pages"] = [dict(vis_a=round(p["vis_a"], 3), t_end=round(p["t_end"], 3),
                            R=(round(p["R"], 3) if p.get("R") is not None else None),
                            T0=(round(p["T0"], 4) if p.get("T0") is not None else None)) for p in pages]
        sm["page_flips"] = [round(p["vis_a"], 3) for p in pages[1:]]
        sm["n_pages"] = len(pages)
        sm["method"] = (sm.get("method") or "").replace("+manual", "") + "+manual"
        sm["label_saved"] = time.strftime("%Y-%m-%d %H:%M:%S")
        sm["n_manual"] = sum(1 for n in out if n["src"] == "manual")
        tmp = self.map_path + ".tmp"
        json.dump(sm, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, self.map_path)
        return dict(ok=True, n_notes=len(out), n_pages=len(pages), path=os.path.relpath(self.map_path, ROOT))


_songs = {}
_songs_lock = threading.Lock()


def song(sid):
    if sid not in VIDEOS:
        raise KeyError(sid)
    with _songs_lock:
        s = _songs.get(sid)
        if s is None:
            s = _songs[sid] = Song(sid)
        return s


def list_songs():
    out = []
    for sid, path in VIDEOS.items():
        mp = os.path.join(OUT, f"song_map_{sid}.json")
        if not (os.path.exists(path) and os.path.exists(mp)):
            continue
        try:
            sm = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        out.append(dict(id=sid, title=sm["meta"].get("title_jp") or sid, n_notes=sm.get("n_notes"),
                        n_pages=sm.get("n_pages"), hud_total=HUD_TOTALS.get(sid), method=sm.get("method")))
    return out


def handle(path, query, body=None):
    """Route one request. Returns (status, content_type, bytes)."""
    def js(obj, status=200):
        return status, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8")
    def g(name, default=None, typ=str):
        v = query.get(name, [None])[0]
        return default if v is None else typ(v)
    try:
        if path == "songs":
            return js(list_songs())
        s = song(g("v") or (body or {}).get("v"))
        if path == "song":
            return js(s.state())
        if path == "frame":
            data = s.jpeg(g("t", 0.0, float), g("crop", "top"), g("q", 85, int))
            return (200, "image/jpeg", data) if data else js(dict(error="no frame"), 404)
        if path == "detect":
            st = g("strict", None, int)
            return js(s.detect(g("t", 0.0, float), None if st is None else bool(st), not bool(g("nolattice", 0, int))))
        if path == "playhead":
            return js(s.playhead(g("t", 0.0, float)))
        if path == "pagescan":
            st = s.state() if body is None else body
            return js(s.pagescan(st["pages"], st.get("notes")))
        if path == "flipstrip":
            data = s.flipstrip(g("x0", 0, int), g("x1", 0, int), g("cy", 0.0, float), g("t", 0.0, float), g("cls", "main"))
            return (200, "image/jpeg", data) if data else js(dict(error="no frame"), 404)
        if path == "fliptime":
            tf = s.fliptime(g("x0", 0, int), g("x1", 0, int), g("cy", 0.0, float), g("cls", "main"), g("t_seen", 0.0, float))
            return js(dict(t_flip=None if tf is None else round(tf, 3)))
        if path == "refit_playhead":
            return js(s.refit_playhead(g("t_a", 0.0, float), g("t_b", 0.0, float), g("R", None, float), g("T0", None, float)))
        if path == "refit_flips":
            return js(s.refit_flips(body["page"], body["notes"]))
        if path == "save":
            return js(s.save(body["pages"], body["notes"], bool(body.get("dry"))))
        return js(dict(error="unknown endpoint " + path), 404)
    except KeyError as e:
        return js(dict(error=f"unknown song {e}"), 404)
    except Exception as e:  # report to the tool instead of a bare 500
        import traceback
        traceback.print_exc()
        return js(dict(error=f"{type(e).__name__}: {e}"), 500)
