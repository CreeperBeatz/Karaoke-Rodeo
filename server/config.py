"""Settings from environment / .env (KEY=VALUE lines, # comments). No third-party dependency."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import paths  # noqa: E402  (creates the data dirs)


def _bool(v, default=False):
    if v is None or v == "":
        return default
    return v.lower() in ("1", "true", "yes", "on")


BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8765").rstrip("/")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
DATA = paths.DATA
DB_PATH = os.environ.get("DB_PATH") or os.path.join(DATA, "app.db")
AVATARS_DIR = os.path.join(DATA, "avatars")
os.makedirs(AVATARS_DIR, exist_ok=True)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "karaoke.rodeo <no-reply@karaoke.rodeo>")
# DEV_MODE: no mail is sent; the magic link is printed to the console and returned to the caller.
DEV_MODE = _bool(os.environ.get("DEV_MODE"), default=not RESEND_API_KEY)
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
COOKIE_SECURE = BASE_URL.startswith("https://")
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "90"))
LOGIN_TOKEN_MINUTES = int(os.environ.get("LOGIN_TOKEN_MINUTES", "15"))
APP_NAME = "karaoke.rodeo"
