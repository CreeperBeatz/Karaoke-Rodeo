"""Import the five PoC songs (output/song_map_v*.json + the mp4s in the repo root) into data/ and the DB.

    python tools/import_poc.py [--publish] [--move] [--cache DIR]

--publish   set status=published (default: labeling, publish from /admin)
--move      move the mp4s into data/songs/<id>/video.mp4 instead of copying
--cache DIR also copy raw_/geo_/audio_ caches from an old scratchpad so the label tool keeps its CV assists
"""
import argparse
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server import config  # noqa: E402
from server.db import connect, migrate, now  # noqa: E402
from server.songmaps import sync_song_row  # noqa: E402
import paths  # noqa: E402

OUT = os.path.join(ROOT, "output")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--move", action="store_true")
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    migrate()
    con = connect()
    for fn in sorted(os.listdir(OUT)):
        m = re.match(r"song_map_(v\d+)\.json$", fn)
        if not m:
            continue
        sid = m.group(1)
        sm = json.load(open(os.path.join(OUT, fn), encoding="utf-8"))
        src_video = os.path.join(ROOT, sm["video"])
        if not os.path.exists(src_video):
            print(f"{sid}: video missing ({sm['video']}), skipped")
            continue
        d = paths.song_dir(sid)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, "video.mp4")
        if not os.path.exists(dst):
            (shutil.move if a.move else shutil.copy2)(src_video, dst)
            print(f"{sid}: video -> {dst}")
        shutil.copy2(os.path.join(OUT, fn), paths.map_path(sid))
        if a.cache:
            for pre, ext in (("raw_", ".pkl"), ("geo_", ".pkl"), ("audio_", ".f32")):
                p = os.path.join(a.cache, f"{pre}{sid}{ext}")
                if os.path.exists(p) and not os.path.exists(os.path.join(paths.CACHE_DIR, os.path.basename(p))):
                    shutil.copy2(p, paths.CACHE_DIR)
        if not os.path.exists(os.path.join(d, "thumb.jpg")):
            try:
                import cv2
                cap = cv2.VideoCapture(dst)
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * 0.3 * (sm.get("duration") or 60))
                ok, fr = cap.read()
                if ok:
                    cv2.imwrite(os.path.join(d, "thumb.jpg"), cv2.resize(fr, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 82])
            except Exception as e:
                print(f"{sid}: thumb failed: {e}")
        status = "published" if a.publish else "labeling"
        row = con.execute("SELECT status FROM songs WHERE id=?", (sid,)).fetchone()
        if not row:
            con.execute("INSERT INTO songs(id,status,created_at,published_at) VALUES(?,?,?,?)",
                        (sid, status, now(), now() if a.publish else None))
        elif a.publish and row["status"] != "published":
            con.execute("UPDATE songs SET status='published', published_at=COALESCE(published_at,?) WHERE id=?", (now(), sid))
        summ = sync_song_row(con, sid)
        print(f"{sid}: {summ['title_jp']} / {summ['artist_jp']}  {summ['n_notes']} notes  -> {status}")
    con.close()
    print("done. data =", paths.DATA)


if __name__ == "__main__":
    main()
