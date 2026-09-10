"""Catalog, song maps and login-gated media streaming."""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

import paths
from ..auth import current_user, require_user
from ..db import get_db, one, rows

router = APIRouter()

SONG_COLS = "id, title_jp, artist_jp, title_en, artist_en, duration, n_notes, n_pages, family, status, published_at"


def _song(db, sid):
    s = one(db.execute(f"SELECT {SONG_COLS} FROM songs WHERE id=?", (sid,)))
    if not s:
        raise HTTPException(404, "曲がありません / no such song")
    return s


def _visible(song, user):
    return song["status"] == "published" or (user and user["is_admin"])


def _top(db, sid, limit=3):
    return rows(db.execute(
        "SELECT p.user_id, MAX(p.score) AS best, u.display_name, u.avatar_ver FROM plays p JOIN users u ON u.id=p.user_id "
        "WHERE p.song_id=? AND p.completed=1 GROUP BY p.user_id ORDER BY best DESC LIMIT ?", (sid, limit)))


@router.get("/api/songs")
def list_songs(db=Depends(get_db), user=Depends(current_user)):
    songs = rows(db.execute(f"SELECT {SONG_COLS} FROM songs WHERE status='published' ORDER BY published_at DESC"))
    mine = {}
    if user:
        for r in rows(db.execute("SELECT song_id, MAX(score) AS best, COUNT(*) AS n, MAX(played_at) AS last FROM plays "
                                 "WHERE user_id=? AND completed=1 GROUP BY song_id", (user["id"],))):
            mine[r["song_id"]] = r
    for s in songs:
        m = mine.get(s["id"])
        s["my_best"] = m["best"] if m else None
        s["my_plays"] = m["n"] if m else 0
        s["my_last"] = m["last"] if m else None
        s["top"] = _top(db, s["id"], 1)
        s["has_thumb"] = os.path.exists(os.path.join(paths.song_dir(s["id"]), "thumb.jpg"))
    return {"songs": songs}


@router.get("/api/songs/{sid}")
def song_detail(sid: str, db=Depends(get_db), user=Depends(current_user)):
    s = _song(db, sid)
    if not _visible(s, user):
        raise HTTPException(404, "曲がありません / no such song")
    s["top"] = _top(db, sid, 10)
    s["has_thumb"] = os.path.exists(os.path.join(paths.song_dir(sid), "thumb.jpg"))
    if user:
        s["my_plays_list"] = rows(db.execute(
            "SELECT id, score, n_perfect, n_great, n_good, n_miss, max_combo, played_at FROM plays "
            "WHERE user_id=? AND song_id=? AND completed=1 ORDER BY played_at DESC LIMIT 30", (user["id"], sid)))
        s["my_best"] = max([p["score"] for p in s["my_plays_list"]], default=None)
    return s


@router.get("/api/songs/{sid}/map")
def song_map(sid: str, db=Depends(get_db), user=Depends(require_user)):
    s = _song(db, sid)
    if not _visible(s, user):
        raise HTTPException(404)
    p = paths.map_path(sid)
    if not os.path.exists(p):
        raise HTTPException(404, "song map missing")
    return FileResponse(p, media_type="application/json", headers={"Cache-Control": "private, max-age=60"})


@router.get("/media/{sid}")
def media(sid: str, db=Depends(get_db), user=Depends(require_user)):
    s = _song(db, sid)
    if not _visible(s, user):
        raise HTTPException(404)
    p = paths.VIDEOS.get(sid)
    if not p:
        raise HTTPException(404, "video missing")
    # Starlette's FileResponse answers Range requests, which <video> seeking needs.
    return FileResponse(p, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600", "Accept-Ranges": "bytes"})


@router.get("/api/songs/{sid}/thumb")
def thumb(sid: str):
    p = os.path.join(paths.song_dir(sid), "thumb.jpg")
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
