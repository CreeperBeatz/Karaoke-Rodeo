"""Magic-link authentication + cookie sessions. Tokens are stored hashed; links are single-use."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response

from . import config, mail
from .db import get_db, now, one

SESSION_COOKIE = "rodeo_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _utcnow():
    return datetime.now(timezone.utc)


def normalize_email(email):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "メールアドレスが正しくありません / invalid email")
    return email


def client_ip(request: Request):
    # Cloudflare Tunnel / reverse proxy first, then the socket peer.
    return (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "?"))


def request_link(db, email, ip, next_url=None):
    email = normalize_email(email)
    hour_ago = _ts(_utcnow() - timedelta(hours=1))
    n_email = db.execute("SELECT COUNT(*) FROM login_tokens WHERE email=? AND created_at>?", (email, hour_ago)).fetchone()[0]
    n_ip = db.execute("SELECT COUNT(*) FROM login_tokens WHERE ip=? AND created_at>?", (ip, hour_ago)).fetchone()[0]
    if n_email >= 5 or n_ip >= 20:
        raise HTTPException(429, "リクエストが多すぎます。しばらく待ってください / too many requests")
    token = secrets.token_urlsafe(32)
    exp = _utcnow() + timedelta(minutes=config.LOGIN_TOKEN_MINUTES)
    if next_url and (not next_url.startswith("/") or next_url.startswith("//")):
        next_url = None
    db.execute("INSERT INTO login_tokens(token_hash,email,created_at,expires_at,ip,next_url) VALUES(?,?,?,?,?,?)",
               (_h(token), email, now(), _ts(exp), ip, next_url))
    link = f"{config.BASE_URL}/auth/verify?token={token}"
    subject, html, text = mail.magic_link_mail(link, config.LOGIN_TOKEN_MINUTES)
    mail.send(email, subject, html, text)
    return link


def _display_name_from_email(email):
    local = email.split("@")[0]
    local = re.sub(r"[._+-]+", " ", local).strip() or "singer"
    return local[:24]


def verify_token(db, token, response: Response, user_agent=""):
    row = one(db.execute("SELECT * FROM login_tokens WHERE token_hash=?", (_h(token),)))
    if not row or row["used_at"] or row["expires_at"] < now():
        raise HTTPException(400, "このリンクは無効か期限切れです / link invalid or expired")
    db.execute("UPDATE login_tokens SET used_at=? WHERE token_hash=?", (now(), row["token_hash"]))
    user = one(db.execute("SELECT * FROM users WHERE email=?", (row["email"],)))
    is_new = user is None
    if is_new:
        db.execute("INSERT INTO users(email,display_name,created_at,last_login_at) VALUES(?,?,?,?)",
                   (row["email"], _display_name_from_email(row["email"]), now(), now()))
        user = one(db.execute("SELECT * FROM users WHERE email=?", (row["email"],)))
    else:
        db.execute("UPDATE users SET last_login_at=? WHERE id=?", (now(), user["id"]))
    create_session(db, user["id"], response, user_agent)
    return user, is_new, row["next_url"]


def create_session(db, user_id, response: Response, user_agent=""):
    token = secrets.token_urlsafe(32)
    exp = _utcnow() + timedelta(days=config.SESSION_DAYS)
    db.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen_at,user_agent) VALUES(?,?,?,?,?,?)",
               (_h(token), user_id, now(), _ts(exp), now(), (user_agent or "")[:200]))
    response.set_cookie(SESSION_COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                        secure=config.COOKIE_SECURE, samesite="lax", path="/")


def logout(db, request: Request, response: Response):
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (_h(tok),))
    response.delete_cookie(SESSION_COOKIE, path="/")


def user_from_request(request: Request, db):
    tok = request.cookies.get(SESSION_COOKIE)
    if not tok:
        return None
    row = one(db.execute(
        "SELECT u.*, s.token_hash AS _sess, s.last_seen_at AS _seen FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.expires_at>?", (_h(tok), now())))
    if not row:
        return None
    if (row.get("_seen") or "") < now()[:13]:  # touch at most hourly
        db.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now(), row["_sess"]))
    row.pop("_sess", None)
    row.pop("_seen", None)
    row["is_admin"] = row["email"] in config.ADMIN_EMAILS
    return row


def current_user(request: Request, db=Depends(get_db)):
    return user_from_request(request, db)


def require_user(user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "ログインが必要です / login required")
    return user


def require_admin(user=Depends(require_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "管理者のみ / admin only")
    return user


def public_user(u):
    """Fields safe to show to other users."""
    return {"id": u["id"], "display_name": u["display_name"], "avatar_ver": u["avatar_ver"]}
