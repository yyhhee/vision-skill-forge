from __future__ import annotations

from .preset_factory import (
    PresetDefinition,
    add_context_confirmation,
    add_final_count,
    constraint,
    disambiguate_category_by_visible_evidence,
    exclude_visible_evidence,
    geometry_validated_builder,
    ledger,
    visible_builder,
    visually_validated_builder,
)
from .preset_relations import (
    illegal_parking_builder,
    missing_equipment_builder,
    person_dwell_builder,
    road_debris_builder,
)
from .preset_temporal import person_fall_builder
from .preset_workflows import (
    SPECIAL_VEHICLE_TARGETS,
    congestion_builder,
    wrong_way_builder,
)
from .video_stability import confirm_variant_objects


FIRE_SMOKE_TARGETS = [{
    "label": "烟火",
    "phrases": ["smoke", "visible smoke", "fire", "flame", "open flame"],
}]

FIRE_SMOKE_EVIDENCE = [
    {
        "color": color,
        "subject_region": [0.0, 0.0, 1.0, 1.0],
        "min_fraction": minimum,
        "selection_mode": "dominant",
        "dominance_margin": 0.03,
    }
    for color, minimum in (
        ("black", 0.12),
        ("gray", 0.20),
        ("red", 0.02),
        ("orange", 0.02),
        ("yellow", 0.02),
    )
]

TRAFFIC_ACCIDENT_TARGETS = [{
    "label": "交通事故",
    "phrases": [
        "vehicle collision",
        "overturned vehicle",
        "crashed vehicle",
        "visible traffic accident scene",
    ],
}]

GARBAGE_TARGETS = [{
    "label": "垃圾容器",
    "phrases": ["trash bin", "garbage container", "waste bin"],
}, {
    "label": "溢出垃圾",
    "phrases": [
        "overflowing trash",
        "trash spilling from a bin",
        "trash attached to a garbage bin",
    ],
}, {
    "label": "散落垃圾",
    "phrases": [
        "loose trash",
        "discarded waste on the ground",
        "small litter",
        "small piece of trash",
    ],
}]

BRIDGE_DAMAGE_TARGETS = [
    {"label": "裂纹", "phrases": ["bridge crack", "concrete crack"]},
    {"label": "锈蚀", "phrases": [
        "bridge corrosion",
        "rust on bridge",
        "visible rust corrosion on bridge surface",
    ]},
    {"label": "渗水", "phrases": ["water seepage", "water stain on concrete"]},
    {"label": "混凝土剥落", "phrases": ["concrete spalling"]},
    {"label": "露筋", "phrases": [
        "exposed rebar",
        "exposed steel reinforcement bar",
        "visible reinforcement steel in concrete",
    ]},
]


