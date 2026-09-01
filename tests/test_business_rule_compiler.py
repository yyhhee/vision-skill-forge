from __future__ import annotations

import pytest

from core.business_capabilities import build_business_capability_registry
from core.business_result_projector import build_runtime_contract
from core.business_rule_editor import BusinessRuleEditor
from core.editor_migrations import migrate_editor_document
from core.editor_schema import (
    BusinessBranch,
    CardinalitySpec,
    ResolvableValue,
    ResourceRequirement,
    RuleGraph,
    TemporalQualifierSpec,
)
from core.editor_service import EditorService
from core.legacy_importer import import_skill_package
from core.registry import build_default_registry
from core.schema import CanonicalSemanticIR
from core.semantic import WorkflowCompiler


def _document(media_type: str):
    registry = build_default_registry()
    semantic = CanonicalSemanticIR.model_validate(
        {
            "schema_version": "1.0",
            "mode": "direct_grounding",
            "target": {
                "concept": "person",
                "source_span": "人",
                "phrases": ["person"],
            },
            "constraints": [],
            "logic": "all",
            "unresolved": [],
            "semantic_hash": "b" * 64,
        }
    )
    package = WorkflowCompiler(registry).compile(
        semantic,
        original_instruction="业务规则编译测试",
        requested_accept=[media_type],
        skill_id="business_rule_compile_fixture",
        display_name="业务规则编译测试",
    )
    document = migrate_editor_document(import_skill_package(package))
    graph = RuleGraph()
    document.skill_template.rule_graph = graph
    document.skill_template.rule_graphs = {media_type: graph}
    document.skill_template.business_branches = []
    document.skill_template.event_patterns = []
    document.skill_template.result_specs = []
    document.skill_template.presentation_specs = []
    document.skill_template.final_decision = None
    document.effective_skill_package = None
    editor = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )
    return registry, editor, document


def _condition(
    editor: BusinessRuleEditor,
    document,
    branch_id: str,
    capability: str,
    name: str,
    parameters: dict,
):
    document, condition_id = editor.add_condition(
        document, branch_id, capability
    )
    document = editor.update_condition(
        document,
        branch_id,
        condition_id,
        display_name=name,
        parameters=parameters,
    )
    return document, condition_id


