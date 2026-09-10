"""Personal history: trend per song, pitch accuracy by note, weak sections, practice calendar."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from ..auth import require_user
from ..db import get_db, rows
from ..songmaps import load_map

router = APIRouter()
NAMES_JP = ["ド", "ド#", "レ", "レ#", "ミ", "ファ", "ファ#", "ソ", "ソ#", "ラ", "ラ#", "シ"]
NAMES_EN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(midi):
    return f"{NAMES_EN[midi % 12]}{midi // 12 - 1}", NAMES_JP[midi % 12]


def _local_day(ts, tz_min):
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - timedelta(minutes=tz_min)
    return dt.date()


@router.get("/api/me/stats")
def my_stats(tz: int = -540, db=Depends(get_db), user=Depends(require_user)):
    """tz = JS Date.getTimezoneOffset() (minutes, UTC-local; JST = -540)."""
    plays = rows(db.execute(
        "SELECT p.id, p.song_id, p.score, p.n_perfect, p.n_great, p.n_good, p.n_miss, p.max_combo, p.played_at, p.results, "
        "s.title_jp, s.artist_jp FROM plays p JOIN songs s ON s.id=p.song_id WHERE p.user_id=? AND p.completed=1 ORDER BY p.played_at",
        (user["id"],)))
    songs = {}
    for p in plays:
        s = songs.setdefault(p["song_id"], {"song_id": p["song_id"], "title_jp": p["title_jp"], "artist_jp": p["artist_jp"],
                                            "n": 0, "best": 0.0, "first": p["played_at"], "last": None, "trend": []})
        s["n"] += 1
        s["best"] = max(s["best"], p["score"])
        s["last"] = p["played_at"]
        s["trend"].append([p["played_at"], round(p["score"], 3)])

    # --- pitch accuracy by note + weak sections (needs the maps) ---
    by_midi = defaultdict(lambda: {"n": 0, "acc": 0.0, "cents": 0.0, "n_cents": 0, "hit": 0})
    weak = {}
    per_song_recent = defaultdict(list)
    for p in plays:
        if p["results"]:
            per_song_recent[p["song_id"]].append(p)
    for sid, ps in per_song_recent.items():
        sm = load_map(sid)
        if not sm:
            continue
        notes = sm.get("notes") or []
        pages = sm.get("pages") or []
        page_acc = defaultdict(lambda: [0.0, 0])
        for p in ps:  # by-note from all plays; weak sections from the last 5 only
            try:
                res = json.loads(p["results"]).get("notes") or []
            except (ValueError, AttributeError):
                continue
            recent = p in ps[-5:]
            for i, r in enumerate(res):
                if i >= len(notes) or not isinstance(r, list) or len(r) < 2:
                    continue
                acc = float(r[1] or 0)
                n = notes[i]
                b = by_midi[int(n["midi"])]
                b["n"] += 1
                b["acc"] += acc
                b["hit"] += 1 if acc >= 0.28 else 0
                if len(r) > 2 and r[2] is not None:
                    b["cents"] += float(r[2])
                    b["n_cents"] += 1
                if recent:
                    pa = page_acc[int(n.get("page", 0))]
                    pa[0] += acc
                    pa[1] += 1
        sec = []
        for pg, (a, k) in page_acc.items():
            if k < 2:
                continue
            pi = pages[pg] if pg < len(pages) else {}
            sec.append({"page": pg, "acc": round(a / k, 3), "n_notes": k,
                        "t_start": round(pi.get("vis_a") or pi.get("T0") or 0, 2), "t_end": round(pi.get("t_end") or 0, 2)})
        sec.sort(key=lambda x: x["acc"])
        weak[sid] = {"pages": sec[:6], "n_pages": len(pages), "all": sorted(sec, key=lambda x: x["page"])}
    notes_out = []
    for midi in sorted(by_midi):
        b = by_midi[midi]
        en, jp = note_name(midi)
        notes_out.append({"midi": midi, "name": en, "name_jp": jp, "n": b["n"], "acc": round(b["acc"] / b["n"], 3),
                          "hit_rate": round(b["hit"] / b["n"], 3),
                          "cents": round(b["cents"] / b["n_cents"], 1) if b["n_cents"] else None})

    # --- calendar & streaks ---
    days = defaultdict(int)
    for p in plays:
        days[_local_day(p["played_at"], tz).isoformat()] += 1
    today = (datetime.now(timezone.utc) - timedelta(minutes=tz)).date()
    streak = 0
    d = today
    if today.isoformat() not in days:
        d = today - timedelta(days=1)
    while d.isoformat() in days:
        streak += 1
        d -= timedelta(days=1)
    longest, run, prev = 0, 0, None
    for ds in sorted(days):
        dd = datetime.fromisoformat(ds).date()
        run = run + 1 if prev and (dd - prev).days == 1 else 1
        longest = max(longest, run)
        prev = dd
    bests = [s["best"] for s in songs.values()]
    best_play = max(plays, key=lambda p: p["score"], default=None)
    return {
        "summary": {"n_plays": len(plays), "n_songs": len(songs), "avg_best": round(sum(bests) / len(bests), 3) if bests else None,
                    "best": {"score": best_play["score"], "song_id": best_play["song_id"], "title_jp": best_play["title_jp"]} if best_play else None,
                    "streak": streak, "longest_streak": longest, "days_practiced": len(days)},
        "songs": sorted(songs.values(), key=lambda s: s["last"], reverse=True),
        "by_note": notes_out,
        "weak": weak,
        "calendar": {"days": days, "today": today.isoformat()},
        "recent": [{"song_id": p["song_id"], "title_jp": p["title_jp"], "score": p["score"], "played_at": p["played_at"],
                    "n_perfect": p["n_perfect"], "n_great": p["n_great"], "n_good": p["n_good"], "n_miss": p["n_miss"],
                    "max_combo": p["max_combo"]} for p in plays[-30:][::-1]],
    }
