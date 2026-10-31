"""Face extraction and model loading, with a stand-in for InsightFace."""
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

import db
import faces as faces_mod
from conftest import person_embedding, write_photo


class FakeAnalyzer:
    """Returns fixed detections in the coordinates of the image it was given."""

    def __init__(self, detections):
        self.detections = detections
        self.seen_shapes = []

    def get(self, bgr):
        self.seen_shapes.append(bgr.shape)
        return self.detections


def detection(bbox, embedding=None, score=0.9):
    return SimpleNamespace(
        bbox=np.array(bbox, dtype=np.float32),
        det_score=score,
        normed_embedding=person_embedding("ali") if embedding is None else embedding,
    )


@pytest.fixture
def analyzer(monkeypatch):
    fake = FakeAnalyzer([])
    monkeypatch.setattr(faces_mod, "get_analyzer", lambda: fake)
    return fake


def test_face_is_returned_with_its_crop(tmp_path, analyzer):
    analyzer.detections = [detection((10, 20, 60, 90))]
    write_photo(tmp_path / "p.jpg", size=(200, 150))

    w, h, found = faces_mod.extract_faces(tmp_path / "p.jpg", file_id=7)

    assert (w, h) == (200, 150)
    assert len(found) == 1
    face = found[0]
    assert face["bbox"] == pytest.approx((10, 20, 50, 70))
    assert face["det_score"] == pytest.approx(0.9)
    assert face["embedding"].dtype == np.float32 and face["embedding"].shape == (512,)
    assert face["thumb_name"] == "7_0.jpg"
    assert (db.FACE_THUMBS_DIR / "7_0.jpg").exists()


def test_large_photo_is_downscaled_and_boxes_mapped_back(tmp_path, analyzer):
    edge = faces_mod.DETECT_MAX_EDGE
    analyzer.detections = [detection((100, 100, 300, 300))]
    write_photo(tmp_path / "big.jpg", size=(edge * 2, edge))

    w, h, found = faces_mod.extract_faces(tmp_path / "big.jpg", file_id=1)

    assert analyzer.seen_shapes == [(edge // 2, edge, 3)]
    assert (w, h) == (edge * 2, edge)
    assert found[0]["bbox"] == pytest.approx((200, 200, 400, 400))


def test_boxes_are_clipped_to_the_image(tmp_path, analyzer):
    analyzer.detections = [detection((-15, -5, 130, 95))]
    write_photo(tmp_path / "p.jpg", size=(120, 90))

    _, _, found = faces_mod.extract_faces(tmp_path / "p.jpg", file_id=1)

    assert found[0]["bbox"] == pytest.approx((0, 0, 120, 90))


def test_degenerate_boxes_and_missing_embeddings_are_dropped(tmp_path, analyzer):
    analyzer.detections = [
        detection((10, 10, 10.5, 40)),
        SimpleNamespace(bbox=np.array([5, 5, 50, 50]), det_score=0.9, normed_embedding=None),
        detection((20, 20, 70, 70)),
    ]
    write_photo(tmp_path / "p.jpg", size=(120, 90))

    _, _, found = faces_mod.extract_faces(tmp_path / "p.jpg", file_id=3)

    assert [f["thumb_name"] for f in found] == ["3_2.jpg"]
    assert sorted(p.name for p in db.FACE_THUMBS_DIR.iterdir()) == ["3_2.jpg"]


def test_face_crop_is_bounded_by_the_thumb_size(tmp_path, analyzer):
    analyzer.detections = [detection((0, 0, 900, 900))]
    write_photo(tmp_path / "p.jpg", size=(1000, 1000))

    faces_mod.extract_faces(tmp_path / "p.jpg", file_id=1)

    with Image.open(db.FACE_THUMBS_DIR / "1_0.jpg") as crop:
        assert max(crop.size) <= faces_mod.THUMB_SIZE


# ---------- model loading ----------

@pytest.fixture
def fake_insightface(monkeypatch):
    """Installs a fake `insightface.app` whose FaceAnalysis we control."""
    behaviour = {"fail": True, "created": 0}

    class FaceAnalysis:
        def __init__(self, **kwargs):
            behaviour["created"] += 1
            if behaviour["fail"]:
                raise OSError("download failed")

        def prepare(self, **kwargs):
            pass

    package = types.ModuleType("insightface")
    app_module = types.ModuleType("insightface.app")
    app_module.FaceAnalysis = FaceAnalysis
    package.app = app_module
    monkeypatch.setitem(sys.modules, "insightface", package)
    monkeypatch.setitem(sys.modules, "insightface.app", app_module)
    monkeypatch.setattr(faces_mod, "_analyzer", None)
    monkeypatch.setattr(faces_mod, "model_state", {"status": "not_loaded", "error": None})
    return behaviour


def test_model_failure_raises_a_model_load_error(fake_insightface):
    with pytest.raises(faces_mod.ModelLoadError, match="download failed"):
        faces_mod.get_analyzer()
    assert faces_mod.model_state == {"status": "error", "error": "download failed"}


def test_model_load_is_retried_and_clears_the_old_error(fake_insightface):
    with pytest.raises(faces_mod.ModelLoadError):
        faces_mod.get_analyzer()

    fake_insightface["fail"] = False
    first = faces_mod.get_analyzer()

    assert first is faces_mod.get_analyzer()
    assert fake_insightface["created"] == 2
    assert faces_mod.model_state == {"status": "ready", "error": None}