def test_image_business_tree_compiles_to_atomic_graph_and_semantic_outputs():
    registry, editor, document = _document("image")
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_clothes",
            display_name="区域1指定着装人员",
            media_type="image",
        ),
        BusinessBranch(
            branch_id="branch_count",
            display_name="区域2人员数量",
            media_type="image",
        ),
    ]
    document, people_id = _condition(
        editor,
        document,
        "branch_clothes",
        "target.detect",
        "检测人员",
        {"targets": ["person"], "phrases": "person", "business_label": "人员"},
    )
    document, red_id = _condition(
        editor,
        document,
        "branch_clothes",
        "attribute.color",
        "红色上衣",
        {
            "source": f"condition:{people_id}",
            "part": "upper_clothing",
            "color": "red",
            # An LLM draft may explicitly emit null for an optional tuning
            # parameter. Compilation must use the documented default.
            "minimum_fraction": None,
        },
    )
    document, gray_id = _condition(
        editor,
        document,
        "branch_clothes",
        "attribute.color",
        "灰色裤子",
        {
            "source": f"condition:{people_id}",
            "part": "lower_clothing",
            "color": "gray",
            "minimum_fraction": 20,
        },
    )
    document, same_id = _condition(
        editor,
        document,
        "branch_clothes",
        "subject.same_attributes",
        "同一人员同时满足着装",
        {
            "subject": f"condition:{people_id}",
            "attributes": [f"condition:{red_id}", f"condition:{gray_id}"],
            "minimum_overlap": None,
        },
    )
    document, people_2_id = _condition(
        editor,
        document,
        "branch_count",
        "target.detect",
        "区域2人员",
        {"targets": ["person"], "phrases": "person", "business_label": "人员"},
    )
    document, count_id = _condition(
        editor,
        document,
        "branch_count",
        "measure.count",
        "区域2人数大于2",
        {
            "source": f"condition:{people_2_id}",
            "scope": "full_frame",
            "group_by": "total",
            "operator": ">",
            "threshold": 2,
        },
    )
    document = editor.set_final_decision(
        document,
        "多区域人员告警",
        "event_decision",
        "branch:branch_clothes",
        source_refs=["branch:branch_clothes", "branch:branch_count"],
        combination="AND",
    )
    document = editor.set_trigger_policy(
        document,
        mode="once",
        cooldown_seconds=30,
        severity="high",
        outputs=["event_record", "annotated_media"],
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "红色上衣、灰色裤子人员",
                "source_ref": f"condition:{same_id}",
                "result_kind": "entities",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            },
            {
                "display_name": "区域2人员数量",
                "source_ref": f"condition:{count_id}",
                "result_kind": "count",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            },
            {
                "display_name": "多区域人员告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            },
        ],
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["image"]
    operators = {item.op for item in variant.nodes}

    assert compiled.validation_report["can_run"] is True
    assert "set.semi_join@1.0" in operators
    red_color = next(
        node
        for node in variant.nodes
        if node.op == "visual.color_fraction@1.0" and node.params["color"] == "red"
    )
    assert red_color.params["min_fraction"] == 0.1
    assert red_color.params["subject_region"] == [0.0, 0.05, 1.0, 0.58]
    shared_ground = next(
        node
        for node in variant.nodes
        if node.op == "rex.ground@1.1"
        and any(
            target.get("phrases") == ["red upper body clothing"]
            for target in node.params.get("targets", [])
        )
    )
    assert any(
        target.get("phrases") == ["gray trousers"]
        for target in shared_ground.params["targets"]
    )
    assert red_color.inputs["objects"] != f"${shared_ground.id}"
    assert any(
        node.op == "spatial.associate@1.0"
        and node.params == {"relation": "best_owner", "threshold": 0.1}
        for node in variant.nodes
    )
    assert sum(node.op == "rex.ground@1.1" for node in variant.nodes) == 1
    pair_filter = next(
        node for node in variant.nodes if node.op == "pairs.filter@1.0"
    )
    assert pair_filter.params["threshold"] == 0.3
    assert "measure.count@1.0" in operators
    assert "logic.all@1.0" in operators
    assert "final_primary" in variant.outputs
    assert "alert_primary" in variant.outputs
    assert "event.trigger@2.0" in operators
    assert "output.draw@1.0" in operators
    assert "media" in variant.outputs
    assert "objects" in variant.outputs
    object_output = variant.outputs["objects"].removeprefix("$")
    object_merge = next(node for node in variant.nodes if node.id == object_output)
    assert object_merge.op == "objects.merge@1.0"
    graph_object_merge = next(
        node
        for node in compiled.skill_template.rule_graphs["image"].nodes
        if node.node_id == object_output
    )
    assert graph_object_merge.business_source_refs == [
        "node:system:branch_entity_evidence"
    ]
    assert all(item.required_outputs for item in compiled.skill_template.result_specs)

    changed = editor.set_trigger_policy(
        document,
        mode="on_change",
        cooldown_seconds=10,
        severity="high",
        outputs=["event_record"],
    )
    changed_compiled = EditorService(registry).apply(changed)
    changed_nodes = changed_compiled.effective_skill_package.variants["image"].nodes
    final_event = next(
        item for item in changed_nodes
        if item.op == "event.from_condition@1.0" and item.id.startswith("final_")
    )
    final_trigger = next(
        item for item in changed_nodes
        if item.op == "event.trigger@2.0" and item.id.startswith("trigger_")
    )
    assert final_event.params["trigger_mode"] == "once"
    assert final_trigger.params["repeat_policy"] == "allow_repeat"

    contract = build_runtime_contract(compiled, "image")
    sources = contract["published_sources"]
    count_result = next(
        item
        for item in compiled.skill_template.result_specs
        if item.display_name == "区域2人员数量"
    )
    assert f"condition:{count_id}" in sources
    assert "branch:branch_count" in sources
    assert "final:primary" in sources
    assert f"result:{count_result.result_id}" in sources
    # The condition remains boolean while its ResultSpec binds to the
    # measurement node selected by the count projection.
    assert sources[f"condition:{count_id}"] != sources[f"result:{count_result.result_id}"]

    reapplied = EditorService(registry).apply(compiled)
    assert reapplied.validation_report["can_run"] is True
    assert "objects" in reapplied.effective_skill_package.variants["image"].outputs


