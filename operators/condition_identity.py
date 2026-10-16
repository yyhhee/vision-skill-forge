"""Explicit identity binding for temporal conditions; never guess key types."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Any

from core.context import ConditionSet, TimedValue


def entity_identity(entity: Any) -> dict[str, Any]:
    """Carry real object/track identity when projecting an entity to a condition."""
    metadata = dict(getattr(entity, "metadata", {}) or {})
    track_id = getattr(entity, "track_id", None)
    if hasattr(entity, "history"):
        track_id = entity.id
    if track_id:
        metadata["track_id"] = track_id
    if hasattr(entity, "bbox") or hasattr(entity, "history"):
        metadata["object_id"] = track_id or entity.id
    if hasattr(entity, "subject_id") and hasattr(entity, "object_id"):
        metadata.update(
            subject_id=entity.subject_id,
            object_id=entity.object_id,
            pair_id=f"{entity.subject_id}|{entity.object_id}",
        )
    return metadata


def bind_condition_identity(condition: ConditionSet, scope: str) -> ConditionSet:
    """Group truth by a typed identity, rejecting missing IDs instead of guessing.

    ``source`` retains historical upstream keys. Explicit scopes must bind
    actual metadata fields so a UI identity option cannot silently be a no-op.
    """
    if scope == "source":
        return condition
    if scope not in {"global", "object", "track", "pair", "region"}:
        raise ValueError(f"不支持的时间身份范围：{scope}")
    grouped: dict[tuple[str, float, int | None], list[TimedValue]] = {}
    identities: dict[str, dict[str, Any]] = {}
    bounds: dict[str, tuple[float, float]] = {}
    frames = {(item.timestamp, item.frame_index) for item in condition.items}
    for item in condition.items:
        metadata = dict(item.metadata)
        if scope == "global":
            key = "global"
            identity = {}
        else:
            field = f"{scope}_id"
            key = metadata.get(field)
            if key is None and metadata.get("scope_type") == scope:
                key = item.key
            if (
                key is None
                and scope == "pair"
                and metadata.get("subject_id") is not None
                and metadata.get("object_id") is not None
            ):
                key = f"{metadata['subject_id']}|{metadata['object_id']}"
            if key is None or key == "":
                raise ValueError(
                    f"时间约束选择了 {scope}，但来源缺少 {field} 身份；请先配置相应目标、轨迹、目标对或区域来源，不能使用全局结果代替。"
                )
            key = str(key)
            identity = {field: key, "identity_scope": scope}
        identities[key] = identity
        first, last = bounds.get(key, (item.timestamp, item.timestamp))
        bounds[key] = min(first, item.timestamp), max(last, item.timestamp)
        grouped.setdefault((key, item.timestamp, item.frame_index), []).append(item)
    output = []
    ordered_frames = sorted(frames, key=lambda frame: (frame[0], frame[1] or 0))
    timestamps = [timestamp for timestamp, _ in ordered_frames]
    for key, identity in sorted(identities.items()):
        # Pad missing observations only inside this identity's observed life.
        # Per-frame object IDs must not create keys x whole-video frames.
        first, last = bounds[key]
        active_frames = ordered_frames[
            bisect_left(timestamps, first) : bisect_right(timestamps, last)
        ]
        for timestamp, frame_index in active_frames:
            samples = grouped.get((key, timestamp, frame_index), [])
            metadata = (
                {**merge_condition_metadata(samples), **identity}
                if scope != "global"
                else identity
            )
            output.append(
                TimedValue(
                    key,
                    timestamp,
                    any(bool(item.value) for item in samples),
                    frame_index,
                    metadata,
                )
            )
    return ConditionSet(output)


def merge_condition_metadata(items: list[TimedValue]) -> dict[str, Any]:
    """Retain non-conflicting identity/evidence fields for same-key logic."""
    metadata: dict[str, Any] = {}
    conflicting = set()
    for item in items:
        for field, value in item.metadata.items():
            if field in metadata and metadata[field] != value:
                conflicting.add(field)
            else:
                metadata[field] = value
    return {
        field: value for field, value in metadata.items() if field not in conflicting
    }
