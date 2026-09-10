# Portable locations for the pipeline + app. Everything lives under KARAOKE_DATA
# (default <repo>/data) so the same code runs on the Windows dev box and the Pi.
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.abspath(os.environ.get("KARAOKE_DATA") or os.path.join(ROOT, "data"))
SONGS_DIR = os.path.join(DATA, "songs")     # songs/<sid>/video.mp4 (+ info.json)
MAPS_DIR = os.path.join(DATA, "maps")       # maps/song_map_<sid>.json
CACHE_DIR = os.path.join(DATA, "cache")     # raw_<sid>.pkl, geo_<sid>.pkl, audio_<sid>.f32
for _d in (SONGS_DIR, MAPS_DIR, CACHE_DIR):
    os.makedirs(_d, exist_ok=True)

# The five PoC videos, still resolvable by their old ids when the mp4 sits in the repo root.
_LEGACY = {
    "v1": "【カラオケ練習用】マリーゴールド／あいみょん｜[Videoke] Mary Gold - Aimyon.mp4",
    "v2": "【カラオケ練習用】残酷な天使のテーゼ／高橋洋子｜[Karaoke] title - _Neon Genesis EVANGELION_ Main Theme.mp4",
    "v3": "【カラオケ練習用】夜に駆ける／YOASOBI｜[Videoke] Yoru ni Kakeru - YOASOBI - カラオケ@DIVA (1080p).mp4",
    "v4": "【カラオケ練習用】残響散歌／Aimer｜[Karaoke] Zankyousanka - Aimer - カラオケ@DIVA (1080p).mp4",
    "v5": "【カラオケ練習用】白日／King Gnu｜[Videoke]Hakujitsu - King Gnu - カラオケ@DIVA (720p).mp4",
}


def map_path(sid, suffix=""):
    return os.path.join(MAPS_DIR, f"song_map_{sid}{suffix}.json")


def song_dir(sid):
    return os.path.join(SONGS_DIR, sid)


def ffmpeg():
    """ffmpeg binary: $FFMPEG, then PATH (apt on the Pi), then the imageio-ffmpeg wheel."""
    p = os.environ.get("FFMPEG")
    if p and os.path.exists(p):
        return p
    p = shutil.which("ffmpeg")
    if p:
        return p
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


class _Videos:
    """dict-like sid -> video path. data/songs/<sid>/video.mp4 first, legacy repo-root files second."""

    def _resolve(self, sid):
        d = song_dir(sid)
        # only the merged file counts: yt-dlp leaves video.f298.mp4 / video.f140.m4a fragments around while downloading
        p = os.path.join(d, "video.mp4")
        if os.path.exists(p):
            return p
        if sid in _LEGACY:
            p = os.path.join(ROOT, _LEGACY[sid])
            if os.path.exists(p):
                return p
        return None

    def __getitem__(self, sid):
        p = self._resolve(sid)
        if p is None:
            raise KeyError(sid)
        return p

    def __contains__(self, sid):
        return self._resolve(sid) is not None

    def get(self, sid, default=None):
        p = self._resolve(sid)
        return default if p is None else p

    def keys(self):
        ids = []
        if os.path.isdir(SONGS_DIR):
            ids += sorted(os.listdir(SONGS_DIR))
        ids += [k for k in _LEGACY if k not in ids]
        return [k for k in ids if self._resolve(k)]

    def items(self):
        return [(k, self[k]) for k in self.keys()]

    def __iter__(self):
        return iter(self.keys())


VIDEOS = _Videos()
