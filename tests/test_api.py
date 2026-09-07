"""The HTTP layer: routing, validation, status codes."""
import db
from conftest import wait_export, wait_scan, write_photo


def cluster_for(client, rel_path: str) -> int:
    return db.get_db().execute(
        "SELECT f.cluster_id c FROM faces f JOIN media_files m ON m.id = f.file_id"
        " WHERE m.rel_path = ?", (rel_path,)).fetchone()["c"]


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_library_is_empty_before_any_scan(client):
    assert client.get("/api/library").json() == {"root_path": None}


def test_scanning_through_the_api(client, photo_root, fake_faces):
    assert client.post("/api/library", json={"root_path": str(photo_root)}).status_code == 200
    wait_scan()

    assert client.get("/api/library").json() == {"root_path": str(photo_root)}
    status = client.get("/api/scan/status").json()
    assert status["total"] == 5 and status["done"] == 5 and status["faces"] == 5


def test_scanning_a_missing_folder_returns_400(client, tmp_path):
    res = client.post("/api/library", json={"root_path": str(tmp_path / "missing")})
    assert res.status_code == 400 and "bulunamadı" in res.json()["detail"]


def test_scan_status_before_any_library(client):
    status = client.get("/api/scan/status").json()
    assert status["root_path"] is None and status["total"] == 0
    assert status["running"] is False


def test_resume_without_library_returns_400(client):
    assert client.post("/api/scan/resume").status_code == 400


def test_pause_is_always_accepted(client):
    assert client.post("/api/scan/pause").status_code == 200


def test_scan_errors_are_listed(client, photo_root, fake_faces):
    fake_faces.fail_on = {"veli.jpg"}
    client.post("/api/library", json={"root_path": str(photo_root)})
    wait_scan()

    errors = client.get("/api/scan/errors").json()
    assert [e["rel_path"] for e in errors] == ["home/veli.jpg"]
    assert "corrupt file" in errors[0]["error"]


# ---------- clusters ----------

def test_clusters_are_listed_largest_first(client, scanned):
    clusters = client.get("/api/clusters").json()
    assert [c["face_count"] for c in clusters] == [2, 2, 1]
    assert all(c["cover_face_id"] for c in clusters)
    assert clusters[0]["photo_count"] == 2


def test_hidden_clusters_are_filtered_by_default(client, scanned):
    target = client.get("/api/clusters").json()[0]["id"]
    client.post(f"/api/clusters/{target}", json={"hidden": True})

    visible = client.get("/api/clusters").json()
    assert target not in [c["id"] for c in visible]

    everything = client.get("/api/clusters?include_hidden=true").json()
    assert target in [c["id"] for c in everything]


def test_renaming_a_cluster(client, scanned):
    target = client.get("/api/clusters").json()[0]["id"]
    client.post(f"/api/clusters/{target}", json={"name": "  Person A  "})

    named = {c["id"]: c["name"] for c in client.get("/api/clusters").json()}
    assert named[target] == "Person A"


def test_blank_name_clears_it(client, scanned):
    target = client.get("/api/clusters").json()[0]["id"]
    client.post(f"/api/clusters/{target}", json={"name": "Ali"})
    client.post(f"/api/clusters/{target}", json={"name": "   "})

    named = {c["id"]: c["name"] for c in client.get("/api/clusters").json()}
    assert named[target] is None


def test_cluster_faces_include_their_photo(client, scanned):
    target = cluster_for(client, "trip/ali.jpg")
    faces = client.get(f"/api/clusters/{target}/faces").json()

    assert {f["rel_path"] for f in faces} == {"trip/ali.jpg", "trip/ali_veli.jpg"}
    assert all(f["file_id"] and f["det_score"] for f in faces)


def test_merging_through_the_api(client, scanned):
    ali, veli = cluster_for(client, "trip/ali.jpg"), cluster_for(client, "home/veli.jpg")
    res = client.post("/api/clusters/merge", json={"target_id": ali, "source_ids": [veli]})

    assert res.status_code == 200
    ids = [c["id"] for c in client.get("/api/clusters").json()]
    assert veli not in ids and ali in ids
    assert len(client.get(f"/api/clusters/{ali}/faces").json()) == 4


