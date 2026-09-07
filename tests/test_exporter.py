"""Export: the matching query, copy safety, name collisions, move mode."""
import os

import pytest

import db
import exporter
from conftest import wait_export, write_photo


def snapshot(root) -> dict[str, tuple[int, bytes]]:
    """Size and content fingerprint, used to prove the source was untouched."""
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.read_bytes())
        for p in sorted(root.rglob("*")) if p.is_file()
    }


ALI = "trip/ali.jpg"       # photo with only ali in it
VELI = "home/veli.jpg"     # photo with only veli in it


def cluster_for(rel_path: str) -> int:
    """Finds a person's cluster id through a photo they appear in alone."""
    return db.get_db().execute(
        "SELECT f.cluster_id c FROM faces f JOIN media_files m ON m.id = f.file_id"
        " WHERE m.rel_path = ?", (rel_path,)).fetchone()["c"]


def all_cluster_ids() -> list[int]:
    return [r["id"] for r in db.get_db().execute("SELECT id FROM clusters ORDER BY id")]


def exported(dest) -> set[str]:
    return {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()}


# ---------- matching query ----------

def test_matching_files_returns_photos_containing_the_person(scanned):
    paths = [r["rel_path"] for r in exporter.matching_files([cluster_for(ALI)])]
    assert paths == ["trip/ali.jpg", "trip/ali_veli.jpg"]


def test_matching_files_unions_selected_people(scanned):
    paths = {r["rel_path"] for r in exporter.matching_files(
        [cluster_for(ALI), cluster_for(VELI)])}
    assert paths == {"trip/ali.jpg", "trip/ali_veli.jpg", "home/veli.jpg"}


def test_shared_photo_is_listed_once(scanned):
    """A photo holding both selected people is still listed once."""
    paths = [r["rel_path"] for r in exporter.matching_files(
        [cluster_for(ALI), cluster_for(VELI)])]
    assert paths.count("trip/ali_veli.jpg") == 1


def test_no_selection_matches_nothing(scanned):
    assert exporter.matching_files([]) == []


def test_unprocessed_files_are_not_exported(scanned):
    """Files that failed or are still pending are not exported."""
    conn = db.get_db()
    conn.execute("UPDATE media_files SET status='error' WHERE rel_path='trip/ali.jpg'")
    conn.commit()
    paths = [r["rel_path"] for r in exporter.matching_files([cluster_for(ALI)])]
    assert paths == ["trip/ali_veli.jpg"]


# ---------- copying ----------

def test_copy_preserves_folder_structure(scanned, tmp_path):
    dest = tmp_path / "out"
    exporter.start_export([cluster_for(ALI)], str(dest))
    status = wait_export()

    assert exported(dest) == {"trip/ali.jpg", "trip/ali_veli.jpg"}
    assert (status["copied"], status["skipped"], status["errors"]) == (2, 0, 0)
    assert status["phase"] == "done"


def test_copy_leaves_the_source_archive_untouched(scanned, tmp_path):
    before = snapshot(scanned)
    exporter.start_export(all_cluster_ids(), str(tmp_path / "out"))
    wait_export()
    assert snapshot(scanned) == before


def test_copy_preserves_file_metadata(scanned, tmp_path):
    src = scanned / "trip/ali.jpg"
    os.utime(src, (1_600_000_000, 1_600_000_000))
    dest = tmp_path / "out"

    exporter.start_export([cluster_for(ALI)], str(dest))
    wait_export()

    copied = dest / "trip/ali.jpg"
    assert copied.read_bytes() == src.read_bytes()
    assert copied.stat().st_mtime == pytest.approx(src.stat().st_mtime, abs=1)


def test_rerunning_an_export_copies_nothing_new(scanned, tmp_path):
    dest = tmp_path / "out"
    ali = [cluster_for(ALI)]
    exporter.start_export(ali, str(dest))
    wait_export()

    exporter.start_export(ali, str(dest))
    status = wait_export()

    assert (status["copied"], status["skipped"]) == (0, 2)
    assert exported(dest) == {"trip/ali.jpg", "trip/ali_veli.jpg"}


def test_different_file_with_same_name_is_kept_side_by_side(scanned, tmp_path):
    """A different file already at the destination is never overwritten."""
    dest = tmp_path / "out"
    existing = dest / "trip/ali.jpg"
    write_photo(existing, size=(500, 500), color=(1, 2, 3))
    original = existing.read_bytes()

    exporter.start_export([cluster_for(ALI)], str(dest))
    status = wait_export()

    assert existing.read_bytes() == original          # untouched
    assert (dest / "trip/ali-1.jpg").exists()         # new file placed beside it
    assert status["copied"] == 2 and status["errors"] == 0


