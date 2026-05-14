"""
Car-only YOLOv8 video evaluation: S3 video + labels -> metrics -> S3.

Label file (JSON in S3): see README "Label format".
Metrics: frame-level 2x2 confusion (car present vs predicted), box-level TP/FP/FN
with IoU matching, precision/recall/accuracy.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import cv2
import numpy as np
from botocore.exceptions import ClientError
from ultralytics import YOLO

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOG = logging.getLogger("car-detector")

# COCO class index for "car" in default YOLOv8 COCO weights
YOLO_COCO_CAR_CLASS_ID = 2


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is not None and v != "":
        return v
    return default


def _env_bool(name: str, default: bool = True) -> bool:
    v = os.environ.get(name)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def iou_xyxy(a: np.ndarray, b: np.ndarray) -> float:
    """a, b: (4,) xyxy pixel coords."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return float(inter / union)


def shrink_gt_boxes_xyxy(boxes: list[np.ndarray], edge_frac: float) -> list[np.ndarray]:
    """
    Inset each GT box by edge_frac times its width (x) and height (y) on each side.
    Simulates loose human boxes vs tight model boxes; lowers IoU when preds match
    pseudo-GT exactly. edge_frac 0 returns unchanged copies.
    """
    if edge_frac <= 0:
        return [np.copy(b) for b in boxes]
    ef = min(float(edge_frac), 0.45)
    out: list[np.ndarray] = []
    for b in boxes:
        x1, y1, x2, y2 = float(b[0]), float(b[1]), float(b[2]), float(b[3])
        w = max(0.0, x2 - x1)
        h = max(0.0, y2 - y1)
        ix, iy = w * ef, h * ef
        nx1, ny1 = x1 + ix, y1 + iy
        nx2, ny2 = x2 - ix, y2 - iy
        if nx2 <= nx1 + 1e-6 or ny2 <= ny1 + 1e-6:
            out.append(np.copy(b))
            continue
        out.append(np.array([nx1, ny1, nx2, ny2], dtype=np.float64))
    return out


def _labeled_box_iou_default(iou_main: float) -> float:
    """
    Default IoU bar for labeled-only matching (unset LABELED_BOX_IOU).
    Tuned with default LABELED_GT_SHRINK (0.01) so pseudo-label self-eval is
    stricter than global IOU_THRESHOLD but not so tight that every match fails.
    """
    return float(min(0.96, max(0.85, iou_main + 0.35)))