def test_unassigning_a_face(client, scanned):
    ali = cluster_for(client, "trip/ali.jpg")
    face_id = client.get(f"/api/clusters/{ali}/faces").json()[0]["id"]

    client.post("/api/faces/unassign", json={"face_ids": [face_id]})

    assert face_id not in [f["id"] for f in client.get(f"/api/clusters/{ali}/faces").json()]
    assert len(client.get("/api/clusters").json()) == 4


def test_recluster_reports_what_it_did(client, scanned):
    assert client.post("/api/recluster").json() == {"assigned": 0, "new_clusters": 0}


# ---------- images ----------

def test_face_thumbnail_is_served(client, scanned):
    face_id = client.get("/api/clusters").json()[0]["cover_face_id"]
    res = client.get(f"/api/face-thumb/{face_id}")
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"


def test_missing_face_thumbnail_returns_404(client, scanned):
    assert client.get("/api/face-thumb/9999").status_code == 404


def test_face_thumbnail_404_when_file_vanished(client, scanned):
    face_id = client.get("/api/clusters").json()[0]["cover_face_id"]
    name = db.get_db().execute(
        "SELECT thumb_name FROM faces WHERE id=?", (face_id,)).fetchone()["thumb_name"]
    (db.FACE_THUMBS_DIR / name).unlink()

    assert client.get(f"/api/face-thumb/{face_id}").status_code == 404


def test_photo_preview_is_served(client, scanned):
    file_id = db.get_db().execute(
        "SELECT id FROM media_files WHERE rel_path='trip/ali.jpg'").fetchone()["id"]
    res = client.get(f"/api/thumb/{file_id}")
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"


def test_missing_photo_preview_returns_404(client, scanned):
    assert client.get("/api/thumb/9999").status_code == 404


# ---------- groups ----------

def test_group_lifecycle(client, scanned):
    ali, veli = cluster_for(client, "trip/ali.jpg"), cluster_for(client, "home/veli.jpg")
    gid = client.post("/api/groups", json={"name": "Family X",
                                           "cluster_ids": [ali, veli]}).json()["id"]

    groups = client.get("/api/groups").json()
    assert len(groups) == 1
    assert groups[0]["name"] == "Family X" and groups[0]["id"] == gid
    assert sorted(groups[0]["cluster_ids"]) == sorted([ali, veli])

    client.delete(f"/api/groups/{gid}")
    assert client.get("/api/groups").json() == []


def test_saving_a_group_twice_replaces_its_members(client, scanned):
    ali, veli = cluster_for(client, "trip/ali.jpg"), cluster_for(client, "home/veli.jpg")
    client.post("/api/groups", json={"name": "Family X", "cluster_ids": [ali, veli]})
    client.post("/api/groups", json={"name": "Family X", "cluster_ids": [ali]})

    groups = client.get("/api/groups").json()
    assert len(groups) == 1 and groups[0]["cluster_ids"] == [ali]


def test_group_needs_a_name_and_members(client, scanned):
    assert client.post("/api/groups", json={"name": " ", "cluster_ids": [1]}).status_code == 400
    assert client.post(
        "/api/groups", json={"name": "Family X", "cluster_ids": []}).status_code == 400


def test_deleting_a_group_keeps_the_clusters(client, scanned):
    ali = cluster_for(client, "trip/ali.jpg")
    gid = client.post(
        "/api/groups", json={"name": "Family X", "cluster_ids": [ali]}).json()["id"]
    client.delete(f"/api/groups/{gid}")

    assert ali in [c["id"] for c in client.get("/api/clusters").json()]


# ---------- export ----------

def test_export_preview_lists_matching_photos(client, scanned):
    ali = cluster_for(client, "trip/ali.jpg")
    preview = client.get(f"/api/export/preview?cluster_ids={ali}").json()

    assert preview["count"] == 2
    assert {f["rel_path"] for f in preview["files"]} == {"trip/ali.jpg", "trip/ali_veli.jpg"}


