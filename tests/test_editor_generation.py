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
    from core.business_capabilities import build_business_capability_registry
    from core.business_rule_editor import BusinessRuleEditor
    from core.editor_service import EditorService
    from core.registry import build_default_registry

    paths = sorted(Path("presets_v2").glob("P*.json"))
    assert len(paths) == 13
    registry = build_default_registry()
    editor = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )
    service = EditorService(registry)
    for path in paths:
        package = SkillPackage.model_validate_json(path.read_text("utf-8"))
        document = editor.prepare(
            build_editor_document(package, source_type="preset")
        )
        assert set(document.skill_template.rule_graphs) == set(package.input.accept)
        assert document.effective_skill_package == package
        assert len(document.skill_template.business_branches) == len(package.input.accept)
        assert {
            item.media_type for item in document.skill_template.business_branches
        } == set(package.input.accept)
        assert all(
            item.display_name == package.display_name
            for item in document.skill_template.business_branches
        )
        expected_outputs = {
            name for variant in package.variants.values() for name in variant.outputs
        }
        actual_outputs = {
            name
            for spec in document.skill_template.result_specs
            for name in spec.required_outputs
        }
        assert expected_outputs <= actual_outputs
        for spec in document.skill_template.result_specs:
            assert spec.source_ref == f"output:{spec.required_outputs[0]}"
            assert spec.media_types
        final = document.skill_template.final_decision
        assert final is not None
        assert set(final.media_source_refs) == set(package.input.accept)

        # Loading a preset into 03 and compiling it again must preserve every
        # proven legacy node while adding only generic final/result nodes.
        compiled = service.apply(document)
        for media_type, original in package.variants.items():
            actual = compiled.effective_skill_package.variants[media_type]
            original_ids = {node.id for node in original.nodes if node.enabled}
            assert original_ids <= {node.id for node in actual.nodes}


def test_detection_preset_final_is_an_explicit_non_empty_set_decision():
    from pathlib import Path
    from core.business_capabilities import build_business_capability_registry
    from core.business_rule_editor import BusinessRuleEditor
    from core.editor_service import EditorService
    from core.registry import build_default_registry

    package = _preset("P03")
    registry = build_default_registry()
    document = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    ).prepare(build_editor_document(package, source_type="preset"))
    compiled = EditorService(registry).apply(document)

    for media_type in package.input.accept:
        variant = compiled.effective_skill_package.variants[media_type]
        nodes = {node.id: node for node in variant.nodes}
        final_ref = variant.outputs["final_primary"]
        final_node = nodes[final_ref[1:]]
        assert final_node.op == "logic.compare@1.0"
        assert final_node.params == {"operator": ">", "value": 0}
        count_ref = final_node.inputs["left"]
        assert nodes[count_ref[1:]].op == "measure.count@1.0"


def test_preset_business_branch_exposes_editable_existing_steps_without_rebuilding_recipe():
    from core.business_capabilities import build_business_capability_registry
    from core.business_rule_editor import BusinessRuleEditor
    from core.registry import build_default_registry

    package = _preset("P04")
    registry = build_default_registry()
    editor = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )
    document = editor.prepare(build_editor_document(package, source_type="preset"))
    branch = document.skill_template.business_branches[0]
    rows = editor.condition_rows(document, branch.branch_id)

    assert rows[0]["kind"] == "导入判定"
    assert {item["category"] for item in rows[1:]} >= {
        "数量与测量", "轨迹与运动", "时间与复杂编排"
    }
    compare = next(
        item for item in rows
        if item["condition_id"] == "existing_node:many"
    )
    params = editor.parameter_rows(
        document, branch.branch_id, compare["condition_id"]
    )
    assert {item["name"] for item in params} >= {"比较方式", "比较值"}

    updated = editor.update_condition(
        document,
        branch.branch_id,
        compare["condition_id"],
        display_name="车辆不少于6辆",
        parameters={"operator": ">=", "threshold": 6},
    )
    node = next(
        item
        for item in updated.skill_template.rule_graphs["video"].nodes
        if item.node_id == "many"
    )
    assert node.display_name == "车辆不少于6辆"
    assert node.params["value"] == 6
