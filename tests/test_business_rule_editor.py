from __future__ import annotations

import pytest
from pathlib import Path

from core.business_capabilities import build_business_capability_registry
from core.business_rule_editor import BusinessRuleEditError, BusinessRuleEditor
from core.editor_schema import BusinessBranch
from core.editor_service import EditorService
from core.legacy_importer import import_skill_package
from core.registry import build_default_registry
from core.schema import CanonicalSemanticIR
from core.semantic import WorkflowCompiler
from core.schema import SkillPackage


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


def test_imported_p04_has_no_speed_or_track_logic_group():
    registry = build_default_registry()
    editor = _editor(registry)
    package = SkillPackage.model_validate_json(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P04_highway_congestion.json"
        ).read_text(encoding="utf-8")
    )
    document = editor.prepare(import_skill_package(package))
    branch = next(
        item for item in document.skill_template.business_branches
        if item.media_type == "video"
    )
    groups = editor.imported_logic_groups(document, branch.branch_id)
    assert groups == []


def test_imported_steps_describe_concrete_objects_and_relations():
    registry = build_default_registry()
    editor = _editor(registry)
    package = SkillPackage.model_validate_json(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P11_service_area_garbage.json"
        ).read_text(encoding="utf-8")
    )
    document = editor.prepare(import_skill_package(package))
    branch = next(
        item
        for item in document.skill_template.business_branches
        if item.media_type == "image"
    )
    rows = editor.condition_rows(document, branch.branch_id)
    names = {row["name"] for row in rows}
    summaries = {row["summary"] for row in rows}
    assert "检测：垃圾容器、溢出垃圾、垃圾堆、散落垃圾" in names
    assert "保留：垃圾容器" in names
    assert "判断：溢出垃圾中心位于垃圾容器的上沿区域" in names
    assert any("垃圾堆" in summary and "垃圾容器" in summary for summary in summaries)
    root = next(row for row in rows if row.get("parent_id") is None)
    assert "保留：" not in root["summary"]
    assert "排除：" not in root["summary"]
    assert root["summary"].count(" → ") == 4
    assert not any(
        row["name"] in {"检测目标", "按类别筛选或排除", "两个目标的空间关系"}
        for row in rows
    )


def test_imported_p04_keeps_full_condition_tree_after_validate_apply():
    registry = build_default_registry()
    editor = _editor(registry)
    package = SkillPackage.model_validate_json(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P04_highway_congestion.json"
        ).read_text(encoding="utf-8")
    )
    document = editor.prepare(import_skill_package(package))
    compiled = EditorService(registry).apply(document)
    branch = next(
        item for item in compiled.skill_template.business_branches
        if item.media_type == "video"
    )
    assert {"lane_count", "many", "events"} <= set(branch.node_ids)
    names = {
        row["name"] for row in editor.condition_rows(compiled, branch.branch_id)
    }
    assert "每个区域的目标数量判断" in names
    assert "速度、停留或静止" not in names


def test_imported_p04_result_specs_keep_regions_and_per_lane_series_semantics():
    package = SkillPackage.model_validate_json(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P04_highway_congestion.json"
        ).read_text(encoding="utf-8")
    )
    document = import_skill_package(package)
    specs = {item.result_id: item for item in document.skill_template.result_specs}
    regions = specs["result_regions"]
    counts = specs["result_measurements_1"]
    assert (regions.semantic_type, regions.value_shape, regions.projection.kind) == (
        "resource", "list", "resource"
    )
    assert (counts.semantic_type, counts.value_shape, counts.projection.kind) == (
        "scalar", "series", "identity"
    )
    assert counts.grouping == ["key"]
    assert "result_measurements_2" not in specs


def test_every_preset_imported_business_step_has_user_facing_parameters():
    registry = build_default_registry()
    editor = _editor(registry)
    root = Path(__file__).resolve().parents[1] / "presets_v2"
    missing = []
    for path in sorted(root.glob("P*.json")):
        package = SkillPackage.model_validate_json(path.read_text(encoding="utf-8"))
        document = editor.prepare(import_skill_package(package))
        for branch in document.skill_template.business_branches:
            for row in editor.condition_rows(document, branch.branch_id):
                if not row.get("imported_step") or row["kind"] != "条件":
                    continue
                parameters = editor.parameter_rows(
                    document,
                    branch.branch_id,
                    row["condition_id"],
                    include_tuning=True,
                )
                if not parameters:
                    missing.append(f"{path.stem}:{row['name']}")
                assert all("_" not in item["name"] for item in parameters)
    assert missing == []


