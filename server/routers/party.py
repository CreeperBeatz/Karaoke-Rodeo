"""Party mode: the host screen shows a QR; friends scan it and join as themselves or as a named guest."""
import hashlib
import io
import secrets
from typing import Optional

import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import config
from ..auth import current_user, require_user
from ..db import get_db, now, one, rows

router = APIRouter()
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
# One colour per seat, in join order: the pitch line on the host screen is drawn in the singer's colour,
# and the same colour marks them on every phone. Distinct up to 8 members, then it wraps.
SEAT_COLOURS = ["#35d6f0", "#ff4d8f", "#5ef07a", "#ffc64b", "#b06bff", "#ff8a3d", "#4d8cff", "#ff5d5d"]


def _code():
    return "".join(secrets.choice(ALPHABET) for _ in range(5))


def _h(t):
    return hashlib.sha256(t.encode()).hexdigest()


def _cookie(code):
    return f"rodeo_party_{code}"


def _party(db, code):
    p = one(db.execute("SELECT * FROM parties WHERE code=?", (code.upper(),)))
    if not p:
        raise HTTPException(404, "パーティーが見つかりません / party not found")
    return p


def _members(db, code):
    ms = rows(db.execute(
        "SELECT m.id, m.user_id, m.guest_name, m.joined_at, m.queue_pos, u.display_name, u.avatar_ver "
        "FROM party_members m LEFT JOIN users u ON u.id=m.user_id WHERE m.party_code=? ORDER BY m.joined_at", (code,)))
    bests = {r["party_member_id"]: r for r in rows(db.execute(
        "SELECT party_member_id, MAX(score) AS best, COUNT(*) AS n FROM plays WHERE party_code=? GROUP BY party_member_id", (code,)))}
    for i, m in enumerate(ms):
        m["name"] = m["display_name"] or m["guest_name"]
        m["color"] = SEAT_COLOURS[i % len(SEAT_COLOURS)]
        m["is_guest"] = m["user_id"] is None
        b = bests.get(m["id"])
        m["best"] = b["best"] if b else None
        m["n_plays"] = b["n"] if b else 0
    return ms


def _my_member(request: Request, db, code, user):
    if user:
        m = one(db.execute("SELECT id FROM party_members WHERE party_code=? AND user_id=?", (code, user["id"])))
        if m:
            return m["id"]
    tok = request.cookies.get(_cookie(code))
    if tok:
        m = one(db.execute("SELECT id FROM party_members WHERE party_code=? AND guest_token_hash=?", (code, _h(tok))))
        if m:
            return m["id"]
    return None


def _state(db, request, p, user):
    code = p["code"]
    return {"code": code, "ended": bool(p["ended_at"]), "host_user_id": p["host_user_id"],
            "is_host": bool(user and user["id"] == p["host_user_id"]),
            "current_member_id": p["current_member_id"], "members": _members(db, code),
            "me_member_id": _my_member(request, db, code, user), "join_url": f"{config.BASE_URL}/p/{code}"}


@router.post("/api/party")
def create_party(request: Request, db=Depends(get_db), user=Depends(require_user)):
    # one open party per host: reuse it
    p = one(db.execute("SELECT * FROM parties WHERE host_user_id=? AND ended_at IS NULL ORDER BY created_at DESC", (user["id"],)))
    if not p:
        code = _code()
        while one(db.execute("SELECT 1 FROM parties WHERE code=?", (code,))):
            code = _code()
        db.execute("INSERT INTO parties(code,host_user_id,created_at) VALUES(?,?,?)", (code, user["id"], now()))
        cur = db.execute("INSERT INTO party_members(party_code,user_id,joined_at) VALUES(?,?,?)", (code, user["id"], now()))
        db.execute("UPDATE parties SET current_member_id=? WHERE code=?", (cur.lastrowid, code))
        p = _party(db, code)
    return _state(db, request, p, user)


@router.get("/api/party/mine")
def my_party(request: Request, db=Depends(get_db), user=Depends(require_user)):
    """The caller's open party (as host), or {} - lets the play page restore its party panel after a reload."""
    p = one(db.execute("SELECT * FROM parties WHERE host_user_id=? AND ended_at IS NULL ORDER BY created_at DESC", (user["id"],)))
    return _state(db, request, p, user) if p else {}


@router.get("/api/party/{code}")
def get_party(code: str, request: Request, db=Depends(get_db), user=Depends(current_user)):
    return _state(db, request, _party(db, code), user)


@router.get("/api/party/{code}/qr.svg")
def party_qr(code: str, db=Depends(get_db)):
    p = _party(db, code)
    buf = io.BytesIO()
    # Ink modules on the dialog's white card: a near-white module colour was invisible on it, and
    # scanners want dark-on-light anyway. light=None keeps the card's rounded corners showing through.
    segno.make(f"{config.BASE_URL}/p/{p['code']}", error="m").save(buf, kind="svg", scale=8, dark="#15120c", light=None, border=1)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


