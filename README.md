# Facey

Finds every photo a given person appears in, and copies those photos somewhere
else. Point it at a folder, let it group the faces, pick the people you want.

## Getting started

Needs macOS, Python 3.11+ and Node 20+. Detection runs on the CPU; expect around
10k photos per hour on Apple Silicon.

```sh
make setup    # venv, npm install, build the UI
make run
```

The first scan downloads the InsightFace `buffalo_l` model (about 330 MB) into
`~/.insightface/models`. Everything after that runs offline.

## Using it

**Scan.** Pick a root folder. Facey walks it recursively and stores a 512-d
descriptor plus a small crop for every face it finds. Later scans only touch
files that are new or changed, and a scan can be paused and resumed. JPEG, PNG,
HEIC/HEIF, WebP, TIFF and BMP are read, with EXIF rotation applied before
detection. Videos are indexed but not analysed yet.

**Fix the grouping.** Clustering splits one person across several clusters when
lighting, age or sunglasses differ, so most of the UI exists to correct that:
merge clusters, pull wrong faces out, name the people you care about, hide the
strangers in the background. Corrections stick, because re-clustering only
places faces that were never assigned.

**Export.** Select people, or a saved group such as "Family X", and Facey lists
every photo containing at least one of them. The source folder structure is
recreated at the destination, so `trip/2019/beach.jpg` lands at
`<dest>/trip/2019/beach.jpg`.

## What happens to your files

- Scanning only reads. No sidecar files, no metadata edits.
- Export copies with `copy2`, so timestamps are preserved, and checks the size
  of each copy afterwards.
- An existing file at the destination is never overwritten. If it is the same
  size it counts as already exported and is skipped; if it differs, the new file
  is written next to it as `name-1.jpg`.
- Move mode is opt-in and confirmed separately. It copies, verifies, then
  deletes. If verification fails the original stays and the bad copy is removed.
- The destination cannot be inside the folder you scanned.

## Where the data lives

`~/Library/Application Support/facey/` holds `facey.db` (file index, face
descriptors, clusters, your names and groups), `face_thumbs/` (200 px crops) and
`photo_thumbs/` (480 px previews, generated on demand). Around 100 MB for a
10k-photo archive. Deleting the folder resets the app and nothing else, and
`make reset` does it with a prompt. `FACEY_DATA_DIR` points it elsewhere.

## Tuning

The ⚙ menu exposes the four thresholds that control clustering:

| Setting | Default | Effect |
|---|---|---|
| `assign_threshold` | 0.45 | Minimum cosine similarity for a face to join an existing person. Raise it if unrelated people get merged. |
| `cluster_distance` | 0.55 | How far apart faces can be and still form one new cluster. Lower it to split aggressively and merge by hand. |
| `min_det_score` | 0.60 | Detections below this are kept but never clustered. |
| `min_face_px` | 40 | Faces smaller than this are kept but never clustered. |

A change affects future clustering only. Nothing already grouped is reshuffled,
and manual corrections are never touched. Use **Re-cluster** to reconsider the
faces that are still unassigned.

## Development

```sh
make          # list every target
make dev      # Vite dev server + app window, hot reload
make test     # 131 tests, no model needed, ~4s
make test-all # adds 8 tests that load the real model
make check    # tests + typecheck + lint
```

```
backend/
  main.py        uvicorn thread, pywebview window, native folder dialogs
  app.py         HTTP API
  db.py          SQLite schema and connections
  scanner.py     folder walking, incremental rescans, background worker
  faces.py       model loading, detection, embeddings, face crops
  clustering.py  incremental assignment, merge and unassign
  exporter.py    verified copy and move
  thumbs.py      preview cache
frontend/src/    React + Tailwind, one view per tab
tests/           pytest
```

The suite runs without the model: face extraction is swapped for a fake that
reads the cast from the filename (`ali_veli.jpg` holds two people) and returns
deterministic embeddings. The tests that do load the model live in
`tests/test_faces_model.py`, behind the `model` marker.