@pytest.mark.parametrize(
    ("dimension", "value"),
    [("size", "small"), ("position", "left"), ("aspect_ratio", "vertical")],
)
def test_geometry_business_value_is_forwarded_to_visual_operator(dimension, value):
    registry, editor, document = _document("image")
    document.skill_template.business_branches = [
        BusinessBranch(branch_id="branch_geometry", display_name="几何筛选", media_type="image")
    ]
    document, detect_id = _condition(
        editor,
        document,
        "branch_geometry",
        "target.detect",
        "检测目标",
        {"targets": ["object"], "phrases": "object", "business_label": "目标"},
    )
    document, geometry_id = _condition(
        editor,
        document,
        "branch_geometry",
        "attribute.geometry",
        "几何属性",
        {
            "source": f"condition:{detect_id}",
            "dimension": dimension,
            "value": value,
            "operator": ">=",
            "threshold": 1,
        },
    )
    document = editor.set_final_decision(
        document,
        "几何筛选结果",
        "detection_summary",
        "branch:branch_geometry",
        source_refs=[f"condition:{geometry_id}"],
        combination="AND",
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["image"]
    geometry = next(node for node in variant.nodes if node.op == "visual.geometry@1.0")
    assert geometry.params["dimension"] == dimension
    assert geometry.params["value"] == value
    if dimension == "aspect_ratio":
        assert geometry.params["aspect_ratio_threshold"] == 1.0


def test_geometry_business_value_defaults_for_legacy_saved_condition():
    registry, editor, document = _document("image")
    document.skill_template.business_branches = [
        BusinessBranch(branch_id="branch_geometry", display_name="几何筛选", media_type="image")
    ]
    document, detect_id = _condition(
        editor,
        document,
        "branch_geometry",
        "target.detect",
        "检测目标",
        {"targets": ["object"], "phrases": "object", "business_label": "目标"},
    )
    document, geometry_id = _condition(
        editor,
        document,
        "branch_geometry",
        "attribute.geometry",
        "历史尺寸条件",
        {
            "source": f"condition:{detect_id}",
            "dimension": "size",
            "operator": ">=",
            "threshold": 1,
        },
    )
    document = editor.set_final_decision(
        document,
        "几何筛选结果",
        "detection_summary",
        "branch:branch_geometry",
        source_refs=[f"condition:{geometry_id}"],
        combination="AND",
    )

    compiled = EditorService(registry).apply(document)
    geometry = next(
        node for node in compiled.effective_skill_package.variants["image"].nodes
        if node.op == "visual.geometry@1.0"
    )
    assert geometry.params["value"] == "medium"


def test_shared_region_requirement_compiles_one_resource_node_and_slot():
    registry, editor, document = _document("image")
    document.skill_template.resource_requirements = [
        ResourceRequirement(
            requirement_id="region_1",
            resource_type="region_collection",
            display_name="区域1",
            semantic_role="region_1",
            cardinality=CardinalitySpec(mode="dynamic", minimum=1),
            allowed_shapes=["rectangle", "polygon"],
            required_before="run",
            media_types=["image"],
        )
    ]
    document.skill_template.business_branches = [
        BusinessBranch(branch_id="branch_a", display_name="分支A", media_type="image"),
        BusinessBranch(branch_id="branch_b", display_name="分支B", media_type="image"),
    ]
    for branch_id in ("branch_a", "branch_b"):
        document, people_id = _condition(
            editor,
            document,
            branch_id,
            "target.detect",
            "检测人员",
            {"targets": ["person"], "phrases": "person", "business_label": "人员"},
        )
        document, _ = _condition(
            editor,
            document,
            branch_id,
            "measure.count",
            "区域人数",
            {
                "source": f"condition:{people_id}",
                "scope": "resource:region_1",
                "group_by": "total",
                "operator": ">",
                "threshold": 1,
            },
        )
    document = editor.set_final_decision(
        document,
        "联合告警",
        "event_decision",
        "branch:branch_a",
        source_refs=["branch:branch_a", "branch:branch_b"],
        combination="AND",
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["image"]
    resource_nodes = [node for node in variant.nodes if node.id == "resource_region_1_regions"]
    slots = [slot for slot in variant.configuration_slots if slot.slot_id == "slot_region_1"]

    assert len(resource_nodes) == 1
    assert len(slots) == 1


def test_video_branch_qualifier_keeps_frames_and_requires_direction_resource():
    registry, editor, document = _document("video")
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_wrong_way",
            display_name="车辆逆行",
            media_type="video",
        )
    ]
    document.skill_template.resource_requirements = [
        ResourceRequirement(
            requirement_id="normal_direction",
            resource_type="direction_collection",
            display_name="正常行驶方向",
            semantic_role="normal_direction",
            cardinality=CardinalitySpec(mode="dynamic", minimum=1),
            required_before="run",
            media_types=["video"],
        )
    ]
    document, vehicles_id = _condition(
        editor,
        document,
        "branch_wrong_way",
        "target.detect",
        "检测车辆",
        {"targets": ["vehicle"], "phrases": "vehicle", "business_label": "车辆"},
    )
    document, _ = _condition(
        editor,
        document,
        "branch_wrong_way",
        "motion.wrong_way",
        "车辆逆行",
        {
            "source": f"condition:{vehicles_id}",
            "scope": "full_frame",
            "reference": "normal_direction",
            "minimum_reverse_angle": 120,
            "minimum_displacement": 2,
        },
    )
    branch = document.skill_template.business_branches[0]
    branch.temporal_qualifiers = [
        TemporalQualifierSpec(
            qualifier_id="wrong_way_3s",
            display_name="同一车辆持续逆行3秒",
            target_ref="branch:branch_wrong_way",
            mode="continuous",
            duration_seconds=ResolvableValue(
                state="explicit", value=3.0, source="user"
            ),
            allowed_gap_seconds=0.5,
            identity_scope="track",
        )
    ]
    document = editor.set_final_decision(
        document,
        "逆行告警",
        "event_decision",
        "branch:branch_wrong_way",
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "逆行告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            }
        ],
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["video"]

    assert compiled.validation_report["can_run"] is False
    assert compiled.validation_report["resource_blockers"] == ["normal_direction"]
    assert any(item.op == "track.iou@1.0" for item in variant.nodes)
    qualifier = next(item for item in variant.nodes if item.op == "temporal.qualify@1.0")
    assert qualifier.params["duration_seconds"] == 3.0
    assert any(slot.slot_id == "slot_normal_direction" for slot in variant.configuration_slots)


