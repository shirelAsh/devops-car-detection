# devops-car-detection

YOLOv8 **car-only** video evaluation: read video + labels from **S3**, run inference, compare to labels, compute **confusion matrix** + **precision / recall / accuracy**, write **metrics JSON** back to **S3**. Docker, docker-compose, Jenkinsfile, and Helm **Job** for EKS are included.

## Submission screenshots

Pipeline evidence (Jenkins → ECR → EKS → S3) lives in [`screenshots/`](screenshots/). Each PNG is shown inline with a short explanation in [`screenshots/README.md`](screenshots/README.md).

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

**Pseudo-labels from video** (dense export, then stratify — see [`docs/LABELS.md`](docs/LABELS.md)):

```powershell
pip install ultralytics opencv-python-headless
python tools/export_yolo_pseudo_labels.py --video examples/video.mp4 -o examples/labels.full.json
python tools/make_stratified_labels.py --input examples/labels.full.json -o examples/labels.json --stride 20
```

## Metrics

- **Frame-level confusion matrix** (car presence vs any car prediction over `CONF_THRESHOLD`). By default **`FRAME_CM_ANNOTATED_FRAMES_ONLY=true`**: only frame indices that **appear in `labels.json`** are counted. That way **stratified / sparse** label files do not treat every unlisted video frame as “no car” ground truth (which used to crush **accuracy_frame_car_presence**). Set **`FRAME_CM_ANNOTATED_FRAMES_ONLY=false`** to restore the old “every video frame” behavior (only if your label file truly annotates absence on all frames).
- **Box-level** TP / FP / FN with greedy IoU matching (`IOU_THRESHOLD`).
- **precision**, **recall** from box counts on **all evaluated frames** (with sparse labels, many frames have no GT, so box-level precision is often low even when the model is reasonable).
- **labeled_frames_with_gt_boxes**, **box_counts_labeled_frames_only**, **precision_labeled_frames_only**, **recall_labeled_frames_only**, **accuracy_box_detection_labeled_frames_only**: only frames where the label file has **≥1 GT car box**. GT boxes are **inset** by `LABELED_GT_SHRINK` (default `0.01`, fraction of each side; `0` = no inset) and matched at **`LABELED_BOX_IOU`** (default stricter than `IOU_THRESHOLD`) so **pseudo-labels from the same detector** usually do **not** read as perfect **1.0** / **1.0** / **1.0**. Tune both env vars for your label style.
- **accuracy_frame_car_presence**: \((TP+TN)/N\) over frames included in the frame confusion matrix (see `frame_cm_scope` and `frames_in_frame_confusion_matrix` in `metrics.json`).
- **accuracy_box_detection**: \(TP/(TP+FP+FN)\) over all frames (global box counts).

Optional gates: non-zero exit if below `MIN_PRECISION`, `MIN_RECALL`, or `MIN_ACCURACY`. `MIN_PRECISION` / `MIN_RECALL` compare to **global** or **labeled** box metrics per **`METRICS_GATE_BOX_METRICS`** (default **`labeled`** in Compose / Helm / Jenkins). `MIN_ACCURACY` uses **frame**-level car presence accuracy (respecting **`FRAME_CM_ANNOTATED_FRAMES_ONLY`**).

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
| `METRICS_GATE_BOX_METRICS` | `labeled` (default in Compose / Helm) or `global` — which box precision/recall `MIN_*` gates use |
| `FRAME_CM_ANNOTATED_FRAMES_ONLY` | `true` (default): frame confusion / `MIN_ACCURACY` only use frame indices listed in `labels.json`. `false`: use every decoded video frame (legacy; harsh with sparse labels). |
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

The **Dockerfile** installs **CPU-only** PyTorch from `download.pytorch.org` so image builds avoid multi‑gigabyte CUDA wheels (faster CI than a default `pip install torch`). For **faster repeat builds**, use BuildKit (Jenkins sets this automatically): PowerShell before `docker compose build`: `$env:DOCKER_BUILDKIT='1'; $env:COMPOSE_DOCKER_CLI_BUILD='1'`.

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

Metrics appear under `s3://$S3_BUCKET/$S3_OUTPUT_PREFIX.../metrics.json`. See **Verification: metrics S3 path and sample output** below for a concrete URI and JSON shape.

