"""Song-map JSON access with an mtime cache (maps are 200-400 KB; stats reads them often)."""
import json
import os
import threading

import paths

_cache = {}
_lock = threading.Lock()


def load_map(sid):
    p = paths.map_path(sid)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    with _lock:
        hit = _cache.get(sid)
        if hit and hit[0] == mt:
            return hit[1]
    with open(p, encoding="utf-8") as fh:
        sm = json.load(fh)
    with _lock:
        _cache[sid] = (mt, sm)
    return sm


def map_summary(sid):
    """Fields the songs table mirrors from the map (None if no map yet)."""
    sm = load_map(sid)
    if not sm:
        return None
    meta = sm.get("meta") or {}
    return dict(
        n_notes=len(sm.get("notes") or []),
        n_pages=sm.get("n_pages") or len(sm.get("pages") or []),
        duration=sm.get("duration"),
        family=sm.get("family"),
        title_jp=meta.get("title_jp"), artist_jp=meta.get("artist_jp"),
        title_en=meta.get("title_en"), artist_en=meta.get("artist_en"),
        method=sm.get("method"), n_manual=sm.get("n_manual"),
    )


def sync_song_row(db, sid):
    """Copy map-derived fields into the songs row; returns the summary."""
    s = map_summary(sid)
    if not s:
        return None
    db.execute(
        "UPDATE songs SET n_notes=?, n_pages=?, duration=COALESCE(?,duration), family=?, "
        "title_jp=COALESCE(title_jp,?), artist_jp=COALESCE(artist_jp,?), title_en=COALESCE(title_en,?), artist_en=COALESCE(artist_en,?) WHERE id=?",
        (s["n_notes"], s["n_pages"], s["duration"], s["family"], s["title_jp"], s["artist_jp"], s["title_en"], s["artist_en"], sid))
    return s
