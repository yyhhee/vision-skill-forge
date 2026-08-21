from __future__ import annotations

import json

import pytest

from core.editor_schema import (
    CardinalitySpec,
    ResolvableValue,
    ResourceRequirement,
    SceneProfile,
    SkillEditorDocument,
    SkillTemplate,
)
from core.legacy_importer import import_skill_package
from core.persistence import SkillDocumentStore
from core.resource_requirements import (
    add_resource,
    complete_collection,
    remove_resource,
    requirement_status,
)
from core.schema import SkillPackage


def _package() -> SkillPackage:
    path = next(__import__("pathlib").Path("presets_v2").glob("P05*.json"))
    return SkillPackage.model_validate_json(path.read_text("utf-8"))


def test_resolvable_value_distinguishes_unknown_default_and_explicit_values():
    pending = ResolvableValue(
        state="unresolved",
        source="natural_language",
        recommended_value=3,
        alternatives=[2, 3, 4],
        reason="人数阈值未明确",
        required_before="run",
    )

    assert pending.blocks("run")
    resolved = pending.resolved(4)
    assert resolved.state == "explicit"
    assert resolved.value == 4
    assert not resolved.blocks("run")

    with pytest.raises(ValueError, match="requires a reason"):
        ResolvableValue(state="unresolved")


def test_dynamic_resource_collection_generates_internal_ids_and_optional_names():
    requirement = ResourceRequirement(
        requirement_id="lanes",
        resource_type="region_collection",
        display_name="车道区域",
        semantic_role="lane",
        cardinality=CardinalitySpec(mode="dynamic", minimum=1),
        binding_policy="for_each",
        allowed_shapes=["rectangle", "polygon"],
    )
    profile = SceneProfile(display_name="当前视频")

    profile, first = add_resource(
        profile,
        requirement,
        geometry={"shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
    )
    profile, second = add_resource(
        profile,
        requirement,
        geometry={"shape": "polygon", "points": [[0.5, 0.1], [0.9, 0.1], [0.8, 0.9]]},
        display_name="东侧车道",
    )

    assert first.resource_id.startswith("res_")
    assert first.resource_id != second.resource_id
    assert first.display_name == "车道1"
    assert second.display_name == "东侧车道"

    template = SkillTemplate(
        skill_id="lane_skill",
        display_name="车道技能",
        original_instruction="检测每条车道",
        source_type="natural_language",
        semantic_ir=_package().semantic_ir,
        resource_requirements=[requirement],
    )
    assert not requirement_status(template, profile)[0]["configured"]
    profile = complete_collection(profile, "lanes")
    assert requirement_status(template, profile)[0]["configured"]

    profile = remove_resource(profile, first.resource_id)
    assert not requirement_status(template, profile)[0]["configured"]


def test_legacy_p05_imports_dynamic_lane_and_matched_direction_requirements():
    package = _package()
    document = import_skill_package(package)
    requirements = {
        item.legacy_metadata.get("slot_id"): item
        for item in document.skill_template.resource_requirements
    }

    assert requirements["lane_regions"].cardinality.mode == "dynamic"
    assert requirements["lane_regions"].binding_policy == "for_each"
    assert requirements["lane_references_manual"].cardinality.mode == "match_collection"
    assert requirements["lane_references_manual"].pairing_policy == "one_per_region"
    assert document.effective_skill_package == package
    assert document.compatibility.editability == "legacy_atomic_only"
    assert set(document.skill_template.rule_graphs) == set(package.input.accept)
    assert document.skill_template.rule_graphs["video"].nodes


def test_skill_document_store_versions_v3_and_imports_v2_files(tmp_path):
    package = _package()
    document = import_skill_package(package)
    store = SkillDocumentStore(tmp_path / "skills")

    first = store.save(document)
    second = store.save(document)
    loaded = store.load(package.skill_id, 2)

    assert first.name == "1.json"
    assert second.name == "2.json"
    assert loaded.version == 2
    assert loaded.skill_template.skill_id == package.skill_id

    legacy_dir = tmp_path / "skills" / "legacy_copy"
    legacy_dir.mkdir()
    data = package.model_dump(mode="json")
    data["skill_id"] = "legacy_copy"
    (legacy_dir / "1.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    imported = store.load("legacy_copy", 1)
    assert imported.schema_version == "3.0"
    assert imported.effective_skill_package.skill_id == "legacy_copy"
