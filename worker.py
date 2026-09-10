"""Background job runner: downloads a YouTube video and runs the extraction pipeline, one job at a time.

    python worker.py            # loop forever (systemd unit on the Pi)
    python worker.py --once     # run at most one job, then exit

Shares the SQLite DB with the web server (WAL). Each stage is a subprocess so a crash in OpenCV
never takes the worker down, and so the stage can be niced on the Pi.
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import config  # noqa: E402  (loads .env, adds pipeline/ to sys.path)
from server.db import connect, now  # noqa: E402
from server.songmaps import sync_song_row  # noqa: E402
import paths  # noqa: E402
import meta  # noqa: E402

PIPELINE = os.path.join(config.ROOT, "pipeline")
STAGES = ["download", "extract", "geotime", "anchor", "lyrics", "finalize"]
WEIGHT = {"download": 10, "extract": 40, "geotime": 35, "anchor": 8, "lyrics": 5, "finalize": 2}
LOG_KEEP = 40_000
YTDLP_FORMAT = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b"


class Cancelled(Exception):
    pass


class StageFailed(Exception):
    pass


def log(con, jid, text):
    cur = con.execute("SELECT log FROM jobs WHERE id=?", (jid,)).fetchone()[0]
    new = (cur + text)[-LOG_KEEP:]
    con.execute("UPDATE jobs SET log=?, heartbeat_at=? WHERE id=?", (new, now(), jid))


def cancel_requested(con, jid):
    r = con.execute("SELECT error FROM jobs WHERE id=?", (jid,)).fetchone()
    return bool(r and r[0] == "cancel requested")


def run_cmd(con, jid, cmd, cwd=None, extra_env=None):
    env = dict(os.environ, KARAOKE_DATA=paths.DATA, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    ncpu = os.cpu_count() or 4
    if not env.get("KARAOKE_WORKERS") and ncpu <= 4:  # Pi 4: leave one core for the web server
        env["KARAOKE_WORKERS"] = str(max(1, ncpu - 1))
    if extra_env:
        env.update(extra_env)
    pre = (lambda: os.nice(10)) if hasattr(os, "nice") else None
    log(con, jid, f"\n$ {' '.join(cmd)}\n")
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", env=env, preexec_fn=pre)
    # reader thread -> queue, so cancellation and heartbeats work even when the stage prints nothing for minutes
    q = queue.Queue()
    threading.Thread(target=lambda: ([q.put(l) for l in p.stdout], q.put(None)), daemon=True).start()
    buf, last, done = [], time.time(), False
    while not done:
        try:
            line = q.get(timeout=1.0)
            if line is None:
                done = True
            else:
                buf.append(line)
        except queue.Empty:
            pass
        if time.time() - last > 2 or done:
            log(con, jid, "".join(buf))
            buf, last = [], time.time()
            if not done and cancel_requested(con, jid):
                p.kill()
                p.wait()
                raise Cancelled()
    p.wait()
    if p.returncode != 0:
        raise StageFailed(f"exit code {p.returncode}")


def ffmpeg_dir_for_ytdlp():
    """yt-dlp wants a directory holding ffmpeg(.exe); the imageio-ffmpeg wheel ships 'ffmpeg-win-x86_64-v7.1.exe',
    so expose that binary under the expected name in data/bin."""
    ff = paths.ffmpeg()
    base = os.path.splitext(os.path.basename(ff))[0]
    if base == "ffmpeg":
        return os.path.dirname(ff)
    bindir = os.path.join(paths.DATA, "bin")
    os.makedirs(bindir, exist_ok=True)
    target = os.path.join(bindir, "ffmpeg" + os.path.splitext(ff)[1])
    if not os.path.exists(target) or os.path.getsize(target) != os.path.getsize(ff):
        try:
            os.link(ff, target)
        except OSError:
            shutil.copy2(ff, target)
    return bindir


def stage_download(con, job, song):
    sid = song["id"]
    d = paths.song_dir(sid)
    os.makedirs(d, exist_ok=True)
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--newline", "--progress-delta", "5", "-f", YTDLP_FORMAT,
           "--merge-output-format", "mp4", "-o", os.path.join(d, "video.%(ext)s"), "--write-info-json",
           "--write-thumbnail", "--convert-thumbnails", "jpg", "--ffmpeg-location", ffmpeg_dir_for_ytdlp(), song["youtube_url"]]
    run_cmd(con, job["id"], cmd)
    if not os.path.exists(os.path.join(d, "video.mp4")):
        raise StageFailed("yt-dlp finished but video.mp4 is missing")
    for fn in os.listdir(d):
        if fn.startswith("video.") and fn.endswith((".jpg", ".webp", ".png")) and fn != "thumb.jpg":
            shutil.move(os.path.join(d, fn), os.path.join(d, "thumb.jpg"))
    info_p = os.path.join(d, "video.info.json")
    if os.path.exists(info_p):
        info = json.load(open(info_p, encoding="utf-8"))
        title = info.get("title") or ""
        m = meta.parse_title_str(title)
        ch = info.get("channel") or info.get("uploader") or ""
        log(con, job["id"], f"title: {title}\nchannel: {ch}\n")
        if "DIVA" not in ch and "カラオケ" not in ch:
            log(con, job["id"], "WARNING: channel does not look like カラオケ@DIVA; the pipeline expects that skin.\n")
        con.execute("UPDATE songs SET title_jp=?, artist_jp=?, title_en=?, artist_en=?, duration=? WHERE id=?",
                    (m["title_jp"] or title[:120], m["artist_jp"] or ch[:120], m["title_en"], m["artist_en"], info.get("duration"), sid))
        # the pipeline reads the title from the file name; give it the same info via a sidecar the map can carry
        json.dump({"title": title, "meta": m, "channel": ch, "youtube_id": info.get("id")},
                  open(os.path.join(d, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.remove(info_p)


def stage_script(script):
    def run(con, job, song):
        run_cmd(con, job["id"], [sys.executable, "-X", "utf8", os.path.join(PIPELINE, script), song["id"]], cwd=PIPELINE)
    return run


def stage_finalize(con, job, song):
    sid = song["id"]
    p = paths.map_path(sid)
    if not os.path.exists(p):
        raise StageFailed("pipeline produced no song map")
    # carry the YouTube title/meta into the map (the pipeline derived meta from the file name "video.mp4")
    info_p = os.path.join(paths.song_dir(sid), "info.json")
    if os.path.exists(info_p):
        info = json.load(open(info_p, encoding="utf-8"))
        sm = json.load(open(p, encoding="utf-8"))
        sm["meta"] = dict(sm.get("meta") or {}, **{k: v for k, v in info["meta"].items() if v})
        sm["meta"]["youtube_id"] = info.get("youtube_id")
        json.dump(sm, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summ = sync_song_row(con, sid)
    if not os.path.exists(os.path.join(paths.song_dir(sid), "thumb.jpg")):
        try:
            import cv2
            cap = cv2.VideoCapture(paths.VIDEOS[sid])
            cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * 0.3 * (summ["duration"] or 60))
            ok, fr = cap.read()
            if ok:
                cv2.imwrite(os.path.join(paths.song_dir(sid), "thumb.jpg"), cv2.resize(fr, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 82])
        except Exception as e:  # thumbnails are cosmetic
            log(con, job["id"], f"thumb failed: {e}\n")
    log(con, job["id"], f"map: {summ['n_notes']} notes, {summ['n_pages']} pages, family {summ['family']}\n")


RUNNERS = {"download": stage_download, "extract": stage_script("extract.py"), "geotime": stage_script("geotime.py"),
           "anchor": stage_script("anchor_audio.py"), "lyrics": stage_script("lyrics.py"), "finalize": stage_finalize}


def claim(con):
    con.execute("BEGIN IMMEDIATE")
    try:
        j = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not j:
            con.execute("COMMIT")
            return None
        con.execute("UPDATE jobs SET status='running', started_at=?, heartbeat_at=? WHERE id=?", (now(), now(), j["id"]))
        con.execute("COMMIT")
        return dict(j)
    except Exception:
        con.execute("ROLLBACK")
        raise


def run_job(con, job):
    jid = job["id"]
    song = con.execute("SELECT * FROM songs WHERE id=?", (job["song_id"],)).fetchone()
    if not song:
        con.execute("UPDATE jobs SET status='failed', error='song row gone', finished_at=? WHERE id=?", (now(), jid))
        return
    song = dict(song)
    stages = STAGES if job["kind"] == "ingest" else STAGES[1:]
    if job["stage"] in stages:  # reprocess from a given stage
        stages = stages[stages.index(job["stage"]):]
    # a published song re-run only from anchor/lyrics keeps its notes -> stays published; anything that rebuilds
    # the notes goes back to 'labeling' for review
    keep_published = song["status"] == "published" and not ({"download", "extract", "geotime"} & set(stages))
    final_status = "published" if keep_published else "labeling"
    con.execute("UPDATE songs SET status='processing' WHERE id=?", (song["id"],))
    done_w = sum(WEIGHT[s] for s in STAGES if s not in stages)
    total = sum(WEIGHT.values())
    print(f"[job {jid}] {song['id']} stages={stages}", flush=True)
    try:
        for st in stages:
            if cancel_requested(con, jid):
                raise Cancelled()
            con.execute("UPDATE jobs SET stage=?, progress=?, heartbeat_at=? WHERE id=?", (st, round(done_w / total, 3), now(), jid))
            log(con, jid, f"\n=== {st} @ {now()} ===\n")
            t0 = time.time()
            RUNNERS[st](con, job, song)
            done_w += WEIGHT[st]
            log(con, jid, f"=== {st} done in {time.time() - t0:.0f} s ===\n")
        con.execute("UPDATE jobs SET status='done', progress=1, finished_at=?, error=NULL WHERE id=?", (now(), jid))
        con.execute("UPDATE songs SET status=? WHERE id=? AND status='processing'", (final_status, song["id"]))
        print(f"[job {jid}] done -> {final_status}", flush=True)
    except Cancelled:
        con.execute("UPDATE jobs SET status='cancelled', finished_at=?, error='cancelled' WHERE id=?", (now(), jid))
        con.execute("UPDATE songs SET status='failed' WHERE id=? AND status='processing'", (song["id"],))
        print(f"[job {jid}] cancelled", flush=True)
    except Exception as e:
        log(con, jid, f"\nERROR: {e}\n")
        con.execute("UPDATE jobs SET status='failed', finished_at=?, error=? WHERE id=?", (now(), str(e)[:500], jid))
        con.execute("UPDATE songs SET status='failed' WHERE id=? AND status='processing'", (song["id"],))
        print(f"[job {jid}] FAILED: {e}", flush=True)


def main():
    once = "--once" in sys.argv
    con = connect()
    # jobs left 'running' by a crash/reboot go back to the queue
    con.execute("UPDATE jobs SET status='queued', stage=NULL WHERE status='running'")
    print(f"worker up  data={paths.DATA}  db={config.DB_PATH}", flush=True)
    while True:
        job = claim(con)
        if job:
            run_job(con, job)
            if once:
                return
        elif once:
            print("no queued jobs")
            return
        else:
            time.sleep(3)


if __name__ == "__main__":
    main()