class JoinIn(BaseModel):
    name: Optional[str] = None


@router.post("/api/party/{code}/join")
def join_party(code: str, body: JoinIn, request: Request, response: Response, db=Depends(get_db), user=Depends(current_user)):
    p = _party(db, code)
    code = p["code"]
    if p["ended_at"]:
        raise HTTPException(410, "このパーティーは終了しました / party ended")
    guest_tok = request.cookies.get(_cookie(code))
    if user:
        m = one(db.execute("SELECT id FROM party_members WHERE party_code=? AND user_id=?", (code, user["id"])))
        if m:
            return _state(db, request, p, user)
        # A guest who logs in later claims their guest seat (and its plays).
        if guest_tok:
            g = one(db.execute("SELECT id FROM party_members WHERE party_code=? AND guest_token_hash=? AND user_id IS NULL", (code, _h(guest_tok))))
            if g:
                db.execute("UPDATE party_members SET user_id=?, guest_token_hash=NULL WHERE id=?", (user["id"], g["id"]))
                db.execute("UPDATE plays SET user_id=? WHERE party_member_id=? AND user_id IS NULL", (user["id"], g["id"]))
                return _state(db, request, p, user)
        db.execute("INSERT INTO party_members(party_code,user_id,joined_at) VALUES(?,?,?)", (code, user["id"], now()))
        return _state(db, request, p, user)
    if guest_tok and one(db.execute("SELECT 1 FROM party_members WHERE party_code=? AND guest_token_hash=?", (code, _h(guest_tok)))):
        return _state(db, request, p, None)
    name = " ".join((body.name or "").split())[:20]
    if not name:
        raise HTTPException(400, "ニックネームを入力してください / nickname required")
    tok = secrets.token_urlsafe(24)
    db.execute("INSERT INTO party_members(party_code,guest_name,guest_token_hash,joined_at) VALUES(?,?,?,?)", (code, name, _h(tok), now()))
    response.set_cookie(_cookie(code), tok, max_age=30 * 86400, httponly=True, secure=config.COOKIE_SECURE, samesite="lax", path="/")
    return _state(db, request, p, None)


class SingerIn(BaseModel):
    member_id: int


@router.post("/api/party/{code}/singer")
def set_singer(code: str, body: SingerIn, request: Request, db=Depends(get_db), user=Depends(require_user)):
    p = _party(db, code)
    if p["host_user_id"] != user["id"]:
        raise HTTPException(403, "ホストのみ / host only")
    if not one(db.execute("SELECT 1 FROM party_members WHERE id=? AND party_code=?", (body.member_id, p["code"]))):
        raise HTTPException(404, "member not found")
    db.execute("UPDATE parties SET current_member_id=? WHERE code=?", (body.member_id, p["code"]))
    db.execute("UPDATE party_members SET queue_pos=NULL WHERE id=?", (body.member_id,))
    return _state(db, request, _party(db, code), user)


@router.post("/api/party/{code}/next")
def request_next(code: str, request: Request, db=Depends(get_db), user=Depends(current_user)):
    """'I'm next' from a phone: puts the caller's seat at the end of the queue (toggle)."""
    p = _party(db, code)
    mid = _my_member(request, db, p["code"], user)
    if not mid:
        raise HTTPException(403, "先に参加してください / join first")
    m = one(db.execute("SELECT queue_pos FROM party_members WHERE id=?", (mid,)))
    if m["queue_pos"] is not None:
        db.execute("UPDATE party_members SET queue_pos=NULL WHERE id=?", (mid,))
    else:
        mx = db.execute("SELECT COALESCE(MAX(queue_pos),0) FROM party_members WHERE party_code=?", (p["code"],)).fetchone()[0]
        db.execute("UPDATE party_members SET queue_pos=? WHERE id=?", (mx + 1, mid))
    return _state(db, request, p, user)


@router.post("/api/party/{code}/end")
def end_party(code: str, request: Request, db=Depends(get_db), user=Depends(require_user)):
    p = _party(db, code)
    if p["host_user_id"] != user["id"]:
        raise HTTPException(403, "ホストのみ / host only")
    db.execute("UPDATE parties SET ended_at=? WHERE code=?", (now(), p["code"]))
    return _state(db, request, _party(db, code), user)


@router.get("/api/party/{code}/board")
def party_board(code: str, db=Depends(get_db)):
    p = _party(db, code)
    plays = rows(db.execute(
        "SELECT pl.id, pl.score, pl.played_at, pl.song_id, s.title_jp, s.artist_jp, pl.party_member_id, "
        "COALESCE(u.display_name, m.guest_name) AS name, u.avatar_ver, m.user_id "
        "FROM plays pl JOIN songs s ON s.id=pl.song_id JOIN party_members m ON m.id=pl.party_member_id LEFT JOIN users u ON u.id=m.user_id "
        "WHERE pl.party_code=? ORDER BY pl.played_at DESC LIMIT 100", (p["code"],)))
    return {"plays": plays, "members": _members(db, p["code"])}
