from __future__ import annotations

from typing import Any

from .preset_factory import (
    VariantDraft,
    append_grounding,
    draw_outputs,
    node,
    start_nodes,
)


Target = dict[str, Any]


VEHICLE_TARGETS: list[Target] = [{
    "label": "车辆",
    "phrases": ["vehicle", "passenger car", "truck"],
}]

CONGESTION_VEHICLE_TARGETS: list[Target] = [{
    "label": "车辆",
    "phrases": [
        "vehicle", "car", "passenger car", "SUV", "van", "truck", "bus"
    ],
}]

PERSON_TARGETS: list[Target] = [{
    "label": "人员",
    "phrases": ["person"],
}]

SPECIAL_VEHICLE_TARGETS: list[Target] = [
    {"label": "消防车", "phrases": ["fire truck", "fire engine"]},
    {"label": "救护车", "phrases": ["ambulance", "emergency medical vehicle"]},
    {"label": "警车", "phrases": ["police car", "police vehicle"]},
    {
        "label": "工程抢险车",
        "phrases": ["engineering rescue vehicle", "emergency repair truck"],
    },
    {
        "label": "道路清障车",
        "phrases": ["tow truck", "road recovery vehicle", "wrecker truck"],
    },
    {
        "label": "环卫车",
        "phrases": ["sanitation vehicle", "street sweeper", "garbage truck"],
    },
    {"label": "油罐车", "phrases": ["tanker truck", "fuel tanker truck"]},
    {
        "label": "混凝土搅拌车",
        "phrases": ["concrete mixer truck", "cement mixer truck"],
    },
    {"label": "混凝土泵车", "phrases": ["concrete pump truck"]},
    {"label": "汽车吊", "phrases": ["truck crane", "mobile crane truck"]},
    {
        "label": "高空作业车",
        "phrases": ["aerial work platform truck", "bucket truck"],
    },
    {
        "label": "危险品运输车",
        "phrases": ["hazardous materials truck", "hazmat transport vehicle"],
    },
]


def congestion_builder(media_type: str) -> VariantDraft:
    if media_type != "video":
        raise ValueError("congestion requires video")
    nodes, frames, detection_frames = start_nodes(
        media_type,
        tile=True,
        tile_include_full_frame=True,
        tile_params={
            "tile_width": 512,
            "tile_height": 512,
            "overlap_x": 0.25,
            "overlap_y": 0.25,
        },
    )
    vehicles, _ = append_grounding(
        nodes,
        "vehicles",
        detection_frames,
        CONGESTION_VEHICLE_TARGETS,
        threshold=0.7,
        keep="best_localization",
    )
    nodes.extend([
        node(
            "vehicle_box_shape",
            "visual.geometry@1.0",
            {"objects": vehicles},
            {
                "dimension": "aspect_ratio",
                "value": "horizontal",
                "aspect_ratio_threshold": 0.6,
            },
        ),
        node(
            "vehicles_localized",
            "filter.apply@1.0",
            {"objects": vehicles, "condition": "$vehicle_box_shape"},
            {"output_label": None},
        ),
        node(
            "lane_regions",
            "region.manual_set@1.0",
            {},
            {"regions": []},
        ),
        node(
            "vehicles_in_lanes",
            "objects.filter_by_regions@1.0",
            {"objects": "$vehicles_localized", "regions": "$lane_regions"},
            {
                "membership_mode": "center",
                "overlap_threshold": 0.1,
                "keep": "inside",
            },
        ),
        node(
            "lane_count", "measure.region_count@1.0",
            {
                "objects": "$vehicles_in_lanes",
                "regions": "$lane_regions",
                "frames": frames,
            },
            {"membership_mode": "center"},
        ),
        node(
            "many",
            "logic.compare@1.0",
            {"left": "$lane_count"},
            {"operator": ">=", "value": 4},
        ),
        node(
            "events",
            "temporal.persist@1.0",
            {"condition": "$many"},
            {
                "seconds": 1.0,
                "scope": "region",
                "gap_tolerance_seconds": 0.6,
            },
        ),
        node(
            "alerts",
            "output.alert@1.0",
            {"events": "$events"},
            {"label": "高速车辆拥堵"},
        ),
    ])
    vehicles = "$vehicles_in_lanes"
    outputs = draw_outputs(
        nodes,
        frames,
        vehicles,
        events_ref="$alerts",
        regions_ref="$lane_regions",
    )
    draw = next(item for item in nodes if item["id"] == "draw")
    draw["inputs"]["measurements"] = "$lane_count"
    # Every box has the same business category in this preset.  Repeating the
    # label over dozens of tiny vehicles hides the box edges, so keep the boxes
    # and aggregate measurements visible while suppressing redundant text.
    # Users can re-enable labels and track identifiers in the draw atom.
    draw["params"]["show_labels"] = False
    draw["params"]["show_track_id"] = False
    outputs["measurements_1"] = "$lane_count"
    return VariantDraft(
        nodes,
        outputs,
        {
            "每条车道": ["lane_regions", "vehicles_in_lanes"],
            "车辆数量不少于4辆": ["lane_regions", "lane_count", "many"],
            "持续1秒": ["many", "events", "alerts"],
        },
        [{
            "slot_id": "lane_regions",
            "kind": "region_set",
            "label": "命名车道区域",
            "required": True,
            "binding": {"node_id": "lane_regions", "parameter": "regions"},
            "allowed_shapes": ["rectangle", "polygon"],
            "minimum_items": 1,
            "source_atom_ids": ["atom_1"],
            "help_text": "请按视频实际车道逐条绘制；初始为空，可添加任意多个区域。车辆统计和输出框统一限定在全部已标注车道区域内；拥堵按每个区域的车辆数量判断，不需要方向箭头。",
        }],
    )


