#!/usr/bin/env python3
"""
Build a stratified subset of an existing labels.json (e.g. full pseudo export).

Build a smaller labels file for evaluation on a stratified frame sample;
unlisted frames have no ground truth in the output artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True, help="Full labels.json")
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--stride", type=int, default=20, help="Keep every Nth labeled frame index")
    args = p.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    frames = data.get("frames")
    if not isinstance(frames, list):
        print("Invalid input: missing frames[]", file=sys.stderr)
        return 2

    out_frames: list[dict] = []
    for entry in frames:
        if not isinstance(entry, dict):
            continue
        i = int(entry.get("i", entry.get("frame", -1)))
        if i < 0:
            continue
        if i % args.stride != 0:
            continue
        boxes = entry.get("boxes", [])
        if isinstance(boxes, list) and boxes:
            out_frames.append({"i": i, "boxes": boxes})

    payload = {
        "schema": "car-detector/1",
        "labeling_method": "stratified_subset",
        "labeling_note": (
            "Subset: every nth frame from a referee export (YOLOv8n car-only, conf=0.25). "
            "Frames not listed have no ground-truth boxes in this file. "
            "For production independent GT, use human annotation (CVAT/Label Studio)."
        ),
        "subset_stride": args.stride,
        "source_file": args.input.name,
        "frames": out_frames,
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(out_frames)} frames to {args.output} (stride={args.stride})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
