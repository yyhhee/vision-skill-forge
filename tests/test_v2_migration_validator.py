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
    assert [node.op for node in package.select_variant("image").nodes] == [
        node.op for node in old.nodes
    ]
    assert package.compatibility_issues[0].code == "v1_semantics_inferred"


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
