"""Photo previews, generated on demand and cached on disk."""
from pathlib import Path

import db
import faces as faces_mod

PREVIEW_EDGE = 480


def get_photo_thumb(file_id: int) -> Path:
    cache = db.PHOTO_THUMBS_DIR / f"{file_id}.jpg"
    if cache.exists():
        return cache
    lib = db.get_library()
    row = db.get_db().execute(
        "SELECT rel_path FROM media_files WHERE id=?", (file_id,)).fetchone()
    if lib is None or row is None:
        raise FileNotFoundError(f"file_id {file_id} bulunamadı")
    src = Path(lib["root_path"]) / row["rel_path"]
    img = faces_mod.load_image(src)
    img.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
    img.save(cache, "JPEG", quality=80)
    return cache
