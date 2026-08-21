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
            "lane_regions",
            "region.manual_set@1.0",
            {},
            {"regions": []},
        ),
        node(
            "lane_count", "measure.region_count@1.0",
            {
                "objects": vehicles,
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
            "lane_speed",
            "measure.region_speed@1.0",
            {"tracks": "$tracks", "regions": "$lane_regions"},
            {
                "window_frames": 2,
                "unit": "pixels_per_second",
                "aggregation": "median",
                "membership_mode": "sample_center",
            },
        ),
        node(
            "slow",
            "logic.compare@1.0",
            {"left": "$lane_speed"},
            {"operator": "<", "value": 10.0},
        ),
        node(
            "congested",
            "logic.all@1.0",
            {"conditions": ["$many", "$slow"]},
        ),
        node(
            "events",
            "temporal.persist@1.0",
            {"condition": "$congested"},
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
    outputs = draw_outputs(
        nodes,
        frames,
        vehicles,
        events_ref="$alerts",
        regions_ref="$lane_regions",
    )
    draw = next(item for item in nodes if item["id"] == "draw")
    draw["inputs"]["measurements"] = "$lane_count"
    outputs["tracks"] = "$tracks"
    outputs["measurements_1"] = "$lane_count"
    outputs["measurements_2"] = "$lane_speed"
    return VariantDraft(
        nodes,
        outputs,
        {
            "每条车道": ["lane_regions"],
            "车辆数量不少于4辆": ["lane_regions", "lane_count", "many"],
            "平均像素速度低于10": ["tracks", "lane_regions", "lane_speed", "slow"],
            "持续1秒": ["congested", "events", "alerts"],
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
            "help_text": "请按视频实际车道逐条绘制；初始为空，可添加任意多个区域。区域只决定拥堵判断范围，不会裁掉全画面的车辆检测框；拥堵只按每个区域的车辆数和速度判断，不需要方向箭头。",
        }],
    )


def wrong_way_builder(media_type: str) -> VariantDraft:
    if media_type != "video":
        raise ValueError("wrong-way detection requires video")
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
                "iou_threshold": 0.2,
                "max_missing_frames": 2,
                "same_label_only": True,
            },
        ),
        node(
            "headings",
            "measure.heading@1.0",
            {"tracks": "$tracks"},
            {"window_frames": 3, "min_displacement_pixels": 5.0},
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
            "opposite",
            "logic.heading_by_lane@1.0",
            {
                "tracks": "$tracks",
                "headings": "$headings",
                "lanes": "$lane_regions",
                "references": "$lane_references",
            },
            {"threshold": -0.5, "membership_mode": "majority_center"},
        ),
        node(
            "events",
            "temporal.persist@1.0",
            {"condition": "$opposite"},
            {
                "seconds": 1.0,
                "scope": "track",
                "gap_tolerance_seconds": 0.6,
            },
        ),
        node(
            "alerts",
            "output.alert@1.0",
            {"events": "$events"},
            {"label": "逆行车辆"},
        ),
        node(
            "event_tracks",
            "tracks.filter_by_events@1.0",
            {"tracks": "$tracks", "events": "$alerts"},
            {
                # Keep the full history for visualization.  Event labels are
                # still restricted to the actual event interval by output.draw,
                # while the vehicle remains visible before and after the event.
                "time_window": "whole_track",
            },
        ),
    ])
    outputs = draw_outputs(
        nodes,
        frames,
        "$event_tracks",
        events_ref="$alerts",
        regions_ref="$lane_regions",
        directions_ref="$lane_references",
    )
    outputs["observed_lane_directions"] = "$lane_references"
    return VariantDraft(
        nodes,
        outputs,
        {
            "每条车道": ["lane_regions"],
            "标注方向后检测与车流方向相反": [
                "tracks", "headings", "lane_regions", "lane_references", "opposite"
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
