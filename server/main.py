"""karaoke.rodeo web server.  Run:  python -m server   (or uvicorn server.main:app)"""
import hashlib
import os
import re

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, config, db
from .routers import admin, party, plays, profile, songs, stats

WEB = os.path.join(config.ROOT, "web")
STATIC = os.path.join(WEB, "static")
# うたう / きろく / ランキング / プロフィール / について / 管理 are views of one document, app.html (see web/static/app.js);
# the rest are documents of their own.
PAGES = {"": "app.html", "songs": "app.html", "stats": "app.html", "leaderboard": "app.html", "profile": "app.html",
         "admin": "app.html", "about": "app.html",
         "login": "login.html", "play": "play.html", "label": "label.html", "welcome": "welcome.html"}

app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
db.migrate()
for r in (profile, songs, plays, stats, party, admin):
    app.include_router(r.router)


# --- cache busting -------------------------------------------------------------------------------
# Cloudflare fronts the Pi, and on the free plan its Browser Cache TTL (4h) rewrites our
# "Cache-Control: no-cache" into "max-age=14400" and caches /static/* at the edge on top of that.
# A deploy's new CSS/JS could therefore stay invisible for hours, with no refresh able to fix it.
# So every .js/.css/.png URL is stamped with ?v=<hash of the static dir>: a deploy changes the URL, and
# the only response that must be fresh is the HTML, which Cloudflare never caches (it is dynamic).
# The icons are stamped too - a new app icon that stays cached for hours reads as a deploy that did not land.
def _asset_version():
    h = hashlib.sha256()
    for name in sorted(os.listdir(STATIC)):
        if name.endswith((".js", ".css", ".png")):
            with open(os.path.join(STATIC, name), "rb") as f:
                h.update(name.encode() + f.read())
    return h.hexdigest()[:10]


ASSET_V = _asset_version()
# The lookahead keeps /static/manifest.json from being read as /static/manifest.js + "on".
_ASSET_URL = re.compile(r"/static/([A-Za-z0-9_.-]+\.(?:js|css|png))(?![\w.-])")
_stamped = {}


def _text(path, media_type, cache, status=200):
    """A text file with every /static/*.js|css|png reference inside it stamped with ?v=ASSET_V.
    The stamp has to reach the JS as well as the HTML: the modules import each other by absolute
    path, and an unstamped import would pull a second, separate copy of common.js."""
    mtime = os.stat(path).st_mtime_ns
    hit = _stamped.get(path)
    if hit is None or hit[0] != mtime:
        with open(path, encoding="utf-8") as f:
            hit = (mtime, _ASSET_URL.sub(rf"/static/\1?v={ASSET_V}", f.read()))
        _stamped[path] = hit
    return Response(hit[1], status_code=status, media_type=media_type, headers={"Cache-Control": cache})


@app.get("/static/{name}")
def static_file(name: str, v: str = ""):
    """Serves /static; .js, .css and .png go out stamped. Nested paths fall through to the mount below."""
    path = os.path.normpath(os.path.join(STATIC, name))
    if not path.startswith(STATIC) or not os.path.isfile(path):
        raise StarletteHTTPException(404)
    if name.endswith((".js", ".css")):
        # A stamped URL names one exact build, so it can be cached hard; a bare one must revalidate.
        return _text(path, "text/javascript" if name.endswith(".js") else "text/css",
                     "public, max-age=31536000, immutable" if v else "no-cache")
    if name.endswith(".png") and v:
        return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})
    return FileResponse(path)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", "microphone=(self), camera=()")
    # /static has ETags but no explicit policy, so browsers cache it heuristically and keep stale JS/CSS after a
    # deploy. no-cache = revalidate every time (a 304 when unchanged), same as the HTML pages.
    if request.url.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith(("/api/", "/media/", "/avatars/")):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
    if exc.status_code == 404:
        return _text(os.path.join(WEB, "404.html"), "text/html", "no-cache", status=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def _page(name):
    return _text(os.path.join(WEB, name), "text/html", "no-cache")


@app.get("/")
def home(user=Depends(auth.current_user)):
    """The front door: visitors get the landing page, singers go straight to the catalogue (/songs is always the catalogue)."""
    return _page("welcome.html" if user is None else "app.html")


@app.get("/p/{code}")
def party_page(code: str):
    return _page("party.html")


@app.get("/{page}")
def page(page: str):
    if page in PAGES:
        return _page(PAGES[page])
    if page.endswith(".html") and page[:-5] in PAGES:
        return RedirectResponse("/" + page[:-5], status_code=301)
    raise StarletteHTTPException(404)
