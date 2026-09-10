"""Admin: song ingestion queue, publishing, and the labeling tool's API (pipeline/labelapi.py)."""
import json
import os
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

import paths
from .. import youtube
from ..auth import require_admin
from ..db import get_db, now, one, rows
from ..songmaps import sync_song_row

router = APIRouter(dependencies=[Depends(require_admin)])
_labelapi = None


def labelapi():
    """Lazy import: needs cv2/numpy, which the web process otherwise never loads."""
    global _labelapi
    if _labelapi is None:
        import labelapi as m
        _labelapi = m
    return _labelapi


class SongIn(BaseModel):
    url: str


def _latest_jobs(db, ids):
    out = {}
    if not ids:
        return out
    q = ",".join("?" * len(ids))
    for j in rows(db.execute(f"SELECT id, song_id, kind, status, stage, progress, error, created_at, started_at, finished_at, heartbeat_at "
                             f"FROM jobs WHERE song_id IN ({q}) ORDER BY id", ids)):
        out[j["song_id"]] = j
    return out


@router.get("/api/admin/songs")
def admin_songs(db=Depends(get_db)):
    songs = rows(db.execute("SELECT * FROM songs ORDER BY created_at DESC"))
    jobs = _latest_jobs(db, [s["id"] for s in songs])
    for s in songs:
        if s["status"] in ("labeling", "published", "hidden"):
            summ = sync_song_row(db, s["id"])
            if summ:
                s.update({k: summ[k] for k in ("n_notes", "n_pages", "duration", "family")})
                s["method"] = summ["method"]
                s["n_manual"] = summ["n_manual"]
        s["job"] = jobs.get(s["id"])
        s["has_video"] = s["id"] in paths.VIDEOS
        s["has_map"] = os.path.exists(paths.map_path(s["id"]))
    queue = rows(db.execute("SELECT id, song_id, kind, status, stage, progress FROM jobs WHERE status IN ('queued','running') ORDER BY id"))
    return {"songs": songs, "queue": queue}


@router.post("/api/admin/songs")
def add_song(body: SongIn, db=Depends(get_db), user=Depends(require_admin)):
    vid = youtube.video_id(body.url)
    if not vid:
        raise HTTPException(400, "YouTubeのURLが読めません / not a YouTube URL")
    existing = one(db.execute("SELECT * FROM songs WHERE id=?", (vid,)))
    if existing and existing["status"] not in ("failed",):
        raise HTTPException(409, f"すでに登録されています ({existing['status']}) / already added")
    if not existing:
        db.execute("INSERT INTO songs(id,youtube_url,status,created_by,created_at) VALUES(?,?,?,?,?)",
                   (vid, youtube.watch_url(vid), "processing", user["id"], now()))
    else:
        db.execute("UPDATE songs SET status='processing', youtube_url=? WHERE id=?", (youtube.watch_url(vid), vid))
    db.execute("INSERT INTO jobs(song_id,kind,status,created_at) VALUES(?,?,?,?)", (vid, "ingest", "queued", now()))
    return {"song": one(db.execute("SELECT * FROM songs WHERE id=?", (vid,)))}


@router.get("/api/admin/jobs/{jid}")
def job_detail(jid: int, db=Depends(get_db)):
    j = one(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)))
    if not j:
        raise HTTPException(404)
    return j


class ReprocessIn(BaseModel):
    from_stage: Optional[str] = None   # extract | geotime | anchor | lyrics (None = full pipeline, keep video)


@router.post("/api/admin/songs/{sid}/reprocess")
def reprocess(sid: str, body: ReprocessIn, db=Depends(get_db)):
    s = one(db.execute("SELECT * FROM songs WHERE id=?", (sid,)))
    if not s:
        raise HTTPException(404)
    if one(db.execute("SELECT 1 FROM jobs WHERE song_id=? AND status IN ('queued','running')", (sid,))):
        raise HTTPException(409, "すでに処理中です / already queued")
    kind = "ingest" if sid not in paths.VIDEOS else "reprocess"
    stage = body.from_stage if body.from_stage in ("extract", "geotime", "anchor", "lyrics") else None
    db.execute("INSERT INTO jobs(song_id,kind,status,stage,created_at) VALUES(?,?,?,?,?)", (sid, kind, "queued", stage, now()))
    if s["status"] in ("failed",):
        db.execute("UPDATE songs SET status='processing' WHERE id=?", (sid,))
    return {"ok": True}


