from __future__ import annotations

from .preset_factory import (
    PresetDefinition,
    add_final_count,
    constraint,
    geometry_validated_builder,
    ledger,
    node,
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
    "phrases": [
        "single individual black wheeled garbage bin",
        "each separate outdoor garbage bin",
    ],
}, {
    "label": "溢出垃圾",
    "phrases": [
        "trash visibly protruding above the rim of a garbage bin",
        "garbage piled above the top opening of a garbage bin",
        "waste spilling out over the upper edge of a garbage bin",
    ],
}, {
    "label": "垃圾堆",
    "phrases": [
        "large pile of mixed garbage bags and loose waste",
        "heap of household trash accumulated on the pavement",
        "visible garbage pile beside a trash collection point",
    ],
}, {
    "label": "散落垃圾",
    "phrases": [
        "isolated loose waste item lying on the pavement",
        "discarded white plastic bag on the ground",
        "crumpled plastic bag lying on the pavement",
        "clearly visible litter item separated from a garbage pile",
        "group of mixed small litter pieces scattered near a garbage bin",
    ],
}]

BRIDGE_DAMAGE_TARGETS = [
    {
        "label": "裂纹",
        "phrases": [
            "thin irregular crack line on a concrete bridge surface",
            "localized visible concrete crack",
        ],
    },
    {
        "label": "锈蚀",
        "phrases": [
            "brown orange rust streak on a concrete bridge pier",
            "localized rusty corrosion stain below exposed metal",
        ],
    },
    {
        "label": "渗水",
        "phrases": [
            "dark vertical water seepage stain on concrete",
            "wet leakage mark on a bridge pier surface",
        ],
    },
    {
        "label": "混凝土剥落",
        "phrases": [
            "broken concrete surface with missing cover",
            "localized concrete spalling patch",
        ],
    },
    {
        "label": "露筋",
        "phrases": [
            "exposed steel reinforcement in damaged bridge concrete",
            "visible reinforcing bar protruding from a concrete bridge pier",
            "small dark exposed reinforcing steel ends in concrete",
        ],
    },
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
    garbage_visible = visible_builder(
        "garbage",
        GARBAGE_TARGETS,
        tile=True,
        tile_params={
            "tile_width": 512,
            "tile_height": 512,
            "overlap_x": 0.2,
            "overlap_y": 0.2,
        },
        dedup_metric="iou",
        dedup_threshold=0.5,
    )

    def garbage_visible_in_detection_regions(media_type: str):
        draft = garbage_visible(media_type)
        nodes = draft.nodes
        draw = next(item for item in nodes if item["op"] == "output.draw@1.0")
        insert_at = nodes.index(draw)
        objects_ref = draft.outputs["objects"]
        nodes[insert_at:insert_at] = [
            node(
                "garbage_container_candidates",
                "objects.filter_by_label@1.0",
                {"objects": objects_ref},
                {"labels": ["垃圾容器"], "mode": "include"},
            ),
            node(
                "garbage_containers",
                "objects.deduplicate@1.0",
                {"objects": "$garbage_container_candidates"},
                {
                    "metric": "ios",
                    "threshold": 0.5,
                    "keep": "best_localization",
                },
            ),
            node(
                "garbage_container_crops",
                "object.crop@1.0",
                {
                    "frames": "$resized",
                    "objects": "$garbage_containers",
                },
                {
                    "padding_fraction": 0.75,
                    "subject_region": [0.0, 0.0, 1.0, 1.0],
                },
            ),
            node(
                "garbage_container_crops_resized",
                "image.resize@1.1",
                {"frames": "$garbage_container_crops"},
                {"mode": "long_side", "long_side": 640},
            ),
            node(
                "garbage_container_evidence_raw",
                "rex.ground@1.1",
                {"frames": "$garbage_container_crops_resized"},
                {
                    "targets": [{
                        "label": "垃圾容器复核证据",
                        "phrases": [
                            "complete freestanding outdoor garbage bin with visible container body",
                            "complete wheeled garbage bin with visible opening and body",
                        ],
                    }],
                },
            ),
            node(
                "garbage_container_evidence",
                "objects.deduplicate@1.0",
                {"objects": "$garbage_container_evidence_raw"},
                {"metric": "ios", "threshold": 0.5, "keep": "first"},
            ),
            node(
                "garbage_container_confirmed",
                "spatial.associate@1.0",
                {
                    "subjects": "$garbage_containers",
                    "objects": "$garbage_container_evidence",
                },
                {
                    "relation": "source_entity",
                    "threshold": 0.0,
                    "subject_region": [0.0, 0.0, 1.0, 1.0],
                    "object_region": [0.0, 0.0, 1.0, 1.0],
                    "same_source_only": False,
                },
            ),
            node(
                "garbage_containers_visible",
                "filter.apply@1.0",
                {
                    "objects": "$garbage_containers",
                    "condition": "$garbage_container_confirmed",
                },
                {"output_label": "垃圾容器"},
            ),
            node(
                "overflow_candidates",
                "objects.filter_by_label@1.0",
                {"objects": objects_ref},
                {"labels": ["溢出垃圾"], "mode": "include"},
            ),
            node(
                "overflow_deduplicated",
                "objects.deduplicate@1.0",
                {"objects": "$overflow_candidates"},
                {
                    "metric": "ios",
                    "threshold": 0.5,
                    "keep": "best_localization",
                },
            ),
            node(
                "overflow_above_container",
                "spatial.associate@1.0",
                {
                    "subjects": "$overflow_deduplicated",
                    "objects": "$garbage_containers_visible",
                },
                {
                    "relation": "center_in_object_region",
                    "threshold": 0.0,
                    "subject_region": [0.0, 0.0, 1.0, 1.0],
                    "object_region": [-0.25, -0.5, 1.25, 0.4],
                    "same_source_only": False,
                },
            ),
            node(
                "overflow_visible",
                "filter.apply@1.0",
                {
                    "objects": "$overflow_deduplicated",
                    "condition": "$overflow_above_container",
                },
                {"output_label": "溢出垃圾"},
            ),
            node(
                "garbage_pile_full_frame_raw",
                "rex.ground@1.1",
                {"frames": "$resized"},
                {"targets": [GARBAGE_TARGETS[2]]},
            ),
            node(
                "garbage_piles",
                "objects.deduplicate@1.0",
                {"objects": "$garbage_pile_full_frame_raw"},
                {
                    "metric": "ios",
                    "threshold": 0.5,
                    "keep": "best_localization",
                },
            ),
            node(
                "scattered_garbage",
                "objects.filter_by_label@1.0",
                {"objects": objects_ref},
                {
                    "labels": ["散落垃圾"],
                    "mode": "include",
                },
            ),
            node(
                "garbage_semantic_results",
                "objects.merge@1.0",
                {
                    "objects": [
                        "$garbage_containers_visible",
                        "$overflow_visible",
                        "$garbage_piles",
                        "$scattered_garbage",
                    ],
                },
            ),
            node(
                "garbage_detection_regions",
                "region.manual_set@1.0",
                {},
                {"regions": []},
            ),
            node(
                "garbage_in_detection_regions",
                "objects.filter_by_regions@1.0",
                {
                    "objects": "$garbage_semantic_results",
                    "regions": "$garbage_detection_regions",
                },
                {
                    "membership_mode": "center",
                    "overlap_threshold": 0.1,
                    "keep": "inside",
                    "empty_regions": "passthrough",
                },
            ),
        ]
        draw["inputs"]["objects"] = "$garbage_in_detection_regions"
        draw["inputs"]["regions"] = "$garbage_detection_regions"
        draft.outputs["objects"] = "$garbage_in_detection_regions"
        draft.outputs["regions"] = "$garbage_detection_regions"
        draft.configuration_slots = [
            *(draft.configuration_slots or []),
            {
                "slot_id": "garbage_detection_regions",
                "kind": "region_set",
                "label": "垃圾检测区域",
                "required": False,
                "binding": {
                    "node_id": "garbage_detection_regions",
                    "parameter": "regions",
                },
                "allowed_shapes": ["rectangle", "polygon"],
                "minimum_items": 1,
                "source_atom_ids": [],
                "help_text": "可围住两处垃圾容器及其周边需要检查的地面；可绘制一个或两个区域。已绘制时仅保留区域内结果，未绘制时检测全画面。",
            },
        ]
        return draft

    bridge_visible_base = visible_builder(
        "bridge_damage",
        BRIDGE_DAMAGE_TARGETS,
        tile=True,
        tile_params={
            "tile_width": 768,
            "tile_height": 768,
            "overlap_x": 0.25,
            "overlap_y": 0.25,
        },
        dedup_threshold=0.55,
    )

    def bridge_visible(media_type: str):
        draft = bridge_visible_base(media_type)
        resize = next(item for item in draft.nodes if item["id"] == "resized")
        resize["params"] = {"mode": "long_side", "long_side": 2048}
        return draft
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
            "按每条车道检测车辆数量不少于4辆且持续1秒的拥堵事件。",
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
            "检测位于手工标注禁停区域内并持续停留10秒的车辆。",
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
                        "temporal",
                        {"type": "persist", "seconds": 10.0},
                        "持续停留10秒",
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
            "检测服务区画面中的垃圾堆、散落垃圾、垃圾容器及溢出垃圾。",
            ("image", "video"),
            ledger(
                "garbage",
                "垃圾堆、散落垃圾、垃圾容器及溢出垃圾",
                [phrase for target in GARBAGE_TARGETS for phrase in target["phrases"]],
                [],
                mode="direct_grounding",
            ),
            lambda media_type: add_final_count(
                stable_video(garbage_visible_in_detection_regions)(media_type),
                media_type,
                group_by="label",
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
                        phrases=[
                            "person actively falling toward the ground",
                            "person losing balance and collapsing",
                            "person bent low while falling",
                            "person lying on the ground",
                        ],
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
            "检测桥梁表面的裂纹、锈蚀、渗水、混凝土剥落和露筋。",
            ("image", "video"),
            ledger(
                "bridge_damage",
                "裂纹、锈蚀、渗水、混凝土剥落和露筋",
                [
                    phrase
                    for target in BRIDGE_DAMAGE_TARGETS
                    for phrase in target["phrases"]
                ],
                [],
                classes=BRIDGE_DAMAGE_TARGETS,
            ),
            stable_video(bridge_visible),
        ),
    ]


__all__ = ["build_preset_definitions"]