def test_complex_pattern_can_be_the_final_semantic_source():
    registry, editor, document = _document("video")
    document.skill_template.business_branches = [
        BusinessBranch(branch_id="branch_accident", display_name="交通事故", media_type="video"),
        BusinessBranch(branch_id="branch_fire", display_name="烟火爆炸", media_type="video"),
    ]
    for branch_id, label in (
        ("branch_accident", "traffic accident"),
        ("branch_fire", "fire and explosion"),
    ):
        document, _ = _condition(
            editor,
            document,
            branch_id,
            "target.detect",
            label,
            {"targets": [label], "phrases": label, "business_label": label},
        )
    document = editor.set_complex_pattern(
        document,
        "video",
        "sequence",
        ["branch_accident", "branch_fire"],
        window_seconds=30,
        display_name="事故后发生烟火爆炸",
    )
    pattern_id = document.skill_template.event_patterns[0].pattern_id
    document = editor.set_final_decision(
        document,
        "事故后烟火爆炸告警",
        "timeline_summary",
        f"event:{pattern_id}",
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "事故后烟火爆炸告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            }
        ],
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["video"]
    assert any(item.op == "temporal.sequence@2.0" for item in variant.nodes)
    assert variant.outputs["final_primary"].startswith("$pattern_")
    contract = build_runtime_contract(compiled, "video")
    assert f"event:{pattern_id}" in contract["published_sources"]
    assert "final:primary" in contract["published_sources"]


