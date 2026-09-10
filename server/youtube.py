"""YouTube URL helpers."""
import re
from urllib.parse import parse_qs, urlparse

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id(url):
    """Return the 11-char video id from any common YouTube URL form, or None."""
    url = (url or "").strip()
    if ID_RE.match(url):
        return url
    try:
        u = urlparse(url if "//" in url else "https://" + url)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host in ("youtu.be", "www.youtu.be"):
        vid = u.path.strip("/").split("/")[0]
        return vid if ID_RE.match(vid) else None
    if not (host.endswith("youtube.com") or host.endswith("youtube-nocookie.com")):
        return None
    q = parse_qs(u.query)
    if "v" in q and ID_RE.match(q["v"][0]):
        return q["v"][0]
    m = re.match(r"^/(?:embed|shorts|live|v)/([A-Za-z0-9_-]{11})", u.path)
    return m.group(1) if m else None


def watch_url(vid):
    return f"https://www.youtube.com/watch?v={vid}"