def test_every_set_preset_atom_parameter_is_visible_and_every_safe_value_writes_back():
    registry = build_default_registry()
    editor = _editor(registry)
    root = Path(__file__).resolve().parents[1] / "presets_v2"
    hidden = []
    for path in sorted(root.glob("P*.json")):
        package = SkillPackage.model_validate_json(path.read_text(encoding="utf-8"))
        document = editor.prepare(import_skill_package(package))
        for branch in document.skill_template.business_branches:
            graph = document.skill_template.rule_graphs[branch.media_type]
            conditions = editor.condition_rows(document, branch.branch_id)
            for condition in conditions:
                if not condition.get("imported_step") or condition["kind"] != "条件":
                    continue
                condition_id = condition["condition_id"]
                node_id = condition_id.split(":", 1)[1]
                node = next(item for item in graph.nodes if item.node_id == node_id)
                capability_id = editor._matched_capability_for_operator(node.operator)
                definition = editor.capabilities.require(capability_id)
                rows = editor.parameter_rows(
                    document, branch.branch_id, condition_id, include_tuning=True
                )
                visible_atom_names = {
                    row["parameter_id"].split(":", 1)[1]
                    for row in rows
                    if row["parameter_id"].startswith("atom_parameter:")
                }
                visible_parameter_ids = {row["parameter_id"] for row in rows}
                for parameter in definition.parameters:
                    if parameter.parameter_id not in visible_parameter_ids:
                        continue
                    for mapping in parameter.maps_to:
                        operator, name = mapping.rsplit(".", 1)
                        if operator == node.operator:
                            visible_atom_names.add(name)
                if definition.capability_id == "target.detect" and "targets" in visible_parameter_ids:
                    visible_atom_names.add("targets")
                hidden.extend(
                    f"{path.stem}:{node.node_id}:{name}"
                    for name in sorted(set(node.params) - visible_atom_names)
                )
                editable = {
                    row["parameter_id"]: row["value"]
                    for row in rows
                    if row["editor"] != "readonly"
                }
                if editable:
                    document = editor.update_condition(
                        document,
                        branch.branch_id,
                        condition_id,
                        parameters=editable,
                    )
                    graph = document.skill_template.rule_graphs[branch.media_type]
    assert hidden == []


def test_color_condition_uses_practical_default_and_keeps_it_user_editable():
    registry, document = _document()
    editor = _editor(registry)
    document, condition_id = editor.add_condition(
        document, "branch_main", "attribute.color"
    )
    rows = editor.parameter_rows(
        document, "branch_main", condition_id, include_tuning=True
    )
    fraction = next(row for row in rows if row["name"] == "颜色至少占该部位")
    # A 5% crop admits bright background pixels as clothing; the practical
    # baseline is now 20%, while the tuning field remains user-editable.
    assert fraction["value"] == 20
    assert fraction["editor"] == "percentage"


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


def test_nested_and_or_formula_can_be_built_from_same_level_conditions():
    registry, document = _document()
    editor = _editor(registry)
    ids = []
    for name in ("A条件", "B条件", "C条件"):
        document, condition_id = editor.add_condition(
            document, "branch_main", "target.detect", display_name=name
        )
        ids.append(condition_id)

    document, and_group = editor.group_expressions(
        document, "branch_main", ids[:2], "AND"
    )
    document, _ = editor.group_expressions(
        document, "branch_main", [and_group, ids[2]], "OR"
    )

    root = document.skill_template.business_branches[0].condition_root
    assert root.operator == "OR"
    assert root.children[0].operator == "AND"
    assert [item.display_name for item in root.children[0].children] == [
        "A条件",
        "B条件",
    ]
    assert root.children[1].display_name == "C条件"


