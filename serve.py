# Dev server with HTTP Range support (required for mp4 seeking) and a
# dynamic /songs.json manifest of processed songs.
import http.server
import json
import os
import re
import socketserver
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
_labelapi = None


def labelapi():
    """Lazy import: the labeling backend needs cv2/numpy, the player does not."""
    global _labelapi
    if _labelapi is None:
        import labelapi as m
        _labelapi = m
    return _labelapi


def build_manifest():
    songs = []
    outdir = os.path.join(ROOT, "output")
    if os.path.isdir(outdir):
        for fn in sorted(os.listdir(outdir)):
            m = re.match(r"song_map_(\w+)\.json$", fn)
            if not m:
                continue
            try:
                sm = json.load(open(os.path.join(outdir, fn), encoding="utf-8"))
            except Exception:
                continue
            if not os.path.exists(os.path.join(ROOT, sm.get("video", ""))):
                continue
            songs.append(dict(
                id=m.group(1),
                map_url="/output/" + fn,
                video_url="/" + urllib.parse.quote(sm["video"]),
                title=sm["meta"].get("title_jp") or sm["video"],
                artist=sm["meta"].get("artist_jp") or "",
                n_notes=sm.get("n_notes"),
                duration=sm.get("duration"),
            ))
    return dict(songs=songs)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def _api(self, body=None):
        u = urllib.parse.urlparse(self.path)
        status, ctype, data = labelapi().handle(u.path[len("/api/label/"):], urllib.parse.parse_qs(u.query), body)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path.startswith("/api/label/"):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else None
            return self._api(body)
        self.send_error(404)

    def do_GET(self):
        if self.path.startswith("/api/label/"):
            return self._api()
        if self.path.split("?")[0] == "/songs.json":
            body = json.dumps(build_manifest(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/app/")
            self.end_headers()
            return
        # Range support for media
        path = self.translate_path(self.path)
        rng = self.headers.get("Range")
        if rng and os.path.isfile(path):
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                size = os.path.getsize(path)
                start = int(m.group(1)) if m.group(1) else 0
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Type", self.guess_type(path))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                with open(path, "rb") as fh:
                    fh.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk = fh.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                            return
                        remaining -= len(chunk)
                return
        super().do_GET()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"serving {ROOT} at http://127.0.0.1:{PORT}/  (app: /app/, labeling tool: /app/label.html)")
        httpd.serve_forever()
