"""SQLite schema and connection helpers.

Application data lives under ~/Library/Application Support/facey/:
  facey.db      — metadata + embeddings
  face_thumbs/  — face crops (small JPEGs)
  photo_thumbs/ — photo previews, generated on demand
The original photos are never written to.
"""
import os
import sqlite3
import threading
from pathlib import Path

DEFAULT_APP_DIR = Path.home() / "Library" / "Application Support" / "facey"

# FACEY_DATA_DIR moves the data elsewhere (tests, portable installs).
APP_DIR = Path(os.environ.get("FACEY_DATA_DIR") or DEFAULT_APP_DIR)
DB_PATH = APP_DIR / "facey.db"
FACE_THUMBS_DIR = APP_DIR / "face_thumbs"
PHOTO_THUMBS_DIR = APP_DIR / "photo_thumbs"


def _ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    FACE_THUMBS_DIR.mkdir(exist_ok=True)
    PHOTO_THUMBS_DIR.mkdir(exist_ok=True)


def use_data_dir(path) -> None:
    """Switches the data directory at runtime. Used by the tests."""
    global APP_DIR, DB_PATH, FACE_THUMBS_DIR, PHOTO_THUMBS_DIR
    close_connection()
    APP_DIR = Path(path)
    DB_PATH = APP_DIR / "facey.db"
    FACE_THUMBS_DIR = APP_DIR / "face_thumbs"
    PHOTO_THUMBS_DIR = APP_DIR / "photo_thumbs"
    _ensure_dirs()

SCHEMA = """
CREATE TABLE IF NOT EXISTS library (
    id INTEGER PRIMARY KEY,
    root_path TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY,
    library_id INTEGER NOT NULL REFERENCES library(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'photo',        -- photo | video (video: phase 2)
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',    -- pending | done | error
    error TEXT,
    width INTEGER,
    height INTEGER,
    face_count INTEGER NOT NULL DEFAULT 0,
    scanned_at TEXT,
    UNIQUE(library_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_media_status ON media_files(status);
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    name TEXT,
    cover_face_id INTEGER,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
    bbox_x REAL, bbox_y REAL, bbox_w REAL, bbox_h REAL,
    det_score REAL,
    embedding BLOB,                            -- 512 x float32, L2-normalized
    thumb_name TEXT,
    cluster_id INTEGER REFERENCES clusters(id) ON DELETE SET NULL,
    quality TEXT NOT NULL DEFAULT 'ok'         -- ok | low (the leftover pool)
);
CREATE INDEX IF NOT EXISTS idx_faces_file ON faces(file_id);
CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    cluster_id INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, cluster_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "assign_threshold": "0.45",   # min cosine similarity to join an existing cluster
    "cluster_distance": "0.55",   # agglomerative cosine distance threshold
    "min_det_score": "0.60",      # below this a face is quality=low
    "min_face_px": "40",          # bbox short edge at full resolution; below this a face is low
}

_local = threading.local()


def get_db() -> sqlite3.Connection:
    """One connection per thread, for the worker threads and uvicorn's own."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        _ensure_dirs()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        _local.conn = conn
    return conn


def close_connection() -> None:
    """Closes this thread's connection, which isolates the tests."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def get_setting(key: str) -> str:
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS[key]


def set_setting(key: str, value: str) -> None:
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))
    db.commit()


def get_library():
    """The single active library, i.e. the most recently added one."""
    return get_db().execute("SELECT * FROM library ORDER BY id DESC LIMIT 1").fetchone()
