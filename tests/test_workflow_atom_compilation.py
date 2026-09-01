from __future__ import annotations

import pytest

from core.registry import build_default_registry
from core.semantic import SemanticNormalizer, SemanticValidationError, WorkflowCompiler
from core.configuration import ConfigurationBinder, configuration_status
from core.validator import validate_executable_skill_package, validate_skill_package


def _compile(
    instruction,
    constraints,
    *,
    mode="workflow",
    requested=None,
    target=None,
    display_name="工作流检测",
):
    target = target or {
        "concept": "vehicle",
        "source_span": "车辆",
        "phrases": ["vehicle"],
    }
    semantic_ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": mode,
            "target": target,
            "constraints": constraints,
            "logic": "all",
        },
        instruction,
    )
    return WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=instruction,
        requested_accept=requested or ["video"],
        skill_id="workflow_detector",
        display_name=display_name,
    )


def _grounding_source(variant, node_id):
    nodes = {node.id: node for node in variant.nodes}
    node = nodes[node_id]
    if node.op == "rex.ground@1.1":
        return node, node.params["targets"]
    assert node.op == "objects.filter_by_label@1.0"
    source = nodes[node.inputs["objects"].removeprefix("$")]
    labels = set(node.params["labels"])
    return source, [
        target for target in source.params["targets"]
        if target["label"] in labels
    ]


def test_quantity_atom_compiles_to_count_and_explicit_comparison():
    instruction = "车辆数量大于5"
    package = _compile(
        instruction,
        [{
            "kind": "quantity",
            "value": {"operator": ">", "value": 5},
            "source": instruction,
            "source_span": "数量大于5",
        }],
        mode="entity_query",
        requested=["image", "video"],
    )

    for media_type in package.input.accept:
        variant = package.variants[media_type]
        count = next(node for node in variant.nodes if node.id == "constraint_1_count")
        compare = next(node for node in variant.nodes if node.id == "constraint_1_compare")
        assert count.op == "measure.count@1.0"
        if media_type == "image":
            assert count.inputs == {"entities": "$candidates"}
            assert count.params == {"scope": "frame"}
            expected_binding = ["constraint_1_count", "constraint_1_compare"]
        else:
            tracks = next(node for node in variant.nodes if node.id == "count_tracks")
            assert tracks.inputs == {"objects": "$candidates"}
            assert count.inputs == {"entities": "$count_tracks"}
            assert count.params == {"scope": "unique"}
            expected_binding = [
                "count_tracks", "constraint_1_count", "constraint_1_compare"
            ]
        assert compare.op == "logic.compare@1.0"
        assert compare.params == {"operator": ">", "value": 5}
        assert variant.atom_bindings["atom_1"] == expected_binding
        assert variant.outputs["measurements"] == "$constraint_1_count"


def test_enumerated_target_classes_compile_to_distinct_grounding_labels():
    instruction = "检测消防车、救护车和警车并标注具体类型"
    target = {
        "concept": "special_vehicle",
        "source_span": "消防车、救护车和警车",
        "phrases": ["fire truck", "ambulance", "police car"],
        "classes": [
            {"label": "消防车", "phrases": ["fire truck", "fire engine"]},
            {"label": "救护车", "phrases": ["ambulance"]},
            {"label": "警车", "phrases": ["police car", "police vehicle"]},
        ],
    }

    package = _compile(
        instruction,
        [],
        mode="direct_grounding",
        requested=["image"],
        target=target,
        display_name="特种车辆检测",
    )

    grounding = next(
        node for node in package.variants["image"].nodes
        if node.op == "rex.ground@1.1"
    )
    assert grounding.params["targets"] == target["classes"]
    assert grounding.params["phrase_selection"] == "primary_per_target"
    deduplication = next(
        node for node in package.variants["image"].nodes
        if node.op == "objects.deduplicate@1.0"
    )
    assert deduplication.params == {
        "metric": "instance", "threshold": 0.45, "keep": "best_localization"
    }


def test_report_only_count_runs_after_attribute_filter_and_is_a_declared_output():
    instruction = "识别白色车辆数量"
    package = _compile(
        instruction,
        [
            {
                "kind": "color",
                "value": "white",
                "source": instruction,
                "source_span": "白色",
            },
            {
                "kind": "quantity",
                "value": {"measure": "count"},
                "source": instruction,
                "source_span": "数量",
            },
        ],
        mode="entity_query",
        requested=["image", "video"],
    )

    for media_type in package.input.accept:
        variant = package.select_variant(media_type)
        filtered = next(node for node in variant.nodes if node.op == "filter.apply@1.0")
        count = next(node for node in variant.nodes if node.op == "measure.count@1.0")
        if media_type == "image":
            assert count.inputs == {"entities": f"${filtered.id}"}
            assert count.params == {"scope": "frame"}
        else:
            tracks = next(node for node in variant.nodes if node.op == "track.iou@1.0")
            assert tracks.inputs == {"objects": f"${filtered.id}"}
            assert count.inputs == {"entities": f"${tracks.id}"}
            assert count.params == {"scope": "unique"}
        assert not any(
            node.op == "logic.compare@1.0"
            and node.inputs.get("left") == f"${count.id}"
            for node in variant.nodes
        )
        assert variant.outputs["measurements"] == f"${count.id}"
        quantity_atom = next(
            item.atom_id
            for item in package.semantic_ir.constraints
            if item.kind == "quantity"
        )
        assert variant.atom_bindings[quantity_atom] == (
            [count.id]
            if media_type == "image"
            else [tracks.id, count.id]
        )


