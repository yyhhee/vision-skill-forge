from __future__ import annotations

import pytest

from core.editor_service import EditorMutationError, EditorService
from core.legacy_importer import import_skill_package
from core.editor_generation import build_editor_document, resolve_pending_decision
from core.registry import build_default_registry
from tests.test_editor_document import _package


def _service_document():
    return EditorService(build_default_registry()), import_skill_package(_package())


def test_editor_service_exposes_complete_registered_operator_catalog():
    service, _ = _service_document()
    catalog = service.operator_catalog()

    operators = {item["operator"] for item in catalog}
    assert "rex.ground@1.1" in operators
    assert "temporal.join@1.0" in operators
    assert "result.project@1.0" in operators
    assert all("inputs" in item and "output" in item for item in catalog)


def test_editor_service_add_copy_delete_and_user_override_are_v3_mutations():
    service, document = _service_document()
    media_type = next(iter(document.skill_template.rule_graphs))
    document = service.add_branch(document, media_type, "review_branch", "用户审核分支")
    document = service.add_node(
        document,
        media_type,
        "region.manual_set@1.0",
        "review_regions",
        branch_id="review_branch",
    )
    document = service.copy_node(document, media_type, "review_regions", "review_regions_copy")
    document = service.set_parameter(
        document,
        "review_regions_copy",
        "regions",
        [{"id": "auto", "label": "实际标注区域", "shape": "polygon", "points": [[0, 0], [1, 0], [1, 1]]}],
    )

    assert document.effective_skill_package is None
    assert document.user_overrides[-1].target_id == "review_regions_copy"
    assert "review_regions_copy" in document.skill_template.business_branches[-1].node_ids

    document = service.delete_node(document, media_type, "review_regions_copy")
    assert not any(item.target_id == "review_regions_copy" for item in document.user_overrides)


def test_editor_service_connect_enforces_port_type_and_cycle_safety():
    service, document = _service_document()
    media_type = next(iter(document.skill_template.rule_graphs))
    document = service.add_node(document, media_type, "logic.all@1.0", "logic_a")
    document = service.add_node(document, media_type, "logic.any@1.0", "logic_b")
    document = service.connect(document, media_type, "logic_a", "logic_b", "conditions")

    with pytest.raises(EditorMutationError, match="形成环"):
        service.connect(document, media_type, "logic_b", "logic_a", "conditions")

    document = service.add_node(document, media_type, "region.manual@1.0", "region_a")
    with pytest.raises(EditorMutationError, match="类型不兼容"):
        service.connect(document, media_type, "region_a", "logic_a", "conditions")


def test_editor_service_replaces_only_when_existing_connections_are_compatible():
    service, document = _service_document()
    media_type = next(iter(document.skill_template.rule_graphs))
    document = service.add_node(document, media_type, "logic.all@1.0", "logic_a")
    document = service.add_node(document, media_type, "logic.any@1.0", "logic_b")
    document = service.connect(document, media_type, "logic_a", "logic_b", "conditions")

    replaced = service.replace_node_operator(document, media_type, "logic_a", "logic.not@1.0")
    node = next(item for item in replaced.skill_template.rule_graphs[media_type].nodes if item.node_id == "logic_a")
    assert node.operator == "logic.not@1.0"


def test_editor_service_apply_compiles_but_gates_unconfigured_scene_resources():
    service, document = _service_document()
    compiled = service.apply(document)

    assert compiled.effective_skill_package is not None
    assert compiled.validation_report["can_run"] is False
    assert compiled.validation_report["resource_blockers"]


def test_editor_service_business_branch_and_recipe_operations_are_reusable():
    service, document = _service_document()
    media_type = next(iter(document.skill_template.rule_graphs))
    document = service.add_branch(document, media_type, "safety_branch", "安全分支")
    document = service.insert_recipe(
        document, media_type, "same_subject_attributes", "safety_branch"
    )
    branch = next(
        item for item in document.skill_template.business_branches
        if item.branch_id == "safety_branch"
    )
    assert len(branch.node_ids) == 4

    document = service.update_branch(
        document, "safety_branch", display_name="同主体属性", enabled=False
    )
    branch = next(item for item in document.skill_template.business_branches if item.branch_id == "safety_branch")
    assert branch.display_name == "同主体属性"
    assert branch.enabled is False


def test_generated_parameters_keep_source_metadata_and_scene_ids_are_stable():
    first = build_editor_document(_package(), source_type="natural_language")
    second = build_editor_document(_package(), source_type="natural_language")

    first_ids = [
        item.resource_id
        for profile in first.scene_profiles
        for collection in profile.collections
        for item in collection.items
    ]
    second_ids = [
        item.resource_id
        for profile in second.scene_profiles
        for collection in profile.collections
        for item in collection.items
    ]
    assert first_ids == second_ids
    sources = [
        source.state
        for graph in first.skill_template.rule_graphs.values()
        for node in graph.nodes
        for source in node.parameter_sources.values()
    ]
    assert sources and set(sources) == {"inferred"}


def test_resolving_uncertain_duration_writes_the_affected_atomic_override():
    package = _package().model_copy(update={"original_instruction": "车辆逆行持续XX秒"})
    document = build_editor_document(package, source_type="natural_language")
    decision = next(item for item in document.skill_template.pending_decisions if item.decision_id == "duration")
    assert decision.affected_ids

    resolved = resolve_pending_decision(document, "duration", 5.0)
    assert any(
        item.target_id in decision.affected_ids
        and item.parameter in {"duration_seconds", "minimum_seconds"}
        and item.value == 5.0
        for item in resolved.user_overrides
    )
