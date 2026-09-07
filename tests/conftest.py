"""Shared fixtures.

The tests never load the InsightFace model: the `fake_faces` fixture swaps face
extraction for deterministic synthetic embeddings, which makes the whole thing
(scanning, clustering, export, API) testable in seconds and offline. The real
model is only used by test_faces_model.py, which runs under `-m model`.
"""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import db  # noqa: E402
import exporter  # noqa: E402
import faces as faces_mod  # noqa: E402
import scanner  # noqa: E402

EMBED_DIM = 512


def person_embedding(person: str, variant: int = 0, noise: float = 0.05) -> np.ndarray:
    """Unit vector for one person, with variants that stay close together.

    Different people are near-orthogonal (cosine ~ 0); variants of the same
    person have cosine > 0.95.
    """
    seed = int(hashlib.sha1(person.encode()).hexdigest()[:8], 16)
    base = np.random.default_rng(seed).normal(size=EMBED_DIM)
    base /= np.linalg.norm(base)
    if variant:
        jitter = np.random.default_rng(seed + variant).normal(size=EMBED_DIM)
        jitter /= np.linalg.norm(jitter)
        base = base + noise * jitter
        base /= np.linalg.norm(base)
    return base.astype(np.float32)


def write_photo(path: Path, size=(120, 90), color=(200, 160, 120)) -> None:
    """Writes a real, tiny JPEG/PNG. The thumbnail code paths need actual files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own data directory, and module-level state is reset."""
    monkeypatch.delenv("FACEY_DATA_DIR", raising=False)
    db.use_data_dir(tmp_path / "appdata")

    _reset_module_state()
    yield
    _stop_threads()
    db.close_connection()
    db.use_data_dir(db.DEFAULT_APP_DIR)


def _reset_module_state() -> None:
    scanner._thread = None
    scanner._pause.clear()
    scanner._stop.clear()
    scanner._state.update(
        {"phase": "idle", "current": None, "run_faces": 0, "error": None})
    exporter._thread = None
    exporter.state.update({
        "phase": "idle", "mode": "copy", "dest": None, "total": 0,
        "copied": 0, "skipped": 0, "errors": 0, "current": None, "error_files": [],
    })


def _stop_threads() -> None:
    scanner._stop.set()
    scanner._pause.clear()
    for t in (scanner._thread, exporter._thread):
        if t is not None and t.is_alive():
            t.join(timeout=10)


class FakeExtractor:
    """Stands in for `faces.extract_faces`.

    Who is in a photo comes from its filename: `ali_veli.jpg` holds two faces,
    one for ali and one for veli. Files with `noface` in the name hold none.
    The same person gets a slightly different embedding in each file.
    """

    def __init__(self):
        self.calls: list[Path] = []
        self.fail_on: set[str] = set()
        self.det_score = 0.9
        self.face_px = 100.0
        self.variant_counter: dict[str, int] = {}

    def __call__(self, path, file_id: int):
        path = Path(path)
        self.calls.append(path)
        if path.name in self.fail_on:
            raise OSError("corrupt file")

        with Image.open(path) as img:
            width, height = img.size

        results = []
        for i, person in enumerate(self.people_in(path)):
            variant = self.variant_counter.get(person, 0)
            self.variant_counter[person] = variant + 1
            thumb_name = f"{file_id}_{i}.jpg"
            write_photo(db.FACE_THUMBS_DIR / thumb_name, size=(40, 40))
            results.append({
                "bbox": (10.0 * i, 5.0, self.face_px, self.face_px),
                "det_score": self.det_score,
                "embedding": person_embedding(person, variant),
                "thumb_name": thumb_name,
            })
        return width, height, results

    @staticmethod
    def people_in(path: Path) -> list[str]:
        stem = path.stem
        if "noface" in stem:
            return []
        return [tok for tok in stem.split("_") if tok]


@pytest.fixture
def fake_faces(monkeypatch):
    extractor = FakeExtractor()
    monkeypatch.setattr(faces_mod, "extract_faces", extractor)
    return extractor


@pytest.fixture
def photo_root(tmp_path):
    """Sample archive with nested folders. Filenames encode who is in each photo."""
    root = tmp_path / "archive"
    for rel in [
        "trip/ali.jpg",
        "trip/ali_veli.jpg",
        "home/veli.jpg",
        "home/nested/ayse.jpg",
        "misc/noface.png",
    ]:
        write_photo(root / rel)
    return root


def wait_scan(timeout: float = 30.0) -> dict:
    """Waits for the scan to finish and returns the final status."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = scanner.get_status()
        if not status["running"] and status["phase"] in ("done", "error"):
            return status
        time.sleep(0.02)
    raise AssertionError(f"scan did not finish in {timeout}s: {scanner.get_status()}")


def wait_export(timeout: float = 30.0) -> dict:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if exporter.state["phase"] in ("done", "error"):
            return dict(exporter.state)
        time.sleep(0.02)
    raise AssertionError(f"export did not finish in {timeout}s: {exporter.state}")


@pytest.fixture
def scanned(photo_root, fake_faces):
    """A library that has already been scanned and clustered."""
    scanner.start_scan(str(photo_root))
    wait_scan()
    return photo_root


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c