def load_labels_json(path: Path) -> dict[int, list[list[float]]]:
    """
    Parse labels JSON. Each frame maps to a list of boxes [x1,y1,x2,y2] (normalized or pixels — see flag).
    Missing frame indices default to no boxes.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    frames_spec = raw.get("frames")
    if not isinstance(frames_spec, list):
        raise ValueError("labels JSON must contain key 'frames' as a list")

    per_frame: dict[int, list[list[float]]] = {}
    for entry in frames_spec:
        if not isinstance(entry, dict):
            continue
        idx = int(entry.get("i", entry.get("frame", -1)))
        if idx < 0:
            continue
        boxes = entry.get("boxes", [])
        if not isinstance(boxes, list):
            continue
        out: list[list[float]] = []
        for b in boxes:
            if isinstance(b, (list, tuple)) and len(b) == 4:
                out.append([float(x) for x in b])
        per_frame[idx] = out
    return per_frame


def normalize_boxes_to_pixels(
    boxes: list[list[float]], w: int, h: int, normalized: bool
) -> list[np.ndarray]:
    res: list[np.ndarray] = []
    for b in boxes:
        x1, y1, x2, y2 = b
        if normalized:
            x1, x2 = x1 * w, x2 * w
            y1, y2 = y1 * h, y2 * h
        res.append(np.array([x1, y1, x2, y2], dtype=np.float64))
    return res


def match_frame(
    gt_boxes: list[np.ndarray],
    pred_boxes: list[np.ndarray],
    pred_scores: list[float],
    iou_threshold: float,
) -> tuple[int, int, int]:
    """
    Greedy match by descending score. Returns TP, FP, FN for this frame.
    """
    if not pred_boxes and not gt_boxes:
        return 0, 0, 0
    if not pred_boxes:
        return 0, 0, len(gt_boxes)
    if not gt_boxes:
        return 0, len(pred_boxes), 0

    order = sorted(range(len(pred_boxes)), key=lambda i: pred_scores[i], reverse=True)
    gt_used = [False] * len(gt_boxes)
    tp = 0
    fp = 0
    for pi in order:
        best_j = -1
        best_iou = 0.0
        for j in range(len(gt_boxes)):
            if gt_used[j]:
                continue
            iou = iou_xyxy(pred_boxes[pi], gt_boxes[j])
            if iou > best_iou:
                best_iou = iou
                best_j = j
        if best_j >= 0 and best_iou >= iou_threshold:
            gt_used[best_j] = True
            tp += 1
        else:
            fp += 1
    fn = sum(1 for u in gt_used if not u)
    return tp, fp, fn


def _metrics_gate_box_mode() -> str:
    raw = (os.environ.get("METRICS_GATE_BOX_METRICS") or "global").strip().lower()
    if raw in ("global", "labeled"):
        return raw
    LOG.warning("Invalid METRICS_GATE_BOX_METRICS=%r, using global", raw)
    return "global"


@dataclass
class RunConfig:
    bucket: str
    video_key: str
    labels_key: str
    output_prefix: str
    region: str
    weights: str
    conf_threshold: float
    iou_threshold: float
    labels_normalized: bool
    labeled_gt_shrink: float
    labeled_box_iou: float
    metrics_gate_box: str
    min_precision: float | None
    min_recall: float | None
    min_accuracy: float | None
    frame_cm_annotated_only: bool


def parse_args() -> RunConfig:
    p = argparse.ArgumentParser(description="YOLOv8 car-only video metrics (S3)")
    p.add_argument("--bucket", default=_env("S3_BUCKET"), help="S3 bucket (env S3_BUCKET)")
    p.add_argument("--video-key", default=_env("S3_VIDEO_KEY"), help="env S3_VIDEO_KEY")
    p.add_argument("--labels-key", default=_env("S3_LABELS_KEY"), help="env S3_LABELS_KEY")
    p.add_argument(
        "--output-prefix",
        default=_env("S3_OUTPUT_PREFIX", "runs/"),
        help="Prefix for metrics JSON in bucket (env S3_OUTPUT_PREFIX)",
    )
    p.add_argument("--region", default=_env("AWS_DEFAULT_REGION", "us-east-1"))
    p.add_argument("--weights", default=_env("YOLO_WEIGHTS", "yolov8n.pt"))
    p.add_argument("--conf", type=float, default=float(_env("CONF_THRESHOLD", "0.35")))
    p.add_argument("--iou", type=float, default=float(_env("IOU_THRESHOLD", "0.5")))
    p.add_argument(
        "--labels-normalized",
        action=argparse.BooleanOptionalAction,
        default=_env("LABELS_NORMALIZED", "true").lower() in ("1", "true", "yes"),
    )
    p.add_argument("--min-precision", type=float, default=None)
    p.add_argument("--min-recall", type=float, default=None)
    p.add_argument("--min-accuracy", type=float, default=None)
    args = p.parse_args()

    def thr(name: str) -> float | None:
        v = _env(name)
        if v is None or v == "":
            return None
        return float(v)

    _sh = _env("LABELED_GT_SHRINK", "0.01")
    labeled_gt_shrink = float(_sh) if _sh is not None else 0.01
    _lio = _env("LABELED_BOX_IOU")
    labeled_box_iou = (
        float(_lio) if _lio is not None and _lio != "" else _labeled_box_iou_default(args.iou)
    )

    return RunConfig(
        bucket=args.bucket or "",
        video_key=args.video_key or "",
        labels_key=args.labels_key or "",
        output_prefix=args.output_prefix.rstrip("/") + "/",
        region=args.region,
        weights=args.weights,
        conf_threshold=args.conf,
        iou_threshold=args.iou,
        labels_normalized=args.labels_normalized,
        labeled_gt_shrink=labeled_gt_shrink,
        labeled_box_iou=labeled_box_iou,
        metrics_gate_box=_metrics_gate_box_mode(),
        min_precision=args.min_precision if args.min_precision is not None else thr("MIN_PRECISION"),
        min_recall=args.min_recall if args.min_recall is not None else thr("MIN_RECALL"),
        min_accuracy=args.min_accuracy if args.min_accuracy is not None else thr("MIN_ACCURACY"),
        frame_cm_annotated_only=_env_bool("FRAME_CM_ANNOTATED_FRAMES_ONLY", True),
    )


def s3_download(s3: Any, bucket: str, key: str, dest: Path) -> None:
    LOG.info("Downloading s3://%s/%s -> %s", bucket, key, dest)
    try:
        s3.download_file(bucket, key, str(dest))
    except ClientError as e:
        LOG.error("S3 download failed: %s", e)
        raise


def s3_upload(s3: Any, bucket: str, key: str, path: Path, content_type: str) -> None:
    LOG.info("Uploading %s -> s3://%s/%s", path, bucket, key)
    extra = {"ContentType": content_type}
    s3.upload_file(str(path), bucket, key, ExtraArgs=extra)


def main() -> int:
    cfg = parse_args()
    if not cfg.bucket or not cfg.video_key or not cfg.labels_key:
        LOG.error("Set --bucket/--video-key/--labels-key or S3_BUCKET, S3_VIDEO_KEY, S3_LABELS_KEY")
        return 2

    session = boto3.session.Session(region_name=cfg.region)
    s3 = session.client("s3")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        video_path = tmp_path / "input.mp4"
        labels_path = tmp_path / "labels.json"
        metrics_path = tmp_path / "metrics.json"

        s3_download(s3, cfg.bucket, cfg.video_key, video_path)
        s3_download(s3, cfg.bucket, cfg.labels_key, labels_path)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            LOG.error("Could not open video: %s", video_path)
            return 2
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        LOG.info("Video frames=%s size=%sx%s fps=%s", n_frames, width, height, fps)

        labels_map = load_labels_json(labels_path)
        if cfg.frame_cm_annotated_only and not labels_map:
            LOG.error(
                "FRAME_CM_ANNOTATED_FRAMES_ONLY=true but labels JSON has no frame entries"
            )
            return 2

        model = YOLO(cfg.weights)

        # Aggregates (all frames — sparse GT inflates FP on unlabeled frames)
        box_tp = box_fp = box_fn = 0
        # Same IoU matching, but only frames where GT has ≥1 car box (fairer precision/recall)
        lab_box_tp = lab_box_fp = lab_box_fn = 0
        labeled_frames_with_gt = 0
        # Frame-level binary: car in GT vs predicted car (any det above conf).
        # When frame_cm_annotated_only, only frames listed in labels.json count (fair sparse labels).
        cm_tn = cm_fp = cm_fn = cm_tp = 0

        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            gt_pixels = normalize_boxes_to_pixels(
                labels_map.get(frame_idx, []), w, h, cfg.labels_normalized
            )

            results = model.predict(
                source=frame,
                conf=cfg.conf_threshold,
                classes=[YOLO_COCO_CAR_CLASS_ID],
                verbose=False,
            )[0]
            pred_boxes: list[np.ndarray] = []
            pred_scores: list[float] = []
            if results.boxes is not None and len(results.boxes) > 0:
                xyxy = results.boxes.xyxy.cpu().numpy()
                confs = results.boxes.conf.cpu().numpy()
                clss = results.boxes.cls.cpu().numpy()
                for i in range(len(xyxy)):
                    if int(clss[i]) != YOLO_COCO_CAR_CLASS_ID:
                        continue
                    pred_boxes.append(xyxy[i].astype(np.float64))
                    pred_scores.append(float(confs[i]))

            tp, fp, fn = match_frame(gt_pixels, pred_boxes, pred_scores, cfg.iou_threshold)
            box_tp += tp
            box_fp += fp
            box_fn += fn

            if len(gt_pixels) > 0:
                labeled_frames_with_gt += 1
                if cfg.labeled_gt_shrink > 0:
                    gt_labeled = shrink_gt_boxes_xyxy(gt_pixels, cfg.labeled_gt_shrink)
                else:
                    gt_labeled = gt_pixels
                tp_l, fp_l, fn_l = match_frame(
                    gt_labeled, pred_boxes, pred_scores, cfg.labeled_box_iou
                )
                lab_box_tp += tp_l
                lab_box_fp += fp_l
                lab_box_fn += fn_l

            include_frame_cm = (not cfg.frame_cm_annotated_only) or (frame_idx in labels_map)
            if include_frame_cm:
                gt_has = len(gt_pixels) > 0
                pred_has = len(pred_boxes) > 0
                if gt_has and pred_has:
                    cm_tp += 1
                elif not gt_has and pred_has:
                    cm_fp += 1
                elif gt_has and not pred_has:
                    cm_fn += 1
                else:
                    cm_tn += 1

            frame_idx += 1
            if n_frames > 0 and frame_idx >= n_frames:
                break

        cap.release()

        total_frames = cm_tp + cm_fp + cm_fn + cm_tn
        denom_pr = box_tp + box_fp
        denom_re = box_tp + box_fn
        precision = (box_tp / denom_pr) if denom_pr > 0 else 1.0 if box_fn == 0 else 0.0
        recall = (box_tp / denom_re) if denom_re > 0 else 1.0 if denom_pr == 0 else 0.0
        accuracy_frames = (cm_tp + cm_tn) / total_frames if total_frames > 0 else 0.0
        box_denom = box_tp + box_fp + box_fn
        accuracy_boxes = box_tp / box_denom if box_denom > 0 else 0.0

        lab_pr_d = lab_box_tp + lab_box_fp
        lab_re_d = lab_box_tp + lab_box_fn
        precision_labeled = (
            (lab_box_tp / lab_pr_d) if lab_pr_d > 0 else (1.0 if lab_box_fn == 0 else 0.0)
        )
        recall_labeled = (
            (lab_box_tp / lab_re_d) if lab_re_d > 0 else (1.0 if lab_pr_d == 0 else 0.0)
        )
        lab_box_denom = lab_box_tp + lab_box_fp + lab_box_fn
        accuracy_boxes_labeled = (
            lab_box_tp / lab_box_denom if lab_box_denom > 0 else 0.0
        )

        confusion_frame = {
            "labels_rows": ["actual_no_car", "actual_car"],
            "labels_cols": ["pred_no_car", "pred_car"],
            "matrix": [[cm_tn, cm_fp], [cm_fn, cm_tp]],
        }

        run_id = os.environ.get("BUILD_ID") or os.environ.get("CI_PIPELINE_ID")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_name = f"{cfg.output_prefix}{run_id + '_' if run_id else ''}{stamp}/metrics.json"

        payload: dict[str, Any] = {
            "schema": "car-detector-metrics/1",
            "generated_at_utc": stamp,
            "video_key": cfg.video_key,
            "labels_key": cfg.labels_key,
            "weights": cfg.weights,
            "conf_threshold": cfg.conf_threshold,
            "iou_match_threshold": cfg.iou_threshold,
            "labeled_box_iou_threshold": cfg.labeled_box_iou,
            "labeled_gt_shrink_edge_fraction": cfg.labeled_gt_shrink,
            "metrics_gate_box_precision_recall": cfg.metrics_gate_box,
            "frame_cm_scope": (
                "label_file_frames_only"
                if cfg.frame_cm_annotated_only
                else "all_video_frames"
            ),
            "label_file_frame_index_count": len(labels_map),
            "frames_in_frame_confusion_matrix": cm_tp + cm_fp + cm_fn + cm_tn,
            "frames_evaluated": frame_idx,
            "video_reported_frame_count": n_frames,
            "confusion_matrix_frame_car_presence": confusion_frame,
            "box_counts": {"TP": box_tp, "FP": box_fp, "FN": box_fn},
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "accuracy_frame_car_presence": round(accuracy_frames, 6),
            "accuracy_box_detection": round(accuracy_boxes, 6),
            "labeled_frames_with_gt_boxes": labeled_frames_with_gt,
            "box_counts_labeled_frames_only": {
                "TP": lab_box_tp,
                "FP": lab_box_fp,
                "FN": lab_box_fn,
            },
            "precision_labeled_frames_only": round(precision_labeled, 6),
            "recall_labeled_frames_only": round(recall_labeled, 6),
            "accuracy_box_detection_labeled_frames_only": round(accuracy_boxes_labeled, 6),
            "notes": (
                "precision/recall/accuracy_box_detection use IoU-matched car boxes on all frames "
                "(sparse labels: many FPs on frames with no GT). "
                "precision_labeled_frames_only / recall_labeled_frames_only / "
                "accuracy_box_detection_labeled_frames_only use frames with ≥1 GT box only, "
                "with GT boxes inset by labeled_gt_shrink_edge_fraction (simulates annotation "
                "tolerance; 0 disables inset) and IoU threshold labeled_box_iou_threshold (stricter "
                "than the global iou_match_threshold unless overridden). "
                "accuracy_frame_car_presence uses frame-level car presence vs any car prediction. "
                "When FRAME_CM_ANNOTATED_FRAMES_ONLY=true (default), that confusion matrix only "
                "includes frames that appear in labels.json, so sparse labels do not treat every "
                "unlisted frame as 'no car' ground truth."
            ),
        }

        metrics_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        s3_upload(s3, cfg.bucket, out_name, metrics_path, "application/json")

        cm_scope = (
            "label-file frames only"
            if cfg.frame_cm_annotated_only
            else "all video frames"
        )
        LOG.info(
            "Confusion (frame car presence, %s): TN=%s FP=%s FN=%s TP=%s",
            cm_scope,
            cm_tn,
            cm_fp,
            cm_fn,
            cm_tp,
        )
        LOG.info("Box TP=%s FP=%s FN=%s", box_tp, box_fp, box_fn)
        LOG.info("Precision=%s Recall=%s Accuracy(frame)=%s Accuracy(box)=%s", precision, recall, accuracy_frames, accuracy_boxes)
        LOG.info(
            "(Labeled frames only, inset-GT + stricter IoU) TP=%s FP=%s FN=%s Prec=%s Rec=%s Acc(box)=%s",
            lab_box_tp,
            lab_box_fp,
            lab_box_fn,
            round(precision_labeled, 6),
            round(recall_labeled, 6),
            round(accuracy_boxes_labeled, 6),
        )
        LOG.info("Metrics written to s3://%s/%s", cfg.bucket, out_name)

        if cfg.metrics_gate_box == "labeled" and labeled_frames_with_gt == 0:
            LOG.error(
                "METRICS_GATE_BOX_METRICS=labeled but no labeled frames have >=1 GT box"
            )
            return 1

        prec_gate = precision_labeled if cfg.metrics_gate_box == "labeled" else precision
        rec_gate = recall_labeled if cfg.metrics_gate_box == "labeled" else recall

        failed = False
        if cfg.min_precision is not None and prec_gate < cfg.min_precision:
            LOG.error(
                "Precision %s < required %s (gate uses %s box metrics)",
                prec_gate,
                cfg.min_precision,
                cfg.metrics_gate_box,
            )
            failed = True
        if cfg.min_recall is not None and rec_gate < cfg.min_recall:
            LOG.error(
                "Recall %s < required %s (gate uses %s box metrics)",
                rec_gate,
                cfg.min_recall,
                cfg.metrics_gate_box,
            )
            failed = True
        if cfg.min_accuracy is not None:
            # Gate on frame-level accuracy by default when MIN_ACCURACY set
            if accuracy_frames < cfg.min_accuracy:
                LOG.error("Accuracy(frame) %s < required %s", accuracy_frames, cfg.min_accuracy)
                failed = True
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
