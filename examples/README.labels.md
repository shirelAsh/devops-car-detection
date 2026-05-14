# Labels for interviews and submissions

## What is in `labels.json` (default in this repo)

- **`labeling_method`: `stratified_subset`** — we keep **every 20th** frame that had boxes in a dense referee export.
- **`labeling_note`** — states that unlisted frames have **no** GT in this file, and that **CVAT / Label Studio** is the path to fully independent human GT.

This is **honest in an interview**: you are not claiming hand-drawn every frame; you are claiming **documented sampling** + clear path to production labeling.

## How it was produced

Dense car boxes (referee export), then stratify:

```powershell
python tools/export_yolo_pseudo_labels.py --video examples/video.mp4 -o examples/labels.full.json
python tools/make_stratified_labels.py --input examples/labels.full.json -o examples/labels.json --stride 20
```

To change density, adjust `--stride` (larger = fewer labeled frames).

## What to say in an interview

1. **“Ground truth strategy”** — stratified sample for cost/latency; full annotation is CVAT + QA.
2. **“Metrics interpretation”** — frames without an entry in `frames[]` are **no GT**; the model can still predict cars there (FP at frame level for those indices).
3. **“Production”** — IAM/IRSA, versioned label artifacts in S3, and label schema version in JSON (`schema`).

## Upload to S3

Use the same keys as your pipeline (`labels.json`). After replacing locally, upload:

```powershell
aws s3 cp .\examples\labels.json s3://YOUR_BUCKET/labels.json --profile car-detector
```
