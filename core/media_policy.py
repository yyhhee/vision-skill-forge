from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
from PIL import Image

from .registry import OperatorRegistry
from .schema import SkillPackage
from .video_sampling import normalize_end_seconds


@dataclass(frozen=True)
class MediaMetadata:
    media_type: str
    width: int
    height: int
    fps: float | None = None
    frame_count: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class ExecutionPolicy:
    media_type: str
    execution_allowed: bool
    duration_seconds: float | None
    selected_start_seconds: float | None
    selected_end_seconds: float | None
    sampled_frame_count: int
    rex_call_count: int
    estimated_processing_seconds: float
    user_limited: bool
    recommended_limit_exceeded: bool
    warnings: list[str]


def read_media_metadata(path: str | Path) -> MediaMetadata:
    media_path = Path(path)
    suffix = media_path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        with Image.open(media_path) as image:
            width, height = image.size
        return MediaMetadata("image", width, height)
    capture = cv2.VideoCapture(str(media_path))
    if not capture.isOpened():
        raise ValueError(f"cannot open media: {media_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if fps <= 0:
        raise ValueError(f"video reports invalid fps: {fps}")
    return MediaMetadata(
        "video",
        width,
        height,
        fps,
        frame_count,
        frame_count / fps,
    )


def _sample_step(metadata: MediaMetadata, params: dict[str, Any]) -> int:
    if metadata.fps is None:
        return 1
    mode = params.get("mode", "fps")
    if mode == "fps":
        return max(1, round(metadata.fps / float(params.get("fps", 1.0))))
    if mode == "interval":
        return max(
            1,
            round(metadata.fps * float(params.get("interval_seconds", 1.0))),
        )
    if mode == "frame_step":
        return max(1, int(params.get("frame_step", 1)))
    raise ValueError(f"unsupported sampling mode: {mode}")


def _selected_frame_range(
    metadata: MediaMetadata, params: dict[str, Any]
) -> tuple[int, int]:
    if metadata.media_type != "video" or metadata.fps is None:
        return (0, 1)
    frame_count = int(metadata.frame_count or 0)
    start = min(
        frame_count,
        max(0, round(float(params.get("start_seconds", 0.0)) * metadata.fps)),
    )
    raw_end = normalize_end_seconds(params.get("end_seconds"))
    end = frame_count if raw_end is None else min(
        frame_count, max(0, round(float(raw_end) * metadata.fps))
    )
    return start, max(start, end)


def estimate_sampled_frames(
    metadata: MediaMetadata, params: dict[str, Any]
) -> int:
    if metadata.media_type == "image":
        return 1
    start, end = _selected_frame_range(metadata, params)
    count = math.ceil((end - start) / _sample_step(metadata, params))
    max_frames = params.get("max_frames")
    if max_frames is not None:
        count = min(count, int(max_frames))
    return max(0, count)


def _tile_positions_count(length: int, tile: int, overlap: float) -> int:
    if length <= tile:
        return 1
    stride = max(1, round(tile * (1 - overlap)))
    count = len(range(0, length - tile + 1, stride))
    last_regular = (count - 1) * stride
    return count + int(last_regular != length - tile)


def _frame_stats_for_variant(
    package: SkillPackage,
    media_type: str,
    metadata: MediaMetadata,
    registry: OperatorRegistry,
) -> tuple[int, int]:
    variant = package.select_variant(media_type)  # media compatibility is explicit.
    stats: dict[str, tuple[int, int, int]] = {}
    rex_calls = 0
    sampled_frames = 1 if media_type == "image" else 0
    for node in variant.nodes:
        if not node.enabled:
            continue
        definition = registry.require(node.op)
        params = dict(definition.defaults)
        params.update(node.params)
        if node.op.startswith("media.image@"):
            stats[node.id] = (1, metadata.width, metadata.height)
            continue
        if node.op.startswith("video.sample@"):
            sampled_frames = estimate_sampled_frames(metadata, params)
            stats[node.id] = (sampled_frames, metadata.width, metadata.height)
            continue
        frames_ref = node.inputs.get("frames")
        if not isinstance(frames_ref, str) or not frames_ref.startswith("$"):
            continue
        source = stats.get(frames_ref[1:])
        if source is None:
            continue
        count, width, height = source
        if node.op.startswith("image.resize@"):
            mode = params["mode"]
            if mode == "long_side":
                scale = int(params["long_side"]) / max(width, height)
                width, height = max(1, round(width * scale)), max(1, round(height * scale))
            elif mode in {"contain", "stretch"}:
                width, height = int(params["width"]), int(params["height"])
            stats[node.id] = (count, width, height)
        elif node.op.startswith("image.tile@"):
            overlap_x = float(params.get("overlap_x", params.get("overlap", 0.2)))
            overlap_y = float(params.get("overlap_y", params.get("overlap", 0.2)))
            tile_count = _tile_positions_count(
                width, int(params["tile_width"]), overlap_x
            ) * _tile_positions_count(
                height, int(params["tile_height"]), overlap_y
            )
            if params.get("include_full_frame", False):
                tile_count += 1
            stats[node.id] = (
                count * tile_count,
                min(width, int(params["tile_width"])),
                min(height, int(params["tile_height"])),
            )
        else:
            stats[node.id] = source
        if node.op.startswith("rex.ground@"):
            rex_calls += count
    return sampled_frames, rex_calls


def inspect_execution_policy(
    package: SkillPackage,
    media_type: str,
    media: MediaMetadata | str | Path,
    registry: OperatorRegistry,
    *,
    estimated_seconds_per_rex_call: float = 1.0,
) -> ExecutionPolicy:
    metadata = media if isinstance(media, MediaMetadata) else read_media_metadata(media)
    if metadata.media_type != media_type:
        raise ValueError(
            f"selected {media_type} variant cannot execute {metadata.media_type} media"
        )
    sampled_frames, rex_calls = _frame_stats_for_variant(
        package, media_type, metadata, registry
    )
    variant = package.select_variant(media_type)
    sample_node = next(
        (node for node in variant.nodes if node.enabled and node.op.startswith("video.sample@")),
        None,
    )
    params: dict[str, Any] = {}
    if sample_node is not None:
        params.update(registry.require(sample_node.op).defaults)
        params.update(sample_node.params)
    duration = metadata.duration_seconds
    start = None
    end = None
    user_limited = False
    if media_type == "video":
        start = max(0.0, float(params.get("start_seconds", 0.0)))
        configured_end = normalize_end_seconds(params.get("end_seconds"))
        end = duration if configured_end is None else min(
            float(configured_end), duration if duration is not None else float(configured_end)
        )
        user_limited = start > 0 or configured_end is not None or params.get("max_frames") is not None
    recommended = package.input.video_guidance.recommended_max_duration_seconds
    exceeded = bool(
        media_type == "video" and duration is not None and duration > recommended
    )
    warnings = []
    if exceeded:
        warnings.append(
            f"视频时长 {duration:.2f}s 超过 Demo 推荐的 {recommended:g}s；"
            "这是 warn-only 策略，系统不会自动截断或拒绝执行。"
        )
    return ExecutionPolicy(
        media_type=media_type,
        execution_allowed=True,
        duration_seconds=duration,
        selected_start_seconds=start,
        selected_end_seconds=end,
        sampled_frame_count=sampled_frames,
        rex_call_count=rex_calls,
        estimated_processing_seconds=rex_calls * estimated_seconds_per_rex_call,
        user_limited=user_limited,
        recommended_limit_exceeded=exceeded,
        warnings=warnings,
    )


__all__ = [
    "ExecutionPolicy",
    "MediaMetadata",
    "estimate_sampled_frames",
    "inspect_execution_policy",
    "read_media_metadata",
]
