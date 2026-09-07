"""End-to-end face extraction against the real InsightFace model.

Slow, and it needs the model, so the default `make test` skips these.
To run them: make test-all   (or pytest -m model)
"""
import numpy as np
import pytest
from PIL import Image

import db
import faces as faces_mod

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def portrait():
    from skimage import data
    return Image.fromarray(data.astronaut())  # public-domain portrait


def extract(path, file_id=1):
    return faces_mod.extract_faces(path, file_id)


def test_model_loads_once():
    assert faces_mod.get_analyzer() is faces_mod.get_analyzer()
    assert faces_mod.model_state["status"] == "ready"


def test_finds_a_face_and_writes_its_thumbnail(tmp_path, portrait):
    path = tmp_path / "portrait.jpg"
    portrait.save(path, quality=95)

    width, height, found = extract(path, file_id=7)

    assert (width, height) == portrait.size
    assert len(found) == 1
    face = found[0]
    assert face["det_score"] > 0.6
    assert face["embedding"].shape == (512,)
    assert face["embedding"].dtype == np.float32
    assert np.isclose(np.linalg.norm(face["embedding"]), 1.0, atol=1e-4)
    assert (db.FACE_THUMBS_DIR / face["thumb_name"]).exists()
    assert face["thumb_name"] == "7_0.jpg"


def test_bounding_box_stays_inside_the_image(tmp_path, portrait):
    path = tmp_path / "portrait.jpg"
    portrait.save(path, quality=95)
    width, height, found = extract(path)

    x, y, w, h = found[0]["bbox"]
    assert 0 <= x and 0 <= y and x + w <= width and y + h <= height
    assert w > 20 and h > 20


def test_photo_without_people_yields_no_faces(tmp_path):
    path = tmp_path / "landscape.jpg"
    gradient = np.tile(np.linspace(0, 255, 256, dtype=np.uint8), (256, 1))
    Image.fromarray(gradient).convert("RGB").save(path)

    _, _, found = extract(path)
    assert found == []


def test_same_person_matches_across_formats_and_sizes(tmp_path, portrait):
    """The same person has to match across JPEG, HEIC and an upscaled copy."""
    jpeg, heic, large = (tmp_path / n for n in ("a.jpg", "b.heic", "c.jpg"))
    portrait.save(jpeg, quality=95)
    portrait.save(heic)
    portrait.resize((portrait.width * 3, portrait.height * 3)).save(large, quality=95)

    embeddings = [extract(p, i)[2][0]["embedding"] for i, p in enumerate((jpeg, heic, large))]

    assert float(embeddings[0] @ embeddings[1]) > 0.9   # JPEG ↔ HEIC
    assert float(embeddings[0] @ embeddings[2]) > 0.85  # scale change, i.e. the downscale path


def test_different_people_are_far_apart(tmp_path, portrait):
    from skimage import data
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    portrait.save(a, quality=95)
    Image.fromarray(data.chelsea()).save(b, quality=95)  # a cat, so no human face

    _, _, first = extract(a, 1)
    _, _, second = extract(b, 2)
    assert len(first) == 1
    if second:  # even a false positive on the cat must not look like a person
        assert float(first[0]["embedding"] @ second[0]["embedding"]) < 0.5


def test_group_photo_finds_multiple_distinct_people(tmp_path):
    import insightface
    bgr = insightface.data.get_image("t1")  # sample group photo
    path = tmp_path / "group.jpg"
    Image.fromarray(bgr[:, :, ::-1]).save(path, quality=95)

    _, _, found = extract(path)

    assert len(found) >= 3
    similarities = [
        float(found[i]["embedding"] @ found[j]["embedding"])
        for i in range(len(found)) for j in range(i + 1, len(found))
    ]
    assert max(similarities) < 0.5  # different people


def test_rotated_photo_is_uprighted_before_detection(tmp_path, portrait):
    """Without the EXIF orientation the face lies sideways and is missed."""
    path = tmp_path / "rotated.jpg"
    rotated = portrait.transpose(Image.ROTATE_90)
    exif = rotated.getexif()
    exif[274] = 6  # Orientation: rotate back
    rotated.save(path, exif=exif, quality=95)

    _, _, found = extract(path)
    assert len(found) == 1
