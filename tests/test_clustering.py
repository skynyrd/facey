"""Clustering: automatic grouping, incremental assignment, surviving manual edits."""
import numpy as np

import clustering
import db
from conftest import person_embedding


def add_face(person: str, variant: int = 0, quality: str = "ok",
             det_score: float = 0.9, cluster_id=None) -> int:
    """Inserts a face directly, so clustering can be tested without a scan."""
    conn = db.get_db()
    lib = db.get_library()
    if lib is None:
        lib_id = conn.execute("INSERT INTO library(root_path) VALUES ('/x')").lastrowid
    else:
        lib_id = lib["id"]
    fid = conn.execute(
        "INSERT INTO media_files(library_id, rel_path, size, mtime, status)"
        " VALUES (?,?,?,?, 'done')",
        (lib_id, f"{person}-{variant}-{np.random.randint(1 << 30)}.jpg", 1, 1.0)).lastrowid
    face_id = conn.execute(
        "INSERT INTO faces(file_id, det_score, embedding, quality, cluster_id, thumb_name)"
        " VALUES (?,?,?,?,?,?)",
        (fid, det_score, person_embedding(person, variant).tobytes(),
         quality, cluster_id, f"{fid}_0.jpg")).lastrowid
    conn.commit()
    return face_id


def cluster_of(face_id: int):
    return db.get_db().execute(
        "SELECT cluster_id FROM faces WHERE id=?", (face_id,)).fetchone()["cluster_id"]


def test_same_person_variants_land_in_one_cluster():
    ids = [add_face("ali", v) for v in range(4)]
    clustering.cluster_unassigned()
    assert len({cluster_of(i) for i in ids}) == 1


def test_different_people_stay_separate():
    ali = add_face("ali")
    veli = add_face("veli")
    ayse = add_face("ayse")
    clustering.cluster_unassigned()
    assert len({cluster_of(ali), cluster_of(veli), cluster_of(ayse)}) == 3


def test_low_quality_faces_are_left_unclustered():
    good = add_face("ali")
    weak = add_face("ali", 1, quality="low")
    clustering.cluster_unassigned()
    assert cluster_of(good) is not None
    assert cluster_of(weak) is None


def test_new_face_joins_existing_cluster():
    first = [add_face("ali", v) for v in range(2)]
    result = clustering.cluster_unassigned()
    assert result["new_clusters"] == 1

    later = add_face("ali", 5)
    result = clustering.cluster_unassigned()
    assert result == {"assigned": 1, "new_clusters": 0}
    assert cluster_of(later) == cluster_of(first[0])


def test_unknown_person_creates_new_cluster():
    add_face("ali")
    clustering.cluster_unassigned()
    stranger = add_face("zeynep")
    result = clustering.cluster_unassigned()
    assert result["new_clusters"] == 1
    assert cluster_of(stranger) is not None


def test_single_unassigned_face_gets_its_own_cluster():
    lone = add_face("ali")
    result = clustering.cluster_unassigned()
    assert result == {"assigned": 1, "new_clusters": 1}
    assert cluster_of(lone) is not None


def test_noop_when_nothing_to_assign():
    add_face("ali")
    clustering.cluster_unassigned()
    assert clustering.cluster_unassigned() == {"assigned": 0, "new_clusters": 0}


def test_raising_assign_threshold_blocks_reassignment():
    """With a high enough threshold even the same person opens a new cluster."""
    first = add_face("ali", 0)
    clustering.cluster_unassigned()
    existing = cluster_of(first)
    db.set_setting("assign_threshold", "0.999")

    later = add_face("ali", 7)
    result = clustering.cluster_unassigned()

    assert result["new_clusters"] == 1
    assert cluster_of(later) != existing


def test_default_threshold_reports_no_new_cluster_for_known_person():
    """The assigned counter is faces placed; a known person opens no new cluster."""
    add_face("ali", 0)
    clustering.cluster_unassigned()

    add_face("ali", 7)
    assert clustering.cluster_unassigned() == {"assigned": 1, "new_clusters": 0}


def test_loose_cluster_distance_merges_everyone():
    ids = [add_face(p) for p in ("ali", "veli", "ayse")]
    db.set_setting("cluster_distance", "2.0")  # cosine distance is always < 2
    clustering.cluster_unassigned()
    assert len({cluster_of(i) for i in ids}) == 1


# ---------- manual edits ----------

def test_merge_moves_faces_and_removes_source():
    a = add_face("ali")
    b = add_face("veli")
    clustering.cluster_unassigned()
    target, source = cluster_of(a), cluster_of(b)

    clustering.merge_clusters(target, [source])

    assert cluster_of(b) == target
    assert db.get_db().execute(
        "SELECT COUNT(*) c FROM clusters WHERE id=?", (source,)).fetchone()["c"] == 0


