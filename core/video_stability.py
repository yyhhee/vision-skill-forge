from __future__ import annotations

from copy import deepcopy

from .schema import SkillPackage
from .validator import assert_valid_skill_package
from .registry import OperatorRegistry


def confirm_variant_objects(
    draft,
    *,
    track_id: str = "result_tracks",
    confirm_id: str = "confirmed_tracks",
    objects_id: str = "confirmed_objects",
    min_hits: int = 2,
    min_span_seconds: float = 0.5,
    iou_threshold: float = 0.2,
    max_missing_frames: int = 1,
):
    """Return a copied VariantDraft with explicit stable-video publication.

    The input object's declared result is tracked, confirmed, and converted
    back to boxes.  The transform is category-agnostic and has no hidden
    runtime behavior.
    """

    from .preset_factory import VariantDraft

    updated = deepcopy(draft)
    nodes = updated.nodes
    existing_ids = {item["id"] for item in nodes}
    if existing_ids & {track_id, confirm_id, objects_id}:
        raise ValueError("track confirmation node id already exists")
    objects_ref = updated.outputs.get("objects")
    if not objects_ref:
        raise ValueError("variant has no objects output")
    draw = next((item for item in nodes if item["op"] == "output.draw@1.0"), None)
    if draw is None:
        raise ValueError("variant has no output.draw node")
    insert_at = nodes.index(draw)
    nodes[insert_at:insert_at] = [
        {
            "id": track_id,
            "op": "track.iou@1.0",
            "inputs": {"objects": objects_ref},
            "params": {
                "iou_threshold": iou_threshold,
                "max_missing_frames": max_missing_frames,
                "same_label_only": True,
            },
        },
        {
            "id": confirm_id,
            "op": "track.confirm@1.0",
            "inputs": {"tracks": f"${track_id}"},
            "params": {
                "min_hits": min_hits,
                "min_span_seconds": min_span_seconds,
            },
        },
        {
            "id": objects_id,
            "op": "objects.from_tracks@1.0",
            "inputs": {"tracks": f"${confirm_id}"},
            "params": {"selection": "all"},
        },
    ]
    draw["inputs"]["objects"] = f"${confirm_id}"
    draw.setdefault("params", {})["show_trajectory"] = True
    updated.outputs["objects"] = f"${objects_id}"
    updated.outputs["tracks"] = f"${confirm_id}"
    return VariantDraft(
        updated.nodes,
        updated.outputs,
        updated.bindings_by_span,
        updated.configuration_slots,
    )


def add_video_track_confirmation(
    package: SkillPackage,
    registry: OperatorRegistry,
    *,
    objects_ref: str,
    frames_ref: str = "$resized",
    track_id: str = "result_tracks",
    confirm_id: str = "confirmed_tracks",
    objects_id: str = "confirmed_objects",
    min_hits: int = 2,
    min_span_seconds: float = 0.5,
    iou_threshold: float = 0.2,
    max_missing_frames: int = 1,
) -> SkillPackage:
    """Wrap a video ObjectSet output in reusable IoU tracking + confirmation.

    This is an explicit package transformation, not a hidden runtime heuristic.
    It is suitable for per-frame video detections where isolated observations
    should not be published as stable results.
    """

    data = deepcopy(package.model_dump(mode="json"))
    variant = data["variants"].get("video")
    if not variant or variant["status"] != "executable":
        raise ValueError("package has no executable video variant")
    nodes = variant["nodes"]
    existing_ids = {node["id"] for node in nodes}
    requested_ids = {track_id, confirm_id, objects_id}
    if existing_ids & requested_ids:
        raise ValueError("track confirmation node id already exists")
    draw = next((node for node in nodes if node["op"] == "output.draw@1.0"), None)
    if draw is None:
        raise ValueError("video variant has no output.draw node")
    insert_at = nodes.index(draw)
    nodes[insert_at:insert_at] = [
        {
            "id": track_id,
            "op": "track.iou@1.0",
            "inputs": {"objects": objects_ref},
            "params": {
                "iou_threshold": iou_threshold,
                "max_missing_frames": max_missing_frames,
                "same_label_only": True,
            },
            "enabled": True,
        },
        {
            "id": confirm_id,
            "op": "track.confirm@1.0",
            "inputs": {"tracks": f"${track_id}"},
            "params": {
                "min_hits": min_hits,
                "min_span_seconds": min_span_seconds,
            },
            "enabled": True,
        },
        {
            "id": objects_id,
            "op": "objects.from_tracks@1.0",
            "inputs": {"tracks": f"${confirm_id}"},
            "params": {"selection": "all"},
            "enabled": True,
        },
    ]
    draw["inputs"]["frames"] = frames_ref
    draw["inputs"]["objects"] = f"${confirm_id}"
    draw.setdefault("params", {})["show_trajectory"] = True
    variant["outputs"]["objects"] = f"${objects_id}"
    variant["outputs"]["tracks"] = f"${confirm_id}"
    result = SkillPackage.model_validate(data)
    assert_valid_skill_package(result, registry)
    return result


__all__ = ["add_video_track_confirmation", "confirm_variant_objects"]
