from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "imgs"
OUTPUT = ROOT / "data" / "demo_media"
VIDEO_IDS = ["P01", "P02", "P04", "P05", "P06", "P07", "P12"]


def image_for(preset_id: str) -> Path:
    return next(IMAGES.glob(f"{preset_id}*"))


def wrong_way_frame(image: np.ndarray, frame_index: int) -> np.ndarray:
    height, width = image.shape[:2]
    yy, xx = np.indices((height, width), dtype=np.float32)
    divider = width * (0.12 + 0.43 * yy / max(1, height - 1))
    shift = float(frame_index * 12)
    source_x = np.where(xx < divider, xx - shift, xx + shift)
    return cv2.remap(image, source_x, yy, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for preset_id in VIDEO_IDS:
        image = cv2.imread(str(image_for(preset_id)))
        if image is None:
            raise ValueError(f"cannot read source image for {preset_id}")
        if preset_id == "P05":
            image = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        height, width = image.shape[:2]
        path = OUTPUT / f"{preset_id}.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 2.0, (width, height))
        if not writer.isOpened():
            raise ValueError(f"cannot create {path}")
        frame_count = 6 if preset_id == "P05" else 4
        for index in range(frame_count):
            frame = wrong_way_frame(image, index) if preset_id == "P05" else image
            writer.write(frame)
        writer.release()
    for preset_id in ["P03", "P08", "P09", "P10", "P11", "P13"]:
        source = image_for(preset_id)
        target = OUTPUT / f"{preset_id}{source.suffix.lower()}"
        target.write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()