def test_conditional_entity_output_uses_the_complete_user_predicate_label():
    instruction = "识别未带安全帽的人。"
    package = _compile(
        instruction,
        [{
            "kind": "wearable",
            "value": "safety helmet",
            "polarity": "absent",
            "source": instruction,
            "source_span": "未带安全帽",
            "phrases": ["person wearing safety helmet"],
        }],
        mode="entity_query",
        requested=["image"],
        target={
            "concept": "person",
            "source_span": "人",
            "phrases": ["person"],
        },
    )

    variant = package.variants["image"]
    relabel = next(
        node for node in variant.nodes if node.op == "objects.relabel@1.0"
    )
    draw = next(node for node in variant.nodes if node.op == "output.draw@1.0")

    assert relabel.params == {"label": "未带安全帽的人"}
    assert relabel.inputs == {"objects": "$filtered"}
    assert draw.inputs["objects"] == f"${relabel.id}"
    assert variant.outputs["objects"] == f"${relabel.id}"


def test_video_report_only_count_is_unique_tracks_while_image_count_is_per_frame():
    instruction = "识别白色车辆数量"
    package = _compile(
        instruction,
        [
            {
                "kind": "color",
                "value": "white",
                "source": instruction,
                "source_span": "白色",
            },
            {
                "kind": "quantity",
                "value": {"measure": "count", "scope": "auto"},
                "source": instruction,
                "source_span": "数量",
            },
        ],
        mode="entity_query",
        requested=["image", "video"],
    )

    image = package.select_variant("image")
    image_count = next(node for node in image.nodes if node.op == "measure.count@1.0")
    assert image_count.inputs == {"entities": "$filtered"}
    assert image_count.params == {"scope": "frame"}

    video = package.select_variant("video")
    video_count = next(node for node in video.nodes if node.op == "measure.count@1.0")
    tracks = next(node for node in video.nodes if node.op == "track.iou@1.0")
    assert video_count.inputs == {"entities": f"${tracks.id}"}
    assert video_count.params == {"scope": "unique"}


def test_human_image_axis_direction_reuses_generic_track_heading_and_compare_atoms():
    instruction = "检测向右运动的人"
    package = _compile(
        instruction,
        [
            {
                "kind": "direction_relation",
                "value": {
                    "relation": "aligned",
                    "reference_scope": "global",
                    "reference_source": "image_axis",
                    "image_axis": "right",
                    "cosine_threshold": 0.5,
                },
                "source": instruction,
                "source_span": "向右运动",
            }
        ],
        target={"concept": "person", "source_span": "人", "phrases": ["person"]},
        display_name="向右运动的人",
    )

    variant = package.select_variant("video")
    tracks = next(node for node in variant.nodes if node.op == "track.iou@1.0")
    headings = next(node for node in variant.nodes if node.op == "measure.heading@1.0")
    reference = next(
        node for node in variant.nodes if node.op == "direction.image_axis@1.0"
    )
    comparison = next(
        node
        for node in variant.nodes
        if node.op == "logic.compare@1.0"
        and node.inputs.get("left") == f"${headings.id}"
    )
    assert tracks.inputs == {"objects": "$candidates"}
    assert headings.inputs == {"tracks": f"${tracks.id}"}
    assert reference.params == {"direction": "right"}
    assert comparison.inputs == {
        "left": f"${headings.id}",
        "right": f"${reference.id}",
    }
    assert comparison.params == {
        "operator": "aligned_direction",
        "threshold": 0.5,
    }
    assert variant.configuration_slots == []
    draw = next(node for node in variant.nodes if node.op == "output.draw@1.0")
    assert draw.inputs["directions"] == f"${reference.id}"
    assert variant.outputs["directions"] == f"${reference.id}"


@pytest.mark.parametrize(
    ("target,display_name"),
    [
        (
            {"concept": "person", "source_span": "人", "phrases": ["person"]},
            "向右运动的人",
        ),
        (
            {"concept": "vehicle", "source_span": "车辆", "phrases": ["vehicle"]},
            "向右运动的车辆",
        ),
        (
            {"concept": "animal", "source_span": "动物", "phrases": ["animal"]},
            "向右运动的动物",
        ),
    ],
)
def test_direction_pipeline_is_entity_agnostic(target, display_name):
    instruction = f"检测{display_name}"
    package = _compile(
        instruction,
        [{
            "kind": "direction_relation",
            "value": {
                "relation": "aligned",
                "reference_scope": "global",
                "reference_source": "image_axis",
                "image_axis": "right",
                "cosine_threshold": 0.5,
            },
            "source": instruction,
            "source_span": "向右运动",
        }],
        target=target,
        display_name=display_name,
    )

    variant = package.select_variant("video")
    ground = next(node for node in variant.nodes if node.id == "candidates_raw")
    assert ground.params["targets"][0]["phrases"] == target["phrases"]
    assert [
        node.op for node in variant.nodes
        if node.op in {
            "track.iou@1.0", "measure.heading@1.0",
            "direction.image_axis@1.0", "logic.compare@1.0",
        }
    ] == [
        "track.iou@1.0", "measure.heading@1.0",
        "direction.image_axis@1.0", "logic.compare@1.0",
    ]


