"""karaoke.rodeo web server.  Run:  python -m server   (or uvicorn server.main:app)"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db
from .routers import admin, party, plays, profile, songs, stats

WEB = os.path.join(config.ROOT, "web")
PAGES = {"": "index.html", "login": "login.html", "play": "play.html", "stats": "stats.html", "leaderboard": "leaderboard.html",
         "profile": "profile.html", "admin": "admin.html", "label": "label.html", "songs": "index.html", "about": "about.html"}

app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
db.migrate()
for r in (profile, songs, plays, stats, party, admin):
    app.include_router(r.router)
app.mount("/static", StaticFiles(directory=os.path.join(WEB, "static")), name="static")


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
        return FileResponse(os.path.join(WEB, "404.html"), status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def _page(name):
    return FileResponse(os.path.join(WEB, name), media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/")
def home():
    return _page("index.html")


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
