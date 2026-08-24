from __future__ import annotations

import pytest

from core.business_capabilities import build_business_capability_registry
from core.business_rule_editor import BusinessRuleEditError, BusinessRuleEditor
from core.editor_schema import BusinessBranch
from core.legacy_importer import import_skill_package
from core.registry import build_default_registry
from core.schema import CanonicalSemanticIR
from core.semantic import WorkflowCompiler


def _document():
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
            "semantic_hash": "a" * 64,
        }
    )
    package = WorkflowCompiler(registry).compile(
        semantic,
        original_instruction="检测人",
        requested_accept=["image", "video"],
        skill_id="business_editor_fixture",
        display_name="业务规则编辑测试",
    )
    document = import_skill_package(package)
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_main",
            display_name="人员条件",
            media_type="image",
        )
    ]
    return registry, document


def _editor(registry):
    return BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )


def test_condition_crud_is_recursive_and_keeps_business_names():
    registry, document = _document()
    editor = _editor(registry)

    document, target_id = editor.add_condition(
        document, "branch_main", "target.detect"
    )
    document = editor.update_condition(
        document,
        "branch_main",
        target_id,
        display_name="检测人员",
        parameters={
            "targets": ["人员"],
            "phrases": "person",
            "business_label": "人员",
        },
    )
    document, color_id = editor.add_condition(
        document, "branch_main", "attribute.color"
    )
    document = editor.update_condition(
        document,
        "branch_main",
        color_id,
        display_name="红色上衣",
        parameters={
            "source": f"condition:{target_id}",
            "part": "upper_clothing",
            "color": "red",
            "minimum_fraction": 20,
        },
    )

    rows = editor.condition_rows(document, "branch_main")
    assert [row["logic"] for row in rows] == ["AND", "ATOM", "ATOM"]
    assert rows[2]["name"] == "红色上衣"
    assert "AND" in editor.branch_rows(document, "image")[0]["summary"]

    document, copied_id = editor.copy_condition(
        document, "branch_main", color_id
    )
    assert copied_id != color_id
    assert len(editor.condition_rows(document, "branch_main")) == 4

    document = editor.delete_condition(document, "branch_main", copied_id)
    document = editor.delete_condition(document, "branch_main", color_id)
    rows = editor.condition_rows(document, "branch_main")
    assert len(rows) == 1
    assert rows[0]["condition_id"] == target_id


def test_parameter_rows_hide_technical_names_and_keep_frames_as_frames():
    registry, document = _document()
    document.skill_template.business_branches[0].media_type = "video"
    editor = _editor(registry)
    document, condition_id = editor.add_condition(
        document, "branch_main", "motion.track"
    )

    rows = editor.parameter_rows(
        document, "branch_main", condition_id, include_tuning=True
    )
    names = {row["name"] for row in rows}
    assert "同一目标匹配要求" in names
    assert "暂时消失可保留多少帧" in names
    assert not any("iou_threshold" in name for name in names)
    missing = next(row for row in rows if row["name"] == "暂时消失可保留多少帧")
    assert missing["unit"] == "帧"


def test_media_conflict_and_source_type_errors_use_business_language():
    registry, document = _document()
    editor = _editor(registry)
    with pytest.raises(BusinessRuleEditError, match="仅适用于视频"):
        editor.add_condition(document, "branch_main", "motion.wrong_way")

    document, target_id = editor.add_condition(
        document, "branch_main", "target.detect"
    )
    document, count_id = editor.add_condition(
        document, "branch_main", "measure.count"
    )
    with pytest.raises(BusinessRuleEditError, match="不能把自己的结果作为输入"):
        editor.update_condition(
            document,
            "branch_main",
            count_id,
            parameters={
                "source": f"condition:{count_id}",
                "scope": "full_frame",
                "group_by": "total",
                "operator": ">",
                "threshold": 2,
            },
        )
    choices = editor.source_choices(document, "branch_main", count_id)
    assert any(item["value"] == f"condition:{target_id}" for item in choices)


