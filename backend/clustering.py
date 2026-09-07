"""Face clustering: incremental assignment to existing clusters, plus
agglomerative clustering for whatever is left over.

Manual edits (merge / unassign / hide) are never undone by the automatic pass.
There is no full re-cluster; only faces with cluster_id IS NULL are placed.
"""
import numpy as np
from sklearn.cluster import AgglomerativeClustering

import db


def _load_matrix(rows):
    ids = [r["id"] for r in rows]
    X = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    return ids, X


def _cluster_centroids(conn):
    """Normalized mean embedding of each cluster."""
    rows = conn.execute(
        "SELECT id, embedding, cluster_id FROM faces WHERE cluster_id IS NOT NULL").fetchall()
    if not rows:
        return None, []
    by_cluster: dict[int, list] = {}
    for r in rows:
        by_cluster.setdefault(r["cluster_id"], []).append(
            np.frombuffer(r["embedding"], dtype=np.float32))
    cids, cents = [], []
    for cid, embs in by_cluster.items():
        c = np.mean(embs, axis=0)
        norm = np.linalg.norm(c)
        if norm > 0:
            cids.append(cid)
            cents.append(c / norm)
    if not cids:
        return None, []
    return np.stack(cents), cids


def cluster_unassigned() -> dict:
    """Places the faces with quality='ok' and cluster_id IS NULL."""
    conn = db.get_db()
    thr_assign = float(db.get_setting("assign_threshold"))
    thr_dist = float(db.get_setting("cluster_distance"))

    rows = conn.execute(
        "SELECT id, embedding FROM faces WHERE cluster_id IS NULL AND quality='ok'").fetchall()
    if not rows:
        refresh_covers(conn)
        conn.commit()
        return {"assigned": 0, "new_clusters": 0}

    ids, X = _load_matrix(rows)

    # 1) assign to existing cluster centroids by cosine similarity
    assigned: dict[int, int] = {}
    centroids, cent_ids = _cluster_centroids(conn)
    if centroids is not None:
        sims = X @ centroids.T
        best = sims.argmax(axis=1)
        best_sim = sims.max(axis=1)
        for i, fid in enumerate(ids):
            if best_sim[i] >= thr_assign:
                assigned[fid] = cent_ids[int(best[i])]

    # 2) cluster whatever is left among themselves
    remaining = [i for i, fid in enumerate(ids) if fid not in assigned]
    new_clusters = 0
    if len(remaining) == 1:
        fid = ids[remaining[0]]
        cur = conn.execute("INSERT INTO clusters DEFAULT VALUES")
        assigned[fid] = cur.lastrowid
        new_clusters = 1
    elif len(remaining) > 1:
        Xr = X[remaining]
        model = AgglomerativeClustering(
            n_clusters=None, distance_threshold=thr_dist,
            metric="cosine", linkage="average")
        labels = model.fit_predict(Xr)
        label_to_cluster: dict[int, int] = {}
        for local_i, label in zip(remaining, labels):
            label = int(label)
            if label not in label_to_cluster:
                cur = conn.execute("INSERT INTO clusters DEFAULT VALUES")
                label_to_cluster[label] = cur.lastrowid
                new_clusters += 1
            assigned[ids[local_i]] = label_to_cluster[label]

    for fid, cid in assigned.items():
        conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (cid, fid))

    refresh_covers(conn)
    conn.commit()
    return {"assigned": len(assigned), "new_clusters": new_clusters}


def refresh_covers(conn) -> None:
    """Repairs clusters whose cover face is missing or stale, drops empty ones."""
    conn.execute("""
        DELETE FROM clusters WHERE id NOT IN (
            SELECT DISTINCT cluster_id FROM faces WHERE cluster_id IS NOT NULL)
    """)
    conn.execute("""
        UPDATE clusters SET cover_face_id = (
            SELECT f.id FROM faces f
            WHERE f.cluster_id = clusters.id
            ORDER BY f.det_score DESC LIMIT 1)
        WHERE cover_face_id IS NULL
           OR cover_face_id NOT IN (SELECT id FROM faces WHERE cluster_id = clusters.id)
    """)


def merge_clusters(target_id: int, source_ids: list[int]) -> None:
    conn = db.get_db()
    sources = [cid for cid in source_ids if cid != target_id]
    if not sources:
        return
    qmarks = ",".join("?" * len(sources))
    conn.execute(
        f"UPDATE faces SET cluster_id=? WHERE cluster_id IN ({qmarks})",
        [target_id, *sources])
    # an unnamed target inherits the first name found among the sources
    target = conn.execute("SELECT name FROM clusters WHERE id=?", (target_id,)).fetchone()
    if target and not target["name"]:
        named = conn.execute(
            f"SELECT name FROM clusters WHERE id IN ({qmarks}) AND name IS NOT NULL LIMIT 1",
            sources).fetchone()
        if named:
            conn.execute("UPDATE clusters SET name=? WHERE id=?", (named["name"], target_id))
    conn.execute(f"DELETE FROM clusters WHERE id IN ({qmarks})", sources)
    refresh_covers(conn)
    conn.commit()


def unassign_faces(face_ids: list[int]) -> None:
    """Pulls the given faces out of their clusters; each becomes a singleton."""
    conn = db.get_db()
    for fid in face_ids:
        cur = conn.execute("INSERT INTO clusters DEFAULT VALUES")
        conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (cur.lastrowid, fid))
    refresh_covers(conn)
    conn.commit()
