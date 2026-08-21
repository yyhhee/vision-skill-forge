from __future__ import annotations

from core.editor_generation import build_editor_document, resolve_pending_decision
from core.recipes import build_recipe_catalog
from core.schema import SkillPackage


def _preset(name):
    return SkillPackage.model_validate_json(
        next(__import__("pathlib").Path("presets_v2").glob(f"{name}*.json")).read_text("utf-8")
    )


def test_unknown_counts_durations_and_windows_become_explicit_pending_decisions():
    package = _preset("P04")
    data = package.model_dump(mode="json")
    data["original_instruction"] = (
        "区域1有XX辆车持续XX秒，随后在XX秒内区域2发生事故则告警"
    )
    document = build_editor_document(SkillPackage.model_validate(data))
    decisions = {
        item.parameter_kind: item for item in document.skill_template.pending_decisions
    }

    assert {"comparison_operator", "count_threshold", "duration", "time_window"} <= set(decisions)
    assert decisions["duration"].resolution.state == "unresolved"
    assert decisions["duration"].resolution.required_before == "run"

    resolved = resolve_pending_decision(document, "duration", 5.0)
    decision = next(
        item for item in resolved.skill_template.pending_decisions
        if item.decision_id == "duration"
    )
    assert decision.resolution.state == "explicit"
    assert decision.resolution.value == 5.0


def test_region_and_lane_counts_are_dynamic_resources_not_required_user_ids():
    package = _preset("P02")
    data = package.model_dump(mode="json")
    data["original_instruction"] = "在视频实际区域中判断事故和车辆逆行"
    document = build_editor_document(SkillPackage.model_validate(data))

    regions = next(
        item for item in document.skill_template.resource_requirements
        if item.resource_type == "region_collection"
    )
    directions = next(
        item for item in document.skill_template.resource_requirements
        if item.resource_type == "direction_collection"
    )
    assert regions.cardinality.mode == "dynamic"
    assert directions.cardinality.mode == "match_collection"
    assert directions.cardinality.source_requirement_id == regions.requirement_id


def test_recipe_catalog_is_composed_only_from_registered_generic_atoms():
    from core.registry import build_default_registry

    registry = build_default_registry()
    recipes = build_recipe_catalog()
    assert "same_subject_attributes" in recipes
    assert "multi_branch_join" in recipes
    for recipe in recipes.values():
        for atom in recipe.atoms:
            assert registry.require(atom).op == atom


def test_all_p01_to_p13_presets_project_without_losing_variants_or_outputs():
    from pathlib import Path

    paths = sorted(Path("presets_v2").glob("P*.json"))
    assert len(paths) == 13
    for path in paths:
        package = SkillPackage.model_validate_json(path.read_text("utf-8"))
        document = build_editor_document(package, source_type="preset")
        assert set(document.skill_template.rule_graphs) == set(package.input.accept)
        assert document.effective_skill_package == package
        expected_outputs = {
            name for variant in package.variants.values() for name in variant.outputs
        }
        actual_outputs = {
            name
            for spec in document.skill_template.result_specs
            for name in spec.required_outputs
        }
        assert expected_outputs <= actual_outputs
