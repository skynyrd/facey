"""Loading InsightFace (buffalo_l) and pulling faces out of photos."""
import threading

import numpy as np
import pillow_heif
from PIL import Image, ImageOps

import db

pillow_heif.register_heif_opener()

DETECT_MAX_EDGE = 1600   # long edge is capped at this before detection
THUMB_SIZE = 200         # target size of a face crop (px)
THUMB_MARGIN = 0.25      # margin added around the bbox, as a fraction

_lock = threading.Lock()
_analyzer = None
# surfaced in the scan status: not_loaded | loading | ready | error
model_state = {"status": "not_loaded", "error": None}


def get_analyzer():
    """Downloads and loads buffalo_l on the first call (~330 MB, ~/.insightface)."""
    global _analyzer
    with _lock:
        if _analyzer is None:
            model_state["status"] = "loading"
            try:
                from insightface.app import FaceAnalysis
                analyzer = FaceAnalysis(
                    name="buffalo_l",
                    allowed_modules=["detection", "recognition"],
                    providers=["CPUExecutionProvider"],
                )
                analyzer.prepare(ctx_id=-1, det_size=(640, 640))
                _analyzer = analyzer
                model_state["status"] = "ready"
            except Exception as exc:
                model_state["status"] = "error"
                model_state["error"] = str(exc)
                raise
    return _analyzer


def load_image(path) -> Image.Image:
    """RGB image with the EXIF orientation applied. HEIC included."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def extract_faces(path, file_id: int):
    """Extracts the faces in a photo.

    Returns (width, height, faces), where each face carries its bbox in
    original-image coordinates, its det_score, an L2-normalized 512d embedding
    and the filename of the crop written to disk.
    """
    img = load_image(path)
    w, h = img.size

    det_img, scale = img, 1.0
    if max(w, h) > DETECT_MAX_EDGE:
        scale = DETECT_MAX_EDGE / max(w, h)
        det_img = img.resize((round(w * scale), round(h * scale)), Image.BILINEAR)

    bgr = np.asarray(det_img)[:, :, ::-1]  # insightface expects BGR
    detected = get_analyzer().get(bgr)

    results = []
    for i, f in enumerate(detected):
        x1, y1, x2, y2 = (float(v) / scale for v in f.bbox)
        x1, y1 = max(0.0, x1), max(0.0, y1)
        x2, y2 = min(float(w), x2), min(float(h), y2)
        bw, bh = x2 - x1, y2 - y1
        if bw <= 1 or bh <= 1 or f.normed_embedding is None:
            continue
        thumb_name = f"{file_id}_{i}.jpg"
        _save_face_thumb(img, (x1, y1, bw, bh), thumb_name)
        results.append({
            "bbox": (x1, y1, bw, bh),
            "det_score": float(f.det_score),
            "embedding": np.asarray(f.normed_embedding, dtype=np.float32),
            "thumb_name": thumb_name,
        })
    return w, h, results


def _save_face_thumb(img: Image.Image, bbox, name: str) -> None:
    x, y, bw, bh = bbox
    mx, my = bw * THUMB_MARGIN, bh * THUMB_MARGIN
    crop = img.crop((round(x - mx), round(y - my), round(x + bw + mx), round(y + bh + my)))
    crop.thumbnail((THUMB_SIZE, THUMB_SIZE))
    crop.save(db.FACE_THUMBS_DIR / name, "JPEG", quality=85)