def test_nested_branch_orchestration_compiles_child_group_before_parent():
    registry, editor, document = _document("video")
    document.skill_template.business_branches = [
        BusinessBranch(branch_id="branch_a", display_name="分支A", media_type="video"),
        BusinessBranch(branch_id="branch_b", display_name="分支B", media_type="video"),
        BusinessBranch(branch_id="branch_c", display_name="分支C", media_type="video"),
    ]
    for branch_id in ("branch_a", "branch_b", "branch_c"):
        document, _ = _condition(
            editor,
            document,
            branch_id,
            "target.detect",
            branch_id,
            {"targets": ["vehicle"], "phrases": "vehicle", "business_label": "车辆"},
        )
    document = editor.set_complex_pattern(
        document, "video", "sequence", ["branch_a", "branch_b"],
        display_name="A后B",
    )
    child_id = document.skill_template.event_patterns[-1].pattern_id
    document = editor.set_complex_pattern(
        document,
        "video",
        "all_completed",
        [f"event:{child_id}", "branch:branch_c"],
        display_name="顺序组与C并行",
    )
    parent_id = document.skill_template.event_patterns[-1].pattern_id
    document = editor.set_final_decision(
        document, "组合完成", "timeline_summary", f"event:{parent_id}"
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["video"]
    child = next(item for item in variant.nodes if item.id == f"pattern_{child_id}_sequence")
    parent = next(item for item in variant.nodes if item.id == f"pattern_{parent_id}_join")
    assert parent.inputs["events"][0] == f"${child.id}"
    assert variant.outputs["final_primary"] == f"${parent.id}"


def test_upper_clothing_color_compiles_tight_carrier_evidence_before_hsv_projection():
    """A garment colour must not be evaluated on the whole person crop."""

    registry, editor, document = _document("image")
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_white_shirt",
            display_name="白色衬衫人员",
            media_type="image",
        )
    ]
    document, people_id = _condition(
        editor,
        document,
        "branch_white_shirt",
        "target.detect",
        "检测人员",
        {"targets": ["person"], "phrases": "person", "business_label": "人员"},
    )
    document, color_id = _condition(
        editor,
        document,
        "branch_white_shirt",
        "attribute.color",
        "白色衬衫",
        {
            "source": f"condition:{people_id}",
            "part": "upper_clothing",
            "color": "white",
        },
    )
    document = editor.set_final_decision(
        document,
        "白色衬衫人员",
        "detection_summary",
        f"condition:{color_id}",
    )
    document = editor.set_result_rows(
        document,
        [{
            "display_name": "白色衬衫人员",
            "source_ref": f"condition:{color_id}",
            "result_kind": "entities",
            "evidence_policy": "required",
            "save_policy": "always",
            "show_in_overview": True,
        }],
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["image"]
    shared_ground = next(
        node
        for node in variant.nodes
        if node.op == "rex.ground@1.1"
        and any(
            target.get("phrases") == ["white shirt"]
            for target in node.params.get("targets", [])
        )
    )
    color = next(
        node
        for node in variant.nodes
        if node.op == "visual.color_fraction@1.0"
        and node.params["color"] == "white"
    )
    owner = next(
        node
        for node in variant.nodes
        if node.op == "spatial.associate@1.0"
        and node.params.get("relation") == "best_owner"
    )
    assert color.inputs["objects"] != f"${shared_ground.id}"
    assert color.params["selection_mode"] == "fraction"
    assert color.params["subject_region"] == [0.0, 0.05, 1.0, 0.58]
    assert color.params["min_fraction"] == 0.1
    assert owner.inputs["objects"].startswith("$"), owner.inputs
    combined = next(
        node
        for node in variant.nodes
        if node.op == "logic.all@1.0"
        and node.id.endswith("_and")
    )
    assert len(combined.inputs["conditions"]) == 2
    # The result is projected back to the original person set after owner
    # matching, so output boxes remain person boxes rather than shirt boxes.
    assert variant.outputs["objects"].startswith("$")
    assert variant.outputs["objects"].removeprefix("$") != shared_ground.id


def test_color_compiler_is_generic_across_carriers_and_aliases():
    """Every named carrier uses tight coloured evidence and best-owner binding."""

    cases = [
        (
            "红色上衣",
            {"part": "upper_clothing", "color": "红色"},
            "red upper body clothing",
            "red",
        ),
        (
            "灰色裤子",
            {"part": "lower_clothing", "color": "grey"},
            "gray trousers",
            "gray",
        ),
        (
            "黄色安全帽",
            {"part": "whole", "color": "yellow"},
            "yellow helmet",
            "yellow",
        ),
        (
            "黑色衣服",
            {"part": "whole", "color": "black"},
            "black clothing",
            "black",
        ),
    ]
    for name, parameters, expected_phrase, expected_color in cases:
        registry, editor, document = _document("image")
        document.skill_template.business_branches = [
            BusinessBranch(
                branch_id="branch_generic_color",
                display_name=name,
                media_type="image",
            )
        ]
        document, people_id = _condition(
            editor,
            document,
            "branch_generic_color",
            "target.detect",
            "检测人员",
            {"targets": ["person"], "phrases": "person", "business_label": "人员"},
        )
        document, color_id = _condition(
            editor,
            document,
            "branch_generic_color",
            "attribute.color",
            name,
            {"source": f"condition:{people_id}", **parameters},
        )
        document = editor.set_final_decision(
            document, name, "detection_summary", f"condition:{color_id}"
        )
        compiled = EditorService(registry).apply(document)
        variant = compiled.effective_skill_package.variants["image"]
        shared_ground = next(
            node
            for node in variant.nodes
            if node.op == "rex.ground@1.1"
            and any(
                target.get("phrases") == [expected_phrase]
                for target in node.params.get("targets", [])
            )
        )
        color = next(
            node
            for node in variant.nodes
            if node.op == "visual.color_fraction@1.0"
            and node.params["color"] == expected_color
        )
        assert color.inputs["objects"] != f"${shared_ground.id}"
        assert color.params["color_tolerance"] == "semantic"
        assert color.params["selection_mode"] == "fraction"
        if expected_phrase == "black clothing":
            # A direct editor value is authoritative; planner-inferred
            # defaults get the carrier-aware recall baseline (covered below).
            assert color.params["min_fraction"] == 0.1


def test_llm_inferred_generic_clothing_uses_recall_baseline():
    registry, editor, document = _document("image")
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_black_clothing",
            display_name="黑色衣服人员",
            media_type="image",
        )
    ]
    document, people_id = _condition(
        editor,
        document,
        "branch_black_clothing",
        "target.detect",
        "检测人员",
        {"targets": ["person"], "phrases": "person", "business_label": "人员"},
    )
    document, color_id = _condition(
        editor,
        document,
        "branch_black_clothing",
        "attribute.color",
        "黑色衣服",
        {
            "source": f"condition:{people_id}",
            "part": "whole",
            "color": "black",
            "minimum_fraction": 20,
        },
    )
    branch = document.skill_template.business_branches[0]
    color_expression = next(
        item
        for item in branch.condition_root.children
        if item.expression_id == color_id
    )
    color_expression.parameter_sources["minimum_fraction"] = ResolvableValue(
        state="inferred",
        value=20,
        source="llm_business_draft",
        required_before="never",
    )
    document = editor.set_final_decision(
        document, "黑色衣服人员", "detection_summary", f"condition:{color_id}"
    )
    compiled = EditorService(registry).apply(document)
    color = next(
        node
        for node in compiled.effective_skill_package.variants["image"].nodes
        if node.op == "visual.color_fraction@1.0"
        and node.params["color"] == "black"
    )
    assert color.params["min_fraction"] == 0.1