def test_global_whole_video_direction_reference_is_target_agnostic_and_explicit():
    instruction = "检测与整段视频多数人员运动方向相反的人"
    package = _compile(
        instruction,
        [{
            "kind": "direction_relation",
            "value": {
                "relation": "opposite",
                "reference_scope": "global",
                "reference_source": "whole_video_majority",
                "cosine_threshold": -0.5,
                "minimum_tracks": 2,
            },
            "source": instruction,
            "source_span": "与整段视频多数人员运动方向相反",
        }],
        target={"concept": "person", "source_span": "人", "phrases": ["person"]},
        display_name="逆向运动人员",
    )

    variant = package.select_variant("video")
    reference = next(
        node for node in variant.nodes
        if node.op == "measure.majority_heading@1.0"
    )
    assert reference.params == {"minimum_tracks": 2, "aggregation": "global"}
    assert variant.configuration_slots == []
    assert variant.outputs["directions"] == f"${reference.id}"


def test_human_global_manual_direction_compiles_a_generic_direction_slot():
    instruction = "检测与手工参考方向相反运动的人"
    package = _compile(
        instruction,
        [
            {
                "kind": "direction_relation",
                "value": {
                    "relation": "opposite",
                    "reference_scope": "global",
                    "reference_source": "manual",
                    "cosine_threshold": -0.5,
                },
                "source": instruction,
                "source_span": "与手工参考方向相反运动",
            }
        ],
        target={"concept": "person", "source_span": "人", "phrases": ["person"]},
        display_name="反向运动的人",
    )

    variant = package.variants["video"]
    reference = next(node for node in variant.nodes if node.op == "direction.manual@1.0")
    comparison = next(
        node
        for node in variant.nodes
        if node.op == "logic.compare@1.0"
        and node.inputs.get("right") == f"${reference.id}"
    )
    assert reference.params == {"vector": [0.0, 0.0]}
    assert comparison.params == {
        "operator": "opposite_direction",
        "threshold": -0.5,
    }
    assert variant.status == "needs_configuration"
    assert len(variant.configuration_slots) == 1
    slot = variant.configuration_slots[0]
    assert slot.kind == "direction"
    assert slot.binding.node_id == reference.id
    assert validate_skill_package(package, build_default_registry()) == []
    assert validate_executable_skill_package(package, build_default_registry()) == [
        f"video: required configuration slot {slot.slot_id} is pending"
    ]


def test_relative_spatial_atom_compiles_reference_entity_and_box_relation():
    instruction = "检测靠近挖掘机的车辆"
    package = _compile(
        instruction,
        [{
            "kind": "spatial_relation",
            "value": {
                "relation": "near",
                "object": {"concept": "excavator", "phrases": ["excavator"]},
                "threshold": 0.15,
            },
            "source": instruction,
            "source_span": "靠近挖掘机",
        }],
        mode="entity_query",
        requested=["image"],
    )

    variant = package.select_variant("image")
    reference = next(node for node in variant.nodes if node.id == "constraint_1_reference")
    relation = next(node for node in variant.nodes if node.id == "constraint_1_relation")
    _grounding, targets = _grounding_source(variant, reference.id)
    assert targets[0]["phrases"] == ["excavator"]
    assert relation.op == "spatial.associate@1.0"
    assert relation.inputs == {
        "subjects": "$candidates",
        "objects": "$constraint_1_reference_dedup",
    }
    assert relation.params == {"relation": "near", "threshold": 0.15}


def test_inside_automatic_region_compiles_region_grounding_and_inside_operator():
    instruction = "检测车道内的车辆"
    package = _compile(
        instruction,
        [{
            "kind": "spatial_relation",
            "value": {
                "relation": "inside_roi",
                "region": {"source": "grounding", "phrases": ["traffic lane"]},
                "mode": "center",
            },
            "source": instruction,
            "source_span": "车道内",
        }],
        mode="entity_query",
        requested=["image"],
    )

    variant = package.select_variant("image")
    region_objects = next(node for node in variant.nodes if node.id == "constraint_1_region_objects")
    region = next(node for node in variant.nodes if node.id == "constraint_1_region")
    inside = next(node for node in variant.nodes if node.id == "constraint_1_inside")
    _grounding, targets = _grounding_source(variant, region_objects.id)
    assert targets[0]["phrases"] == ["traffic lane"]
    assert region.op == "region.from_objects@1.0"
    assert inside.inputs == {"objects": "$candidates", "region": "$constraint_1_region"}


