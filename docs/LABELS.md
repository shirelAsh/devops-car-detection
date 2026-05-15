# Labels

The **`examples/`** directory is **gitignored** — keep video, dense exports, and `labels.json` there only on your machine (or use any paths you like). **CI and the detector use S3** (`S3_VIDEO_KEY`, `S3_LABELS_KEY`).

## What is in `labels.json` (S3 artifact; optional local copy)

The canonical file for the pipeline is **`labels.json` in S3** (`S3_LABELS_KEY`). Regenerate locally when needed, then `aws s3 cp` to the bucket.

- **`labeling_method`: `stratified_subset`** — we keep **every 20th** frame that had boxes in a dense referee export.
- **`labeling_note`** — states that unlisted frames have **no** GT in this file, and that **CVAT / Label Studio** is the path to fully independent human GT.


## How it was produced

Dense car boxes (referee export), then stratify (paths assume a local `examples/` folder):

```powershell
python tools/export_yolo_pseudo_labels.py --video examples/video.mp4 -o examples/labels.full.json
python tools/make_stratified_labels.py --input examples/labels.full.json -o examples/labels.json --stride 20
```

To change density, adjust `--stride` (larger = fewer labeled frames).


## Upload to S3

Use the same keys as your pipeline (`labels.json`). After generating locally, upload:

```powershell
aws s3 cp .\examples\labels.json s3://YOUR_BUCKET/labels.json --profile car-detector
```
