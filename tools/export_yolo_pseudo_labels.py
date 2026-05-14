#!/usr/bin/env python3
"""
Export pseudo ground-truth labels from YOLOv8 car detections (normalized xyxy).

Use for pipeline testing only — labels are model predictions, not human GT.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
from ultralytics import YOLO

YOLO_COCO_CAR_CLASS_ID = 2


def main() -> int:
    p = argparse.ArgumentParser(description="YOLO pseudo-labels -> labels.json")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("-o", "--output", type=Path, default=Path("labels.pseudo.json"))
    p.add_argument("--weights", default="yolov8n.pt")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--stride", type=int, default=1, help="Process every Nth frame (1 = all)")
    args = p.parse_args()

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 2

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        print(f"Cannot open video: {args.video}", file=sys.stderr)
        return 2

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
    model = YOLO(args.weights)

    frames_out: list[dict] = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % args.stride != 0:
            i += 1
            continue

        results = model.predict(
            source=frame,
            conf=args.conf,
            classes=[YOLO_COCO_CAR_CLASS_ID],
            verbose=False,
        )[0]
        boxes_norm: list[list[float]] = []
        if results.boxes is not None and len(results.boxes) > 0:
            xyxy = results.boxes.xyxy.cpu().numpy()
            clss = results.boxes.cls.cpu().numpy()
            for j in range(len(xyxy)):
                if int(clss[j]) != YOLO_COCO_CAR_CLASS_ID:
                    continue
                x1, y1, x2, y2 = xyxy[j].tolist()
                boxes_norm.append(
                    [
                        x1 / w,
                        y1 / h,
                        x2 / w,
                        y2 / h,
                    ]
                )
        if boxes_norm:
            frames_out.append({"i": i, "boxes": boxes_norm})
        i += 1

    cap.release()

    payload = {
        "schema": "car-detector/1",
        "note": "pseudo-labels from YOLO export_yolo_pseudo_labels.py — not independent human GT",
        "frames": frames_out,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(frames_out)} labeled frames to {args.output} (video frames scanned: {i})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
