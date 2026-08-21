from __future__ import annotations

from typing import Any

from .preset_factory import (
    VariantDraft,
    append_grounding,
    draw_outputs,
    node,
    start_nodes,
)
from .preset_workflows import PERSON_TARGETS, Target, VEHICLE_TARGETS


def person_dwell_builder(media_type: str) -> VariantDraft:
    if media_type != "video":
        raise ValueError("dwell detection requires video")
    nodes, frames, detection_frames = start_nodes(media_type)
    people, _ = append_grounding(
        nodes, "people", detection_frames, PERSON_TARGETS
    )
    nodes.extend([
        node(
            "tracks",
            "track.iou@1.0",
            {"objects": people},
            {
                "iou_threshold": 0.25,
                "max_missing_frames": 2,
                "same_label_only": True,
            },
        ),
        node(
            "lane_region",
            "region.manual@1.0",
            {},
            {
                "shape": "rectangle",
                "points": [[0.05, 0.35], [0.95, 0.98]],
            },
        ),
        node(
            "inside_lane",
            "spatial.inside@1.0",
            {"objects": "$tracks", "region": "$lane_region"},
            {"mode": "center", "overlap_threshold": 0.5},
        ),
        node(
            "events",
            "temporal.persist@1.0",
            {"condition": "$inside_lane"},
            {
                "seconds": 10.0,
                "scope": "track",
                "gap_tolerance_seconds": 1.1,
            },
        ),
        node(
            "alerts",
            "output.alert@1.0",
            {"events": "$events"},
            {"label": "车道人员逗留"},
        ),
        node(
            "event_tracks",
            "tracks.filter_by_events@1.0",
            {"tracks": "$tracks", "events": "$alerts"},
            {"time_window": "whole_track"},
        ),
    ])
    return VariantDraft(
        nodes,
        draw_outputs(
            nodes,
            frames,
            "$event_tracks",
            events_ref="$alerts",
            regions_ref="$lane_region",
        ),
        {
            "在手工标注车道区域内": ["lane_region", "inside_lane"],
            "持续逗留1秒": ["inside_lane", "events", "alerts"],
        },
        [{
            "slot_id": "lane_region",
            "kind": "region",
            "label": "车道区域",
            "required": True,
            "binding": {"node_id": "lane_region", "parameter": "points"},
            "allowed_shapes": ["rectangle", "polygon"],
            "minimum_items": 1,
            "source_atom_ids": ["atom_1"],
            "help_text": "在原图或视频标注帧上修改车道矩形或多边形",
        }],
    )


def illegal_parking_builder(media_type: str) -> VariantDraft:
    if media_type != "video":
        raise ValueError("illegal-parking detection requires video")
    nodes, frames, detection_frames = start_nodes(media_type)
    vehicles, _ = append_grounding(
        nodes, "vehicles", detection_frames, VEHICLE_TARGETS
    )
    nodes.extend([
        node(
            "tracks",
            "track.iou@1.0",
            {"objects": vehicles},
            {
                "iou_threshold": 0.25,
                "max_missing_frames": 2,
                "same_label_only": True,
            },
        ),
        node(
            "no_parking_region",
            "region.manual@1.0",
            {},
            {
                "shape": "rectangle",
                "points": [[0.05, 0.35], [0.95, 0.98]],
            },
        ),
        node(
            "inside_region",
            "spatial.inside@1.0",
            {"objects": "$tracks", "region": "$no_parking_region"},
            {"mode": "center", "overlap_threshold": 0.5},
        ),
        node(
            "speed",
            "measure.speed@1.0",
            {"tracks": "$tracks"},
            {
                "window_frames": 2,
                "unit": "pixels_per_second",
                "aggregation": "per_track",
            },
        ),
        node(
            "stationary",
            "logic.compare@1.0",
            {"left": "$speed"},
            {"operator": "<", "value": 2.0},
        ),
        node(
            "violation_condition",
            "logic.all@1.0",
            {"conditions": ["$inside_region", "$stationary"]},
        ),
        node(
            "events",
            "temporal.persist@1.0",
            {"condition": "$violation_condition"},
            {
                "seconds": 10.0,
                "scope": "track",
                "gap_tolerance_seconds": 1.1,
            },
        ),
        node(
            "alerts",
            "output.alert@1.0",
            {"events": "$events"},
            {"label": "车辆违停"},
        ),
        node(
            "event_tracks",
            "tracks.filter_by_events@1.0",
            {"tracks": "$tracks", "events": "$alerts"},
            {"time_window": "whole_track"},
        ),
    ])
    return VariantDraft(
        nodes,
        draw_outputs(
            nodes,
            frames,
            "$event_tracks",
            events_ref="$alerts",
            regions_ref="$no_parking_region",
        ),
        {
            "位于手工标注禁停区域内": [
                "no_parking_region", "inside_region"
            ],
            "像素速度低于2": ["tracks", "speed", "stationary"],
            "持续10秒": ["violation_condition", "events", "alerts"],
        },
        [{
            "slot_id": "no_parking_region",
            "kind": "region",
            "label": "禁停区域",
            "required": True,
            "binding": {
                "node_id": "no_parking_region",
                "parameter": "points",
            },
            "allowed_shapes": ["rectangle", "polygon"],
            "minimum_items": 1,
            "source_atom_ids": ["atom_1"],
            "help_text": "在原图或视频标注帧上修改禁停矩形或多边形",
        }],
    )


