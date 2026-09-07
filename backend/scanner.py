"""Incremental folder scanning and the background face-extraction worker."""
import os
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

import db
import clustering
import faces as faces_mod

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}
# videos are recorded but not processed (phase 2)
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp", ".mts", ".wmv"}

# phase: idle | enumerating | scanning | clustering | done | error
_state = {"phase": "idle", "current": None, "run_faces": 0, "error": None}
_pause = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _clear_thumbs() -> None:
    """Empties the preview and face-crop caches. Source photos are untouched."""
    for directory in (db.FACE_THUMBS_DIR, db.PHOTO_THUMBS_DIR):
        for f in directory.glob("*.jpg"):
            f.unlink(missing_ok=True)


def start_scan(root_path: str) -> None:
    """Records the library and starts the scan on a background thread.

    Only one library is active at a time, so picking a different root drops all
    previous data. The same root means an incremental scan.
    """
    global _thread
    root = Path(root_path).expanduser()
    if not root.is_dir():
        raise ValueError(f"Klasör bulunamadı: {root}")
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("Tarama zaten sürüyor")
        conn = db.get_db()
        lib = db.get_library()
        if lib is None or lib["root_path"] != str(root):
            # New root, clean slate. The on-disk previews have to go too:
            # once the rows are gone SQLite reuses ids from 1, so the previous
            # library's cache would be served for the new files.
            _clear_thumbs()
            conn.execute("DELETE FROM group_members")
            conn.execute("DELETE FROM groups")
            conn.execute("DELETE FROM faces")
            conn.execute("DELETE FROM clusters")
            conn.execute("DELETE FROM media_files")
            conn.execute("DELETE FROM library")
            conn.execute("INSERT INTO library(root_path) VALUES (?)", (str(root),))
            conn.commit()
        _pause.clear()
        _stop.clear()
        _state.update({"phase": "enumerating", "current": None, "run_faces": 0, "error": None})
        _thread = threading.Thread(target=_worker, daemon=True)
        _thread.start()


def pause() -> None:
    _pause.set()


def resume() -> None:
    """Continues a paused or half-finished scan."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            _pause.clear()
            return
        if db.get_library() is None:
            raise RuntimeError("Önce bir klasör seçin")
        _pause.clear()
        _stop.clear()
        _state.update({"phase": "scanning", "current": None, "run_faces": 0, "error": None})
        _thread = threading.Thread(target=_worker, args=(False,), daemon=True)
        _thread.start()


def get_status() -> dict:
    conn = db.get_db()
    counts = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM media_files WHERE type='photo' GROUP BY status")}
    total = sum(counts.values())
    done = counts.get("done", 0) + counts.get("error", 0)
    total_faces = conn.execute("SELECT COUNT(*) AS n FROM faces").fetchone()["n"]
    lib = db.get_library()
    running = _thread is not None and _thread.is_alive()
    phase = _state["phase"]
    if running and _pause.is_set():
        phase = "paused"
    return {
        "phase": phase,
        "running": running,
        "paused": _pause.is_set(),
        "root_path": lib["root_path"] if lib else None,
        "total": total,
        "done": done,
        "pending": counts.get("pending", 0),
        "errors": counts.get("error", 0),
        "faces": total_faces,
        "current": _state["current"],
        "model": faces_mod.model_state["status"],
        "error": _state["error"],
    }


def _worker(enumerate_first: bool = True) -> None:
    try:
        if enumerate_first:
            _enumerate()
        _state["phase"] = "scanning"
        _process_pending()
        if _stop.is_set():
            return
        _state["phase"] = "clustering"
        _state["current"] = None
        clustering.cluster_unassigned()
        _state["phase"] = "done"
    except Exception as exc:
        traceback.print_exc()
        _state["phase"] = "error"
        _state["error"] = str(exc)


def _enumerate() -> None:
    """Walks the disk and syncs the DB. A changed file goes back to pending;
    rows whose file is gone are deleted and their faces cascade with them."""
    conn = db.get_db()
    lib = db.get_library()
    root = Path(lib["root_path"])
    existing = {r["rel_path"]: r for r in conn.execute(
        "SELECT id, rel_path, size, mtime FROM media_files WHERE library_id=?", (lib["id"],))}
    seen = set()

    def walk(d: Path):
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                walk(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in PHOTO_EXTS:
                    ftype = "photo"
                elif ext in VIDEO_EXTS:
                    ftype = "video"
                else:
                    continue
                st = entry.stat()
                rel = str(Path(entry.path).relative_to(root))
                seen.add(rel)
                row = existing.get(rel)
                if row is None:
                    conn.execute(
                        "INSERT INTO media_files(library_id, rel_path, type, size, mtime) VALUES (?,?,?,?,?)",
                        (lib["id"], rel, ftype, st.st_size, st.st_mtime))
                elif row["size"] != st.st_size or abs(row["mtime"] - st.st_mtime) > 1e-6:
                    # changed: drop the old faces and the stale preview, reprocess
                    conn.execute("DELETE FROM faces WHERE file_id=?", (row["id"],))
                    (db.PHOTO_THUMBS_DIR / f"{row['id']}.jpg").unlink(missing_ok=True)
                    conn.execute(
                        "UPDATE media_files SET size=?, mtime=?, status='pending', error=NULL, face_count=0 WHERE id=?",
                        (st.st_size, st.st_mtime, row["id"]))

    walk(root)
    missing = [r["id"] for rel, r in existing.items() if rel not in seen]
    for fid in missing:
        conn.execute("DELETE FROM media_files WHERE id=?", (fid,))
    conn.commit()


def _process_pending() -> None:
    conn = db.get_db()
    lib = db.get_library()
    root = Path(lib["root_path"])
    while not _stop.is_set():
        while _pause.is_set() and not _stop.is_set():
            _stop.wait(0.2)
        row = conn.execute(
            "SELECT id, rel_path FROM media_files WHERE status='pending' AND type='photo' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            break
        _state["current"] = row["rel_path"]
        now = datetime.now(timezone.utc).isoformat()
        try:
            w, h, found = faces_mod.extract_faces(root / row["rel_path"], row["id"])
            min_score = float(db.get_setting("min_det_score"))
            min_px = float(db.get_setting("min_face_px"))
            for face in found:
                bx, by, bw, bh = face["bbox"]
                quality = "ok" if (face["det_score"] >= min_score and min(bw, bh) >= min_px) else "low"
                conn.execute(
                    "INSERT INTO faces(file_id, bbox_x, bbox_y, bbox_w, bbox_h, det_score, embedding, thumb_name, quality)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (row["id"], bx, by, bw, bh, face["det_score"],
                     face["embedding"].tobytes(), face["thumb_name"], quality))
            conn.execute(
                "UPDATE media_files SET status='done', width=?, height=?, face_count=?, scanned_at=?, error=NULL WHERE id=?",
                (w, h, len(found), now, row["id"]))
            _state["run_faces"] += len(found)
        except Exception as exc:
            conn.execute(
                "UPDATE media_files SET status='error', error=?, scanned_at=? WHERE id=?",
                (str(exc)[:500], now, row["id"]))
        conn.commit()
    _state["current"] = None