def test_export_preview_rejects_garbage(client, scanned):
    assert client.get("/api/export/preview?cluster_ids=abc").status_code == 400


def test_export_preview_tolerates_trailing_commas(client, scanned):
    ali = cluster_for(client, "trip/ali.jpg")
    assert client.get(f"/api/export/preview?cluster_ids={ali},").json()["count"] == 2


def test_export_through_the_api(client, scanned, tmp_path):
    ali = cluster_for(client, "trip/ali.jpg")
    dest = tmp_path / "out"

    assert client.post("/api/export", json={
        "cluster_ids": [ali], "dest_path": str(dest), "mode": "copy"}).status_code == 200
    wait_export()

    status = client.get("/api/export/status").json()
    assert status["copied"] == 2 and status["phase"] == "done"
    assert (dest / "trip/ali.jpg").exists()


def test_export_requires_a_selection(client, scanned, tmp_path):
    res = client.post("/api/export", json={"cluster_ids": [], "dest_path": str(tmp_path)})
    assert res.status_code == 400


def test_export_into_the_library_is_rejected(client, scanned):
    ali = cluster_for(client, "trip/ali.jpg")
    res = client.post("/api/export", json={
        "cluster_ids": [ali], "dest_path": str(scanned / "inside")})
    assert res.status_code == 400 and "içinde olamaz" in res.json()["detail"]


def test_export_status_is_idle_before_any_run(client):
    assert client.get("/api/export/status").json()["phase"] == "idle"


# ---------- settings and maintenance ----------

def test_settings_roundtrip(client):
    assert client.get("/api/settings").json() == db.DEFAULT_SETTINGS

    client.post("/api/settings", json={"values": {"assign_threshold": "0.6"}})
    assert client.get("/api/settings").json()["assign_threshold"] == "0.6"


def test_unknown_setting_is_rejected(client):
    res = client.post("/api/settings", json={"values": {"kahve": "1"}})
    assert res.status_code == 400


def test_non_numeric_setting_is_rejected(client):
    res = client.post("/api/settings", json={"values": {"assign_threshold": "yüksek"}})
    assert res.status_code == 400
    assert client.get("/api/settings").json()["assign_threshold"] == "0.45"


def test_a_bad_value_does_not_partially_apply_the_batch(client):
    """If one value in a batch is invalid, none of them may be written."""
    client.post("/api/settings", json={
        "values": {"min_face_px": "10", "assign_threshold": "elma"}})

    assert client.get("/api/settings").json()["min_face_px"] == "40"


def test_clearing_the_preview_cache(client, scanned):
    file_id = db.get_db().execute(
        "SELECT id FROM media_files WHERE rel_path='trip/ali.jpg'").fetchone()["id"]
    client.get(f"/api/thumb/{file_id}")
    assert list(db.PHOTO_THUMBS_DIR.glob("*.jpg"))

    assert client.post("/api/cache/clear").json()["removed"] >= 1

    assert not list(db.PHOTO_THUMBS_DIR.glob("*.jpg"))
    assert list(db.FACE_THUMBS_DIR.glob("*.jpg"))  # face crops survive, no rescan needed


def test_api_routes_are_not_shadowed_by_the_static_mount(client):
    """dist/ is served from the root, but it must not shadow the /api routes."""
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/clusters").status_code == 200


def test_resume_restarts_a_partial_scan(client, scanned, fake_faces):
    conn = db.get_db()
    conn.execute("UPDATE media_files SET status='pending' WHERE rel_path='home/veli.jpg'")
    conn.commit()

    assert client.post("/api/scan/resume").status_code == 200
    wait_scan()
    assert client.get("/api/scan/status").json()["pending"] == 0


def test_unreadable_photo_preview_returns_500(client, scanned):
    """A corrupt file must not quietly turn into an empty image."""
    file_id = db.get_db().execute(
        "SELECT id FROM media_files WHERE rel_path='trip/ali.jpg'").fetchone()["id"]
    (scanned / "trip/ali.jpg").write_bytes(b"not a jpeg")

    assert client.get(f"/api/thumb/{file_id}").status_code == 500
