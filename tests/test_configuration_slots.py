from __future__ import annotations

import json

import pytest

from core.configuration import ConfigurationBinder, configuration_status
from core.registry import build_default_registry
from core.runtime import SkillPackageRuntime
from core.schema import SkillPackage
from core.validator import (
    validate_executable_skill_package,
    validate_skill_package,
)
from core.persistence import RunStore
from pathlib import Path


def _semantic_ir():
    return {
        "schema_version": "1.0",
        "mode": "workflow",
        "target": {
            "concept": "vehicle",
            "source_span": "车辆",
            "phrases": ["vehicle"],
        },
        "constraints": [
            {
                "atom_id": "atom_1",
                "kind": "spatial_relation",
                "value": {
                    "relation": "inside_roi",
                    "region": {"source": "manual"},
                },
                "source": "检测禁停区域内的车辆",
                "source_span": "禁停区域内",
                "polarity": "required",
                "phrases": [],
                "temporal": False,
            }
        ],
        "logic": "all",
        "unresolved": [],
        "semantic_hash": "a" * 64,
    }


def _pending_package() -> SkillPackage:
    return SkillPackage.model_validate(
        {
            "schema_version": "2.0",
            "skill_id": "parking_zone_vehicle",
            "version": 1,
            "display_name": "禁停区车辆",
            "original_instruction": "检测禁停区域内的车辆",
            "compile_status": "needs_review",
            "input": {
                "requested_accept": ["video"],
                "accept": ["video"],
            },
            "semantic_ir": _semantic_ir(),
            "variants": {
                "video": {
                    "media_type": "video",
                    "status": "needs_configuration",
                    "nodes": [
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
                            "params": {"mode": "fps", "fps": 2.0},
                        },
                        {
                            "id": "resized",
                            "op": "image.resize@1.1",
                            "inputs": {"frames": "$frames"},
                            "params": {"mode": "long_side", "long_side": 1280},
                        },
                        {
                            "id": "vehicles_raw",
                            "op": "rex.ground@1.1",
                            "inputs": {"frames": "$resized"},
                            "params": {
                                "targets": [
                                    {"label": "车辆", "phrases": ["vehicle"]}
                                ]
                            },
                        },
                        {
                            "id": "vehicles",
                            "op": "objects.deduplicate@1.0",
                            "inputs": {"objects": "$vehicles_raw"},
                            "params": {
                                "metric": "ios",
                                "threshold": 0.5,
                                "keep": "first",
                            },
                        },
                        {
                            "id": "no_parking_region",
                            "op": "region.manual@1.0",
                            "inputs": {},
                            "params": {"shape": "polygon", "points": []},
                        },
                        {
                            "id": "inside",
                            "op": "spatial.inside@1.0",
                            "inputs": {
                                "objects": "$vehicles",
                                "region": "$no_parking_region",
                            },
                            "params": {
                                "mode": "center",
                                "overlap_threshold": 0.5,
                            },
                        },
                        {
                            "id": "filtered",
                            "op": "filter.apply@1.0",
                            "inputs": {
                                "objects": "$vehicles",
                                "condition": "$inside",
                            },
                            "params": {"output_label": "禁停区车辆"},
                        },
                        {
                            "id": "draw",
                            "op": "output.draw@1.0",
                            "inputs": {
                                "frames": "$resized",
                                "objects": "$filtered",
                                "regions": "$no_parking_region",
                            },
                            "params": {},
                        },
                    ],
                    "outputs": {
                        "media": "$draw",
                        "objects": "$filtered",
                        "regions": "$no_parking_region",
                    },
                    "atom_bindings": {
                        "atom_1": ["no_parking_region", "inside"]
                    },
                    "configuration_slots": [
                        {
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
                            "help_text": "在原图或视频标注帧上绘制禁停区域",
                        }
                    ],
                }
            },
            "compatibility_issues": [],
        }
    )


def test_pending_region_slot_is_a_valid_draft_but_not_executable():
    package = _pending_package()
    registry = build_default_registry()

    assert validate_skill_package(package, registry) == []
    assert configuration_status(package) == [
        {
            "media_type": "video",
            "slot_id": "no_parking_region",
            "label": "禁停区域",
            "kind": "region",
            "required": True,
            "active": True,
            "configured": False,
            "node_id": "no_parking_region",
        }
    ]
    assert validate_executable_skill_package(package, registry) == [
        "video: required configuration slot no_parking_region is pending"
    ]