def wrong_way_builder(media_type: str) -> VariantDraft:
    if media_type != "video":
        raise ValueError("wrong-way detection requires video")
    nodes, frames, detection_frames = start_nodes(media_type)
    # Direction inference needs a denser timeline than generic event detection.
    # At 1 FPS, a following vehicle can occupy almost the same box as the
    # preceding vehicle and be joined into its track, creating false reverse
    # motion.  Two samples per second is the verified P05 baseline.
    next(item for item in nodes if item["id"] == "frames")["params"]["fps"] = 2.0
    vehicles, _ = append_grounding(
        nodes, "vehicles", detection_frames, CONGESTION_VEHICLE_TARGETS
    )
    nodes.extend([
        node(
            "tracks",
            "track.iou@1.0",
            {"objects": "$vehicles_in_lanes"},
            {
                "iou_threshold": 0.35,
                "max_missing_frames": 1,
                "same_label_only": True,
                "motion_consistency": True,
                "motion_prediction": True,
                "min_direction_cosine": 0.0,
                "min_motion_pixels": 5.0,
            },
        ),
        node(
            "headings",
            "measure.heading@1.0",
            {"tracks": "$tracks"},
            {
                "window_frames": 3,
                "min_displacement_pixels": 8.0,
                "min_displacement_box_ratio": 0.15,
            },
        ),
        node(
            "lane_regions",
            "region.manual_set@1.0",
            {},
            {"regions": []},
        ),
        node(
            "lane_references",
            "direction.manual_set@1.0",
            {},
            {"directions": []},
        ),
        node(
            "vehicles_in_lanes",
            "objects.filter_by_regions@1.0",
            {"objects": vehicles, "regions": "$lane_regions"},
            {
                "membership_mode": "center",
                "overlap_threshold": 0.1,
                "keep": "inside",
            },
        ),
        node(
            "opposite",
            "logic.heading_by_lane@1.0",
            {
                "tracks": "$tracks",
                "headings": "$headings",
                "lanes": "$lane_regions",
                "references": "$lane_references",
            },
            {
                "threshold": -0.5,
                "membership_mode": "majority_center",
                "relation": "opposite",
                "scope_overrides": {},
            },
        ),
        node(
            "events",
            "temporal.persist@1.0",
            {"condition": "$opposite"},
            {
                "seconds": 1.0,
                "scope": "track",
                # P05 samples at 2 FPS and tracking tolerates one missing
                # sample. Direction evidence can therefore be 1.0 second
                # apart without representing a real interruption.
                "gap_tolerance_seconds": 1.1,
                "scope_overrides": {},
                "override_scope_field": "region_id",
            },
        ),
        node(
            "alerts",
            "output.alert@1.0",
            {"events": "$events"},
            {"label": "逆行车辆"},
        ),
    ])
    outputs = draw_outputs(
        nodes,
        frames,
        "$tracks",
        events_ref="$alerts",
        regions_ref="$lane_regions",
        directions_ref="$lane_references",
    )
    # Result media shows every detected/tracked vehicle.  The event stream only
    # changes matching boxes to orange and appends “逆行车辆”; normal traffic
    # must not disappear merely because it did not trigger an alert.
    outputs["objects"] = "$vehicles_in_lanes"
    outputs["tracks"] = "$tracks"
    outputs["observed_lane_directions"] = "$lane_references"
    draw = next(item for item in nodes if item["id"] == "draw")
    draw["params"].update({
        "show_labels": False,
        "show_track_id": False,
        "show_event_labels": True,
        # Wrong-way is a causal motion conclusion.  Do not project a later
        # confirmed event back onto the track's first observation: frame 0 has
        # no displacement evidence and must remain an ordinary vehicle box.
        "event_time_window": "event",
    })
    return VariantDraft(
        nodes,
        outputs,
        {
            "每条车道": ["lane_regions"],
            "标注方向后检测与车流方向相反": [
                "vehicles_in_lanes", "tracks", "headings", "lane_regions", "lane_references", "opposite"
            ],
            "持续1秒": ["opposite", "events", "alerts"],
        },
        [
            {
                "slot_id": "lane_regions",
                "kind": "region_set",
                "label": "命名车道区域",
                "required": True,
                "binding": {"node_id": "lane_regions", "parameter": "regions"},
                "allowed_shapes": ["rectangle", "polygon"],
                "minimum_items": 1,
                "source_atom_ids": ["atom_1"],
                "help_text": "请按视频实际车道逐条绘制；初始为空，可添加任意多个区域。",
            },
            {
                "slot_id": "lane_references_manual",
                "kind": "direction_set",
                "label": "逐车道参考方向",
                "required": True,
                "binding": {
                    "node_id": "lane_references",
                    "parameter": "directions",
                },
                "allowed_shapes": [],
                "minimum_items": 1,
                "source_atom_ids": ["atom_1"],
                "help_text": "逆行判断需要为每个已保存车道绘制一条参考方向箭头；箭头 key 会自动绑定该车道。",
                "key_source_slot_id": "lane_regions",
            },
        ],
    )


__all__ = [
    "PERSON_TARGETS",
    "SPECIAL_VEHICLE_TARGETS",
    "Target",
    "VEHICLE_TARGETS",
    "congestion_builder",
    "wrong_way_builder",
]