def test_manual_roi_relation_without_points_compiles_a_pending_region_slot():
    instruction = "检测危险区域内的车辆"
    semantic_ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {"concept": "vehicle", "source_span": "车辆", "phrases": ["vehicle"]},
            "constraints": [{
                "kind": "spatial_relation",
                "value": {"relation": "inside_roi", "region": {"source": "manual"}},
                "source": instruction,
                "source_span": "危险区域内",
            }],
            "logic": "all",
        },
        instruction,
    )

    package = WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=instruction,
        requested_accept=["image"],
        skill_id="danger_zone_vehicle",
        display_name="危险区域车辆",
    )

    variant = package.variants["image"]
    region = next(node for node in variant.nodes if node.id == "constraint_1_region")
    assert region.op == "region.manual@1.0"
    assert region.params == {"shape": "polygon", "points": []}
    assert variant.status == "needs_configuration"
    assert [slot.kind for slot in variant.configuration_slots] == ["region"]
    assert validate_skill_package(package, build_default_registry()) == []
    assert validate_executable_skill_package(package, build_default_registry()) == [
        "image: required configuration slot constraint_1_region is pending"
    ]


def test_region_motion_and_persist_compile_one_track_keyed_event_workflow():
    instruction = "检测禁停区域内速度低于2并持续10秒的车辆"
    package = _compile(
        instruction,
        [
            {
                "kind": "spatial_relation",
                "value": {
                    "relation": "inside_roi",
                    "region": {
                        "source": "manual",
                        "semantic_role": "no_parking",
                        "allowed_shapes": ["rectangle", "polygon"],
                    },
                    "mode": "center",
                },
                "source": instruction,
                "source_span": "禁停区域内",
            },
            {
                "kind": "motion",
                "value": {
                    "measure": "speed",
                    "operator": "<",
                    "threshold": 2.0,
                    "unit": "pixels_per_second",
                    "aggregation": "per_track",
                    "window_frames": 2,
                },
                "source": instruction,
                "source_span": "速度低于2",
            },
            {
                "kind": "temporal",
                "value": {
                    "type": "persist",
                    "seconds": 10.0,
                    "gap_tolerance_seconds": 1.1,
                },
                "source": instruction,
                "source_span": "持续10秒",
                "temporal": True,
            },
        ],
    )

    variant = package.variants["video"]
    assert variant.status == "needs_configuration"
    tracks = [node for node in variant.nodes if node.op == "track.iou@1.0"]
    assert len(tracks) == 1
    region = next(node for node in variant.nodes if node.op == "region.manual@1.0")
    inside = next(node for node in variant.nodes if node.op == "spatial.inside@1.0")
    speed = next(node for node in variant.nodes if node.op == "measure.speed@1.0")
    compare = next(
        node
        for node in variant.nodes
        if node.op == "logic.compare@1.0" and node.inputs.get("left") == f"${speed.id}"
    )
    combined = next(node for node in variant.nodes if node.op == "logic.all@1.0")
    event = next(node for node in variant.nodes if node.op == "event.from_condition@1.0")
    matched_tracks = next(node for node in variant.nodes if node.op == "tracks.filter@1.0")
    boxes = next(node for node in variant.nodes if node.op == "objects.from_tracks@1.0")
    draw = next(node for node in variant.nodes if node.op == "output.draw@1.0")
    assert inside.inputs == {"objects": f"${tracks[0].id}", "region": f"${region.id}"}
    assert speed.inputs == {"tracks": f"${tracks[0].id}"}
    assert speed.params == {
        "window_frames": 2,
        "unit": "pixels_per_second",
        "aggregation": "per_track",
    }
    assert compare.params["operator"] == "<"
    assert compare.params["value"] == 2.0
    assert set(combined.inputs["conditions"]) == {f"${inside.id}", f"${compare.id}"}
    assert event.inputs == {"condition": f"${combined.id}"}
    assert event.params == {
        "seconds": 10.0,
        "scope": "track",
        "gap_tolerance_seconds": 1.1,
        "trigger_mode": "once",
        "label": "工作流检测",
    }
    assert matched_tracks.inputs == {
        "tracks": f"${tracks[0].id}",
        "condition": f"${combined.id}",
    }
    assert matched_tracks.params == {"history_mode": "matching_samples"}
    assert boxes.inputs == {"tracks": f"${matched_tracks.id}"}
    assert boxes.params == {"selection": "all"}
    relabel = next(node for node in variant.nodes if node.op == "objects.relabel@1.0")
    assert relabel.inputs == {"objects": f"${boxes.id}"}
    assert draw.inputs["objects"] == f"${relabel.id}"
    alert = next(node for node in variant.nodes if node.op == "output.alert@1.0")
    assert alert.inputs == {"events": f"${event.id}"}
    assert draw.inputs["events"] == f"${alert.id}"
    assert draw.inputs["regions"] == f"${region.id}"
    assert variant.outputs == {
        "media": f"${draw.id}",
        "objects": f"${relabel.id}",
        "tracks": f"${matched_tracks.id}",
        "events": f"${alert.id}",
        "regions": f"${region.id}",
        "condition": f"${combined.id}",
        "measurements": f"${speed.id}",
    }
    assert validate_skill_package(package, build_default_registry()) == []

    ready = ConfigurationBinder(build_default_registry()).bind_region(
        package,
        media_type="video",
        slot_id=variant.configuration_slots[0].slot_id,
        shape="rectangle",
        points=[[0.1, 0.2], [0.9, 0.9]],
    )
    assert ready.variants["video"].status == "executable"
    assert validate_executable_skill_package(ready, build_default_registry()) == []


