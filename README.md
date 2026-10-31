# Facey

Facey is a desktop app that finds every photo a person appears in and copies
those photos to another folder. Point it at your photo archive, let it group
the faces, pick the people you want, and export.

Everything runs locally. No photo, face or name ever leaves your computer.

> The user interface is currently in Turkish.

## Features

- **Recursive scan** of a folder: JPEG, PNG, HEIC/HEIF, WebP, TIFF and BMP,
  with EXIF rotation applied before detection.
- **Incremental rescans.** Only new or changed files are processed, and a scan
  can be paused and resumed.
- **Automatic grouping** of faces into people, using
  [InsightFace](https://github.com/deepinsight/insightface) `buffalo_l`
  embeddings and agglomerative clustering.
- **Manual corrections that stick:** merge clusters, pull wrong faces out, name
  people, hide strangers. Re-clustering never undoes your edits.
- **Saved groups** such as "Family X", so a recurring export is one click.
- **Safe export.** Files are copied, never overwritten, and checked after
  copying. Move mode is optional.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- About 330 MB of disk space for the face-recognition model, downloaded on the
  first scan

Facey is developed on macOS. It also works on Linux and Windows, where the app
window needs a [pywebview backend](https://pywebview.flowrl.com/guide/installation.html):
GTK or Qt on Linux, WebView2 (preinstalled on Windows 10 and 11) on Windows.
If you'd rather not install one, use the browser instead (see below).

Detection runs on the CPU. Expect roughly 10,000 photos per hour on Apple
Silicon.

## Getting started

```sh
git clone <this repository> facey
cd facey
make setup    # creates .venv, installs Python and Node packages, builds the UI
make run      # opens the app window
```

To use a regular browser instead of the app window:

```sh
make build
make headless   # then open http://127.0.0.1:8756
```

In the browser, folder pickers become a prompt where you type the path.

The first scan downloads the model into `~/.insightface/models`. After that
Facey works offline.

## How it works

1. **Scan.** Choose a root folder. Facey walks it, detects every face, and
   stores a 512-dimensional descriptor plus a small crop for each one. Videos
   are indexed but not analysed yet.
2. **Fix the grouping.** Clustering sometimes splits one person into several
   clusters when lighting, age or sunglasses differ. The People tab is where
   you merge those, remove wrong faces, name the people you care about and
   hide the rest.
3. **Export.** Select people, or a saved group, and Facey lists every photo
   that contains at least one of them. The folder structure is recreated at
   the destination, so `trip/2019/beach.jpg` lands at
   `<destination>/trip/2019/beach.jpg`.

Choosing a different root folder starts a new library and discards the
previous one's faces, names and groups. Rescanning the same folder keeps them.

## Your files are safe

- Scanning only reads. Facey writes no sidecar files and edits no metadata.
- Export copies with `shutil.copy2`, so timestamps are preserved, and checks
  the size of every copy.
- A file at the destination is never overwritten. If it has the same size it
  counts as already exported and is skipped. Otherwise the new file is written
  next to it as `name-1.jpg`.
- Move mode is opt-in and confirmed separately. It copies, verifies, and only
  then deletes the original. If verification fails, the original stays and the
  bad copy is removed.
- The destination cannot be inside the scanned folder.
- The local API only accepts requests from the app itself, so other websites
  open in your browser cannot reach it.

## Where the data lives

| Platform | Folder |
|---|---|
| macOS | `~/Library/Application Support/facey/` |
| Linux | `$XDG_DATA_HOME/facey/`, by default `~/.local/share/facey/` |
| Windows | `%APPDATA%\facey\` |

Set `FACEY_DATA_DIR` to use another folder.

The folder holds `facey.db` (file index, face descriptors, clusters, names and
groups), `face_thumbs/` (200 px face crops) and `photo_thumbs/` (480 px
previews, created on demand). A 10,000-photo archive takes about 100 MB.

Deleting this folder resets Facey and touches nothing else. `make reset` does
it after asking for confirmation.

## Tuning

The ⚙ menu has four thresholds that control clustering:

| Setting | Default | Effect |
|---|---|---|
| `assign_threshold` | 0.45 | Minimum cosine similarity for a face to join an existing person. Raise it if different people get merged. |
| `cluster_distance` | 0.55 | Maximum distance between faces in one new cluster. Lower it to split aggressively, then merge by hand. |
| `min_det_score` | 0.60 | Detections below this score are kept but never clustered. |
| `min_face_px` | 40 | Faces smaller than this (shorter side, in pixels) are kept but never clustered. |

Changes apply to future clustering only. Faces that are already grouped stay
where they are, and manual corrections are never touched. **Re-cluster** places
the faces that are still unassigned.

## Development

```sh
make            # list every target
make dev        # Vite dev server plus the app window, with hot reload
make test       # fast suite, no model needed (a few seconds)
make test-all   # also runs the tests that load the real model
make coverage   # test suite with a coverage report in htmlcov/
make check      # tests, type-check and lint, as CI would run them
```

The fast suite does not load the model. Face extraction is replaced by a fake
that reads who is in a photo from its file name (`ali_veli.jpg` holds two
people) and returns deterministic embeddings. The tests that use the real model
live in `tests/test_faces_model.py`, behind the `model` marker.

### Project layout

```
backend/
  main.py        starts the API server and the pywebview window, native folder dialog
  app.py         HTTP API (FastAPI)
  db.py          SQLite schema, connections, data folder
  scanner.py     folder walking, incremental rescans, background worker
  faces.py       model loading, detection, embeddings, face crops
  clustering.py  incremental assignment, merge and unassign
  exporter.py    verified copy and move
  thumbs.py      preview cache
frontend/src/    React, TypeScript and Tailwind, one view per tab
tests/           pytest
```

## Contributing

Issues and pull requests are welcome. Please run `make check` before opening a
pull request, and add a test for any bug you fix.

## License

[MIT](LICENSE)

The InsightFace models are distributed under their own terms. The pretrained
`buffalo_l` weights are licensed for non-commercial research use only, so check
[InsightFace's license](https://github.com/deepinsight/insightface#license)
before using Facey commercially.
