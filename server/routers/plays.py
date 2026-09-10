"""Score submission and leaderboards."""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_user, require_user
from ..db import get_db, now, one, rows

router = APIRouter()
MAX_RESULTS_BYTES = 300_000


class PlayIn(BaseModel):
    song_id: str
    score: float = Field(ge=0, le=100)
    counts: dict = {}
    max_combo: int = Field(0, ge=0)
    completed: bool = True
    latency_ms: Optional[int] = None
    results: Optional[dict] = None          # {"notes": [[rating 0..3, acc 0..1, cents|null], ...]}
    party_code: Optional[str] = None
    member_id: Optional[int] = None


def _cnt(d, k):
    try:
        return max(0, int(d.get(k, 0)))
    except (TypeError, ValueError):
        return 0


@router.post("/api/plays")
def submit_play(p: PlayIn, db=Depends(get_db), user=Depends(require_user)):
    song = one(db.execute("SELECT id, status FROM songs WHERE id=?", (p.song_id,)))
    if not song or (song["status"] != "published" and not user["is_admin"]):
        raise HTTPException(404, "曲がありません / no such song")
    user_id, member_id, party_code = user["id"], None, None
    if p.party_code and p.member_id:
        m = one(db.execute("SELECT m.*, pa.host_user_id, pa.ended_at FROM party_members m JOIN parties pa ON pa.code=m.party_code "
                           "WHERE m.id=? AND m.party_code=?", (p.member_id, p.party_code.upper())))
        if not m or m["ended_at"] or m["host_user_id"] != user["id"]:
            raise HTTPException(400, "パーティーの参加者が見つかりません / party member not found")
        user_id, member_id, party_code = m["user_id"], m["id"], m["party_code"]
    results = None
    if p.results is not None:
        results = json.dumps(p.results, separators=(",", ":"))
        if len(results) > MAX_RESULTS_BYTES:
            raise HTTPException(413, "results too large")
    best_before = None
    if user_id is not None:
        r = db.execute("SELECT MAX(score) FROM plays WHERE user_id=? AND song_id=? AND completed=1", (user_id, p.song_id)).fetchone()
        best_before = r[0]
    cur = db.execute(
        "INSERT INTO plays(user_id,party_member_id,party_code,song_id,score,n_perfect,n_great,n_good,n_miss,max_combo,completed,latency_ms,results,played_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, member_id, party_code, p.song_id, round(p.score, 3), _cnt(p.counts, "PERFECT"), _cnt(p.counts, "GREAT"),
         _cnt(p.counts, "GOOD"), _cnt(p.counts, "MISS"), p.max_combo, 1 if p.completed else 0, p.latency_ms, results, now()))
    out = {"id": cur.lastrowid, "best_before": best_before, "is_pb": p.completed and (best_before is None or p.score > best_before)}
    if user_id is not None and p.completed:
        out["rank"] = 1 + db.execute(
            "SELECT COUNT(*) FROM (SELECT user_id, MAX(score) b FROM plays WHERE song_id=? AND completed=1 AND user_id IS NOT NULL "
            "GROUP BY user_id) WHERE b > ?", (p.song_id, max(p.score, best_before or 0))).fetchone()[0]
        out["n_players"] = db.execute("SELECT COUNT(DISTINCT user_id) FROM plays WHERE song_id=? AND completed=1 AND user_id IS NOT NULL",
                                      (p.song_id,)).fetchone()[0]
    return out


@router.get("/api/songs/{sid}/leaderboard")
def song_leaderboard(sid: str, db=Depends(get_db), user=Depends(current_user)):
    board = rows(db.execute(
        "SELECT p.user_id, MAX(p.score) AS best, COUNT(*) AS n, MAX(p.played_at) AS last, u.display_name, u.avatar_ver "
        "FROM plays p JOIN users u ON u.id=p.user_id WHERE p.song_id=? AND p.completed=1 GROUP BY p.user_id ORDER BY best DESC LIMIT 100",
        (sid,)))
    for i, r in enumerate(board):
        r["rank"] = i + 1
        r["me"] = bool(user and r["user_id"] == user["id"])
    return {"board": board}


@router.get("/api/leaderboard")
def overall_leaderboard(db=Depends(get_db), user=Depends(current_user)):
    board = rows(db.execute(
        "WITH best AS (SELECT user_id, song_id, MAX(score) AS s FROM plays WHERE user_id IS NOT NULL AND completed=1 GROUP BY user_id, song_id) "
        "SELECT u.id AS user_id, u.display_name, u.avatar_ver, AVG(best.s) AS avg_best, COUNT(*) AS n_songs, MAX(best.s) AS top, "
        "(SELECT COUNT(*) FROM plays WHERE user_id=u.id AND completed=1) AS n_plays "
        "FROM best JOIN users u ON u.id=best.user_id GROUP BY u.id ORDER BY avg_best DESC LIMIT 100"))
    for i, r in enumerate(board):
        r["rank"] = i + 1
        r["me"] = bool(user and r["user_id"] == user["id"])
    recent = rows(db.execute(
        "SELECT p.score, p.played_at, p.song_id, s.title_jp, s.artist_jp, u.id AS user_id, u.display_name, u.avatar_ver "
        "FROM plays p JOIN users u ON u.id=p.user_id JOIN songs s ON s.id=p.song_id "
        "WHERE p.completed=1 AND s.status='published' ORDER BY p.played_at DESC LIMIT 20"))
    return {"board": board, "recent": recent}


@router.get("/api/me/plays")
def my_plays(song: Optional[str] = None, limit: int = 50, db=Depends(get_db), user=Depends(require_user)):
    q = ("SELECT p.id, p.song_id, p.score, p.n_perfect, p.n_great, p.n_good, p.n_miss, p.max_combo, p.played_at, p.completed, "
         "s.title_jp, s.artist_jp FROM plays p JOIN songs s ON s.id=p.song_id WHERE p.user_id=?")
    args = [user["id"]]
    if song:
        q += " AND p.song_id=?"
        args.append(song)
    q += " ORDER BY p.played_at DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    return {"plays": rows(db.execute(q, args))}