## Cursor prompt (assignment)

Use this block as the **Cursor prompt you used** in your write-up. If your real wording was different, **replace the quoted block** with your exact chat prompt (keep the heading so graders can find it).

> Implement a DevOps-ready **car detection evaluation service** for video:
>
> - Use **YOLOv8** pretrained weights; evaluate **COCO class “car” only** (`classes=[2]`).
> - **Download** an MP4 and a `labels.json` from **S3** (bucket + keys via env), run frame-by-frame inference, compare predictions to labels (xyxy boxes, normalized by default).
> - Compute a **2×2 confusion matrix** for frame-level car presence vs predicted presence, plus **box-level** TP/FP/FN with IoU matching, **precision / recall / accuracy**, and **labeled-frame-only** metrics where labels are sparse; write **`metrics.json`** back to S3 under `S3_OUTPUT_PREFIX`, optionally with `BUILD_ID` in the path.
> - Support optional **CI gates**: `MIN_PRECISION`, `MIN_RECALL`, `MIN_ACCURACY` and `METRICS_GATE_BOX_METRICS` / `FRAME_CM_ANNOTATED_FRAMES_ONLY` for fair sparse labels.
> - Provide **Dockerfile** (CPU-friendly PyTorch), **docker-compose** for local runs, **Jenkinsfile** (build + `docker compose run`, Windows `bat` + Linux `sh`, optional ECR), and a **Helm Job** for EKS with IRSA notes in `values.yaml`. Document env vars and verification in **README**.

## Verification: metrics S3 path and sample output

After a **green** Jenkins or local `docker compose run --rm detector`, the log line `Metrics written to s3://…` is the object to cite.

**Examples (this project, `eu-west-1`):**

- **Jenkins** build **#15** (image tag `15` in ECR):  
  `s3://cardetectordatastack-cardetectorbucketf3ab59bc-fwx6sufdchpi/runs/15_20260515T081940Z/metrics.json`
- **EKS** Helm Job (no `BUILD_ID` in path):  
  `s3://cardetectordatastack-cardetectorbucketf3ab59bc-fwx6sufdchpi/runs/20260515T091032Z/metrics.json`

**List or download (AWS CLI, same profile/region as the run):**

```powershell
aws s3 ls s3://cardetectordatastack-cardetectorbucketf3ab59bc-fwx6sufdchpi/runs/ --profile car-detector
aws s3 cp s3://cardetectordatastack-cardetectorbucketf3ab59bc-fwx6sufdchpi/runs/15_20260515T081940Z/metrics.json - --profile car-detector
```

**Tiny `metrics.json` excerpt** (fields and order may vary slightly; values match that run’s console summary):

```json
{
  "schema": "car-detector-metrics/1",
  "frame_cm_scope": "label_file_frames_only",
  "frames_in_frame_confusion_matrix": 23,
  "accuracy_frame_car_presence": 1.0,
  "precision_labeled_frames_only": 1.0,
  "recall_labeled_frames_only": 0.382353,
  "accuracy_box_detection_labeled_frames_only": 0.382353
}
```

**Expected console lines** (abridged): `Confusion (frame car presence, label-file frames only): …` then `Metrics written to s3://…`.

## Jenkins

**Why there is no “Build Environment” block:** that section exists on **Freestyle** jobs. This repo uses a **Pipeline** job (**Pipeline script from SCM**). Environment for `docker compose` comes from the **`Jenkinsfile`** (`parameters` + `environment {}`), not from a separate Build Environment UI.

