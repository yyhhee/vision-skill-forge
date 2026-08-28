from __future__ import annotations

import pytest

from core.migration import migrate_v1_spec
from core.registry import build_default_registry
from core.schema import VisualSkillSpec
from core.validator import validate_skill_package


def _v1_image_spec() -> VisualSkillSpec:
    return VisualSkillSpec.model_validate(
        {
            "version": "0.1",
            "name": "person_detector",
            "display_name": "人员检测",
            "original_instruction": "检测人员",
            "input": {"accept": ["image"]},
            "nodes": [
                {
                    "id": "image",
                    "op": "media.image@1.0",
                    "inputs": {"media": "$input"},
                    "params": {},
                },
                {
                    "id": "objects",
                    "op": "rex.ground@1.0",
                    "inputs": {"frames": "$image"},
                    "params": {
                        "targets": [{"label": "人员", "phrases": ["person"]}]
                    },
                },
                {
                    "id": "draw",
                    "op": "output.draw@1.0",
                    "inputs": {"frames": "$image", "objects": "$objects"},
                    "params": {},
                },
            ],
            "outputs": {"media": "$draw", "objects": "$objects"},
        }
    )


def test_explicit_v1_migration_preserves_workflow_and_marks_inferred_semantics_for_review():
    old = _v1_image_spec()

    package = migrate_v1_spec(old)

    assert package.schema_version == "2.0"
    assert package.skill_id == old.name
    assert package.input.accept == ["image"]
    assert package.compile_status == "needs_review"
    assert package.semantic_ir.target.phrases == ["person"]
    nodes = package.select_variant("image").nodes
    assert [node.op for node in nodes] == [
        "media.image@1.0",
        "rex.ground@1.1",
        "objects.deduplicate@1.0",
        "output.draw@1.0",
    ]
    assert package.select_variant("image").outputs["objects"] == "$objects_deduplicated"
    assert package.compatibility_issues[0].code == "v1_semantics_inferred"


def test_v1_migration_replaces_all_retired_atoms_with_current_explicit_nodes():
    old = VisualSkillSpec.model_validate(
        {
            "version": "0.1",
            "name": "legacy_video",
            "display_name": "旧视频技能",
            "original_instruction": "先出现人员再出现车辆",
            "input": {"accept": ["video"]},
            "nodes": [
                {"id": "video", "op": "media.video@1.0", "inputs": {"media": "$input"}},
                {"id": "frames", "op": "video.sample@1.0", "inputs": {"video": "$video"}, "params": {"mode": "interval", "fps": 1.0}},
                {"id": "resize", "op": "image.resize@1.0", "inputs": {"frames": "$frames"}, "params": {"mode": "long_side", "long_side": 1280}},
                {"id": "tiles", "op": "image.tile@1.0", "inputs": {"frames": "$resize"}, "params": {"tile_width": 512, "tile_height": 512, "overlap": 0.25, "include_full_frame": False}},
                {"id": "objects", "op": "rex.ground@1.0", "inputs": {"frames": "$tiles"}, "params": {"targets": [{"label": "人员", "phrases": ["person"]}], "deduplicate_iou": 0.6, "deduplicate_metric": "ios"}},
                {"id": "sequence", "op": "temporal.sequence@1.0", "inputs": {"events": ["$objects", "$objects"]}, "params": {"steps": ["人员", "车辆"], "max_gap_seconds": 4, "same_key": False}},
            ],
            "outputs": {"objects": "$objects", "events": "$sequence"},
        }
    )

    package = migrate_v1_spec(old)
    nodes = {node.id: node for node in package.select_variant("video").nodes}

    assert nodes["frames"].op == "video.sample@1.1"
    assert nodes["frames"].params["interval_seconds"] == 1.0
    assert nodes["resize"].op == "image.resize@1.1"
    assert nodes["tiles"].op == "image.tile@1.1"
    assert nodes["tiles"].params["overlap_x"] == nodes["tiles"].params["overlap_y"] == 0.25
    assert nodes["objects"].op == "rex.ground@1.1"
    assert nodes["objects_deduplicated"].inputs["objects"] == "$objects"
    assert nodes["objects_deduplicated"].params == {"metric": "ios", "threshold": 0.6, "keep": "first"}
    assert nodes["sequence"].op == "temporal.sequence@2.0"
    assert nodes["sequence"].inputs["events"] == ["$objects_deduplicated", "$objects_deduplicated"]
    assert nodes["sequence"].params["correlation_scope"] == "global"
    assert package.select_variant("video").outputs["objects"] == "$objects_deduplicated"
    assert not {
        "video.sample@1.0", "image.resize@1.0", "image.tile@1.0", "rex.ground@1.0", "temporal.sequence@1.0"
    } & {node.op for node in nodes.values()}


def test_retired_atoms_are_not_registered_after_v1_migration_support_is_added():
    registry = build_default_registry()
    assert not {
        "video.sample@1.0", "image.resize@1.0", "image.tile@1.0", "rex.ground@1.0", "temporal.sequence@1.0"
    } & {definition.op for definition in registry.definitions()}


def test_v1_migration_is_never_implicit_in_v2_schema_validation():
    with pytest.raises(Exception):
        from core.schema import SkillPackage

        SkillPackage.model_validate(_v1_image_spec().model_dump(mode="json"))


def test_package_validator_validates_each_executable_variant_with_registry_types():
    package = migrate_v1_spec(_v1_image_spec())
    package.variants["image"].nodes[1].inputs["frames"] = "$objects"

    errors = validate_skill_package(package, build_default_registry())

    assert any("image/objects: type mismatch" in error for error in errors)


def test_package_validator_rejects_unresolved_semantics_as_compiled():
    package = migrate_v1_spec(_v1_image_spec())
    package.compile_status = "compiled"
    package.semantic_ir.unresolved = [
        {"source_span": "特殊状态", "reason": "not mapped to a registered capability"}
    ]

    errors = validate_skill_package(package, build_default_registry())

    assert "compiled package cannot contain unresolved semantics" in errors
