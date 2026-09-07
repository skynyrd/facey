"""FastAPI application: every API route, plus the built frontend in production."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import clustering
import db
import exporter
import scanner
import thumbs

app = FastAPI(title="Facey")

# in dev the UI is served by Vite (5173), a different origin
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------- library + scanning ----------

class LibraryIn(BaseModel):
    root_path: str


@app.get("/api/library")
def get_library():
    lib = db.get_library()
    return {"root_path": lib["root_path"] if lib else None}


@app.post("/api/library")
def set_library(body: LibraryIn):
    try:
        scanner.start_scan(body.root_path)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/api/scan/status")
def scan_status():
    return scanner.get_status()


@app.post("/api/scan/pause")
def scan_pause():
    scanner.pause()
    return {"ok": True}


@app.post("/api/scan/resume")
def scan_resume():
    try:
        scanner.resume()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/api/scan/errors")
def scan_errors():
    rows = db.get_db().execute(
        "SELECT rel_path, error FROM media_files WHERE status='error' ORDER BY rel_path").fetchall()
    return [dict(r) for r in rows]


# ---------- clusters ----------

@app.get("/api/clusters")
def clusters(include_hidden: bool = False):
    where = "" if include_hidden else "WHERE c.hidden = 0"
    rows = db.get_db().execute(f"""
        SELECT c.id, c.name, c.hidden, c.cover_face_id,
               COUNT(f.id) AS face_count,
               COUNT(DISTINCT f.file_id) AS photo_count
        FROM clusters c LEFT JOIN faces f ON f.cluster_id = c.id
        {where}
        GROUP BY c.id
        ORDER BY face_count DESC, c.id
    """).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/clusters/{cluster_id}/faces")
def cluster_faces(cluster_id: int):
    rows = db.get_db().execute("""
        SELECT f.id, f.file_id, f.det_score, m.rel_path
        FROM faces f JOIN media_files m ON m.id = f.file_id
        WHERE f.cluster_id = ?
        ORDER BY f.det_score DESC
    """, (cluster_id,)).fetchall()
    return [dict(r) for r in rows]


class MergeIn(BaseModel):
    target_id: int
    source_ids: list[int]


@app.post("/api/clusters/merge")
def merge(body: MergeIn):
    clustering.merge_clusters(body.target_id, body.source_ids)
    return {"ok": True}


class ClusterUpdate(BaseModel):
    name: str | None = None
    hidden: bool | None = None


@app.post("/api/clusters/{cluster_id}")
def update_cluster(cluster_id: int, body: ClusterUpdate):
    conn = db.get_db()
    if body.name is not None:
        conn.execute("UPDATE clusters SET name=? WHERE id=?",
                     (body.name.strip() or None, cluster_id))
    if body.hidden is not None:
        conn.execute("UPDATE clusters SET hidden=? WHERE id=?",
                     (1 if body.hidden else 0, cluster_id))
    conn.commit()
    return {"ok": True}


class FaceIds(BaseModel):
    face_ids: list[int]


@app.post("/api/faces/unassign")
def unassign(body: FaceIds):
    clustering.unassign_faces(body.face_ids)
    return {"ok": True}


@app.post("/api/recluster")
def recluster():
    return clustering.cluster_unassigned()


# ---------- images ----------

@app.get("/api/face-thumb/{face_id}")
def face_thumb(face_id: int):
    row = db.get_db().execute(
        "SELECT thumb_name FROM faces WHERE id=?", (face_id,)).fetchone()
    if row is None:
        raise HTTPException(404)
    path = db.FACE_THUMBS_DIR / row["thumb_name"]
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/thumb/{file_id}")
def photo_thumb(file_id: int):
    try:
        path = thumbs.get_photo_thumb(file_id)
    except FileNotFoundError:
        raise HTTPException(404)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return FileResponse(path, media_type="image/jpeg")


# ---------- groups ----------

class GroupIn(BaseModel):
    name: str
    cluster_ids: list[int]


@app.get("/api/groups")
def groups():
    conn = db.get_db()
    rows = conn.execute("SELECT id, name FROM groups ORDER BY name").fetchall()
    result = []
    for g in rows:
        members = [r["cluster_id"] for r in conn.execute(
            "SELECT cluster_id FROM group_members WHERE group_id=?", (g["id"],))]
        result.append({"id": g["id"], "name": g["name"], "cluster_ids": members})
    return result


@app.post("/api/groups")
def save_group(body: GroupIn):
    name = body.name.strip()
    if not name or not body.cluster_ids:
        raise HTTPException(400, "İsim ve en az bir kişi gerekli")
    conn = db.get_db()
    row = conn.execute("SELECT id FROM groups WHERE name=?", (name,)).fetchone()
    if row:
        gid = row["id"]
        conn.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
    else:
        gid = conn.execute("INSERT INTO groups(name) VALUES (?)", (name,)).lastrowid
    for cid in set(body.cluster_ids):
        conn.execute(
            "INSERT OR IGNORE INTO group_members(group_id, cluster_id) VALUES (?,?)", (gid, cid))
    conn.commit()
    return {"id": gid}


@app.delete("/api/groups/{group_id}")
def delete_group(group_id: int):
    conn = db.get_db()
    conn.execute("DELETE FROM groups WHERE id=?", (group_id,))
    conn.commit()
    return {"ok": True}


# ---------- export ----------

@app.get("/api/export/preview")
def export_preview(cluster_ids: str):
    try:
        ids = [int(x) for x in cluster_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "cluster_ids virgülle ayrılmış sayılar olmalı")
    files = exporter.matching_files(ids)
    return {"count": len(files),
            "files": [{"id": r["id"], "rel_path": r["rel_path"]} for r in files]}


class ExportIn(BaseModel):
    cluster_ids: list[int]
    dest_path: str
    mode: str = "copy"


@app.post("/api/export")
def start_export(body: ExportIn):
    if not body.cluster_ids:
        raise HTTPException(400, "En az bir kişi seçin")
    try:
        exporter.start_export(body.cluster_ids, body.dest_path, body.mode)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/api/export/status")
def export_status():
    return exporter.get_status()


# ---------- settings ----------

@app.get("/api/settings")
def get_settings():
    return {k: db.get_setting(k) for k in db.DEFAULT_SETTINGS}


class SettingsIn(BaseModel):
    values: dict[str, str]


@app.post("/api/settings")
def set_settings(body: SettingsIn):
    # Validate everything first, then write: one bad value must not leave a half-saved batch.
    for k, v in body.values.items():
        if k not in db.DEFAULT_SETTINGS:
            raise HTTPException(400, f"Bilinmeyen ayar: {k}")
        try:
            float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"'{k}' sayısal olmalı, alınan: {v!r}")
    for k, v in body.values.items():
        db.set_setting(k, v)
    return {"ok": True}




# ---------- maintenance ----------

@app.post("/api/cache/clear")
def clear_cache():
    """Empties the preview cache. The DB and the face crops are left alone."""
    n = 0
    for f in db.PHOTO_THUMBS_DIR.glob("*.jpg"):
        f.unlink(missing_ok=True)
        n += 1
    return {"removed": n}


# ---------- frontend (production) ----------

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="static")