def road_debris_builder(media_type: str) -> VariantDraft:
    nodes, frames, detection_frames = start_nodes(media_type)
    roads, road_nodes = append_grounding(
        nodes,
        "roads",
        detection_frames,
        [{"label": "道路", "phrases": ["road surface", "roadway"]}],
    )
    debris, debris_nodes = append_grounding(
        nodes,
        "debris",
        detection_frames,
        [{
            "label": "道路抛洒物",
            "phrases": ["road debris", "fallen cargo", "road obstacle"],
        }],
    )
    # Keep detector-derived ROI as an explicit disabled capability for
    # migration/inspection, but make the active boundary hand-configured so
    # every spatial assumption is visible and editable in 02 Annotation.
    auto_region = node(
        "road_regions_auto",
        "region.from_objects@1.0",
        {"objects": roads},
        {"mode": "all"},
    )
    auto_region["enabled"] = False
    # Its upstream detector is disabled with the optional branch so the
    # package has no hidden inference path and remains validator-clean.
    for candidate in nodes:
        if candidate["id"] in set(road_nodes):
            candidate["enabled"] = False
    nodes.extend([
        auto_region,
        node(
            "road_regions",
            "region.manual_set@1.0",
            {},
            {"regions": []},
        ),
        node(
            "inside_road",
            "spatial.inside@1.0",
            {"objects": debris, "region": "$road_regions"},
            {"mode": "center", "overlap_threshold": 0.5},
        ),
        node(
            "violations",
            "filter.apply@1.0",
            {"objects": debris, "condition": "$inside_road"},
            {"output_label": "道路抛洒物"},
        ),
    ])
    return VariantDraft(
        nodes,
        draw_outputs(
            nodes,
            frames,
            "$violations",
            regions_ref="$road_regions",
        ),
        {
            "道路上的": debris_nodes + [
                "road_regions", "inside_road", "violations"
            ],
        },
        [{
            "slot_id": "road_regions",
            "kind": "region_set",
            "label": "道路检测区域",
            "required": True,
            "binding": {"node_id": "road_regions", "parameter": "regions"},
            "allowed_shapes": ["rectangle", "polygon"],
            "minimum_items": 1,
            "source_atom_ids": ["atom_1"],
            "help_text": "请在 02 标注中手工圈出需要检测抛洒物的道路区域，可添加多个区域。",
        }],
    )


def missing_equipment_builder(
    *,
    worker_targets: list[Target],
    equipment_targets: list[Target],
    subject_region: list[float],
    output_label: str,
    constraint_span: str,
    association_relation: str = "source_entity",
    association_subject_region: list[float] | None = None,
    same_source_only: bool = False,
    video_evidence_hold_seconds: float | None = None,
) -> Any:
    def build(media_type: str) -> VariantDraft:
        nodes, frames, detection_frames = start_nodes(media_type)
        workers, worker_nodes = append_grounding(
            nodes, "workers", detection_frames, worker_targets
        )
        crop_subjects = workers
        subject_tracking_nodes: list[str] = []
        if media_type == "video" and video_evidence_hold_seconds is not None:
            nodes.extend([
                node(
                    "subject_tracks",
                    "track.iou@1.0",
                    {"objects": workers},
                    {
                        "iou_threshold": 0.2,
                        "max_missing_frames": 1,
                        "same_label_only": True,
                    },
                ),
                node(
                    "tracked_subjects",
                    "objects.from_tracks@1.0",
                    {"tracks": "$subject_tracks"},
                    {"selection": "all"},
                ),
            ])
            crop_subjects = "$tracked_subjects"
            subject_tracking_nodes = ["subject_tracks", "tracked_subjects"]
        nodes.append(node(
            "equipment_crops",
            "object.crop@1.0",
            {"frames": detection_frames, "objects": crop_subjects},
            {
                "padding_fraction": 0.05,
                "subject_region": subject_region,
            },
        ))
        nodes.append(node(
            "equipment_crop_resized",
            "image.resize@1.1",
            {"frames": "$equipment_crops"},
            {
                "mode": "long_side",
                "long_side": 640,
                "interpolation": "bicubic",
            },
        ))
        equipment, equipment_nodes = append_grounding(
            nodes, "equipment", "$equipment_crop_resized", equipment_targets
        )
        nodes.append(
            node(
                "has_equipment",
                "spatial.associate@1.0",
                {"subjects": workers, "objects": equipment},
                {
                    "relation": association_relation,
                    "threshold": 0.0,
                    "subject_region": association_subject_region
                    or [0.0, 0.0, 1.0, 1.0],
                    "same_source_only": same_source_only,
                },
            )
        )
        evidence_ref = "$has_equipment"
        evidence_hold_nodes: list[str] = []
        if media_type == "video" and video_evidence_hold_seconds is not None:
            nodes.append(node(
                "equipment_evidence_hold",
                "temporal.hold@1.0",
                {"condition": "$has_equipment"},
                {"seconds": video_evidence_hold_seconds, "value": True},
            ))
            evidence_ref = "$equipment_evidence_hold"
            evidence_hold_nodes = ["equipment_evidence_hold"]
        nodes.extend([
            node(
                "missing_equipment",
                "logic.not@1.0",
                {"condition": evidence_ref},
            ),
            node(
                "violations",
                "filter.apply@1.0",
                {"objects": workers, "condition": "$missing_equipment"},
                {"output_label": output_label},
            ),
        ])
        return VariantDraft(
            nodes,
            draw_outputs(nodes, frames, "$violations"),
            {
                constraint_span: worker_nodes + [
                    *subject_tracking_nodes,
                    "equipment_crops", "equipment_crop_resized"
                ] + equipment_nodes + [
                    "has_equipment", *evidence_hold_nodes,
                    "missing_equipment", "violations"
                ],
            },
        )

    return build


__all__ = [
    "illegal_parking_builder",
    "missing_equipment_builder",
    "person_dwell_builder",
    "road_debris_builder",
]
