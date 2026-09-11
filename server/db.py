"""SQLite access: one short-lived connection per request (cheap; WAL mode lets readers and the worker coexist)."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
# Append-only list of (version, sql). schema.sql is version 1.
MIGRATIONS = [
    # 2: login codes - the magic-link mail also carries a 6-digit code that can be typed into an installed app
    #    (iOS keeps a home-screen app's cookies apart from Safari, so the link alone cannot log the app in).
    (2, "ALTER TABLE login_tokens ADD COLUMN code_hash TEXT;\n"
        "ALTER TABLE login_tokens ADD COLUMN code_attempts INTEGER NOT NULL DEFAULT 0;"),
    # 3: furigana for the song menu. Aozora-style markup, 漢字《かな》 (an optional ｜ marks where the base starts);
    #    the catalogue renders it as <ruby>. Edited in the admin table; the songs that exist today get theirs here.
    (3, "ALTER TABLE songs ADD COLUMN title_ruby TEXT;\n"
        "ALTER TABLE songs ADD COLUMN artist_ruby TEXT;\n"
        "UPDATE songs SET title_ruby='残酷《ざんこく》な天使《てんし》のテーゼ', artist_ruby='高橋《たかはし》洋子《ようこ》' WHERE id='v2';\n"
        "UPDATE songs SET title_ruby='夜《よる》に駆《か》ける' WHERE id='v3';\n"
        "UPDATE songs SET title_ruby='残響《ざんきょう》散歌《さんか》' WHERE id='v4';\n"
        "UPDATE songs SET title_ruby='白日《はくじつ》' WHERE id='v5';\n"
        "UPDATE songs SET artist_ruby='米津《よねづ》玄師《けんし》' WHERE id='qCyvFHauKt0';"),
]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    con = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def migrate():
    con = connect()
    try:
        v = con.execute("PRAGMA user_version").fetchone()[0]
        if v < 1:
            con.executescript(open(SCHEMA, encoding="utf-8").read())
            con.execute("PRAGMA user_version=1")
            v = 1
        for ver, sql in MIGRATIONS:
            if v < ver:
                con.executescript(sql)
                con.execute(f"PRAGMA user_version={ver}")
                v = ver
    finally:
        con.close()


def get_db():
    """FastAPI dependency."""
    con = connect()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def tx(con):
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def one(cur):
    r = cur.fetchone()
    return dict(r) if r else None
