"""Copying or moving the photos of the selected people into a destination folder.

Safety rules:
- Copy is the default; move is confirmed separately in the UI.
- A file at the destination is NEVER overwritten (same size: skip, otherwise: -1 suffix).
- Every copy is size-verified; a move is copy + verify + delete.
- The destination cannot sit inside the library, or the next scan would index the copies.
"""
import shutil
import threading
from pathlib import Path

import db

# phase: idle | running | done | error
state = {
    "phase": "idle", "mode": "copy", "dest": None,
    "total": 0, "copied": 0, "skipped": 0, "errors": 0,
    "current": None, "error_files": [],
}
_thread: threading.Thread | None = None
_lock = threading.Lock()


def matching_files(cluster_ids: list[int]):
    """Photos holding at least one face from the selected clusters."""
    if not cluster_ids:
        return []
    qmarks = ",".join("?" * len(cluster_ids))
    return db.get_db().execute(
        f"""SELECT DISTINCT m.id, m.rel_path FROM media_files m
            JOIN faces f ON f.file_id = m.id
            WHERE f.cluster_id IN ({qmarks}) AND m.type='photo' AND m.status='done'
            ORDER BY m.rel_path""",
        cluster_ids).fetchall()


def start_export(cluster_ids: list[int], dest_path: str, mode: str = "copy") -> None:
    global _thread
    if mode not in ("copy", "move"):
        raise ValueError("mode 'copy' veya 'move' olmalı")
    lib = db.get_library()
    if lib is None:
        raise RuntimeError("Kütüphane yok")
    root = Path(lib["root_path"]).resolve()
    dest = Path(dest_path).expanduser().resolve()
    if dest == root or root in dest.parents:
        raise ValueError("Hedef klasör, kaynak kütüphanenin içinde olamaz")
    dest.mkdir(parents=True, exist_ok=True)
    files = [(r["id"], r["rel_path"]) for r in matching_files(cluster_ids)]
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("Dışa aktarma zaten sürüyor")
        state.update({
            "phase": "running", "mode": mode, "dest": str(dest),
            "total": len(files), "copied": 0, "skipped": 0, "errors": 0,
            "current": None, "error_files": [],
        })
        _thread = threading.Thread(target=_run, args=(files, root, dest, mode), daemon=True)
        _thread.start()


def _unique_target(target: Path) -> Path:
    stem, suffix = target.stem, target.suffix
    for i in range(1, 1000):
        candidate = target.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Benzersiz isim bulunamadı: {target}")


def _run(files, root: Path, dest: Path, mode: str) -> None:
    for _file_id, rel in files:
        state["current"] = rel
        src = root / rel
        target = dest / rel
        try:
            if not src.exists():
                raise FileNotFoundError("kaynak dosya artık yok")
            src_size = src.stat().st_size
            if target.exists():
                if target.stat().st_size == src_size:
                    state["skipped"] += 1     # already exported
                    continue
                target = _unique_target(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            if target.stat().st_size != src_size:
                target.unlink(missing_ok=True)
                raise IOError("boyut doğrulaması başarısız")
            if mode == "move":
                src.unlink()
            state["copied"] += 1
        except Exception as exc:
            state["errors"] += 1
            state["error_files"].append({"path": rel, "error": str(exc)[:300]})
    state["current"] = None
    state["phase"] = "done"


def get_status() -> dict:
    return dict(state)