def test_merge_inherits_name_when_target_unnamed():
    a, b = add_face("ali"), add_face("veli")
    clustering.cluster_unassigned()
    target, source = cluster_of(a), cluster_of(b)
    db.get_db().execute("UPDATE clusters SET name='Veli' WHERE id=?", (source,))
    db.get_db().commit()

    clustering.merge_clusters(target, [source])
    assert db.get_db().execute(
        "SELECT name FROM clusters WHERE id=?", (target,)).fetchone()["name"] == "Veli"


def test_merge_keeps_target_name():
    a, b = add_face("ali"), add_face("veli")
    clustering.cluster_unassigned()
    target, source = cluster_of(a), cluster_of(b)
    conn = db.get_db()
    conn.execute("UPDATE clusters SET name='Ali' WHERE id=?", (target,))
    conn.execute("UPDATE clusters SET name='Veli' WHERE id=?", (source,))
    conn.commit()

    clustering.merge_clusters(target, [source])
    assert conn.execute(
        "SELECT name FROM clusters WHERE id=?", (target,)).fetchone()["name"] == "Ali"


def test_merge_ignores_target_in_source_list():
    """A target listed among its own sources must not be deleted with its faces."""
    a = add_face("ali")
    clustering.cluster_unassigned()
    target = cluster_of(a)

    clustering.merge_clusters(target, [target])

    assert cluster_of(a) == target
    assert db.get_db().execute(
        "SELECT COUNT(*) c FROM clusters WHERE id=?", (target,)).fetchone()["c"] == 1


def test_merge_with_no_sources_is_noop():
    a = add_face("ali")
    clustering.cluster_unassigned()
    clustering.merge_clusters(cluster_of(a), [])
    assert cluster_of(a) is not None


def test_manual_merge_survives_reclustering():
    """The core promise: a manual merge is not undone by the automatic pass."""
    a, b = add_face("ali"), add_face("veli")
    clustering.cluster_unassigned()
    target = cluster_of(a)
    clustering.merge_clusters(target, [cluster_of(b)])

    add_face("ayse")
    clustering.cluster_unassigned()

    assert cluster_of(a) == target and cluster_of(b) == target


def test_unassigned_face_is_not_reabsorbed():
    """A face pulled out by hand must not be pulled back in by re-clustering."""
    ids = [add_face("ali", v) for v in range(3)]
    clustering.cluster_unassigned()
    original = cluster_of(ids[0])

    clustering.unassign_faces([ids[2]])
    moved_to = cluster_of(ids[2])
    assert moved_to != original

    clustering.cluster_unassigned()
    assert cluster_of(ids[2]) == moved_to


def test_unassign_gives_each_face_its_own_cluster():
    ids = [add_face("ali", v) for v in range(3)]
    clustering.cluster_unassigned()
    clustering.unassign_faces(ids[:2])
    assert cluster_of(ids[0]) != cluster_of(ids[1])


def test_empty_clusters_are_pruned():
    a = add_face("ali")
    clustering.cluster_unassigned()
    conn = db.get_db()
    orphan = conn.execute("INSERT INTO clusters(name) VALUES ('orphan')").lastrowid
    conn.commit()

    clustering.refresh_covers(conn)
    conn.commit()

    assert conn.execute(
        "SELECT COUNT(*) c FROM clusters WHERE id=?", (orphan,)).fetchone()["c"] == 0
    assert cluster_of(a) is not None


def test_cover_face_is_the_sharpest_one():
    add_face("ali", 0, det_score=0.7)
    best = add_face("ali", 1, det_score=0.99)
    clustering.cluster_unassigned()

    cover = db.get_db().execute(
        "SELECT cover_face_id FROM clusters WHERE id=?", (cluster_of(best),)).fetchone()
    assert cover["cover_face_id"] == best


def test_cover_is_replaced_when_that_face_leaves():
    a = add_face("ali", 0, det_score=0.99)
    b = add_face("ali", 1, det_score=0.8)
    clustering.cluster_unassigned()
    original_cluster = cluster_of(a)

    clustering.unassign_faces([a])

    cover = db.get_db().execute(
        "SELECT cover_face_id FROM clusters WHERE id=?", (original_cluster,)).fetchone()
    assert cover["cover_face_id"] == b


def test_centroid_uses_all_faces_of_a_cluster():
    """The centroid has to be the cluster mean, not a single face."""
    ids = [add_face("ali", v) for v in range(3)]
    clustering.cluster_unassigned()
    centroids, cluster_ids = clustering._cluster_centroids(db.get_db())

    assert cluster_ids == [cluster_of(ids[0])]
    assert np.isclose(np.linalg.norm(centroids[0]), 1.0, atol=1e-5)