def test_per_named_region_opposite_direction_compiles_auto_and_manual_references():
    instruction = "按每条车道检测与整段视频多数车流方向相反并持续1秒的车辆"
    package = _compile(
        instruction,
        [
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": "many",
                    "semantic_role": "lane",
                    "allowed_shapes": ["polygon"],
                },
                "source": instruction,
                "source_span": "每条车道",
            },
            {
                "kind": "direction_relation",
                "value": {
                    "relation": "opposite",
                    "reference_scope": "per_named_region",
                    "reference_source": "whole_video_majority",
                    "cosine_threshold": -0.5,
                    "minimum_tracks": 2,
                },
                "source": instruction,
                "source_span": "与整段视频多数车流方向相反",
            },
            {
                "kind": "temporal",
                "value": {"type": "persist", "seconds": 1.0},
                "source": instruction,
                "source_span": "持续1秒",
                "temporal": True,
            },
        ],
    )

    variant = package.variants["video"]
    region_slot = next(
        slot for slot in variant.configuration_slots if slot.kind == "region_set"
    )
    assert region_slot.allowed_shapes == ["rectangle", "polygon"]
    assert variant.status == "needs_configuration"
    lanes = next(node for node in variant.nodes if node.op == "region.manual_set@1.0")
    tracks = next(node for node in variant.nodes if node.op == "track.iou@1.0")
    headings = next(node for node in variant.nodes if node.op == "measure.heading@1.0")
    references = next(
        node for node in variant.nodes if node.op == "measure.lane_majority_heading@1.0"
    )
    opposite = next(node for node in variant.nodes if node.op == "logic.heading_by_lane@1.0")
    assert lanes.params == {"regions": []}
    assert headings.inputs == {"tracks": f"${tracks.id}"}
    assert references.inputs == {
        "tracks": f"${tracks.id}",
        "directions": f"${headings.id}",
        "lanes": f"${lanes.id}",
    }
    assert references.params["minimum_tracks"] == 2
    assert opposite.inputs == {
        "tracks": f"${tracks.id}",
        "headings": f"${headings.id}",
        "lanes": f"${lanes.id}",
        "references": f"${references.id}",
    }
    slots = {slot.kind: slot for slot in variant.configuration_slots}
    assert slots["region_set"].binding.node_id == lanes.id
    assert slots["direction_set"].binding.node_id == references.id
    assert slots["direction_set"].active_when_op == ["direction.manual_set@1.0"]
    assert slots["direction_set"].key_source_slot_id == slots["region_set"].slot_id
    status = {item["kind"]: item for item in configuration_status(package)}
    assert status["region_set"]["configured"] is False
    assert status["direction_set"]["active"] is False


def test_named_region_congestion_compiles_lane_keyed_count_speed_and_events():
    instruction = "按每条车道检测车辆数量不少于4辆、平均速度低于10并持续1秒的拥堵"
    package = _compile(
        instruction,
        [
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": "many",
                    "semantic_role": "lane",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "每条车道",
            },
            {
                "kind": "quantity",
                "value": {
                    "measure": "count",
                    "operator": ">=",
                    "value": 4,
                    "group_by": "named_region",
                    "region_role": "lane",
                },
                "source": instruction,
                "source_span": "车辆数量不少于4辆",
            },
            {
                "kind": "motion",
                "value": {
                    "measure": "speed",
                    "operator": "<",
                    "threshold": 10.0,
                    "unit": "pixels_per_second",
                    "aggregation": "region_median",
                    "group_by": "named_region",
                    "region_role": "lane",
                },
                "source": instruction,
                "source_span": "平均速度低于10",
            },
            {
                "kind": "temporal",
                "value": {"type": "persist", "seconds": 1.0},
                "source": instruction,
                "source_span": "持续1秒",
                "temporal": True,
            },
        ],
    )

    variant = package.variants["video"]
    lanes = next(node for node in variant.nodes if node.op == "region.manual_set@1.0")
    count = next(node for node in variant.nodes if node.op == "measure.region_count@1.0")
    speed = next(node for node in variant.nodes if node.op == "measure.region_speed@1.0")
    event = next(node for node in variant.nodes if node.op == "event.from_condition@1.0")
    assert count.inputs == {
        "objects": "$candidates",
        "regions": f"${lanes.id}",
        "frames": "$resized",
    }
    assert speed.inputs["regions"] == f"${lanes.id}"
    assert event.params["scope"] == "region"
    assert variant.outputs["regions"] == f"${lanes.id}"
    assert {
        value for key, value in variant.outputs.items()
        if key.startswith("measurements_")
    } == {f"${count.id}", f"${speed.id}"}


