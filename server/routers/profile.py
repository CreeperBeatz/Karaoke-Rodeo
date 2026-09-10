"""Login endpoints, /api/me, avatars."""
import io
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image, ImageOps
from pydantic import BaseModel

from .. import auth, config
from ..db import get_db, one

router = APIRouter()
MAX_AVATAR_BYTES = 4 * 1024 * 1024


class LoginIn(BaseModel):
    email: str
    next: Optional[str] = None


@router.post("/api/auth/request")
def auth_request(body: LoginIn, request: Request, db=Depends(get_db)):
    link = auth.request_link(db, body.email, auth.client_ip(request), body.next)
    out = {"ok": True, "dev_mode": config.DEV_MODE}
    if config.DEV_MODE:
        out["dev_link"] = link  # no mail is sent in dev mode; the link is shown in the UI instead
    return out


@router.get("/auth/verify")
def auth_verify(token: str, request: Request, db=Depends(get_db)):
    resp = RedirectResponse("/", status_code=303)
    try:
        user, is_new, next_url = auth.verify_token(db, token, resp, request.headers.get("user-agent", ""))
    except HTTPException as e:
        return RedirectResponse(f"/login?error={e.status_code}", status_code=303)
    if is_new:
        resp.headers["location"] = "/profile?welcome=1" + (f"&next={next_url}" if next_url else "")
    elif next_url:
        resp.headers["location"] = next_url
    return resp


@router.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, db=Depends(get_db)):
    auth.logout(db, request, response)
    return {"ok": True}


def _me(user):
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"], "avatar_ver": user["avatar_ver"],
            "latency_ms": user["latency_ms"], "is_admin": user["is_admin"], "created_at": user["created_at"]}


@router.get("/api/me")
def me(user=Depends(auth.current_user)):
    return {"user": _me(user) if user else None, "dev_mode": config.DEV_MODE, "app": config.APP_NAME}


class MePatch(BaseModel):
    display_name: Optional[str] = None
    latency_ms: Optional[int] = None


@router.patch("/api/me")
def patch_me(body: MePatch, db=Depends(get_db), user=Depends(auth.require_user)):
    if body.display_name is not None:
        name = " ".join(body.display_name.split())[:24]
        if not name:
            raise HTTPException(400, "名前を入力してください / name required")
        db.execute("UPDATE users SET display_name=? WHERE id=?", (name, user["id"]))
    if body.latency_ms is not None:
        db.execute("UPDATE users SET latency_ms=? WHERE id=?", (max(0, min(1000, body.latency_ms)), user["id"]))
    u = one(db.execute("SELECT * FROM users WHERE id=?", (user["id"],)))
    u["is_admin"] = user["is_admin"]
    return {"user": _me(u)}


def _avatar_path(uid):
    return os.path.join(config.AVATARS_DIR, f"{uid}.webp")


@router.post("/api/me/avatar")
async def upload_avatar(file: UploadFile, db=Depends(get_db), user=Depends(auth.require_user)):
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "4MB以下の画像にしてください / image too large (4 MB max)")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        im = ImageOps.exif_transpose(im)
    except Exception:
        raise HTTPException(400, "画像を読み込めません / not a readable image")
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (19, 26, 46, 255))
    im = Image.alpha_composite(bg, im).convert("RGB")
    im = ImageOps.fit(im, (256, 256), Image.LANCZOS, centering=(0.5, 0.4))
    im.save(_avatar_path(user["id"]), "WEBP", quality=86, method=6)
    db.execute("UPDATE users SET avatar_ver=avatar_ver+1 WHERE id=?", (user["id"],))
    ver = db.execute("SELECT avatar_ver FROM users WHERE id=?", (user["id"],)).fetchone()[0]
    return {"avatar_ver": ver}


@router.delete("/api/me/avatar")
def delete_avatar(db=Depends(get_db), user=Depends(auth.require_user)):
    try:
        os.remove(_avatar_path(user["id"]))
    except OSError:
        pass
    db.execute("UPDATE users SET avatar_ver=0 WHERE id=?", (user["id"],))
    return {"avatar_ver": 0}


@router.get("/avatars/{uid}.webp")
def avatar(uid: int):
    p = _avatar_path(uid)
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})