def test_color_compiler_uses_attribute_evidence_for_non_clothing_targets():
    """Whole-object colours use model evidence before colour verification."""

    registry, editor, document = _document("image")
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_red_car",
            display_name="红色汽车",
            media_type="image",
        )
    ]
    document, car_id = _condition(
        editor,
        document,
        "branch_red_car",
        "target.detect",
        "检测汽车",
        {"targets": ["car"], "phrases": "car", "business_label": "汽车"},
    )
    document, color_id = _condition(
        editor,
        document,
        "branch_red_car",
        "attribute.color",
        "红色汽车",
        {"source": f"condition:{car_id}", "part": "whole", "color": "red"},
    )
    document = editor.set_final_decision(
        document, "红色汽车", "detection_summary", f"condition:{color_id}"
    )

    compiled_document = EditorService(registry).apply(document)
    variant = compiled_document.effective_skill_package.variants["image"]
    shared_ground = next(
        node
        for node in variant.nodes
        if node.op == "rex.ground@1.1"
        and any(
            target.get("phrases") == ["red car"]
            for target in node.params.get("targets", [])
        )
    )
    color = next(
        node
        for node in variant.nodes
        if node.op == "visual.color_fraction@1.0"
        and node.params["color"] == "red"
    )
    owner = next(
        node
        for node in variant.nodes
        if node.op == "spatial.associate@1.0"
        and node.params.get("relation") == "best_owner"
    )
    assert color.inputs["objects"] != f"${shared_ground.id}"
    assert color.params["selection_mode"] == "fraction"
    assert owner.inputs["subjects"].startswith("$")
    assert owner.inputs["objects"].startswith("$")
    assert variant.outputs["objects"].startswith("$")
    assert variant.outputs["objects"].removeprefix("$") != shared_ground.id


