"""Preview generation and image loading (EXIF orientation, HEIC)."""
import pytest
from PIL import Image

import db
import faces as faces_mod
import thumbs
from conftest import write_photo


def test_preview_is_generated_and_cached(scanned):
    file_id = db.get_db().execute(
        "SELECT id FROM media_files WHERE rel_path='trip/ali.jpg'").fetchone()["id"]

    path = thumbs.get_photo_thumb(file_id)

    assert path == db.PHOTO_THUMBS_DIR / f"{file_id}.jpg"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "JPEG"


def test_cached_preview_is_reused(scanned):
    file_id = db.get_db().execute(
        "SELECT id FROM media_files WHERE rel_path='trip/ali.jpg'").fetchone()["id"]
    thumbs.get_photo_thumb(file_id)

    sentinel = b"served from cache"
    (db.PHOTO_THUMBS_DIR / f"{file_id}.jpg").write_bytes(sentinel)

    assert thumbs.get_photo_thumb(file_id).read_bytes() == sentinel


def test_preview_is_downscaled(scanned, tmp_path):
    """A large photo must not exceed PREVIEW_EDGE once previewed."""
    big = scanned / "trip/ali.jpg"
    write_photo(big, size=(2000, 1200))
    conn = db.get_db()
    file_id = conn.execute(
        "SELECT id FROM media_files WHERE rel_path='trip/ali.jpg'").fetchone()["id"]

    with Image.open(thumbs.get_photo_thumb(file_id)) as img:
        assert max(img.size) == thumbs.PREVIEW_EDGE
        assert img.size == (thumbs.PREVIEW_EDGE, round(thumbs.PREVIEW_EDGE * 1200 / 2000))


def test_small_photo_is_not_upscaled(scanned):
    file_id = db.get_db().execute(
        "SELECT id FROM media_files WHERE rel_path='trip/ali.jpg'").fetchone()["id"]
    with Image.open(thumbs.get_photo_thumb(file_id)) as img:
        assert img.size == (120, 90)


def test_unknown_file_id_raises(scanned):
    with pytest.raises(FileNotFoundError):
        thumbs.get_photo_thumb(9999)


def test_preview_without_a_library_raises():
    with pytest.raises(FileNotFoundError):
        thumbs.get_photo_thumb(1)


# ---------- image loading ----------

def test_exif_rotation_is_applied(tmp_path):
    """iPhone photos carry a rotation tag; faces must not come out sideways."""
    path = tmp_path / "rotated.jpg"
    img = Image.new("RGB", (100, 50), (10, 20, 30))
    exif = img.getexif()
    exif[274] = 6  # Orientation: 90° CW
    img.save(path, exif=exif)

    assert faces_mod.load_image(path).size == (50, 100)


def test_heic_photos_can_be_read(tmp_path):
    path = tmp_path / "iphone.heic"
    Image.new("RGB", (64, 48), (200, 100, 50)).save(path)

    loaded = faces_mod.load_image(path)
    assert loaded.size == (64, 48) and loaded.mode == "RGB"


def test_grayscale_and_palette_images_become_rgb(tmp_path):
    for mode, name in (("L", "gray.png"), ("P", "palette.png")):
        path = tmp_path / name
        Image.new(mode, (20, 20)).save(path)
        assert faces_mod.load_image(path).mode == "RGB"