def test_fixed_region_count_threshold_compiles_reusable_event_graph():
    instruction = "检测固定区域内有大于2辆车辆，触发事件告警"
    package = _compile(
        instruction,
        [
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": "one",
                    "semantic_role": "area",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "固定区域",
            },
            {
                "kind": "quantity",
                "value": {
                    "measure": "count",
                    "operator": ">",
                    "value": 2,
                    "group_by": "named_region",
                    "region_role": "area",
                },
                "source": instruction,
                "source_span": "大于2辆车",
            },
        ],
    )

    variant = package.variants["video"]
    assert any(node.op == "region.manual@1.0" for node in variant.nodes)
    assert any(node.op == "measure.region_count@1.0" for node in variant.nodes)
    assert any(node.op == "logic.compare@1.0" for node in variant.nodes)
    assert any(node.op == "event.from_condition@1.0" for node in variant.nodes)
    assert any(node.op == "output.alert@1.0" for node in variant.nodes)
    assert "events" in variant.outputs
    assert any(slot.kind == "region" for slot in variant.configuration_slots)


def test_stream_grounding_uses_target_entity_label_not_skill_display_name():
    instruction = "检测固定区域内有大于2辆车辆，触发事件告警"
    package = _compile(
        instruction,
        [
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": "one",
                    "semantic_role": "area",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "固定区域",
            },
            {
                "kind": "quantity",
                "value": {
                    "measure": "count",
                    "operator": ">",
                    "value": 2,
                    "group_by": "named_region",
                    "region_role": "area",
                },
                "source": instruction,
                "source_span": "大于2辆车辆",
            },
        ],
    )

    grounding = next(
        node for node in package.variants["video"].nodes
        if node.id == "candidates_raw"
    )
    assert grounding.params["targets"][0]["label"] == "车辆"


def test_fixed_region_count_range_and_persistence_compiles_as_composed_atoms():
    instruction = "检测固定区域内有大于2辆车辆且少于5辆车辆，且持续时间不少于1s，触发事件告警"
    package = _compile(
        instruction,
        [
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": "one",
                    "semantic_role": "area",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "固定区域",
            },
            {
                "kind": "quantity",
                "value": {"measure": "count", "operator": ">", "value": 2, "group_by": "named_region", "region_role": "area"},
                "source": instruction,
                "source_span": "大于2辆车",
            },
            {
                "kind": "quantity",
                "value": {"measure": "count", "operator": "<", "value": 5, "group_by": "named_region", "region_role": "area"},
                "source": instruction,
                "source_span": "少于5辆车",
            },
            {
                "kind": "temporal",
                "value": {"type": "persist", "seconds": 1.0},
                "source": instruction,
                "source_span": "持续时间不少于1s",
                "temporal": True,
            },
        ],
    )

    variant = package.variants["video"]
    assert sum(node.op == "measure.region_count@1.0" for node in variant.nodes) == 2
    assert sum(node.op == "logic.compare@1.0" for node in variant.nodes) == 2
    assert any(node.op == "logic.all@1.0" for node in variant.nodes)
    assert any(node.op == "event.from_condition@1.0" for node in variant.nodes)
    assert any(node.op == "output.alert@1.0" for node in variant.nodes)
    assert "events" in variant.outputs
    assert any(slot.kind == "region" for slot in variant.configuration_slots)
    combined = next(node for node in variant.nodes if node.op == "logic.all@1.0")
    assert combined.params["combine_scope"] == "by_key"


def test_independent_regions_merge_for_display_and_combine_on_same_frame():
    instruction = "区域1有不少于1辆车，区域2有不少于2辆车，则发出告警"
    package = _compile(
        instruction,
        [
            {
                "kind": "quantity",
                "value": {
                    "measure": "count", "operator": ">=", "value": 1,
                    "group_by": "named_region", "region_role": "region_1",
                },
                "source": instruction,
                "source_span": "区域1有不少于1辆车",
            },
            {
                "kind": "quantity",
                "value": {
                    "measure": "count", "operator": ">=", "value": 2,
                    "group_by": "named_region", "region_role": "region_2",
                },
                "source": instruction,
                "source_span": "区域2有不少于2辆车",
            },
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual", "cardinality": "one",
                    "semantic_role": "region_1",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "区域1",
            },
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual", "cardinality": "one",
                    "semantic_role": "region_2",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "区域2",
            },
        ],
        target={
            "concept": "vehicle",
            "source_span": "车",
            "phrases": ["vehicle"],
        },
    )

    variant = package.variants["video"]
    nodes = {node.id: node for node in variant.nodes}

    assert nodes["draw_regions"].op == "regions.merge@1.0"
    assert nodes["draw_regions"].inputs == {
        "regions": ["$constraint_3_regions", "$constraint_4_regions"]
    }
    assert nodes["draw"].inputs["regions"] == "$draw_regions"
    assert variant.outputs["regions"] == "$draw_regions"
    assert nodes["stream_conditions"].params["combine_scope"] == "frame_any"


