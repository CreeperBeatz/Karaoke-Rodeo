# Song metadata from the channel's filename/title format:
#   【カラオケ練習用】<title_jp>／<artist_jp>｜[Videoke|Karaoke] <english part>
import re
import os

NOTE_NAMES_JP = ["ド", "ド#", "レ", "レ#", "ミ", "ファ", "ファ#",
                 "ソ", "ソ#", "ラ", "ラ#", "シ"]
# pitch-class index (0 = C) for each label
NOTE_PC = {n: i for i, n in enumerate(NOTE_NAMES_JP)}
NOTE_NAMES_EN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def parse_title(path):
    return parse_title_str(os.path.splitext(os.path.basename(path))[0], os.path.basename(path))


def parse_title_str(base, filename=None):
    """Same parser for a YouTube title string (from yt-dlp's info.json)."""
    m = re.match(r"【カラオケ練習用】(?P<title>[^／]+)／(?P<artist>[^｜|]+)[｜|]\s*(?P<en>.*)", base)
    out = {"filename": filename or base, "title_jp": None, "artist_jp": None,
           "english_part": None, "title_en": None, "artist_en": None}
    if not m:
        return out
    out["title_jp"] = m.group("title").strip()
    out["artist_jp"] = m.group("artist").strip()
    en = m.group("en").strip()
    out["english_part"] = en
    m2 = re.match(r"\[(?:Videoke|Karaoke)\]\s*(?P<t>[^-]+?)\s*-\s*(?P<a>.+)", en)
    if m2:
        out["title_en"] = m2.group("t").strip()
        out["artist_en"] = re.sub(r"\s*-\s*カラオケ@DIVA.*$", "", m2.group("a")).strip()
    return out


if __name__ == "__main__":
    import json
    for f in [
        "【カラオケ練習用】マリーゴールド／あいみょん｜[Videoke] Mary Gold - Aimyon.mp4",
        "【カラオケ練習用】残酷な天使のテーゼ／高橋洋子｜[Karaoke] title - _Neon Genesis EVANGELION_ Main Theme.mp4",
    ]:
        print(json.dumps(parse_title(f), ensure_ascii=False, indent=1))