1. Agent with Docker and `docker compose` v2 + AWS CLI (or use plugins). The agent user must have AWS credentials (e.g. `~/.aws` or instance role) matching `AWS_PROFILE` in the parameters.
2. Job definition: **Pipeline script from SCM** → your repo/branch → **Script Path** `Jenkinsfile`.
3. Run **Build with Parameters** (Hebrew UI often: **בנייה עם פרמטרים**). Set **S3_BUCKET** (required), and adjust **S3_VIDEO_KEY**, **S3_LABELS_KEY**, **AWS_DEFAULT_REGION**, **AWS_PROFILE** as needed.
4. **Metric gates (requirement 4):** the `Jenkinsfile` defaults are **`METRICS_GATE_BOX_METRICS=labeled`**, **`MIN_PRECISION=0.05`**, **`MIN_RECALL=0.05`**, **`MIN_ACCURACY=0.45`** so a successful build implies metrics cleared those floors (container exits non‑zero otherwise). Clear those parameter fields **and** remove matching Jenkins globals if you need to disable gates for debugging.
5. **ECR push:** fill **Build with Parameters** fields **`ECR_REGISTRY`** (e.g. `123456789012.dkr.ecr.eu-west-1.amazonaws.com`) and **`ECR_REPOSITORY`** (repo name only, e.g. `car-detector`), or set the same names as Jenkins **global / node** environment variables. The **`Push to ECR`** stage runs only when both are non-empty; the pipeline sets **`CAR_DETECTOR_IMAGE`** to `registry/repo:BUILD_NUMBER` so **`Run detector`** uses that image. The agent needs AWS permissions for ECR push (see [`docs/ECR_AND_IRSA.md`](docs/ECR_AND_IRSA.md)).
6. **Windows agents:** the pipeline uses **`bat`** when `isUnix()` is false. If you still see “Cannot run program `sh`”, pull the latest `Jenkinsfile` (or add Git’s `bin` to the Jenkins service `PATH` so `sh` exists).

## Helm on EKS

**ECR + IRSA first:** step-by-step is in [`docs/ECR_AND_IRSA.md`](docs/ECR_AND_IRSA.md) (create ECR repo, push image, S3 IAM policy, OIDC/IRSA role, then Helm below).

Create an IAM role (IRSA) with least-privilege S3 access; set `serviceAccount.annotations` in `values.yaml` (or `--set` as in the doc). Default **MIN_*** / **METRICS_GATE_BOX_METRICS** in `values.yaml` match the Jenkins gates; override with `--set` if needed.

**Cluster used in this project:** `car-detector-eks` (`eu-west-1`). Connect:

```powershell
aws eks update-kubeconfig --region eu-west-1 --name car-detector-eks --profile car-detector
```

**Helm install (this account — replace role ARN if yours differs):**

```powershell
helm upgrade --install car-detector ./helm/car-detector `
  -n car-detector --create-namespace `
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=arn:aws:iam::737404990857:role/CarDetectorEksS3Role `
  --set image.repository=737404990857.dkr.ecr.eu-west-1.amazonaws.com/car-detector `
  --set image.tag=15 `
  --set env.S3_BUCKET=cardetectordatastack-cardetectorbucketf3ab59bc-fwx6sufdchpi `
  --set env.S3_VIDEO_KEY=video.mp4 `
  --set env.S3_LABELS_KEY=labels.json `
  --set env.AWS_DEFAULT_REGION=eu-west-1
```

If a Job already exists, delete it before changing the pod template: `kubectl delete job car-detector-car-detector -n car-detector`, then run Helm again.

Generic placeholders (other accounts):

```bash
helm upgrade --install car-detector ./helm/car-detector -n car-detector --create-namespace \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=arn:aws:iam::ACCOUNT_ID:role/YOUR_IRSA_ROLE \
  --set image.repository=ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/car-detector \
  --set image.tag=YOUR_TAG \
  --set env.S3_BUCKET=your-bucket \
  --set env.S3_VIDEO_KEY=video.mp4 \
  --set env.S3_LABELS_KEY=labels.json \
  --set env.AWS_DEFAULT_REGION=eu-west-1
```

Verify:

```powershell
kubectl get jobs -n car-detector
kubectl get pods -n car-detector
kubectl logs -n car-detector -l app.kubernetes.io/name=car-detector --tail=80
```

Expect Job **Complete 1/1** and logs with `Confusion …` and `Metrics written to s3://…`. Completed Job pods may disappear from `kubectl get pods` while the Job remains **Complete**.

## Optional: S3 bucket with AWS CDK (Python)

For IaC, see [`infra/cdk/README.md`](infra/cdk/README.md) — deploys a private, encrypted S3 bucket; optional **ECR** repo; optional **EKS** cluster (`-c enableEks=true`) for Helm/IRSA work. Use the stack output as `S3_BUCKET`.

## License

Use and modify for your DevOps assignment as required by your course or employer.
