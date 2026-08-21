from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from core.media_policy import (
    MediaMetadata,
    estimate_sampled_frames,
    inspect_execution_policy,
)
from core.registry import build_default_registry
from core.schema import SkillPackage


def _package(nodes: list[dict], *, recommended_seconds: float = 30.0) -> SkillPackage:
    return SkillPackage.model_validate(
        {
            "schema_version": "2.0",
            "skill_id": "media_policy_demo",
            "version": 1,
            "display_name": "媒体策略演示",
            "original_instruction": "检测车辆",
            "input": {
                "requested_accept": ["video"],
                "accept": ["video"],
                "video_guidance": {
                    "recommended_max_duration_seconds": recommended_seconds,
                    "enforcement": "warn_only",
                },
            },
            "semantic_ir": {
                "schema_version": "1.0",
                "mode": "direct_grounding",
                "target": {
                    "concept": "vehicle",
                    "source_span": "车辆",
                    "phrases": ["vehicle"],
                },
                "constraints": [],
                "logic": "all",
                "unresolved": [],
                "semantic_hash": "a" * 64,
            },
            "variants": {
                "video": {
                    "media_type": "video",
                    "status": "executable",
                    "nodes": nodes,
                    "outputs": {"objects": "$objects"},
                }
            },
        }
    )


def _nodes(sample_params: dict, *, tiled: bool = False) -> list[dict]:
    nodes = [
        {
            "id": "media",
            "op": "media.video@1.0",
            "inputs": {"media": "$input"},
            "params": {},
        },
        {
            "id": "frames",
            "op": "video.sample@1.1",
            "inputs": {"video": "$media"},
            "params": sample_params,
        },
    ]
    frames_ref = "$frames"
    if tiled:
        nodes.append(
            {
                "id": "tiles",
                "op": "image.tile@1.0",
                "inputs": {"frames": "$frames"},
                "params": {
                    "tile_width": 40,
                    "tile_height": 40,
                    "overlap": 0.5,
                    "include_full_frame": True,
                },
            }
        )
        frames_ref = "$tiles"
    nodes.append(
        {
            "id": "objects",
            "op": "rex.ground@1.0",
            "inputs": {"frames": frames_ref},
            "params": {
                "targets": [{"label": "车辆", "phrases": ["vehicle"]}]
            },
        }
    )
    return nodes


def test_sampling_estimate_supports_all_three_explicit_modes():
    metadata = MediaMetadata(
        media_type="video",
        width=100,
        height=60,
        fps=10.0,
        frame_count=100,
        duration_seconds=10.0,
    )

    assert estimate_sampled_frames(
        metadata,
        {"mode": "fps", "fps": 2.0, "start_seconds": 1.0, "end_seconds": 4.0},
    ) == 6
    assert estimate_sampled_frames(
        metadata,
        {
            "mode": "interval",
            "interval_seconds": 0.5,
            "start_seconds": 1.0,
            "end_seconds": 4.0,
        },
    ) == 6
    assert estimate_sampled_frames(
        metadata,
        {"mode": "frame_step", "frame_step": 4, "max_frames": 7},
    ) == 7


def test_over_30_seconds_is_warn_only_and_never_an_implicit_clip():
    metadata = MediaMetadata(
        media_type="video",
        width=100,
        height=60,
        fps=2.0,
        frame_count=80,
        duration_seconds=40.0,
    )
    package = _package(_nodes({"mode": "fps", "fps": 2.0}))

    policy = inspect_execution_policy(
        package, "video", metadata, build_default_registry()
    )

    assert policy.execution_allowed is True
    assert policy.sampled_frame_count == 80
    assert policy.selected_start_seconds == 0.0
    assert policy.selected_end_seconds == 40.0
    assert policy.user_limited is False
    assert policy.recommended_limit_exceeded is True
    assert policy.warnings
    assert "不会自动截断" in policy.warnings[0]


def test_user_selected_segment_is_explicit_and_call_estimate_counts_tiles():
    metadata = MediaMetadata(
        media_type="video",
        width=100,
        height=60,
        fps=2.0,
        frame_count=80,
        duration_seconds=40.0,
    )
    package = _package(
        _nodes(
            {
                "mode": "interval",
                "interval_seconds": 0.5,
                "start_seconds": 5.0,
                "end_seconds": 10.0,
            },
            tiled=True,
        )
    )

    policy = inspect_execution_policy(
        package, "video", metadata, build_default_registry()
    )

    # 5 秒片段、每 0.5 秒一帧；100x60 经 40x40/50% overlap 为 8 个切片 + 1 全图。
    assert policy.sampled_frame_count == 10
    assert policy.rex_call_count == 90
    assert policy.user_limited is True
    assert policy.selected_start_seconds == 5.0
    assert policy.selected_end_seconds == 10.0


def test_call_estimate_supports_v11_tiles_with_axis_specific_overlap():
    metadata = MediaMetadata(
        media_type="video",
        width=100,
        height=60,
        fps=2.0,
        frame_count=4,
        duration_seconds=2.0,
    )
    nodes = _nodes({"mode": "fps", "fps": 2.0}, tiled=False)
    nodes.insert(
        2,
        {
            "id": "tiles",
            "op": "image.tile@1.1",
            "inputs": {"frames": "$frames"},
            "params": {
                "tile_width": 40,
                "tile_height": 40,
                "overlap_x": 0.5,
                "overlap_y": 0.0,
                "include_full_frame": True,
            },
        },
    )
    nodes[-1]["inputs"]["frames"] = "$tiles"
    package = _package(nodes)

    policy = inspect_execution_policy(
        package, "video", metadata, build_default_registry()
    )

    # 水平方向 4 块，垂直方向 2 块，再加 1 张全图；4 帧共 36 次 Rex 调用。
    assert policy.sampled_frame_count == 4
    assert policy.rex_call_count == 36


def test_policy_can_read_real_video_metadata(tmp_path: Path):
    path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 2.0, (100, 60)
    )
    assert writer.isOpened()
    for _ in range(8):
        writer.write(np.zeros((60, 100, 3), dtype=np.uint8))
    writer.release()

    package = _package(_nodes({"mode": "frame_step", "frame_step": 2}))
    policy = inspect_execution_policy(
        package, "video", path, build_default_registry()
    )

    assert policy.duration_seconds == 4.0
    assert policy.sampled_frame_count == 4
    assert policy.rex_call_count == 4
    assert policy.warnings == []