def test_binding_polygon_writes_node_value_and_promotes_variant_to_ready():
    package = _pending_package()

    bound = ConfigurationBinder(build_default_registry()).bind_region(
        package,
        media_type="video",
        slot_id="no_parking_region",
        shape="polygon",
        points=[[0.1, 0.2], [0.9, 0.2], [0.8, 0.9], [0.2, 0.9]],
    )

    node = next(
        node
        for node in bound.variants["video"].nodes
        if node.id == "no_parking_region"
    )
    assert node.params == {
        "shape": "polygon",
        "points": [[0.1, 0.2], [0.9, 0.2], [0.8, 0.9], [0.2, 0.9]],
    }
    assert bound.variants["video"].status == "executable"
    assert bound.compile_status == "compiled"
    assert validate_executable_skill_package(bound, build_default_registry()) == []


def test_runtime_rejects_pending_configuration_before_creating_a_run(tmp_path):
    class NeverCalledRex:
        def detect(self, image, phrases):
            raise AssertionError("Rex must not be called for a pending skill")

    run_root = tmp_path / "runs"
    runtime = SkillPackageRuntime(
        build_default_registry(), rex=NeverCalledRex(), run_store=RunStore(run_root)
    )

    with pytest.raises(ValueError, match="configuration slot no_parking_region"):
        runtime.run(_pending_package(), _pending_package(), tmp_path / "missing.mp4")

    assert not run_root.exists()


def _lane_package() -> SkillPackage:
    path = next((Path(__file__).resolve().parents[1] / "presets_v2").glob("P05*.json"))
    data = json.loads(path.read_text("utf-8"))
    variant = data["variants"]["video"]
    for node in variant["nodes"]:
        if node["id"] == "lane_regions":
            node["params"] = {"regions": [
                {
                    "id": "lane_left",
                    "label": "左侧车道",
                    "shape": "polygon",
                    "points": [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]],
                },
                {
                    "id": "lane_right",
                    "label": "右侧车道",
                    "shape": "polygon",
                    "points": [[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]],
                },
            ]}
        elif node["id"] == "lane_references":
            node["params"] = {"directions": [
                {"key": "lane_left", "vector": [0.0, -1.0]},
                {"key": "lane_right", "vector": [0.0, 1.0]},
            ]}
    variant["configuration_slots"] = [
        {
            "slot_id": "lane_regions",
            "kind": "region_set",
            "label": "车道区域",
            "required": True,
            "binding": {"node_id": "lane_regions", "parameter": "regions"},
            "allowed_shapes": ["rectangle", "polygon"],
            "minimum_items": 1,
            "source_atom_ids": ["atom_1"],
            "help_text": "逐条配置命名车道",
        },
        {
            "slot_id": "lane_directions",
            "kind": "direction_set",
            "label": "逐车道方向",
            "required": True,
            "binding": {
                "node_id": "lane_references",
                "parameter": "directions",
            },
            "minimum_items": 1,
            "source_atom_ids": ["atom_1"],
            "help_text": "手工模式下每条车道一个方向",
            "active_when_op": ["direction.manual_set@1.0"],
            "key_source_slot_id": "lane_regions",
        },
    ]
    return SkillPackage.model_validate(data)


def test_manual_lane_directions_require_exactly_the_named_lane_keys():
    binder = ConfigurationBinder(build_default_registry())
    package = _lane_package()
    initial = {item["slot_id"]: item for item in configuration_status(package)}
    assert initial["lane_regions"]["configured"] is True
    assert initial["lane_directions"]["active"] is True
    assert initial["lane_directions"]["configured"] is True

    data = package.model_dump(mode="json")
    direction = next(
        node for node in data["variants"]["video"]["nodes"]
        if node["id"] == "lane_references"
    )
    direction["params"] = {"directions": []}
    package = SkillPackage.model_validate(data)

    one_direction = binder.bind_named_direction(
        package,
        media_type="video",
        slot_id="lane_directions",
        key="lane_left",
        start=[0.2, 0.8],
        end=[0.8, 0.2],
    )
    status = {item["slot_id"]: item for item in configuration_status(one_direction)}
    assert status["lane_directions"]["active"] is True
    assert status["lane_directions"]["configured"] is False
    assert one_direction.variants["video"].status == "needs_configuration"
    assert validate_executable_skill_package(
        one_direction, build_default_registry()
    ) == ["video: required configuration slot lane_directions is pending"]

    complete = binder.bind_named_direction(
        one_direction,
        media_type="video",
        slot_id="lane_directions",
        key="lane_right",
        start=[0.8, 0.2],
        end=[0.2, 0.8],
    )
    node = next(
        node
        for node in complete.variants["video"].nodes
        if node.id == "lane_references"
    )
    assert node.op == "direction.manual_set@1.0"
    assert {item["key"] for item in node.params["directions"]} == {
        "lane_left",
        "lane_right",
    }
    assert node.params["directions"][0]["start"]
    assert node.params["directions"][0]["end"]
    assert complete.variants["video"].status == "executable"
    assert validate_executable_skill_package(complete, build_default_registry()) == []