def test_parallel_coloured_target_branches_share_one_grounding_request():
    """Independent branches share inference but keep evidence chains separate."""

    registry, editor, document = _document("image")
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_sofa", display_name="黄色沙发", media_type="image"
        ),
        BusinessBranch(
            branch_id="branch_chair", display_name="白色椅子", media_type="image"
        ),
    ]
    document, sofa_id = _condition(
        editor,
        document,
        "branch_sofa",
        "target.detect",
        "检测沙发",
        {"targets": ["sofa"], "phrases": "sofa", "business_label": "沙发"},
    )
    document, yellow_sofa_id = _condition(
        editor,
        document,
        "branch_sofa",
        "attribute.color",
        "沙发颜色黄色",
        {"source": f"condition:{sofa_id}", "part": "whole", "color": "yellow"},
    )
    document, chair_id = _condition(
        editor,
        document,
        "branch_chair",
        "target.detect",
        "检测椅子",
        {"targets": ["chair"], "phrases": "chair", "business_label": "椅子"},
    )
    document, white_chair_id = _condition(
        editor,
        document,
        "branch_chair",
        "attribute.color",
        "椅子颜色白色",
        {"source": f"condition:{chair_id}", "part": "whole", "color": "white"},
    )
    document, _ = _condition(
        editor,
        document,
        "branch_chair",
        "subject.same_attributes",
        "椅子与颜色同一主体",
        {
            "subject": f"condition:{chair_id}",
            "attributes": [f"condition:{white_chair_id}"],
        },
    )
    document = editor.set_final_decision(
        document,
        "黄色沙发与白色椅子",
        "detection_summary",
        "branch:branch_sofa",
        source_refs=["branch:branch_sofa", "branch:branch_chair"],
        combination="AND",
    )

    compiled_document = EditorService(registry).apply(document)
    variant = compiled_document.effective_skill_package.variants["image"]
    grounds = [node for node in variant.nodes if node.op == "rex.ground@1.1"]
    assert len(grounds) == 1
    deduplicated = [
        node for node in variant.nodes if node.op == "objects.deduplicate@1.0"
    ]
    assert len(deduplicated) == 1
    assert deduplicated[0].inputs == {"objects": f"${grounds[0].id}"}
    assert deduplicated[0].params == {
        "metric": "instance",
        "threshold": 0.45,
        "keep": "best_localization",
    }
    phrases = {
        tuple(target["phrases"])
        for target in grounds[0].params["targets"]
    }
    assert phrases == {("sofa",), ("yellow sofa",), ("chair",), ("white chair",)}
    assert sum(node.op == "spatial.associate@1.0" for node in variant.nodes) == 2
    assert not any(
        node.op in {"pairs.build@1.0", "pairs.measure@1.0", "pairs.filter@1.0"}
        for node in variant.nodes
    )
    color_rows = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    ).condition_rows(compiled_document, "branch_sofa")
    yellow_row = next(row for row in color_rows if row["name"] == "沙发颜色黄色")
    assert "yellow sofa" in yellow_row["summary"]
    assert "模型属性证据「yellow sofa」归属于基础目标「检测沙发」" in yellow_row["summary"]
    assert "yellow占比校验与该归属证据同时满足" in yellow_row["summary"]
    sofa_root = next(row for row in color_rows if row["parent_id"] is None)
    assert sofa_root["verification_logic"] == "AND"
    assert [
        member["name"] for member in sofa_root["verification_members"]
    ] == [
        "模型「sofa」+ yellow占比",
        "模型「yellow sofa」+ 同一主体归属",
    ]