def test_recursive_orchestration_can_combine_existing_groups_and_apply_not():
    registry, document = _document()
    editor = _editor(registry)
    ids = []
    for name in ("A条件", "B条件", "C条件", "D条件", "E条件"):
        document, condition_id = editor.add_condition(
            document, "branch_main", "target.detect", display_name=name
        )
        ids.append(condition_id)

    document, left_group = editor.group_expressions(
        document, "branch_main", ids[:2], "AND"
    )
    document, right_group = editor.group_expressions(
        document, "branch_main", ids[2:4], "OR"
    )
    document, nested_group = editor.group_expressions(
        document, "branch_main", [left_group, right_group], "OR"
    )
    document, not_group = editor.group_expressions(
        document, "branch_main", [nested_group], "NOT"
    )

    root = document.skill_template.business_branches[0].condition_root
    assert root.operator == "AND"
    assert root.children[0].expression_id == not_group
    assert root.children[0].operator == "NOT"
    assert root.children[0].children[0].operator == "OR"
    assert [child.operator for child in root.children[0].children[0].children] == [
        "AND",
        "OR",
    ]
    formula = editor.expression_summary(root)
    assert "NOT ((A条件 AND B条件) OR (C条件 OR D条件))" in formula
    assert "AND E条件" in formula

    # Selecting the wrapped group again toggles NOT off without producing a
    # double-negative expression.
    document, restored_group = editor.group_expressions(
        document, "branch_main", [nested_group], "NOT"
    )
    assert restored_group == nested_group
    root = document.skill_template.business_branches[0].condition_root
    assert root.children[0].operator == "OR"


def test_generated_nested_group_relation_is_editable_and_can_be_negated():
    registry, document = _document()
    editor = _editor(registry)
    ids = []
    for name in ("A条件", "B条件", "C条件"):
        document, condition_id = editor.add_condition(
            document, "branch_main", "target.detect", display_name=name
        )
        ids.append(condition_id)
    document, group_id = editor.group_expressions(
        document, "branch_main", ids[:2], "AND"
    )

    groups = editor.expression_logic_groups(document, "branch_main")
    assert any(item["group_id"] == group_id for item in groups)
    updated = editor.update_expression_logic_group(
        document,
        "branch_main",
        group_id,
        "N_OF_M",
        required_count=1,
        negated=True,
    )
    root = updated.skill_template.business_branches[0].condition_root
    assert root.operator == "AND"
    assert root.children[0].operator == "NOT"
    assert root.children[0].children[0].operator == "N_OF_M"
    assert root.children[0].children[0].required_count == 1
    group = next(
        item
        for item in editor.expression_logic_groups(updated, "branch_main")
        if item["group_id"] == group_id
    )
    assert group["negated"] is True
    assert "NOT" in group["summary"]


def test_delete_protects_referenced_conditions_and_cascade_removes_dependents():
    registry, document = _document()
    editor = _editor(registry)
    document, target_id = editor.add_condition(
        document, "branch_main", "target.detect", display_name="检测人员"
    )
    document, color_id = editor.add_condition(
        document, "branch_main", "attribute.color", display_name="红色上衣"
    )
    document = editor.update_condition(
        document,
        "branch_main",
        color_id,
        parameters={
            "source": f"condition:{target_id}",
            "part": "upper_clothing",
            "color": "red",
            "minimum_fraction": 20,
        },
    )

    with pytest.raises(BusinessRuleEditError, match="红色上衣"):
        editor.delete_condition(document, "branch_main", target_id)

    document = editor.delete_condition(
        document, "branch_main", target_id, cascade=True
    )
    assert editor.condition_rows(document, "branch_main") == []


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
    document = editor.set_complex_pattern(
        document, "image", "all_completed", image_ids
    )
    assert document.skill_template.event_patterns[-1].gateways[0].mode == "all_completed"
    with pytest.raises(BusinessRuleEditError, match="顺序关系需要视频流程"):
        editor.set_complex_pattern(
            document, "image", "sequence", image_ids
        )


def test_sequence_can_have_no_maximum_delay_and_exclusive_is_a_gateway():
    registry, document = _document()
    editor = _editor(registry)
    document.skill_template.business_branches[0].media_type = "video"
    document = editor.add_branch(document, "video", "第二分支")
    branch_ids = [item["branch_id"] for item in editor.branch_rows(document, "video")]

    sequenced = editor.set_complex_pattern(
        document, "video", "sequence", branch_ids
    )
    transition = sequenced.skill_template.event_patterns[0].transitions[0]
    assert transition.maximum_delay_seconds.state == "not_applicable"

    exclusive = editor.set_complex_pattern(
        document, "video", "exclusive", branch_ids
    )
    assert exclusive.skill_template.event_patterns[0].gateways[0].mode == "exclusive"


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