def test_single_direction_slot_binds_exact_arrow_endpoints_and_becomes_executable():
    from core.semantic import SemanticNormalizer, WorkflowCompiler

    instruction = "检测与手工参考方向相反运动的人"
    semantic = SemanticNormalizer().normalize_ledger(
        {
            "mode": "workflow",
            "target": {
                "concept": "person",
                "source_span": "人",
                "phrases": ["person"],
            },
            "constraints": [
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
            "logic": "all",
        },
        instruction,
    )
    package = WorkflowCompiler(build_default_registry()).compile(
        semantic,
        original_instruction=instruction,
        requested_accept=["video"],
        skill_id="manual_person_direction",
        display_name="反向运动的人",
    )
    slot = package.variants["video"].configuration_slots[0]

    bound = ConfigurationBinder(build_default_registry()).bind_direction(
        package,
        media_type="video",
        slot_id=slot.slot_id,
        start=[0.15, 0.75],
        end=[0.85, 0.25],
    )

    node = next(
        item
        for item in bound.variants["video"].nodes
        if item.id == slot.binding.node_id
    )
    assert node.params == {
        "vector": [0.7, -0.5],
        "start": [0.15, 0.75],
        "end": [0.85, 0.25],
    }
    assert bound.variants["video"].status == "executable"
    assert validate_executable_skill_package(bound, build_default_registry()) == []


def test_named_region_binding_upserts_and_deleting_a_lane_cleans_matching_direction():
    binder = ConfigurationBinder(build_default_registry())
    package = _lane_package()
    manual = binder.bind_named_direction(
        binder.bind_named_direction(
            package,
            media_type="video",
            slot_id="lane_directions",
            key="lane_left",
            start=[0.0, 0.5],
            end=[0.5, 0.5],
        ),
        media_type="video",
        slot_id="lane_directions",
        key="lane_right",
        start=[1.0, 0.5],
        end=[0.5, 0.5],
    )

    changed = binder.bind_named_region(
        manual,
        media_type="video",
        slot_id="lane_regions",
        region_id="lane_left",
        label="上行车道",
        shape="polygon",
        points=[[0.0, 0.0], [0.5, 0.0], [0.45, 1.0], [0.0, 1.0]],
    )
    lane_node = next(
        node for node in changed.variants["video"].nodes if node.id == "lane_regions"
    )
    assert len(lane_node.params["regions"]) == 2
    assert next(
        item for item in lane_node.params["regions"] if item["id"] == "lane_left"
    )["label"] == "上行车道"

    reopened = binder.delete_named_region(
        changed,
        media_type="video",
        slot_id="lane_regions",
        region_id="lane_right",
    )
    status = {item["slot_id"]: item for item in configuration_status(reopened)}
    assert status["lane_regions"]["configured"] is True
    assert status["lane_directions"]["configured"] is True
    assert reopened.variants["video"].status == "executable"
    direction_node = next(
        node
        for node in reopened.variants["video"].nodes
        if node.id == "lane_references"
    )
    assert {item["key"] for item in direction_node.params["directions"]} == {
        "lane_left"
    }


def test_named_region_and_direction_sets_accept_an_arbitrary_third_area():
    """The workflow uses named sets, not a fixed two-lane special case."""

    binder = ConfigurationBinder(build_default_registry())
    package = _lane_package()
    third_lane = binder.bind_named_region(
        package,
        media_type="video",
        slot_id="lane_regions",
        region_id="lane_3",
        label="第三区域",
        shape="rectangle",
        points=[[0.65, 0.15], [0.95, 0.85]],
    )
    with_direction = binder.bind_named_direction(
        third_lane,
        media_type="video",
        slot_id="lane_directions",
        key="lane_3",
        start=[0.8, 0.8],
        end=[0.8, 0.2],
    )

    regions = next(
        node for node in with_direction.variants["video"].nodes
        if node.id == "lane_regions"
    )
    directions = next(
        node for node in with_direction.variants["video"].nodes
        if node.id == "lane_references"
    )
    assert {item["id"] for item in regions.params["regions"]} >= {"lane_3"}
    assert {item["key"] for item in directions.params["directions"]} >= {"lane_3"}