def build_preset_definitions() -> list[PresetDefinition]:
    def stable_video(builder):
        def build(media_type: str):
            draft = builder(media_type)
            return (
                confirm_variant_objects(draft)
                if media_type == "video"
                else draft
            )

        return build

    no_helmet = missing_equipment_builder(
        worker_targets=[{
            "label": "施工人员",
            "phrases": ["construction worker", "worker at construction site"],
        }],
        equipment_targets=[{
            "label": "安全帽",
            "phrases": ["safety helmet", "hard hat"],
        }],
        subject_region=[0.0, 0.0, 1.0, 0.45],
        output_label="未戴安全帽人员",
        constraint_span="没有佩戴安全帽",
        video_evidence_hold_seconds=1.5,
    )
    no_safety_rope = missing_equipment_builder(
        worker_targets=[{
            "label": "高处作业人员",
            "phrases": ["worker at height", "person working at height"],
        }],
        equipment_targets=[{
            "label": "防坠挂绳钩",
            "phrases": [
                "lanyard hook",
                "safety hook",
                "safety carabiner",
            ],
        }],
        subject_region=[-0.6, -0.6, 1.6, 1.2],
        output_label="未系安全绳人员",
        constraint_span="没有连接安全绳或安全带",
        association_relation="center_in_subject_region",
        association_subject_region=[-0.6, -0.6, 1.6, 0.0],
        same_source_only=True,
    )
    garbage_visible = exclude_visible_evidence(
        visible_builder(
            "garbage",
            GARBAGE_TARGETS,
            tile=True,
            tile_params={
                "tile_width": 384,
                "tile_height": 384,
                "overlap_x": 0.25,
                "overlap_y": 0.25,
            },
        ),
        [
            {
                "id": "garbage",
                "source_span": "整齐包装货物",
                "target": {
                    "label": "整齐包装货物",
                    "phrases": [
                        "neatly stacked packages",
                        "cardboard boxes on a pallet",
                        "shrink wrapped package",
                    ],
                },
            },
        ],
        association_relation="mutual_match",
    )
    garbage_disambiguated = disambiguate_category_by_visible_evidence(
        garbage_visible,
        candidate_labels=["散落垃圾"],
        evidence_target={
            "label": "垃圾容器",
            "phrases": [
                "trash bin", "garbage container", "waste bin",
                "complete trash bin with visible container body",
            ],
        },
    )
    garbage_confirmed = lambda media_type: add_context_confirmation(
        garbage_disambiguated(media_type),
        candidate_phrases=["trash bin", "garbage container", "waste bin"],
        confirmation_targets=[{
            "label": "垃圾容器复核证据",
            "phrases": [
                "complete trash bin with visible container body",
                "complete garbage container with visible opening and body",
            ],
        }],
        padding_fraction=1.0,
        crop_long_side=640,
    )
    bridge_visible = exclude_visible_evidence(
        visible_builder(
            "bridge_damage",
            BRIDGE_DAMAGE_TARGETS,
            tile=True,
            tile_include_full_frame=False,
            dedup_threshold=0.35,
        ),
        [{
            "id": "bridge_damage",
            "source_span": "规则施工缝",
            "target": {
                "label": "规则施工缝",
                "phrases": [
                    "regular construction joint",
                    "straight concrete seam",
                    "intact concrete with construction joints",
                ],
            },
        }],
        association_relation="mutual_match",
    )
    return [
        PresetDefinition(
            "P01",
            "P01_fire_smoke.json",
            "fire_smoke",
            "烟火检测",
            "检测画面中的烟雾或明火。",
            ("image", "video"),
            ledger(
                "fire_smoke",
                "烟雾或明火",
                FIRE_SMOKE_TARGETS[0]["phrases"],
                mode="direct_grounding",
            ),
            visually_validated_builder(
                "fire_smoke",
                FIRE_SMOKE_TARGETS,
                FIRE_SMOKE_EVIDENCE,
                alert_label="烟火检测",
            ),
        ),
        PresetDefinition(
            "P02",
            "P02_traffic_accident.json",
            "traffic_accident",
            "交通事故检测",
            "检测车辆碰撞、侧翻或受损车辆形成的可见事故外观。",
            ("image", "video"),
            ledger(
                "visible_traffic_accident",
                "可见事故外观",
                TRAFFIC_ACCIDENT_TARGETS[0]["phrases"],
                mode="direct_grounding",
            ),
            visible_builder(
                "traffic_accident",
                TRAFFIC_ACCIDENT_TARGETS,
                alert_label="交通事故检测",
            ),
        ),
        PresetDefinition(
            "P03",
            "P03_special_vehicles.json",
            "special_vehicles",
            "特种车辆检测",
            "检测画面中的特种车辆并标注具体类型。",
            ("image", "video"),
            ledger(
                "special_vehicle",
                "特种车辆",
                [phrase for target in SPECIAL_VEHICLE_TARGETS for phrase in target["phrases"]],
                mode="direct_grounding",
                classes=SPECIAL_VEHICLE_TARGETS,
            ),
            visible_builder("special_vehicles", SPECIAL_VEHICLE_TARGETS),
        ),
        PresetDefinition(
            "P04",
            "P04_highway_congestion.json",
            "highway_congestion",
            "高速车辆拥堵",
            "按每条车道检测车辆数量不少于4辆、平均像素速度低于10且持续1秒的拥堵事件。",
            ("video",),
            ledger(
                "vehicle",
                "车辆",
                ["vehicle"],
                [
                    constraint(
                        "region_requirement",
                        {
                            "source": "manual",
                            "cardinality": "many",
                            "semantic_role": "lane",
                            "allowed_shapes": ["rectangle", "polygon"],
                        },
                        "每条车道",
                    ),
                    constraint(
                        "quantity",
                        {
                            "measure": "count",
                            "operator": ">=",
                            "value": 4,
                            "group_by": "named_region",
                            "region_role": "lane",
                        },
                        "车辆数量不少于4辆",
                    ),
                    constraint(
                        "motion",
                        {
                            "measure": "speed",
                            "operator": "<",
                            "threshold": 10.0,
                            "unit": "pixels_per_second",
                            "aggregation": "region_median",
                            "group_by": "named_region",
                            "region_role": "lane",
                        },
                        "平均像素速度低于10",
                    ),
                    constraint(
                        "temporal",
                        {"type": "persist", "seconds": 1.0},
                        "持续1秒",
                        temporal=True,
                    ),
                ],
                mode="workflow",
            ),
            congestion_builder,
        ),
        PresetDefinition(
            "P05",
            "P05_highway_wrong_way.json",
            "highway_wrong_way",
            "高速车辆逆行",
            "按每条车道标注方向后检测与车流方向相反并持续1秒的车辆。",
            ("video",),
            ledger(
                "vehicle",
                "车辆",
                ["vehicle"],
                [
                    constraint(
                        "region_requirement",
                        {
                            "source": "manual",
                            "cardinality": "many",
                            "semantic_role": "lane",
                            "allowed_shapes": ["rectangle", "polygon"],
                        },
                        "每条车道",
                    ),
                    constraint(
                        "direction_relation",
                        {
                            "relation": "opposite",
                            "reference_scope": "per_named_region",
                            "reference_source": "manual",
                            "cosine_threshold": -0.5,
                        },
                        "标注方向后检测与车流方向相反",
                    ),
                    constraint(
                        "temporal",
                        {"type": "persist", "seconds": 1.0},
                        "持续1秒",
                        temporal=True,
                    ),
                ],
                mode="workflow",
            ),
            wrong_way_builder,
        ),
        PresetDefinition(
            "P06",
            "P06_highway_person_dwell.json",
            "highway_person_dwell",
            "车道人员逗留",
            "检测在手工标注车道区域内持续逗留1秒的人员。",
            ("video",),
            ledger(
                "person",
                "人员",
                ["person"],
                [
                    constraint(
                        "spatial_relation",
                        {
                            "relation": "inside_roi",
                            "region": {
                                "source": "manual",
                                "semantic_role": "lane",
                                "shape": "polygon",
                                "allowed_shapes": ["rectangle", "polygon"],
                            },
                        },
                        "在手工标注车道区域内",
                    ),
                    constraint(
                        "temporal",
                        {"type": "persist", "seconds": 1.0},
                        "持续逗留1秒",
                        temporal=True,
                    ),
                ],
                mode="workflow",
            ),
            person_dwell_builder,
        ),
        PresetDefinition(
            "P07",
            "P07_illegal_parking.json",
            "illegal_parking",
            "车辆违停",
            "检测位于手工标注禁停区域内、像素速度低于2并持续10秒的车辆。",
            ("video",),
            ledger(
                "vehicle",
                "车辆",
                ["vehicle"],
                [
                    constraint(
                        "spatial_relation",
                        {
                            "relation": "inside_roi",
                            "region": {
                                "source": "manual",
                                "semantic_role": "no_parking",
                                "shape": "polygon",
                                "allowed_shapes": ["rectangle", "polygon"],
                            },
                        },
                        "位于手工标注禁停区域内",
                    ),
                    constraint(
                        "motion",
                        {
                            "measure": "speed",
                            "operator": "<",
                            "threshold": 2.0,
                            "unit": "pixels_per_second",
                            "aggregation": "per_track",
                        },
                        "像素速度低于2",
                    ),
                    constraint(
                        "temporal",
                        {"type": "persist", "seconds": 10.0},
                        "持续10秒",
                        temporal=True,
                    ),
                ],
                mode="workflow",
            ),
            illegal_parking_builder,
        ),
        PresetDefinition(
            "P08",
            "P08_road_debris.json",
            "road_debris",
            "道路抛洒物",
            "检测道路上的抛洒物、掉落货物或障碍物。",
            ("image", "video"),
            ledger(
                "road_debris",
                "抛洒物、掉落货物或障碍物",
                ["road debris", "fallen cargo", "road obstacle"],
                [
                    constraint(
                        "spatial_relation",
                        {
                            "relation": "inside_roi",
                            "region": {
                                "source": "grounding",
                                "phrases": ["road surface", "roadway"],
                                "mode": "all",
                            },
                        },
                        "道路上的",
                    ),
                ],
            ),
            stable_video(road_debris_builder),
        ),
        PresetDefinition(
            "P09",
            "P09_no_helmet.json",
            "no_helmet",
            "施工未戴安全帽",
            "检测施工人员中没有佩戴安全帽的人。",
            ("image", "video"),
            ledger(
                "construction_worker",
                "施工人员",
                ["construction worker", "worker at construction site"],
                [
                    constraint(
                        "wearable",
                        "safety_helmet",
                        "没有佩戴安全帽",
                        phrases=["safety helmet", "hard hat"],
                    ),
                ],
            ),
            stable_video(no_helmet),
        ),
        PresetDefinition(
            "P10",
            "P10_no_safety_rope.json",
            "no_safety_rope",
            "高处作业未系安全绳",
            "检测高处作业人员中没有连接安全绳或安全带的人。",
            ("image", "video"),
            ledger(
                "worker_at_height",
                "高处作业人员",
                ["worker at height", "person working at height"],
                [
                    constraint(
                        "wearable",
                        "connected_fall_arrest_lanyard",
                        "没有连接安全绳或安全带",
                        phrases=[
                            "lanyard hook",
                            "safety hook",
                            "safety carabiner",
                        ],
                    ),
                ],
            ),
            no_safety_rope,
        ),
        PresetDefinition(
            "P11",
            "P11_service_area_garbage.json",
            "service_area_garbage",
            "服务区垃圾",
            "检测服务区画面中的垃圾、垃圾容器及溢出垃圾，排除整齐包装货物。",
            ("image", "video"),
            ledger(
                "garbage",
                "垃圾、垃圾容器及溢出垃圾",
                [phrase for target in GARBAGE_TARGETS for phrase in target["phrases"]],
                [
                    constraint(
                        "entity_exclusion", "orderly_packages", "整齐包装货物",
                        phrases=[
                            "neatly stacked packages",
                            "cardboard boxes on a pallet",
                            "shrink wrapped package",
                        ],
                    ),
                ],
                mode="direct_grounding",
            ),
            lambda media_type: add_final_count(
                stable_video(garbage_confirmed)(media_type), media_type, group_by="label"
            ),
        ),
        PresetDefinition(
            "P12",
            "P12_person_fall.json",
            "person_fall",
            "人员摔倒",
            "检测出现摔倒或躺在地面上的可见姿态并持续1秒的人员。",
            ("video",),
            ledger(
                "person",
                "人员",
                ["person"],
                [
                    constraint(
                        "pose",
                        "fallen_or_lying",
                        "出现摔倒或躺在地面上的可见姿态",
                        phrases=["person lying on the ground"],
                    ),
                    constraint(
                        "temporal",
                        {"type": "persist", "seconds": 1.0},
                        "持续1秒",
                        temporal=True,
                    ),
                ],
                mode="workflow",
            ),
            person_fall_builder,
        ),
        PresetDefinition(
            "P13",
            "P13_bridge_damage.json",
            "bridge_damage",
            "桥梁病害",
            "检测桥梁表面的裂纹、锈蚀、渗水、混凝土剥落和露筋，排除规则施工缝。",
            ("image", "video"),
            ledger(
                "bridge_damage",
                "裂纹、锈蚀、渗水、混凝土剥落和露筋",
                [
                    "bridge crack",
                    "concrete crack",
                    "bridge corrosion",
                    "rust on bridge",
                    "visible rust corrosion on bridge surface",
                    "water seepage",
                    "water stain on concrete",
                    "concrete spalling",
                    "exposed rebar",
                    "exposed steel reinforcement bar",
                    "visible reinforcement steel in concrete",
                ],
                [
                    constraint(
                        "entity_exclusion", "regular_construction_joint",
                        "规则施工缝",
                        phrases=[
                            "regular construction joint",
                            "straight concrete seam",
                            "intact concrete with construction joints",
                        ],
                    ),
                ],
                classes=BRIDGE_DAMAGE_TARGETS,
            ),
            stable_video(bridge_visible),
        ),
    ]


__all__ = ["build_preset_definitions"]
