"""Folder scanning: discovery, incremental rescans, error tolerance, library resets."""
import os

import pytest

import db
import scanner
from conftest import wait_scan, write_photo


def files_in_db() -> dict[str, dict]:
    return {r["rel_path"]: dict(r) for r in db.get_db().execute(
        "SELECT rel_path, type, status, face_count FROM media_files")}


def face_count() -> int:
    return db.get_db().execute("SELECT COUNT(*) c FROM faces").fetchone()["c"]


def test_scan_indexes_nested_photos(scanned):
    indexed = files_in_db()
    assert set(indexed) == {
        "trip/ali.jpg", "trip/ali_veli.jpg",
        "home/veli.jpg", "home/nested/ayse.jpg", "misc/noface.png",
    }
    assert all(f["status"] == "done" for f in indexed.values())


def test_face_counts_match_photo_contents(scanned):
    indexed = files_in_db()
    assert indexed["trip/ali_veli.jpg"]["face_count"] == 2
    assert indexed["trip/ali.jpg"]["face_count"] == 1
    assert indexed["misc/noface.png"]["face_count"] == 0
    assert face_count() == 5


def test_scan_groups_people_across_folders(scanned):
    """ali is in trip/ali.jpg and in ali_veli.jpg; both faces land in one cluster."""
    rows = db.get_db().execute("""
        SELECT c.id, COUNT(*) n FROM clusters c
        JOIN faces f ON f.cluster_id = c.id GROUP BY c.id ORDER BY n DESC""").fetchall()
    assert [r["n"] for r in rows] == [2, 2, 1]  # ali, veli, ayse


def test_hidden_files_and_folders_are_skipped(photo_root, fake_faces):
    write_photo(photo_root / ".hidden/secret.jpg")
    write_photo(photo_root / "trip/.ali.jpg")
    scanner.start_scan(str(photo_root))
    wait_scan()
    assert not any(p.startswith(".") or "/." in p for p in files_in_db())


def test_unsupported_extensions_are_ignored(photo_root, fake_faces):
    (photo_root / "notes.txt").write_text("hello")
    (photo_root / "archive.zip").write_bytes(b"PK")
    scanner.start_scan(str(photo_root))
    wait_scan()
    assert "notes.txt" not in files_in_db()
    assert "archive.zip" not in files_in_db()


def test_videos_are_recorded_but_not_processed(photo_root, fake_faces):
    """Groundwork for phase 2: videos are indexed but never sent to extraction."""
    (photo_root / "trip/clip.mov").write_bytes(b"fake movie")
    scanner.start_scan(str(photo_root))
    status = wait_scan()

    row = files_in_db()["trip/clip.mov"]
    assert row["type"] == "video" and row["status"] == "pending"
    assert not any(c.name == "clip.mov" for c in fake_faces.calls)
    assert status["total"] == 5  # the counters only cover photos


def test_rescan_skips_unchanged_files(scanned, fake_faces):
    first_pass = len(fake_faces.calls)
    scanner.start_scan(str(scanned))
    wait_scan()
    assert len(fake_faces.calls) == first_pass  # nothing was reprocessed


def test_rescan_processes_only_new_files(scanned, fake_faces):
    fake_faces.calls.clear()
    write_photo(scanned / "home/zeynep.jpg")

    scanner.start_scan(str(scanned))
    wait_scan()

    assert [c.name for c in fake_faces.calls] == ["zeynep.jpg"]
    assert "home/zeynep.jpg" in files_in_db()


def test_modified_file_is_reprocessed_without_duplicating_faces(scanned, fake_faces):
    target = scanned / "trip/ali.jpg"
    write_photo(target, size=(200, 150), color=(10, 20, 30))
    os.utime(target, (1_600_000_000, 1_600_000_000))
    before = face_count()

    fake_faces.calls.clear()
    scanner.start_scan(str(scanned))
    wait_scan()

    assert [c.name for c in fake_faces.calls] == ["ali.jpg"]
    assert face_count() == before  # old faces removed, new ones written
    assert files_in_db()["trip/ali.jpg"]["face_count"] == 1


def test_deleted_file_is_removed_with_its_faces(scanned, fake_faces):
    (scanned / "trip/ali_veli.jpg").unlink()

    scanner.start_scan(str(scanned))
    wait_scan()

    assert "trip/ali_veli.jpg" not in files_in_db()
    assert face_count() == 3


def test_unreadable_file_is_recorded_and_scan_continues(photo_root, fake_faces):
    fake_faces.fail_on = {"veli.jpg"}

    scanner.start_scan(str(photo_root))
    status = wait_scan()

    assert status["phase"] == "done" and status["errors"] == 1
    row = db.get_db().execute(
        "SELECT status, error FROM media_files WHERE rel_path='home/veli.jpg'").fetchone()
    assert row["status"] == "error" and "corrupt file" in row["error"]
    assert files_in_db()["trip/ali.jpg"]["status"] == "done"  # the rest still completed


def test_low_quality_faces_are_flagged(photo_root, fake_faces):
    fake_faces.det_score = 0.3  # min_det_score defaults to 0.60
    scanner.start_scan(str(photo_root))
    wait_scan()

    qualities = {r["quality"] for r in db.get_db().execute("SELECT quality FROM faces")}
    assert qualities == {"low"}
    assert db.get_db().execute("SELECT COUNT(*) c FROM clusters").fetchone()["c"] == 0


def test_tiny_faces_are_flagged(photo_root, fake_faces):
    fake_faces.face_px = 10.0  # min_face_px defaults to 40
    scanner.start_scan(str(photo_root))
    wait_scan()
    assert {r["quality"] for r in db.get_db().execute("SELECT quality FROM faces")} == {"low"}


