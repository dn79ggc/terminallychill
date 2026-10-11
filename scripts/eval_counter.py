"""Report counter error against hand-counted photos.

This script does not download pictures and does not invent counts.
Supply data/eval/hand_counts.json (see hand_counts.example.json) before expecting a number.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "data" / "eval" / "hand_counts.json"


def main() -> int:
    if not MANIFEST.is_file():
        print("No hand-counted photos have been supplied.")
        print(f"Add them to {MANIFEST.name} when they exist. This script does not invent counts.")
        print("The field list is in data/eval/hand_counts.example.json.")
        return 0
    photos = json.loads(MANIFEST.read_text(encoding="utf-8")).get("photos") or []
    if not photos:
        print("hand_counts.json has no photos. No accuracy number was computed.")
        return 0

    from app.vision import DetectorUnavailable, count_image_bytes

    rows = []
    for item in photos:
        missing = [key for key in ("file", "count", "url", "license") if key not in item]
        if missing or isinstance(item.get("count"), bool) or not isinstance(item.get("count"), int) or item["count"] < 0:
            print("A photo entry is missing a hand count, file, url, or license. No accuracy number was computed.")
            return 1
        path = Path(item["file"])
        if not path.is_file():
            path = ROOT / item["file"]
        if not path.is_file():
            print(f"Missing photo file {item['file']}. No accuracy number was computed.")
            return 1
        rows.append((path, item))

    errors = []
    for path, item in rows:
        try:
            predicted = count_image_bytes(path.read_bytes())
        except DetectorUnavailable:
            print("Person detector is not configured. Set PERSON_MODEL_DIR. No accuracy number was computed.")
            return 1
        hand = item["count"]
        errors.append(predicted - hand)
        note = item.get("note") or ""
        print(f"{path.name}\thand {hand}\tcounted {predicted}\terror {predicted - hand}\t{item['license']}\t{note}")

    mae = sum(abs(value) for value in errors) / len(errors)
    bias = sum(errors) / len(errors)
    print(f"photos\t{len(errors)}")
    print(f"mean_absolute_error\t{mae:.2f}")
    print(f"mean_bias_counted_minus_hand\t{bias:.2f}")
    print("Bias is counted minus the hand count. Positive means the detector counted too many people.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
