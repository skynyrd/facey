"""Schema, settings and referential integrity."""
import sqlite3

import numpy as np
import pytest

import db


def table_names(conn) -> set[str]:
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def test_schema_creates_all_tables():
    conn = db.get_db()
    assert {"library", "media_files", "faces", "clusters",
            "groups", "group_members", "settings"} <= table_names(conn)


def test_defaults_are_seeded():
    for key, value in db.DEFAULT_SETTINGS.items():
        assert db.get_setting(key) == value


def test_setting_survives_reconnect():
    db.set_setting("assign_threshold", "0.7")
    db.close_connection()
    assert db.get_setting("assign_threshold") == "0.7"


def test_reseeding_does_not_overwrite_user_settings():
    db.set_setting("min_face_px", "12")
    db.close_connection()
    db.get_db()  # schema + INSERT OR IGNORE run again
    assert db.get_setting("min_face_px") == "12"


def test_get_library_returns_most_recent():
    conn = db.get_db()
    conn.execute("INSERT INTO library(root_path) VALUES ('/a')")
    conn.execute("INSERT INTO library(root_path) VALUES ('/b')")
    conn.commit()
    assert db.get_library()["root_path"] == "/b"


def test_get_library_none_when_empty():
    assert db.get_library() is None


def test_deleting_file_cascades_to_faces():
    conn = db.get_db()
    lib = conn.execute("INSERT INTO library(root_path) VALUES ('/x')").lastrowid
    fid = conn.execute(
        "INSERT INTO media_files(library_id, rel_path, size, mtime) VALUES (?,?,?,?)",
        (lib, "a.jpg", 1, 1.0)).lastrowid
    conn.execute("INSERT INTO faces(file_id) VALUES (?)", (fid,))
    conn.commit()

    conn.execute("DELETE FROM media_files WHERE id=?", (fid,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM faces").fetchone()["c"] == 0


def test_deleting_cluster_nulls_face_reference():
    """Deleting a cluster keeps its faces and only drops the link."""
    conn = db.get_db()
    lib = conn.execute("INSERT INTO library(root_path) VALUES ('/x')").lastrowid
    fid = conn.execute(
        "INSERT INTO media_files(library_id, rel_path, size, mtime) VALUES (?,?,?,?)",
        (lib, "a.jpg", 1, 1.0)).lastrowid
    cid = conn.execute("INSERT INTO clusters DEFAULT VALUES").lastrowid
    conn.execute("INSERT INTO faces(file_id, cluster_id) VALUES (?,?)", (fid, cid))
    conn.commit()

    conn.execute("DELETE FROM clusters WHERE id=?", (cid,))
    conn.commit()
    row = conn.execute("SELECT cluster_id FROM faces").fetchone()
    assert row is not None and row["cluster_id"] is None


def test_deleting_group_cascades_to_members():
    conn = db.get_db()
    cid = conn.execute("INSERT INTO clusters DEFAULT VALUES").lastrowid
    gid = conn.execute("INSERT INTO groups(name) VALUES ('Family X')").lastrowid
    conn.execute("INSERT INTO group_members(group_id, cluster_id) VALUES (?,?)", (gid, cid))
    conn.commit()

    conn.execute("DELETE FROM groups WHERE id=?", (gid,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM group_members").fetchone()["c"] == 0


def test_same_path_cannot_be_indexed_twice():
    conn = db.get_db()
    lib = conn.execute("INSERT INTO library(root_path) VALUES ('/x')").lastrowid
    conn.execute(
        "INSERT INTO media_files(library_id, rel_path, size, mtime) VALUES (?,?,?,?)",
        (lib, "a.jpg", 1, 1.0))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO media_files(library_id, rel_path, size, mtime) VALUES (?,?,?,?)",
            (lib, "a.jpg", 2, 2.0))


def test_embedding_roundtrips_as_float32():
    conn = db.get_db()
    lib = conn.execute("INSERT INTO library(root_path) VALUES ('/x')").lastrowid
    fid = conn.execute(
        "INSERT INTO media_files(library_id, rel_path, size, mtime) VALUES (?,?,?,?)",
        (lib, "a.jpg", 1, 1.0)).lastrowid
    vec = np.random.default_rng(0).normal(size=512).astype(np.float32)
    conn.execute("INSERT INTO faces(file_id, embedding) VALUES (?,?)", (fid, vec.tobytes()))
    conn.commit()

    blob = conn.execute("SELECT embedding FROM faces").fetchone()["embedding"]
    restored = np.frombuffer(blob, dtype=np.float32)
    assert restored.shape == (512,)
    np.testing.assert_array_equal(restored, vec)


def test_data_dir_is_isolated_per_directory(tmp_path):
    db.get_db().execute("INSERT INTO library(root_path) VALUES ('/first')")
    db.get_db().commit()

    db.use_data_dir(tmp_path / "other")
    assert db.get_library() is None
    assert (tmp_path / "other" / "facey.db").exists()
    assert (tmp_path / "other" / "face_thumbs").is_dir()
    assert (tmp_path / "other" / "photo_thumbs").is_dir()


def test_unknown_setting_falls_back_to_default():
    db.get_db().execute("DELETE FROM settings WHERE key='min_face_px'")
    db.get_db().commit()
    assert db.get_setting("min_face_px") == db.DEFAULT_SETTINGS["min_face_px"]