def test_target_in_one_region_and_count_in_another_use_explicit_frame_broadcast():
    instruction = "区域1有指定人员，并且区域2人数大于等于3，则告警"
    package = _compile(
        instruction,
        [
            {
                "kind": "spatial_relation",
                "value": {
                    "relation": "inside_roi",
                    "region": {
                        "source": "manual",
                        "semantic_role": "region_1",
                        "shape": "polygon",
                        "allowed_shapes": ["rectangle", "polygon"],
                    },
                },
                "source": instruction,
                "source_span": "区域1",
            },
            {
                "kind": "quantity",
                "value": {
                    "measure": "count", "operator": ">=", "value": 3,
                    "group_by": "named_region", "region_role": "region_2",
                },
                "source": instruction,
                "source_span": "区域2人数大于等于3",
            },
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual", "cardinality": "one",
                    "semantic_role": "region_2",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "区域2",
            },
        ],
        target={
            "concept": "person",
            "source_span": "人员",
            "phrases": ["person"],
        },
    )

    nodes = {node.id: node for node in package.variants["video"].nodes}
    assert nodes["stream_conditions"].params["combine_scope"] == "frame_any"
    condition_nodes = {
        nodes[reference.removeprefix("$")].op
        for reference in nodes["stream_conditions"].inputs["conditions"]
    }
    assert condition_nodes == {"spatial.inside@1.0", "logic.compare@1.0"}


def test_static_named_regions_count_and_immediate_alert_support_images():
    instruction = "区域1有指定人员，区域2中人的数量大于2，则发出告警"
    package = _compile(
        instruction,
        [
            {
                "kind": "spatial_relation",
                "value": {
                    "relation": "inside_roi",
                    "region": {
                        "source": "manual", "semantic_role": "region_1",
                        "shape": "polygon",
                        "allowed_shapes": ["rectangle", "polygon"],
                    },
                },
                "source": instruction,
                "source_span": "区域1",
            },
            {
                "kind": "quantity",
                "value": {
                    "measure": "count", "operator": ">", "value": 2,
                    "group_by": "named_region", "region_role": "region_2",
                },
                "source": instruction,
                "source_span": "区域2中人的数量大于2",
            },
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual", "cardinality": "one",
                    "semantic_role": "region_2",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "区域2",
            },
        ],
        requested=["image", "video"],
        target={
            "concept": "person",
            "source_span": "人员",
            "phrases": ["person"],
        },
    )

    assert package.input.accept == ["image", "video"]
    image = package.variants["image"]
    image_ops = {node.op for node in image.nodes}
    assert "track.iou@1.0" not in image_ops
    assert "objects.from_tracks@1.0" not in image_ops
    assert "measure.region_count@1.0" in image_ops
    assert "event.from_condition@1.0" in image_ops
    assert "output.alert@1.0" in image_ops
    assert image.status == "needs_configuration"
    assert {slot.label for slot in image.configuration_slots} == {"区域1", "区域2"}


def test_independent_region_attribute_branch_and_plain_count_branch_are_combined():
    instruction = "区域1有穿红色衣服、灰色裤子的人，区域2中人的数量大于2，则发出告警。"
    package = _compile(
        instruction,
        [
            {
                "kind": "color", "value": "red",
                "source": "区域1有穿红色衣服、灰色裤子的人",
                "source_span": "红色衣服",
                "carrier": "upper_body_clothing", "carrier_span": "衣服",
            },
            {
                "kind": "color", "value": "gray",
                "source": "区域1有穿红色衣服、灰色裤子的人",
                "source_span": "灰色裤子",
                "carrier": "lower_body_clothing", "carrier_span": "裤子",
            },
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual", "cardinality": "one",
                    "semantic_role": "region1",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": "区域1有穿红色衣服、灰色裤子的人",
                "source_span": "区域1",
            },
            {
                "kind": "quantity",
                "value": {
                    "measure": "count", "operator": ">", "value": 2,
                    "group_by": "named_region", "region_role": "region2",
                },
                "source": "区域2中人的数量大于2",
                "source_span": "人的数量大于2",
            },
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual", "cardinality": "one",
                    "semantic_role": "region2",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": "区域2中人的数量大于2",
                "source_span": "区域2",
            },
        ],
        requested=["image", "video"],
        target={"concept": "person", "source_span": "人", "phrases": ["person"]},
        display_name="多区域人员告警",
    )

    for media_type in package.input.accept:
        variant = package.variants[media_type]
        nodes = {node.id: node for node in variant.nodes}
        region1 = next(
            item for item in package.semantic_ir.constraints
            if item.kind == "region_requirement"
            and item.value["semantic_role"] == "region1"
        )
        quantity = next(
            item for item in package.semantic_ir.constraints
            if item.kind == "quantity"
        )
        region1_binding = variant.atom_bindings[region1.atom_id]
        quantity_binding = variant.atom_bindings[quantity.atom_id]
        region1_count = nodes[next(
            node_id for node_id in region1_binding
            if node_id.endswith("_region_count")
        )]
        quantity_count = nodes[next(
            node_id for node_id in quantity_binding
            if node_id.endswith("_count")
        )]

        assert region1_count.inputs["objects"] == "$entity_filtered"
        assert quantity_count.inputs["objects"] == "$candidates"
        assert nodes["stream_conditions"].op == "logic.all@1.0"
        assert nodes["stream_conditions"].params["combine_scope"] == "frame_any"
        assert nodes["condition_event"].inputs["condition"] == "$stream_conditions"
        assert not any(node.op == "objects.relabel@1.0" for node in variant.nodes)
        assert nodes["business_label_branch_1"].params["output_label"] == (
            "红色上衣、灰色裤子人员"
        )
        assert nodes["business_label_branch_2"].params["output_label"] == "人员"
        assert nodes["business_label_outside_1"].inputs["left"] == "$candidates"
        assert nodes["business_labeled_objects"].op == "objects.merge@1.0"
        assert variant.outputs["objects"] == "$business_labeled_objects"
        _grounding, targets = _grounding_source(variant, "candidates_raw")
        assert targets[0]["label"] == "人"
        assert nodes["condition_event"].params["label"] == "多区域人员告警"
        assert nodes["alerts"].params["label"] == "多区域人员告警"
        assert variant.outputs["events"] == "$alerts"

    ready_image = package
    for slot in package.variants["image"].configuration_slots:
        ready_image = ConfigurationBinder(build_default_registry()).bind_region(
            ready_image,
            media_type="image",
            slot_id=slot.slot_id,
            shape="rectangle",
            points=[[0.1, 0.1], [0.4, 0.4]],
        )
    assert validate_executable_skill_package(
        ready_image, build_default_registry(), "image"
    ) == []
    assert any(
        error.startswith("video: required configuration slot")
        for error in validate_executable_skill_package(
            ready_image, build_default_registry()
        )
    )