@router.post("/api/admin/jobs/{jid}/cancel")
def cancel_job(jid: int, db=Depends(get_db)):
    j = one(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)))
    if not j:
        raise HTTPException(404)
    if j["status"] == "queued":
        db.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=?", (now(), jid))
    elif j["status"] == "running":
        db.execute("UPDATE jobs SET error='cancel requested' WHERE id=?", (jid,))  # the worker checks this between stages
    return {"ok": True}


@router.post("/api/admin/songs/{sid}/publish")
def publish(sid: str, db=Depends(get_db)):
    if not os.path.exists(paths.map_path(sid)):
        raise HTTPException(400, "song map がありません / no map yet")
    if sid not in paths.VIDEOS:
        raise HTTPException(400, "動画がありません / no video")
    sync_song_row(db, sid)
    db.execute("UPDATE songs SET status='published', published_at=COALESCE(published_at,?) WHERE id=?", (now(), sid))
    return {"ok": True}


@router.post("/api/admin/songs/{sid}/unpublish")
def unpublish(sid: str, db=Depends(get_db)):
    db.execute("UPDATE songs SET status='labeling' WHERE id=?", (sid,))
    return {"ok": True}


@router.post("/api/admin/songs/{sid}/hide")
def hide(sid: str, db=Depends(get_db)):
    db.execute("UPDATE songs SET status='hidden' WHERE id=?", (sid,))
    return {"ok": True}


class SongPatch(BaseModel):
    title_jp: Optional[str] = None
    artist_jp: Optional[str] = None
    title_en: Optional[str] = None
    artist_en: Optional[str] = None


@router.patch("/api/admin/songs/{sid}")
def patch_song(sid: str, body: SongPatch, db=Depends(get_db)):
    for k, v in body.model_dump(exclude_none=True).items():
        db.execute(f"UPDATE songs SET {k}=? WHERE id=?", (v.strip()[:120], sid))
    # keep the map's meta in step so the label tool / exports agree
    p = paths.map_path(sid)
    if os.path.exists(p):
        sm = json.load(open(p, encoding="utf-8"))
        sm.setdefault("meta", {}).update({k: v for k, v in body.model_dump(exclude_none=True).items()})
        json.dump(sm, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"song": one(db.execute("SELECT * FROM songs WHERE id=?", (sid,)))}


@router.delete("/api/admin/songs/{sid}")
def delete_song(sid: str, purge: bool = False, db=Depends(get_db)):
    """Deletes the DB row (plays cascade). purge=1 also removes the video, caches and maps on disk."""
    if one(db.execute("SELECT 1 FROM jobs WHERE song_id=? AND status='running'", (sid,))):
        raise HTTPException(409, "処理中は削除できません / job running")
    db.execute("DELETE FROM songs WHERE id=?", (sid,))
    if purge:
        shutil.rmtree(paths.song_dir(sid), ignore_errors=True)
        for fn in os.listdir(paths.MAPS_DIR):
            if fn.startswith(f"song_map_{sid}.") or fn == f"song_map_{sid}.json":
                os.remove(os.path.join(paths.MAPS_DIR, fn))
        for fn in os.listdir(paths.CACHE_DIR):
            if fn.endswith(f"_{sid}.pkl") or fn.endswith(f"_{sid}.f32"):
                os.remove(os.path.join(paths.CACHE_DIR, fn))
    return {"ok": True}


# ---- labeling tool backend (GET + POST /api/label/<path>?...) -------------------------------------
@router.api_route("/api/label/{path:path}", methods=["GET", "POST"])
async def label_api(path: str, request: Request):
    body = None
    if request.method == "POST":
        raw = await request.body()
        body = json.loads(raw.decode("utf-8")) if raw else None
    query = {k: request.query_params.getlist(k) for k in request.query_params.keys()}
    status, ctype, data = labelapi().handle(path, query, body)
    return Response(content=data, status_code=status, media_type=ctype, headers={"Cache-Control": "no-store"})