def test_color_evidence_combination_mode_controls_execution_generically():
    expected = {
        "AND": (True, True, "logic.all@1.0"),
        "OR": (True, True, "logic.any@1.0"),
        "FRACTION_ONLY": (True, False, None),
        "SEMANTIC_ONLY": (False, True, None),
    }

    for mode, (has_fraction, has_semantic, logic_op) in expected.items():
        registry, editor, document = _document("image")
        document.skill_template.business_branches = [
            BusinessBranch(
                branch_id="branch_main",
                display_name="颜色目标",
                media_type="image",
            )
        ]
        document, target_id = _condition(
            editor,
            document,
            "branch_main",
            "target.detect",
            "检测目标",
            {"targets": ["sofa"], "phrases": "sofa"},
        )
        document, color_id = _condition(
            editor,
            document,
            "branch_main",
            "attribute.color",
            "颜色属性",
            {
                "source": f"condition:{target_id}",
                "part": "whole",
                "color": "yellow",
                "verification_logic": mode,
            },
        )
        document = editor.set_final_decision(
            document,
            "颜色目标结果",
            "detection_summary",
            "branch:branch_main",
        )

        compiled = EditorService(registry).apply(document)
        variant = compiled.effective_skill_package.variants["image"]
        assert any(
            node.op == "visual.color_fraction@1.0" for node in variant.nodes
        ) is has_fraction
        assert any(
            node.op == "spatial.associate@1.0"
            and node.params.get("relation") == "best_owner"
            for node in variant.nodes
        ) is has_semantic
        phrases = {
            phrase
            for node in variant.nodes
            if node.op == "rex.ground@1.1"
            for target in node.params["targets"]
            for phrase in target["phrases"]
        }
        assert ("yellow sofa" in phrases) is has_semantic
        if logic_op is None:
            assert not any(
                node.op in {"logic.all@1.0", "logic.any@1.0"}
                and node.id.endswith(("_and", "_or"))
                and color_id in node.id
                for node in variant.nodes
            )
        else:
            combined = next(
                node
                for node in variant.nodes
                if node.op == logic_op
                and node.id.endswith(("_and", "_or"))
                and color_id in node.id
            )
            assert combined.params["combine_scope"] == "by_key"
            assert len(combined.inputs["conditions"]) == 2
        rows = BusinessRuleEditor(
            build_business_capability_registry(registry), registry
        ).condition_rows(compiled, "branch_main")
        root = next(row for row in rows if row["parent_id"] is None)
        assert len(root["verification_members"]) == (
            2 if mode in {"AND", "OR"} else 1
        )
        assert root["verification_logic"] == (
            mode if mode in {"AND", "OR"} else ""
        )