def test_not_wrap_and_branch_guards_are_deterministic():
    registry, document = _document()
    editor = _editor(registry)
    document, condition_id = editor.add_condition(
        document, "branch_main", "target.detect"
    )
    document, group_id = editor.wrap_with_group(
        document, "branch_main", condition_id, "NOT"
    )
    rows = editor.condition_rows(document, "branch_main")
    assert rows[0]["condition_id"] == group_id
    assert rows[0]["logic"] == "NOT"

    with pytest.raises(BusinessRuleEditError, match="至少需要保留一个"):
        editor.delete_branch(document, "branch_main")


def test_imported_configuration_slots_survive_rule_graph_recompile():
    registry, document = _document()
    original = next(iter(document.skill_template.rule_graphs.values()))
    # The ordinary fixture has no slots; this checks the compiler path remains
    # lossless when a node carries one after a package import.
    from core.schema import ConfigurationBinding, ConfigurationSlot

    node = original.nodes[0]
    node.configuration_slots = [
        ConfigurationSlot(
            slot_id="region_slot",
            kind="region_set",
            label="区域",
            binding=ConfigurationBinding(node_id=node.node_id, parameter="regions"),
            allowed_shapes=["rectangle", "polygon"],
        )
    ]
    # Slot/operator compatibility is deliberately not asserted here: the
    # preservation contract belongs to the graph compiler, not the binder.
    from core.rule_graph import RuleGraphCompiler

    compiled = RuleGraphCompiler(registry)._compile_variant(
        original, "image", document.skill_template.semantic_ir, []
    )
    assert compiled["configuration_slots"][0]["slot_id"] == "region_slot"
    assert compiled["configuration_slots"][0]["binding"]["node_id"] == node.node_id


def test_complex_pattern_uses_stable_branch_references_and_video_boundary():
    registry, document = _document()
    editor = _editor(registry)
    document.skill_template.business_branches[0].media_type = "video"
    document = editor.rename_branch(document, "branch_main", "事故")
    document = editor.add_branch(document, "video", "烟火")
    branches = editor.branch_rows(document, "video")
    branch_ids = [item["branch_id"] for item in branches]

    document = editor.set_complex_pattern(
        document,
        "video",
        "sequence",
        branch_ids,
        window_seconds=30,
        correlation_scope="global",
        display_name="事故后烟火",
    )
    pattern = document.skill_template.event_patterns[0]
    assert pattern.pattern_type == "sequence"
    assert [stage.source_ref for stage in pattern.stages] == [
        f"branch:{item}" for item in branch_ids
    ]
    assert pattern.transitions[0].maximum_delay_seconds.value == 30

    document = editor.add_branch(document, "image", "图片条件A")
    document = editor.add_branch(document, "image", "图片条件B")
    image_ids = [item["branch_id"] for item in editor.branch_rows(document, "image")]
    with pytest.raises(BusinessRuleEditError, match="需要视频流程"):
        editor.set_complex_pattern(
            document, "image", "all_active", image_ids
        )


def test_result_final_and_trigger_are_one_semantic_document():
    registry, document = _document()
    editor = _editor(registry)
    document, condition_id = editor.add_condition(
        document, "branch_main", "target.detect"
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "人员框",
                "source_ref": f"condition:{condition_id}",
                "result_kind": "entities",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            },
            {
                "display_name": "人员是否出现",
                "source_ref": "branch:branch_main",
                "result_kind": "decision",
                "evidence_policy": "optional",
                "save_policy": "always",
                "show_in_overview": True,
            },
        ],
    )
    assert len(document.skill_template.result_specs) == 2
    assert document.skill_template.result_specs[0].semantic_type == "entity_set"
    result_id = document.skill_template.result_specs[1].result_id
    document = editor.set_final_decision(
        document,
        "人员检测结果",
        "detection_summary",
        f"result:{result_id}",
    )
    document = editor.set_trigger_policy(
        document,
        mode="on_change",
        cooldown_seconds=10,
        severity="high",
        outputs=["event_record", "annotated_media"],
    )
    assert document.skill_template.final_decision.display_name == "人员检测结果"
    assert document.skill_template.trigger_policy.trigger_moment == "false_to_true"
    assert document.skill_template.trigger_policy.cooldown_seconds == 10
