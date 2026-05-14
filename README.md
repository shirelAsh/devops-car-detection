# devops-car-detection

YOLOv8 **car-only** video evaluation: read video + labels from **S3**, run inference, compare to labels, compute **confusion matrix** + **precision / recall / accuracy**, write **metrics JSON** back to **S3**. Docker, docker-compose, Jenkinsfile, and Helm **Job** for EKS are included.

## Label format (`labels.json` in S3)

Coordinates are **xyxy**: `[x1, y1, x2, y2]`. By default boxes are **normalized** to `0–1` relative to frame width/height; set `LABELS_NORMALIZED=false` for pixel coordinates.

```json
{
  "schema": "car-detector/1",
  "frames": [
    { "i": 0, "boxes": [[0.1, 0.2, 0.4, 0.55]] },
    { "i": 1, "boxes": [] }
  ]
}
```

- `i` (or `frame`): zero-based frame index.
- `boxes`: list of car bounding boxes (only the **car** class is evaluated; labels should be cars only).

**Pseudo-labels from video** (dense export, then stratify — details and interview notes in [`docs/LABELS.md`](docs/LABELS.md)):

```powershell
pip install ultralytics opencv-python-headless
python tools/export_yolo_pseudo_labels.py --video examples/video.mp4 -o examples/labels.full.json
python tools/make_stratified_labels.py --input examples/labels.full.json -o examples/labels.json --stride 20
```

## Metrics

- **Frame-level confusion matrix** (car presence vs any car prediction over `CONF_THRESHOLD`).
- **Box-level** TP / FP / FN with greedy IoU matching (`IOU_THRESHOLD`).
- **precision**, **recall** from box counts on **all evaluated frames** (with sparse labels, many frames have no GT, so box-level precision is often low even when the model is reasonable).
- **labeled_frames_with_gt_boxes**, **box_counts_labeled_frames_only**, **precision_labeled_frames_only**, **recall_labeled_frames_only**, **accuracy_box_detection_labeled_frames_only**: only frames where the label file has **≥1 GT car box**. GT boxes are **inset** by `LABELED_GT_SHRINK` (default `0.01`, fraction of each side; `0` = no inset) and matched at **`LABELED_BOX_IOU`** (default stricter than `IOU_THRESHOLD`) so **pseudo-labels from the same detector** usually do **not** read as perfect **1.0** / **1.0** / **1.0**. Tune both env vars for your label style.
- **accuracy_frame_car_presence**: \((TP+TN)/N\) over frames.
- **accuracy_box_detection**: \(TP/(TP+FP+FN)\) over all frames (global box counts).

Optional gates: non-zero exit if below `MIN_PRECISION`, `MIN_RECALL`, or `MIN_ACCURACY`. `MIN_PRECISION` / `MIN_RECALL` compare to the **global** box precision/recall by default; set **`METRICS_GATE_BOX_METRICS=labeled`** to gate on **precision_labeled_frames_only** / **recall_labeled_frames_only** instead. `MIN_ACCURACY` always uses **frame**-level car presence accuracy.

## Environment variables

| Variable | Meaning |
|----------|---------|
| `S3_BUCKET` | Bucket for video, labels, and output prefix |
| `S3_VIDEO_KEY` | Key to input `.mp4` |
| `S3_LABELS_KEY` | Key to `labels.json` |
| `S3_OUTPUT_PREFIX` | Prefix for uploaded metrics (default `runs/`) |
| `AWS_DEFAULT_REGION` | AWS region |
| `YOLO_WEIGHTS` | e.g. `yolov8n.pt` (downloaded on first run if missing) |
| `CONF_THRESHOLD` | YOLO confidence (default `0.35`) |
| `IOU_THRESHOLD` | Match threshold (default `0.5`) |
| `LABELS_NORMALIZED` | `true` / `false` |
| `BUILD_ID` | Optional; appended to output path for CI |
| `MIN_PRECISION`, `MIN_RECALL`, `MIN_ACCURACY` | Optional CI gates |
| `METRICS_GATE_BOX_METRICS` | `global` (default) or `labeled` — which box precision/recall `MIN_*` gates use |
| `LABELED_GT_SHRINK` | Fraction of each GT box’s width/height inset per side for labeled-only matching (default `0.01`; `0` = no inset, old “optimistic” behavior) |
| `LABELED_BOX_IOU` | IoU threshold for that pass (unset ≈ `max(0.85, IOU_THRESHOLD+0.35)`, capped at `0.96`) |
| `YOLO_CONFIG_DIR` | Ultralytics config cache (Dockerfile default `/tmp/Ultralytics`) |

## Local run (Docker Compose)

**Config:** copy the template and edit if needed:

```powershell
Copy-Item .env.example .env
# Edit .env — at minimum set S3_BUCKET, S3_VIDEO_KEY, S3_LABELS_KEY
```

Docker Compose loads **`.env`** in the project root automatically (no need to `$env:S3_*` each session).

Prerequisites: Docker, AWS credentials under `%USERPROFILE%\.aws`. Set `AWS_PROFILE` in `.env` (e.g. `car-detector`). Override the credentials mount with `AWS_CREDENTIALS_DIR` in `.env` if needed.

PowerShell example (if you prefer not to use `.env` for some vars):

```powershell
$env:AWS_PROFILE = "car-detector"
$env:S3_BUCKET = "your-bucket"
$env:S3_VIDEO_KEY = "datasets/video/sample.mp4"
$env:S3_LABELS_KEY = "datasets/labels/sample.json"
$env:AWS_DEFAULT_REGION = "us-east-1"
# Only if Compose still cannot find credentials:
# $env:AWS_CREDENTIALS_DIR = "$env:USERPROFILE\.aws"

docker compose build detector
docker compose run --rm detector
```

Metrics appear under `s3://$S3_BUCKET/$S3_OUTPUT_PREFIX.../metrics.json`.

## Jenkins

1. Agent with Docker and `docker compose` v2 + AWS CLI (or use plugins).
2. Define pipeline from repo `Jenkinsfile`.
3. Set job environment / parameters: `S3_BUCKET`, `S3_VIDEO_KEY`, `S3_LABELS_KEY`, optional `MIN_*`, `AWS_DEFAULT_REGION`.
4. For ECR push, set `ECR_REGISTRY` (e.g. `123456789012.dkr.ecr.region.amazonaws.com`) and `ECR_REPOSITORY`; image tag uses `BUILD_NUMBER` via `CAR_DETECTOR_IMAGE`.

## Helm on EKS

Create an IAM role (IRSA) with least-privilege S3 access; set `serviceAccount.annotations` in `values.yaml`.

```bash
helm upgrade --install car-detector ./helm/car-detector -n car-detector --create-namespace \
  --set image.repository=YOUR_ECR/car-detector \
  --set image.tag=YOUR_TAG \
  --set env.S3_BUCKET=your-bucket \
  --set env.S3_VIDEO_KEY=datasets/video/sample.mp4 \
  --set env.S3_LABELS_KEY=datasets/labels/sample.json
```

Verify:

```bash
kubectl get jobs,pods -n car-detector
kubectl logs -n car-detector job/car-detector-car-detector
```

## Cursor prompt (fill in what you used)

> *(Paste the prompt you used in Cursor to generate or refine this project.)*

## Optional: S3 bucket with AWS CDK (Python)

For IaC and interviews, see [`infra/cdk/README.md`](infra/cdk/README.md) — deploys a private, encrypted S3 bucket; use the stack output as `S3_BUCKET`.

## License

Use and modify for your DevOps assignment as required by your course or employer.