def test_two_distinct_regions_can_be_saved_one_after_another():
    instruction = "检测区域1和区域2内的车辆"
    package = _compile(
        instruction,
        [
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": "one",
                    "semantic_role": "area_1",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "区域1",
            },
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": "one",
                    "semantic_role": "area_2",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": instruction,
                "source_span": "区域2",
            },
            {
                "kind": "spatial_relation",
                "value": {
                    "relation": "inside_roi",
                    "region": {"source": "manual", "semantic_role": "area_1"},
                },
                "source": instruction,
                "source_span": "区域1",
            },
            {
                "kind": "spatial_relation",
                "value": {
                    "relation": "inside_roi",
                    "region": {"source": "manual", "semantic_role": "area_2"},
                },
                "source": instruction,
                "source_span": "区域2",
            },
        ],
    )

    variant = package.variants["video"]
    slots = [slot for slot in variant.configuration_slots if slot.kind == "region"]
    assert [slot.label for slot in slots] == ["区域1", "区域2"]

    partial = ConfigurationBinder(build_default_registry()).bind_region(
        package,
        media_type="video",
        slot_id=slots[0].slot_id,
        shape="rectangle",
        points=[[0.1, 0.1], [0.4, 0.4]],
    )
    status = configuration_status(partial)
    assert partial.variants["video"].status == "needs_configuration"
    assert status[0]["configured"] is True
    assert status[1]["configured"] is False


def test_persist_atom_rejects_image_but_builds_video_tracking_and_event():
    instruction = "车辆持续出现超过10秒"
    package = _compile(
        instruction,
        [{
            "kind": "temporal",
            "value": {"type": "persist", "seconds": 10, "gap_tolerance_seconds": 0.5},
            "source": instruction,
            "source_span": "持续出现超过10秒",
            "temporal": True,
        }],
        requested=["image", "video"],
    )

    assert package.input.requested_accept == ["image", "video"]
    assert package.input.accept == ["video"]
    assert package.variants["image"].status == "unsupported"
    video = package.select_variant("video")
    assert [node.op for node in video.nodes if node.id in video.atom_bindings["atom_1"]] == [
        "track.iou@1.0",
        "region.full_frame@1.0",
        "spatial.inside@1.0",
        "temporal.persist@1.0",
    ]
    assert video.outputs["events"] == "$constraint_1_persist"
    assert validate_skill_package(package, build_default_registry()) == []


def test_sequence_atom_compiles_affirmative_steps_and_fixed_sequence_operator():
    instruction = "车辆先进入区域再离开"
    package = _compile(
        instruction,
        [{
            "kind": "temporal",
            "value": {
                "type": "sequence",
                "steps": [
                    {"label": "进入", "phrases": ["vehicle entering an area"]},
                    {"label": "离开", "phrases": ["vehicle leaving an area"]},
                ],
                "max_gap_seconds": 5,
                "same_key": False,
            },
            "source": instruction,
            "source_span": "先进入区域再离开",
            "temporal": True,
        }],
    )

    video = package.select_variant("video")
    sequence = next(node for node in video.nodes if node.id == "constraint_1_sequence")
    assert sequence.op == "temporal.sequence@2.0"
    assert sequence.params == {
        "transitions": [{
            "relation": "after",
            "source_anchor": "end",
            "target_anchor": "start",
            "minimum_delay_seconds": 0.0,
            "maximum_delay_seconds": 5,
        }],
        "correlation_scope": "global",
        "correlation_fields": [],
        "consume_events": True,
        "label": "离开",
    }
    assert len(sequence.inputs["events"]) == 2