def test_missing_source_is_reported_without_stopping_the_run(scanned, tmp_path):
    (scanned / "trip/ali.jpg").unlink()  # still in the DB, gone from disk
    dest = tmp_path / "out"

    exporter.start_export([cluster_for(ALI)], str(dest))
    status = wait_export()

    assert status["errors"] == 1 and status["copied"] == 1
    assert status["error_files"][0]["path"] == "trip/ali.jpg"
    assert exported(dest) == {"trip/ali_veli.jpg"}


def test_export_creates_missing_destination(scanned, tmp_path):
    dest = tmp_path / "deep" / "new" / "out"
    exporter.start_export([cluster_for(ALI)], str(dest))
    wait_export()
    assert dest.is_dir() and exported(dest)


# ---------- move ----------

def test_move_removes_the_originals(scanned, tmp_path):
    dest = tmp_path / "out"
    exporter.start_export([cluster_for(ALI)], str(dest), mode="move")
    status = wait_export()

    assert status["copied"] == 2 and status["errors"] == 0
    assert not (scanned / "trip/ali.jpg").exists()
    assert not (scanned / "trip/ali_veli.jpg").exists()
    assert (scanned / "home/veli.jpg").exists()  # unselected photos stay put
    assert exported(dest) == {"trip/ali.jpg", "trip/ali_veli.jpg"}


def test_move_keeps_the_original_when_the_copy_fails(scanned, tmp_path, monkeypatch):
    """If verification fails the source has to survive: no data loss."""
    import shutil

    def truncated_copy(src, dst, *a, **kw):
        open(dst, "wb").close()  # truncated copy
        return dst

    monkeypatch.setattr(shutil, "copy2", truncated_copy)
    exporter.start_export([cluster_for(ALI)], str(tmp_path / "out"), mode="move")
    status = wait_export()

    assert status["errors"] == 2 and status["copied"] == 0
    assert (scanned / "trip/ali.jpg").exists()
    assert not (tmp_path / "out" / "trip/ali.jpg").exists()  # the bad copy was cleaned up


# ---------- validation and safety ----------

def test_destination_inside_the_library_is_rejected(scanned):
    with pytest.raises(ValueError):
        exporter.start_export([1], str(scanned / "export_here"))


def test_destination_equal_to_the_library_is_rejected(scanned):
    with pytest.raises(ValueError):
        exporter.start_export([1], str(scanned))


def test_unknown_mode_is_rejected(scanned, tmp_path):
    with pytest.raises(ValueError):
        exporter.start_export([1], str(tmp_path / "out"), mode="delete")


def test_export_without_a_library_is_rejected(tmp_path):
    with pytest.raises(RuntimeError):
        exporter.start_export([1], str(tmp_path / "out"))


def test_rejected_export_does_not_create_the_destination(scanned, tmp_path):
    dest = tmp_path / "out"
    with pytest.raises(ValueError):
        exporter.start_export([1], str(dest), mode="delete")
    assert not dest.exists()


def test_status_is_a_copy_not_the_live_state(scanned, tmp_path):
    exporter.start_export([cluster_for(ALI)], str(tmp_path / "out"))
    wait_export()
    status = exporter.get_status()
    status["copied"] = 999
    assert exporter.get_status()["copied"] != 999


def test_second_export_is_rejected_while_one_is_running(scanned, tmp_path, monkeypatch):
    import shutil
    import threading
    started, release = threading.Event(), threading.Event()
    real_copy = shutil.copy2

    def slow_copy(src, dst, *a, **kw):
        started.set()
        release.wait(5)
        return real_copy(src, dst, *a, **kw)

    monkeypatch.setattr(shutil, "copy2", slow_copy)
    exporter.start_export([cluster_for(ALI)], str(tmp_path / "out"))
    assert started.wait(5)
    try:
        with pytest.raises(RuntimeError, match="zaten sürüyor"):
            exporter.start_export([cluster_for(ALI)], str(tmp_path / "out2"))
    finally:
        release.set()
    wait_export()


def test_collision_suffixes_increment(tmp_path):
    target = tmp_path / "foto.jpg"
    write_photo(target)
    assert exporter._unique_target(target).name == "foto-1.jpg"

    write_photo(tmp_path / "foto-1.jpg")
    assert exporter._unique_target(target).name == "foto-2.jpg"
