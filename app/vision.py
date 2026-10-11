"""Count people in one image with MobileNet-SSD. The image stays in memory.

Weights are read from PERSON_MODEL_DIR. See data/models/SOURCE.md for the
download URL and the MIT license. This module does not claim a measured accuracy.
"""
from __future__ import annotations

import os
from pathlib import Path

# A small PNG can declare a huge pixel count (0.3 MB -> 100 Mpx -> about 300 MB decoded).
# OpenCV reads this limit lazily, so it must be set before the first decode.
# 40 Mpx still allows a 12 to 48 MP phone photo.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "40000000")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.config import get_settings

# PASCAL VOC class order used by this MobileNet-SSD. 15 is "person".
PERSON_CLASS = 15
CONFIDENCE_MIN = 0.5
INPUT_SIZE = 300
MAX_SIDE = 800
PROTOTXT_NAME = "deploy.prototxt"
WEIGHTS_NAME = "mobilenet_iter_73000.caffemodel"

_net = None
_net_dir: str | None = None


class DetectorUnavailable(Exception):
    """The weight files are missing or PERSON_MODEL_DIR is unset."""


def reset_detector() -> None:
    global _net, _net_dir
    _net = None
    _net_dir = None


def model_paths() -> tuple[Path, Path]:
    directory = Path(get_settings().person_model_dir)
    return directory / PROTOTXT_NAME, directory / WEIGHTS_NAME


def load_net():
    global _net, _net_dir
    directory = get_settings().person_model_dir
    if not directory:
        raise DetectorUnavailable("Person detector is not configured.")
    if _net is not None and _net_dir == directory:
        return _net
    prototxt, weights = model_paths()
    if not prototxt.is_file() or not weights.is_file():
        raise DetectorUnavailable("Person detector is not configured.")
    _net = cv2.dnn.readNetFromCaffe(str(prototxt), str(weights))
    _net_dir = directory
    return _net


def decode_image(data: bytes):
    if not data:
        raise ValueError("not an image")
    array = np.frombuffer(data, dtype=np.uint8)
    try:
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    except cv2.error:
        raise ValueError("not an image") from None
    if image is None or image.size == 0:
        raise ValueError("not an image")
    return image


def _downscale(image):
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= MAX_SIDE:
        return image
    scale = MAX_SIDE / longest
    return cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)


def _iou(a, b) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _keep_boxes(boxes: list[tuple[float, float, float, float, float]]) -> list:
    ordered = sorted(boxes, key=lambda item: item[4], reverse=True)
    kept = []
    for box in ordered:
        if all(_iou(box, other) < 0.45 for other in kept):
            kept.append(box)
    return kept


def count_people(image, net) -> int:
    """How many person boxes the detector returns. Not a hand count."""
    prepared = _downscale(image)
    blob = cv2.dnn.blobFromImage(prepared, 0.007843, (INPUT_SIZE, INPUT_SIZE), 127.5, swapRB=False, crop=False)
    net.setInput(blob)
    detections = net.forward()
    boxes = []
    for index in range(detections.shape[2]):
        confidence = float(detections[0, 0, index, 2])
        class_id = int(detections[0, 0, index, 1])
        if class_id != PERSON_CLASS or confidence < CONFIDENCE_MIN:
            continue
        x1 = min(1.0, max(0.0, float(detections[0, 0, index, 3])))
        y1 = min(1.0, max(0.0, float(detections[0, 0, index, 4])))
        x2 = min(1.0, max(0.0, float(detections[0, 0, index, 5])))
        y2 = min(1.0, max(0.0, float(detections[0, 0, index, 6])))
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append((x1, y1, x2, y2, confidence))
    return len(_keep_boxes(boxes))


def count_image_bytes(data: bytes) -> int:
    image = decode_image(data)
    return count_people(image, load_net())
