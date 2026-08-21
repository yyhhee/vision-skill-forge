from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from core.media_assets import MediaAssetStore


def test_image_ingest_preserves_original_bytes_and_deduplicates_by_sha256(tmp_path):
    source = tmp_path / "施工现场.png"
    Image.new("RGB", (83, 47), (20, 80, 140)).save(source)
    original = source.read_bytes()
    store = MediaAssetStore(tmp_path / "assets")

    first = store.ingest(source)
    second = store.ingest(source)

    assert first.asset_id == second.asset_id
    assert first.stored_path == second.stored_path
    assert Path(first.stored_path).read_bytes() == original
    assert first.media_type == "image"
    assert (first.width, first.height) == (83, 47)
    assert first.fps is None
    assert len(list((tmp_path / "assets").glob("*/original.*"))) == 1
    persisted = json.loads(
        (Path(first.stored_path).parent / "metadata.json").read_text("utf-8")
    )
    assert persisted["asset_id"] == first.asset_id
    assert persisted["original_name"] == "施工现场.png"


def test_video_ingest_preserves_original_fps_size_frames_and_bytes(tmp_path):
    source = tmp_path / "traffic.avi"
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (96, 54)
    )
    for index in range(7):
        writer.write(np.full((54, 96, 3), index * 20, dtype=np.uint8))
    writer.release()
    original = source.read_bytes()

    asset = MediaAssetStore(tmp_path / "assets").ingest(source)

    assert Path(asset.stored_path).read_bytes() == original
    assert asset.media_type == "video"
    assert (asset.width, asset.height) == (96, 54)
    assert asset.fps == 5.0
    assert asset.frame_count == 7
    assert asset.duration_seconds == 1.4