def test_switching_library_clears_previous_data(scanned, fake_faces, tmp_path):
    db.get_db().execute("UPDATE clusters SET name='Ali' WHERE id=1")
    db.get_db().commit()

    other = tmp_path / "other_archive"
    write_photo(other / "kemal.jpg")
    scanner.start_scan(str(other))
    wait_scan()

    assert set(files_in_db()) == {"kemal.jpg"}
    assert face_count() == 1
    assert db.get_db().execute(
        "SELECT COUNT(*) c FROM clusters WHERE name='Ali'").fetchone()["c"] == 0
    assert db.get_library()["root_path"] == str(other)


def test_switching_library_discards_stale_thumbnails(scanned, tmp_path, fake_faces):
    """Ids restart at 1 in a new library, so a leftover preview would show the
    wrong photo."""
    import thumbs
    thumbs.get_photo_thumb(1)
    stale = (db.PHOTO_THUMBS_DIR / "1.jpg").read_bytes()
    assert list(db.FACE_THUMBS_DIR.glob("*.jpg"))

    other = tmp_path / "other_archive"
    write_photo(other / "kemal.jpg", size=(300, 200), color=(0, 0, 255))
    scanner.start_scan(str(other))
    wait_scan()

    cached = db.PHOTO_THUMBS_DIR / "1.jpg"
    assert not cached.exists() or cached.read_bytes() != stale


def test_rescanning_same_library_preserves_manual_edits(scanned, fake_faces):
    conn = db.get_db()
    conn.execute("UPDATE clusters SET name='Ali' WHERE id=1")
    conn.commit()

    scanner.start_scan(str(scanned))
    wait_scan()

    assert conn.execute(
        "SELECT COUNT(*) c FROM clusters WHERE name='Ali'").fetchone()["c"] == 1


def test_status_reports_progress_and_root(scanned):
    status = scanner.get_status()
    assert status["root_path"] == str(scanned)
    assert status["total"] == 5 and status["done"] == 5
    assert status["pending"] == 0 and status["errors"] == 0
    assert status["faces"] == 5
    assert status["running"] is False and status["current"] is None


def test_scanning_missing_folder_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        scanner.start_scan(str(tmp_path / "missing"))


def test_scanning_a_file_instead_of_folder_is_rejected(tmp_path):
    target = tmp_path / "a.jpg"
    write_photo(target)
    with pytest.raises(ValueError):
        scanner.start_scan(str(target))


def test_resume_without_library_is_rejected():
    with pytest.raises(RuntimeError):
        scanner.resume()


def test_resume_finishes_a_partially_scanned_library(scanned, fake_faces):
    """A half-finished scan, e.g. after the app was closed, picks up where it stopped."""
    conn = db.get_db()
    conn.execute("UPDATE media_files SET status='pending' WHERE rel_path='home/veli.jpg'")
    conn.execute("DELETE FROM faces WHERE file_id IN "
                 "(SELECT id FROM media_files WHERE rel_path='home/veli.jpg')")
    conn.commit()
    fake_faces.calls.clear()

    scanner.resume()
    status = wait_scan()

    assert [c.name for c in fake_faces.calls] == ["veli.jpg"]
    assert status["pending"] == 0


def test_pause_stops_the_worker_and_resume_continues(photo_root, fake_faces, monkeypatch):
    import threading
    started = threading.Event()
    release = threading.Event()
    original = fake_faces.__call__

    def slow(path, file_id):
        started.set()
        release.wait(5)
        return original(path, file_id)

    monkeypatch.setattr("faces.extract_faces", slow)
    scanner.start_scan(str(photo_root))
    assert started.wait(5)
    scanner.pause()
    release.set()

    assert scanner.get_status()["paused"] is True
    scanner.resume()
    wait_scan()
    assert scanner.get_status()["pending"] == 0


def test_modified_photo_drops_its_stale_preview(scanned, fake_faces):
    """When a photo changes, its cached preview has to be regenerated too."""
    import thumbs
    conn = db.get_db()
    file_id = conn.execute(
        "SELECT id FROM media_files WHERE rel_path='trip/ali.jpg'").fetchone()["id"]
    thumbs.get_photo_thumb(file_id)
    stale = (db.PHOTO_THUMBS_DIR / f"{file_id}.jpg").read_bytes()

    target = scanned / "trip/ali.jpg"
    write_photo(target, size=(300, 200), color=(0, 0, 255))
    os.utime(target, (1_600_000_000, 1_600_000_000))
    scanner.start_scan(str(scanned))
    wait_scan()

    assert thumbs.get_photo_thumb(file_id).read_bytes() != stale


def test_second_scan_is_rejected_while_one_is_running(photo_root, fake_faces, monkeypatch):
    import threading
    started, release = threading.Event(), threading.Event()

    def slow(path, file_id):
        started.set()
        release.wait(5)
        return 10, 10, []

    monkeypatch.setattr("faces.extract_faces", slow)
    scanner.start_scan(str(photo_root))
    assert started.wait(5)
    try:
        with pytest.raises(RuntimeError, match="zaten sürüyor"):
            scanner.start_scan(str(photo_root))
    finally:
        release.set()
    wait_scan()


def test_worker_crash_is_surfaced_in_the_status(photo_root, fake_faces, monkeypatch):
    def boom():
        raise OSError("disk read failed")

    monkeypatch.setattr(scanner, "_enumerate", boom)
    scanner.start_scan(str(photo_root))
    status = wait_scan()

    assert status["phase"] == "error" and "disk read failed" in status["error"]
