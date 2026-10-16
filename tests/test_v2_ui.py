from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import gradio as gr
import pytest
from PIL import Image

from core.registry import build_default_registry
from core.schema import SkillPackage


def test_current_config_table_keeps_a_and_b_as_separate_effective_rows():
    from app_v2 import effective_condition_config_rows

    table = effective_condition_config_rows(
        [{"name": "颜色", "value": "黄色", "unit": "", "source": "LLM建议", "help": "用户选择的颜色。"}],
        [{
            "condition_id": "group",
            "verification_child_ids": ["base", "color"],
            "verification_logic": "AND",
            "verification_members": [
                {"name": "模型「sofa」+ yellow占比", "summary": "条件 A：校验黄色占比。"},
                {"name": "模型「yellow sofa」+ 同一主体归属", "summary": "条件 B：匹配回同一主体。"},
            ],
        }],
        "color",
    )

    assert table[-3][0:2] == ["条件 A", "模型「sofa」+ yellow占比"]
    assert table[-2][0:2] == ["条件 B", "模型「yellow sofa」+ 同一主体归属"]
    assert table[-1][0:2] == ["最终复核组合", "（条件 A） AND （条件 B）"]
    assert table[-1][3] == "LLM业务编排 + 系统确定性编译"
    assert "条件 A：" not in table[-2][4]


def test_internal_verification_modes_have_user_facing_labels():
    from ui.event_rule_editor import friendly_choice_label

    assert friendly_choice_label("FRACTION_ONLY") == "仅颜色占比"
    assert friendly_choice_label("SEMANTIC_ONLY") == "仅模型属性证据"


def test_current_config_table_scales_logic_members_beyond_b():
    from app_v2 import effective_condition_config_rows

    table = effective_condition_config_rows(
        [],
        [{
            "condition_id": "group",
            "logic_child_ids": ["a", "b", "c", "d"],
            "logic_relation_label": "AND",
            "member_summaries": ["条件甲", "条件乙", "条件丙", "条件丁"],
        },
        {"condition_id": "a", "name": "条件甲", "summary": "甲说明"},
        {"condition_id": "b", "name": "条件乙", "summary": "乙说明"},
        {"condition_id": "c", "name": "条件丙", "summary": "丙说明"},
        {"condition_id": "d", "name": "条件丁", "summary": "丁说明"}],
        "c",
    )

    assert [row[0] for row in table] == [
        "条件 A", "条件 B", "条件 C", "条件 D", "最终复核组合"
    ]
    assert table[-1][1] == "（条件 A） AND （条件 B） AND （条件 C） AND （条件 D）"


def test_condition_tree_separates_formula_group_members_and_atomic_details():
    from ui.event_rule_editor import render_condition_tree

    rows = [
        {
            "condition_id": "group",
            "parent_id": None,
            "depth": 0,
            "kind": "条件组",
            "logic": "AND",
            "category": "逻辑组合",
            "name": "属性条件组",
            "summary": "检测目标 AND 属性复核",
            "status": "可用",
            "member_summaries": ["检测目标", "属性复核"],
            "logic_relation_label": "AND",
        },
        {
            "condition_id": "a",
            "parent_id": "group",
            "depth": 1,
            "kind": "条件",
            "logic": "ATOM",
            "category": "目标与属性",
            "name": "检测目标",
            "summary": "模型检测基础目标。",
            "status": "已配置",
            "logic_member_label": "条件 A",
        },
        {
            "condition_id": "b",
            "parent_id": "group",
            "depth": 1,
            "kind": "条件",
            "logic": "ATOM",
            "category": "目标与属性",
            "name": "属性复核",
            "summary": "模型属性证据归属于同一主体。",
            "status": "已配置",
            "logic_member_label": "条件 B",
        },
    ]

    rendered = render_condition_tree(rows)
    assert rendered.count("检测目标 AND 属性复核") == 1
    assert rendered.count("模型检测基础目标。") == 1
    assert rendered.count("模型属性证据归属于同一主体。") == 1
    assert "<i>条件 A</i>检测目标" in rendered
    assert "<i>条件 B</i>属性复核" in rendered


def test_colour_branch_renders_effective_a_b_evidence_instead_of_dependencies():
    from ui.event_rule_editor import render_condition_tree

    rows = [
        {
            "condition_id": "group",
            "parent_id": None,
            "depth": 0,
            "kind": "条件组",
            "logic": "AND",
            "category": "逻辑组合",
            "name": "黄色目标条件组",
            "summary": "检测目标 AND 黄色属性",
            "status": "可用",
            "effective_formula": (
                "模型「object」+ yellow占比 AND "
                "模型「yellow object」+ 同一主体归属"
            ),
            "verification_logic": "AND",
            "verification_child_ids": ["base", "color"],
            "verification_members": [
                {
                    "name": "模型「object」+ yellow占比",
                    "summary": "条件 A：在基础主体框内校验黄色占比。",
                },
                {
                    "name": "模型「yellow object」+ 同一主体归属",
                    "summary": "条件 B：语义证据匹配回同一主体。",
                },
            ],
        },
        {"condition_id": "base", "parent_id": "group", "kind": "条件"},
        {"condition_id": "color", "parent_id": "group", "kind": "条件"},
    ]

    rendered = render_condition_tree(rows)
    assert "检测目标 AND 黄色属性" not in rendered
    assert rendered.count("模型「object」+ yellow占比") == 3
    assert rendered.count("模型「yellow object」+ 同一主体归属") == 3
    assert "条件 A：在基础主体框内校验黄色占比。" in rendered
    assert "条件 B：语义证据匹配回同一主体。" in rendered


def test_colour_review_defaults_to_the_editable_a_b_capability(tmp_path):
    from core.business_capabilities import build_business_capability_registry
    from core.business_rule_draft import apply_business_rule_draft
    from core.editor_service import EditorService
    from tests.test_business_rule_draft import _base

    registry, document, _ = _base(("image",))
    draft = {
        "schema_version": "1.0",
        "media_requirement": "image",
        "branches": [{
            "key": "colored_object",
            "name": "黄色目标",
            "media_type": "image",
            "logic": "AND",
            "conditions": [
                {
                    "key": "object",
                    "name": "检测目标",
                    "capability_id": "target.detect",
                    "parameters": {"targets": ["object"], "phrases": "object"},
                },
                {
                    "key": "yellow",
                    "name": "黄色属性",
                    "capability_id": "attribute.color",
                    "parameters": {
                        "source": "condition:object",
                        "part": "whole",
                        "color": "yellow",
                        "verification_logic": "AND",
                    },
                },
            ],
        }],
        "final_decision": {
            "name": "黄色目标结果",
            "decision_type": "detection_summary",
            "source_refs": ["branch:colored_object"],
            "combination": "AND",
        },
        "results": [{
            "key": "matches",
            "name": "黄色目标",
            "source_ref": "condition:colored_object.yellow",
            "result_kind": "entities",
        }],
    }
    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    compiled = EditorService(registry).apply(converted)
    controller = _controller(tmp_path)
    view = controller.business_rule_view(
        controller._dump(compiled), "image"
    )

    selected = next(
        row
        for row in view["conditions"]
        if row["condition_id"] == view["condition_id"]
    )
    assert selected["capability_id"] == "attribute.color"
    assert selected["review_primary"] is True
    assert view["condition_name"] == "黄色属性复核（AND）"
    assert "条件 A（颜色占比）" in view["parameter_help"]
    assert "条件 B（模型属性语义 + 同一主体归属）" in view["parameter_help"]
    assert "模型「object」+ yellow占比" in view["condition_tree"]


def test_json_object_or_empty_preserves_ui_after_a_failed_generation():
    from app_v2 import json_object_or_empty

    assert json_object_or_empty("") == {}
    assert json_object_or_empty("not-json") == {}
    assert json_object_or_empty('{"original_instruction": "检测人员"}') == {
        "original_instruction": "检测人员"
    }


def test_generic_parameter_editor_covers_every_registered_business_parameter_type(tmp_path):
    from app_v2 import SUPPORTED_BUSINESS_PARAMETER_EDITORS

    controller = _controller(tmp_path)
    registered = {
        parameter.editor
        for capability in controller.business_capabilities.definitions()
        for parameter in capability.parameters
    }

    assert registered <= SUPPORTED_BUSINESS_PARAMETER_EDITORS
    assert {
        "text",
        "number",
        "select",
        "multi_select",
        "scene_resource_select",
        "direction_resource_select",
        "source_select",
    } <= registered
    assert "boolean" in SUPPORTED_BUSINESS_PARAMETER_EDITORS


def test_annotation_guidance_is_generic_and_video_sampling_defaults_to_one_fps():
    from app_v2 import ANNOTATION_GUIDANCE_MARKDOWN
    from core.preset_factory import start_nodes

    assert "车道向导" not in ANNOTATION_GUIDANCE_MARKDOWN
    assert "命名区域" in ANNOTATION_GUIDANCE_MARKDOWN
    assert "参考方向" in ANNOTATION_GUIDANCE_MARKDOWN
    assert build_default_registry().require("video.sample@1.1").defaults["fps"] == 1.0
    nodes, _, _ = start_nodes("video")
    assert next(node for node in nodes if node["id"] == "frames")["params"]["fps"] == 1.0


def test_empty_business_secondary_controls_match_all_19_frontend_outputs(tmp_path):
    controller = _controller(tmp_path)

    values = controller.business_secondary_controls("", "image")

    assert len(values) == 19
    assert values[6:13] == (
        "最终结果", "event_decision", values[8], "AND", 1, True, True
    )
    assert values[14:18] == ("none", 0, "medium", ["event_record"])


def test_business_output_can_delete_the_selected_row_but_keeps_one(tmp_path):
    controller = _controller(tmp_path)
    rows = [
        ["车辆数量", "区域1", "数量", "辆", "必须保存", "每次保存", "是"],
        ["拥堵状态", "最终判定", "是否满足", "", "尽量保存", "满足时保存", "是"],
    ]

    remaining = controller.business_delete_output_row(rows, "车辆数量")

    assert [row[0] for row in remaining] == ["拥堵状态"]
    with pytest.raises(gr.Error, match="至少需要保留一个"):
        controller.business_delete_output_row(remaining, "拥堵状态")


def test_multi_branch_controls_show_basic_relation_and_publish_combination_to_final(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P01_fire_smoke.json"
    ).read_text("utf-8")
    document = controller._editor_document(effective, "", source_type="preset")
    first_id = document.skill_template.business_branches[0].branch_id
    document = controller.business_rule_editor.add_branch(
        document, "image", "第二分支"
    )
    second_id = document.skill_template.business_branches[-1].branch_id
    document = controller.business_rule_editor.set_complex_pattern(
        document,
        "image",
        "all_completed",
        [first_id, second_id],
        display_name="并行阶段",
    )

    values = controller.business_secondary_controls(
        controller._dump(document), "image"
    )

    assert "并行" in values[5]
    assert "当前生效分支编排" in values[5]
    assert "AND" in values[5]
    assert "第二分支" in values[5]
    assert "阶段完成" in values[5]
    final_choice_values = {value for _, value in values[8].choices}
    pattern_id = document.skill_template.event_patterns[0].pattern_id
    assert f"event:{pattern_id}" in final_choice_values
    assert values[18]["visible"] is True


def test_branch_orchestration_can_reuse_a_saved_group_as_parent_input(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P01_fire_smoke.json"
    ).read_text("utf-8")
    document = controller._editor_document(effective, "", source_type="preset")
    document.skill_template.business_branches[0].media_type = "video"
    first_id = document.skill_template.business_branches[0].branch_id
    document = controller.business_rule_editor.add_branch(document, "video", "分支B")
    document = controller.business_rule_editor.add_branch(document, "video", "分支C")
    second_id = document.skill_template.business_branches[-2].branch_id
    third_id = document.skill_template.business_branches[-1].branch_id
    document = controller.business_rule_editor.set_complex_pattern(
        document, "video", "sequence", [first_id, second_id], display_name="A后B"
    )
    child_id = document.skill_template.event_patterns[-1].pattern_id
    document = controller.business_rule_editor.set_complex_pattern(
        document,
        "video",
        "all_completed",
        [f"event:{child_id}", third_id],
        display_name="顺序组与C并行",
    )

    values = controller.business_secondary_controls(controller._dump(document), "video")

    assert "当前生效分支编排" in values[5]
    assert "（" in values[5] and "→" in values[5]
    assert "AND" in values[5] and "分支C" in values[5]
    choice_values = {value for _, value in values[0].choices}
    assert f"event:{child_id}" in choice_values


def test_preset_business_parameter_change_compiles_to_the_current_effective_package(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text("utf-8")
    document = controller._editor_document(effective, "", source_type="preset")
    document = controller.business_rule_editor.prepare(document)
    branch = document.skill_template.business_branches[0]
    document = controller.business_rule_editor.update_condition(
        document,
        branch.branch_id,
        "existing_node:many",
        parameters={"operator": ">=", "threshold": 6},
    )

    compiled_json, package_json, status = controller.unified_validate_apply(
        controller._dump(document)
    )

    compiled = controller._parse_editor_json(compiled_json)
    package = SkillPackage.model_validate_json(package_json)
    many = next(node for node in package.variants["video"].nodes if node.id == "many")
    assert many.params["value"] == 6
    assert compiled.effective_skill_package == package
    assert "当前运行版本已更新" in status


def test_business_parameters_use_controlled_editor_instead_of_freeform_table(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text("utf-8")
    document = controller.business_rule_editor.prepare(
        controller._editor_document(effective, "", source_type="preset")
    )
    branch = document.skill_template.business_branches[0]
    editor_json = controller._dump(document)

    controls = controller.business_parameter_controls(
        editor_json,
        "video",
        branch.branch_id,
        "existing_node:many",
        False,
        "operator",
    )

    assert controls[2]["visible"] is True
    assert ("大于（>）", ">") in controls[2]["choices"]
    assert ("小于等于（<=）", "<=") in controls[2]["choices"]
    assert controls[1]["visible"] is False

    updated_json, status = controller.business_apply_parameter(
        editor_json,
        branch.branch_id,
        "existing_node:many",
        "operator",
        "<",
        [],
        None,
        None,
        None,
        None,
        False,
    )
    updated = controller._parse_editor_json(updated_json)
    graph = updated.skill_template.rule_graphs["video"]
    assert next(node for node in graph.nodes if node.node_id == "many").params["operator"] == "<"
    assert "比较方式" in status

    target_condition = next(
        row["condition_id"]
        for row in controller.business_rule_editor.condition_rows(
            document, branch.branch_id
        )
        if row.get("capability_id") == "target.detect"
    )
    target_values = controller.business_parameter_controls(
        editor_json,
        "video",
        branch.branch_id,
        target_condition,
        False,
        "targets",
    )
    assert target_values[7]["visible"] is True
    assert target_values[7]["value"] == "车辆"
    assert "逗号分隔" in target_values[8]

    phrase = controller.business_parameter_controls(
        editor_json,
        "video",
        branch.branch_id,
        target_condition,
        False,
        "phrases",
    )
    assert phrase[6]["visible"] is True
    assert "可直接修改" in phrase[8]


def test_missing_association_editor_help_uses_generic_business_terms(tmp_path):
    controller = _controller(tmp_path)
    _, effective, *_ = controller.load_preset("P10_no_safety_rope")
    document = controller._editor_document(effective, "", source_type="preset")
    branch = document.skill_template.business_branches[0]
    editor_json = controller._dump(document)

    missing_condition = next(
        row["condition_id"]
        for row in controller.business_rule_editor.condition_rows(
            document, branch.branch_id
        )
        if row.get("capability_id") == "subject.missing_equipment"
    )
    controls = controller.business_parameter_controls(
        editor_json,
        "image",
        branch.branch_id,
        missing_condition,
        False,
    )

    assert "主体目标" in controls[8]
    assert "高处作业人员" in controls[8]
    assert "应有关联物" in controls[8]
    assert "模型正向语义证据" in controls[8]


def test_event_editor_restores_the_loaded_default_after_parameter_changes(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text("utf-8")
    baseline = controller._editor_document(effective, "", source_type="preset")
    prepared = controller.business_rule_editor.prepare(baseline)
    branch = prepared.skill_template.business_branches[0]
    changed = controller.business_rule_editor.update_condition(
        prepared,
        branch.branch_id,
        "existing_node:many",
        parameters={"operator": ">", "threshold": 99},
    )
    assert next(
        node for node in changed.skill_template.rule_graphs["video"].nodes
        if node.node_id == "many"
    ).params["value"] == 99

    restored_json, status = controller.restore_default_editor_document(
        effective, "预置演示技能"
    )
    restored = controller._parse_editor_json(restored_json)
    assert next(
        node for node in restored.skill_template.rule_graphs["video"].nodes
        if node.node_id == "many"
    ).params["value"] != 99
    assert "已还原" in status


def test_video_sampling_editor_defaults_to_one_fps(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    sampling = next(
        component
        for component in config["components"]
        if component["type"] == "radio"
        and component.get("props", {}).get("label") == "抽帧模式"
    )

    assert sampling["props"]["value"] == "fps"


def test_temporal_event_controls_expose_and_update_dwell_threshold(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P06_highway_person_dwell.json"
    ).read_text(encoding="utf-8")

    controls = controller.read_temporal_controls(effective, "video")

    assert len(controls) == 1
    assert controls == [{
        "node_id": "events",
        "label": "持续事件：车道人员逗留",
        "event_label": "车道人员逗留",
        "condition_summary": "目标位于标注区域内",
        "duration_summary": "连续满足上述条件 10 秒后触发",
        "seconds": 10.0,
        "gap_tolerance_seconds": 1.1,
        "trigger_mode": "once",
    }]
    updated = controller.apply_temporal_control(
        effective, "video", "events", 15.0, 0.75, "repeat"
    )
    events = next(
        node for node in json.loads(updated)["variants"]["video"]["nodes"]
        if node["id"] == "events"
    )
    assert events["params"] == {
        "seconds": 15.0,
        "scope": "track",
        "gap_tolerance_seconds": 0.75,
        "trigger_mode": "repeat",
    }


def test_temporal_controls_explain_congestion_count_and_region_scope(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")

    control = controller.read_temporal_controls(effective, "video")[0]

    assert control["event_label"] == "高速车辆拥堵"
    assert control["condition_summary"] == "每个命名区域内目标数量 >= 4"
    assert control["duration_summary"] == "连续满足上述条件 1 秒后触发"


def test_temporal_rules_markdown_explains_when_duration_configuration_applies(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")

    markdown = controller.temporal_rules_markdown(effective, "video")

    assert "**高速车辆拥堵**" in markdown
    assert "每个命名区域内目标数量 >= 4" in markdown
    assert "连续满足上述条件 1 秒后触发" in markdown
    assert "需要时在上方「事件规则编辑」修改持续时间" in markdown


def test_immediate_fall_event_summary_describes_fallen_state_not_full_frame_scope(tmp_path):
    from core.semantic import SemanticNormalizer, WorkflowCompiler

    instruction = "识别视频中是否有人摔倒"
    semantic_ir = SemanticNormalizer().normalize_ledger({
        "mode": "workflow",
        "target": {
            "concept": "person",
            "source_span": "人",
            "phrases": ["person"],
        },
        "constraints": [{
            "kind": "state",
            "value": "fallen",
            "source": instruction,
            "source_span": "摔倒",
            "phrases": ["person fallen"],
        }],
        "logic": "all",
        "unresolved": [],
    }, instruction)
    package = WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=instruction,
        requested_accept=["video"],
        skill_id="fall_event_summary",
        display_name="人员摔倒事件",
    )

    summary = _controller(tmp_path).read_temporal_controls(
        package.model_dump_json(), "video"
    )[0]["condition_summary"]

    assert summary == "检测到人员摔倒事件"


def test_event_rule_controls_expose_editable_congestion_atoms(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")

    controls = controller.read_event_rule_controls(effective, "video")

    assert len(controls) == 1
    regional_parameters = controls[0].pop("regional_parameters")
    assert controls == [{
        "event_id": "events",
        "event_label": "高速车辆拥堵",
        "scope": "region",
        "scope_label": "每个命名区域（在“02 标注”绘制或修改区域）",
        "scope_choices": ["region"],
        "category_node_id": "vehicles_raw",
        "categories": ["车辆"],
        "selected_categories": ["车辆"],
        "comparisons": [
            {
                "node_id": "many",
                "measure": "每个命名区域内目标数量",
                "operator": ">=",
                "value": 4.0,
            },
        ],
        "logic_node_id": None,
        "logic": "all",
        "condition_kind": "comparison",
        "condition_summary": "每个命名区域内目标数量 >= 4",
        "atom_summary": "统计范围：每个命名区域（在“02 标注”绘制或修改区域）；可在本页修改类别、阈值、逻辑、持续与告警。",
        "seconds": 1.0,
        "gap_tolerance_seconds": 0.6,
        "trigger_mode": "once",
        "alert_node_id": "alerts",
    }]
    assert [item["id"] for item in regional_parameters] == [
        "many::operator",
        "many::value",
    ]


def test_event_rule_controls_recover_target_label_from_semantics(tmp_path):
    controller = _controller(tmp_path)
    data = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P04_highway_congestion.json"
        ).read_text(encoding="utf-8")
    )
    data["display_name"] = "我的视觉技能"
    for node in data["variants"]["video"]["nodes"]:
        if node["id"] == "vehicles_raw":
            node["params"]["targets"][0]["label"] = "我的视觉技能"

    controls = controller.read_event_rule_controls(
        json.dumps(data, ensure_ascii=False), "video"
    )

    assert controls[0]["categories"] == ["车辆"]
    assert controls[0]["selected_categories"] == ["车辆"]

    updated = controller.apply_event_rule_control(
        json.dumps(data, ensure_ascii=False),
        "video",
        "events",
        "vehicles_raw",
        ["车辆"],
        ["many"],
        [">="],
        [4],
        "all",
        1,
        0.6,
        "once",
        "我的视觉技能",
    )
    nodes = {
        node["id"] for node in json.loads(updated)["variants"]["video"]["nodes"]
    }
    updated_grounding = next(
        node for node in json.loads(updated)["variants"]["video"]["nodes"]
        if node["id"] == "vehicles_raw"
    )
    assert "vehicles_raw" in nodes
    assert updated_grounding["params"]["targets"][0]["label"] == "车辆"


def test_configuration_guidance_explains_congestion_atomic_steps(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")

    markdown = controller.configuration_guidance_markdown(effective, "video")

    for text in [
        "识别出的原子能力",
        "车辆",
        "每个命名区域",
        "数量 >= 4",
        "持续 1 秒",
        "高速车辆拥堵",
        "02 标注",
    ]:
        assert text in markdown


def test_required_scene_input_precedes_event_rule_configuration(tmp_path):
    """Required regions must be annotated before their event conditions are edited."""
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")

    markdown = controller.configuration_guidance_markdown(effective, "video")
    assert "先到“02 标注”配置" in markdown
    assert "再到“03 审核”调整上述阈值、持续与告警" in markdown

    config = build_v2_app(controller).get_config_file()
    workflow_tabs = [
        component["props"]["label"]
        for component in config["components"]
        if component["type"] == "tabitem"
        and component.get("props", {}).get("label", "")[:3] in {
            "01 ", "02 ", "03 ", "04 ", "05 "
        }
    ]
    assert workflow_tabs == ["01 创建", "02 标注", "03 审核", "04 运行", "05 资产"]


def test_configuration_guidance_explains_direction_without_numeric_comparison(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P05_highway_wrong_way.json"
    ).read_text(encoding="utf-8")

    markdown = controller.configuration_guidance_markdown(effective, "video")

    for text in ["车辆", "方向", "车道", "参考方向箭头", "不是数量或速度比较"]:
        assert text in markdown
    assert "0 条可比较条件" not in markdown


def test_event_rule_controls_describe_direction_without_comparisons(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P05_highway_wrong_way.json"
    ).read_text(encoding="utf-8")

    control = controller.read_event_rule_controls(effective, "video")[0]

    assert control["categories"] == ["车辆"]
    assert control["comparisons"] == []
    assert control["condition_kind"] == "direction"
    assert "方向" in control["condition_summary"]
    assert "不是数量或速度比较" in control["atom_summary"]


def test_event_rule_controls_describe_generic_boolean_state_condition(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P12_person_fall.json"
    ).read_text(encoding="utf-8")

    control = controller.read_event_rule_controls(effective, "video")[0]

    assert control["condition_kind"] == "state"
    assert control["state_condition"]["node_id"] == "fallen_present"
    assert "存在" in control["condition_summary"]


def test_optimized_fall_event_has_no_redundant_association_branch(tmp_path):

    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P12_person_fall.json"
    ).read_text(encoding="utf-8")

    control = controller.read_event_rule_controls(effective, "video")[0]

    assert control.get("associations", []) == []
    assert control["state_condition"]["node_id"] == "fallen_present"


def test_grounding_prompt_controls_expose_every_grounding_node(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P12_person_fall.json"
    ).read_text(encoding="utf-8")

    controls = controller.grounding_prompt_controls(effective, "video")

    assert [item["node_id"] for item in controls] == ["fallen_people_raw"]
    assert controls[0]["prompt"].startswith("Detect person actively falling")
    assert controls[0]["is_override"] is False


def test_grounding_prompt_control_shows_model_phrases_and_business_labels(tmp_path):
    controller = _controller(tmp_path)
    data = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P12_person_fall.json"
        ).read_text(encoding="utf-8")
    )
    node = next(
        node for node in data["variants"]["video"]["nodes"]
        if node["op"].startswith("rex.ground@")
    )
    node["params"]["targets"] = [
        {"label": "沙发", "phrases": ["sofa"]},
        {"label": "黄色", "phrases": ["yellow sofa"]},
        {"label": "椅子", "phrases": ["chair"]},
        {"label": "白色", "phrases": ["white chair"]},
    ]

    controls = controller.grounding_prompt_controls(
        json.dumps(data, ensure_ascii=False), "video"
    )

    assert controls[0]["label"] == (
        "sofa（沙发）；yellow sofa（黄色）；chair（椅子）；white chair（白色）"
    )


def test_grounding_prompt_control_updates_and_resets_only_selected_node(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P12_person_fall.json"
    ).read_text(encoding="utf-8")

    updated = controller.apply_grounding_prompt_control(
        effective, "video", "fallen_people_raw", "Someone fell down"
    )
    nodes = {
        node["id"]: node
        for node in json.loads(updated)["variants"]["video"]["nodes"]
    }
    assert nodes["fallen_people_raw"]["params"]["query_prompt"] == "Someone fell down"
    assert sum(node["op"] == "rex.ground@1.1" for node in nodes.values()) == 1

    reset = controller.reset_grounding_prompt_control(
        updated, "video", "fallen_people_raw"
    )
    reset_nodes = {
        node["id"]: node
        for node in json.loads(reset)["variants"]["video"]["nodes"]
    }
    assert "query_prompt" not in reset_nodes["fallen_people_raw"]["params"]


def test_review_page_exposes_editable_grounding_prompt_card(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    labels = {
        component.get("props", {}).get("label")
        for component in config["components"]
    }

    assert "要编辑的模型检测节点" in labels
    assert "模型检测提示词" in labels


def test_optimized_fall_event_tracks_the_single_pose_detection_set(tmp_path):

    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P12_person_fall.json"
    ).read_text(encoding="utf-8")

    nodes = {
        node["id"]: node
        for node in json.loads(effective)["variants"]["video"]["nodes"]
    }

    assert nodes["tracks"]["inputs"] == {"objects": "$fallen_people"}
    assert nodes["fallen_present"]["inputs"] == {"sets": "$tracks"}
    assert nodes["events"]["inputs"] == {"condition": "$fallen_present"}


def test_event_rule_editor_includes_association_configuration_card(tmp_path):
    """The event editor must expose the reusable candidate-association inputs."""

    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    labels = {
        component.get("props", {}).get("label")
        for component in config["components"]
    }

    assert "要编辑的目标关联" in labels
    assert "主体候选框" in labels
    assert "关联候选框" in labels
    assert "框重叠阈值" in labels


def test_boolean_state_event_can_edit_duration_and_alert_without_numeric_cards(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P12_person_fall.json"
    ).read_text(encoding="utf-8")

    updated = controller.apply_event_rule_cards(
        effective, "video", "events", [], "all", 3.0, 1.1, "repeat", "摔倒告警"
    )
    nodes = {
        node["id"]: node
        for node in json.loads(updated)["variants"]["video"]["nodes"]
    }
    assert nodes["events"]["params"]["seconds"] == 3.0
    assert nodes["events"]["params"]["trigger_mode"] == "repeat"
    assert nodes["alerts"]["params"]["label"] == "摔倒告警"


def test_p08_manual_road_region_is_explained_on_annotation_page(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P08_road_debris.json"
    ).read_text(encoding="utf-8")

    overview = controller.annotation_overview(effective, "image")

    assert "02 标注道路区域" in overview
    assert "标注" in overview


def test_p08_manual_road_region_requires_annotation_before_run(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P08_road_debris.json"
    ).read_text(encoding="utf-8")

    document = controller._editor_document(
        effective, "", source_type="preset"
    )
    package = SkillPackage.model_validate_json(effective)

    assert {
        item.display_name for item in document.skill_template.resource_requirements
    } == {"02 标注道路区域"}
    assert document.validation_report["resource_blockers"]
    assert document.validation_report["can_run"] is False
    for variant in package.variants.values():
        assert not any(
            node.op == "region.from_objects@1.0" for node in variant.nodes
        )
        road_region = next(
            node for node in variant.nodes if node.op == "region.manual_set@1.0"
        )
        assert road_region.enabled is True
        assert len(variant.configuration_slots) == 1


def test_p08_image_annotation_unblocks_only_the_image_execution_path(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P08_road_debris.json"
    ).read_text(encoding="utf-8")
    editor_json = controller._dump(
        controller._editor_document(effective, "", source_type="preset")
    )
    updated, _, _ = controller.bind_annotation(
        effective,
        "image",
        "slot_resource_road_area",
        "rectangle",
        "[[0.1, 0.1], [0.8, 0.8]]",
    )

    image_document = controller._parse_editor_json(
        controller.prepare_run_editor_document(updated, editor_json, "image")
    )
    video_document = controller._parse_editor_json(
        controller.prepare_run_editor_document(updated, editor_json, "video")
    )

    assert image_document.validation_report["can_run"] is True
    assert video_document.validation_report["can_run"] is False
    assert video_document.validation_report["resource_blockers"]


def test_p11_generic_llm_flow_has_no_unrequested_detection_region_requirement(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P11_service_area_garbage.json"
    ).read_text(encoding="utf-8")

    document = controller._editor_document(
        effective, "", source_type="preset"
    )

    requirements = document.skill_template.resource_requirements
    assert requirements == []
    assert document.validation_report["resource_blockers"] == []
    assert document.validation_report["can_run"] is True


def test_render_label_positions_stack_same_anchor():
    from operators.output import _label_position

    first = _label_position((12, 18), 0, 22)
    second = _label_position((12, 18), 1, 22)

    assert first != second
    assert second[1] > first[1]


def test_event_rule_controls_apply_existing_congestion_atoms(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")

    updated = controller.apply_event_rule_control(
        effective,
        "video",
        "events",
        "vehicles_raw",
        ["车辆"],
        ["many"],
        [">"],
        [5],
        "all",
        3,
        0.8,
        "repeat",
        "车道拥堵预警",
    )
    variant = json.loads(updated)["variants"]["video"]
    nodes = {node["id"]: node for node in variant["nodes"]}

    assert nodes["many"]["params"] == {"operator": ">", "value": 5.0}
    assert "slow" not in nodes
    assert "congested" not in nodes
    assert nodes["events"]["params"] == {
        "seconds": 3.0,
        "scope": "region",
        "gap_tolerance_seconds": 0.8,
        "trigger_mode": "repeat",
    }
    assert nodes["alerts"]["params"]["label"] == "车道拥堵预警"
    assert variant["configuration_slots"] == json.loads(effective)["variants"]["video"][
        "configuration_slots"
    ]


def test_event_rule_can_override_each_named_region_threshold(tmp_path):
    controller = _controller(tmp_path)
    data = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P04_highway_congestion.json"
        ).read_text(encoding="utf-8")
    )
    lanes = next(
        node for node in data["variants"]["video"]["nodes"]
        if node["id"] == "lane_regions"
    )
    lanes["params"]["regions"] = [
        {
            "id": "northbound",
            "label": "北向车道",
            "shape": "rectangle",
            "points": [[0.1, 0.1], [0.4, 0.9]],
        },
        {
            "id": "southbound",
            "label": "南向车道",
            "shape": "rectangle",
            "points": [[0.6, 0.1], [0.9, 0.9]],
        },
    ]
    effective = json.dumps(data, ensure_ascii=False)

    control = controller.read_event_rule_controls(effective, "video")[0]
    assert control["region_ids"] == ["northbound", "southbound"]
    assert control["regions"] == [
        {"id": "northbound", "label": "北向车道"},
        {"id": "southbound", "label": "南向车道"},
    ]

    updated = controller.apply_event_rule_control(
        effective,
        "video",
        "events",
        "vehicles_raw",
        ["车辆"],
        ["many"],
        [">="],
        [4],
        "all",
        1,
        0.6,
        "once",
        "高速车辆拥堵",
        region_overrides={
            "northbound": {"many": 2},
            "southbound": {"many": 6},
        },
    )
    nodes = {
        node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]
    }
    assert nodes["many"]["params"]["overrides"] == {
        "northbound": 2.0,
        "southbound": 6.0,
    }


def test_event_rule_can_override_each_named_region_operator(tmp_path):
    controller = _controller(tmp_path)
    data = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P04_highway_congestion.json"
        ).read_text(encoding="utf-8")
    )
    lanes = next(node for node in data["variants"]["video"]["nodes"] if node["id"] == "lane_regions")
    lanes["params"]["regions"] = [
        {"id": "northbound", "label": "北向", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
        {"id": "southbound", "label": "南向", "shape": "rectangle", "points": [[0.6, 0.1], [0.9, 0.9]]},
    ]

    updated = controller.apply_event_rule_control(
        json.dumps(data, ensure_ascii=False), "video", "events", "vehicles_raw",
        ["车辆"], ["many"], [">="], [4], "all", 1,
        0.6, "once", "高速车辆拥堵",
        region_operator_overrides={
            "northbound": {"many": ">"},
        },
    )
    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]}
    assert nodes["many"]["params"]["operator_overrides"] == {"northbound": ">"}


def test_region_overrides_survive_business_validate_and_apply(tmp_path):
    controller = _controller(tmp_path)
    data = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P04_highway_congestion.json"
        ).read_text(encoding="utf-8")
    )
    lanes = next(
        node for node in data["variants"]["video"]["nodes"]
        if node["id"] == "lane_regions"
    )
    lanes["params"]["regions"] = [
        {"id": "lane_1", "label": "车道1", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
        {"id": "lane_2", "label": "车道2", "shape": "rectangle", "points": [[0.4, 0.1], [0.7, 0.9]]},
    ]
    effective = json.dumps(data, ensure_ascii=False)
    document = controller.business_rule_editor.prepare(
        controller._editor_document(effective, "", source_type="preset")
    )
    updated_effective = controller.apply_event_rule_control(
        effective, "video", "events", "vehicles_raw", ["车辆"],
        ["many"], [">="], [4], "all", 1, 0.6,
        "once", "高速车辆拥堵",
        region_overrides={"lane_1": {"many": 8}, "lane_2": {"many": 5}},
        region_operator_overrides={"lane_1": {"many": ">="}, "lane_2": {"many": ">="}},
    )
    editor_json = controller.sync_editor_region_overrides(
        controller._dump(document), updated_effective, "video", ["many"]
    )
    compiled_json, package_json, _ = controller.unified_validate_apply(editor_json)
    package = SkillPackage.model_validate_json(package_json)
    many = next(node for node in package.variants["video"].nodes if node.id == "many")
    assert many.params["overrides"] == {"lane_1": 8.0, "lane_2": 5.0}
    compiled = controller._parse_editor_json(compiled_json)
    branch = next(
        item for item in compiled.skill_template.business_branches
        if item.media_type == "video"
    )
    assert len(controller.business_rule_editor.condition_rows(compiled, branch.branch_id)) >= 6


def test_wrong_way_exposes_and_persists_parameters_for_each_annotated_lane(tmp_path):
    controller = _controller(tmp_path)
    data = json.loads((
        Path(__file__).resolve().parents[1]
        / "presets_v2" / "P05_highway_wrong_way.json"
    ).read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in data["variants"]["video"]["nodes"]}
    nodes["lane_regions"]["params"]["regions"] = [
        {"id": "lane_1", "label": "车道1", "shape": "rectangle",
         "points": [[0.1, 0.1], [0.4, 0.9]]},
        {"id": "lane_2", "label": "车道2", "shape": "rectangle",
         "points": [[0.5, 0.1], [0.8, 0.9]]},
    ]
    nodes["lane_references"]["params"]["directions"] = [
        {"key": "lane_1", "label": "车道1方向", "vector": [0.0, -1.0],
         "start": [0.2, 0.8], "end": [0.2, 0.2]},
        {"key": "lane_2", "label": "车道2方向", "vector": [0.0, -1.0],
         "start": [0.6, 0.8], "end": [0.6, 0.2]},
    ]
    effective = json.dumps(data, ensure_ascii=False)
    controls = controller.read_event_rule_controls(effective, "video")

    assert controls[0]["region_ids"] == ["lane_1", "lane_2"]
    assert controls[0]["region_references"] == {
        "lane_1": "已配置参考箭头",
        "lane_2": "已配置参考箭头",
    }
    assert [item["id"] for item in controls[0]["regional_parameters"]] == [
        "opposite::threshold",
        "opposite::relation",
        "events::seconds",
        "events::gap_tolerance_seconds",
        "events::trigger_mode",
    ]

    updated, changed = controller.apply_region_parameter_override(
        effective, "video", "events", "lane_1", "opposite::threshold", -0.7
    )
    updated, changed_event = controller.apply_region_parameter_override(
        updated, "video", "events", "lane_2", "events::seconds", 3
    )
    updated_nodes = {
        node["id"]: node
        for node in json.loads(updated)["variants"]["video"]["nodes"]
    }
    assert changed == ["opposite"]
    assert changed_event == ["events"]
    assert updated_nodes["opposite"]["params"]["scope_overrides"] == {
        "lane_1": {"threshold": -0.7}
    }
    assert updated_nodes["events"]["params"]["scope_overrides"] == {
        "lane_2": {"seconds": 3.0}
    }

    document = controller.business_rule_editor.prepare(
        controller._editor_document(effective, "", source_type="preset")
    )
    editor_json = controller.sync_editor_region_overrides(
        controller._dump(document), updated, "video", ["opposite", "events"]
    )
    _, package_json, _ = controller.unified_validate_apply(editor_json)
    compiled_nodes = {
        node.id: node
        for node in SkillPackage.model_validate_json(package_json).variants["video"].nodes
    }
    assert compiled_nodes["opposite"].params["scope_overrides"]["lane_1"] == {
        "threshold": -0.7
    }
    assert compiled_nodes["events"].params["scope_overrides"]["lane_2"] == {
        "seconds": 3.0
    }


def test_imported_wrong_way_is_rendered_as_an_aligned_workflow_not_a_fake_logic_tree(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2" / "P05_highway_wrong_way.json"
    ).read_text(encoding="utf-8")
    document = controller._editor_document(effective, "", source_type="preset")
    view = controller.business_rule_view(
        controller._dump(document), "video"
    )

    assert "当前生效流程" in view["condition_tree"]
    assert "箭头表示处理先后" in view["condition_tree"]
    assert "步骤 1" in view["condition_tree"]
    assert "--rule-depth:2" not in view["condition_tree"]
    group_control = controller.business_rule_controls(
        controller._dump(document), "video"
    )[-1]
    assert group_control.choices == []
    assert group_control.interactive is False


def test_imported_congestion_shows_one_count_condition_without_speed_logic_group(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2" / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")
    document = controller._editor_document(effective, "", source_type="preset")
    editor_json = controller._dump(document)
    view = controller.business_rule_view(editor_json, "video")
    rows = controller.business_rule_editor.condition_rows(
        document, view["branch_id"]
    )

    root = next(row for row in rows if row.get("parent_id") is None)
    assert "每个区域的目标数量判断" in root["summary"]
    assert "目标速度" not in root["summary"]
    assert not any(row.get("logic") == "AND" for row in rows)

    controls = controller.business_rule_controls(editor_json, "video")
    assert controls[-2]["visible"] is False
    assert controls[-1].choices == []


def test_annotation_sync_updates_the_business_draft_resource_node(tmp_path):
    controller = _controller(tmp_path)
    base = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")
    document = controller._editor_document(base, "", source_type="preset")
    data = json.loads(base)
    lanes = next(
        node for node in data["variants"]["video"]["nodes"]
        if node["id"] == "lane_regions"
    )
    lanes["params"]["regions"] = [
        {"id": "lane_1", "label": "车道1", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]}
    ]
    package = SkillPackage.model_validate(data)

    synced = controller._sync_editor_scene_resources(document, package)

    graph = synced.skill_template.rule_graphs["video"]
    draft_lanes = next(node for node in graph.nodes if node.node_id == "lane_regions")
    assert draft_lanes.params["regions"][0]["id"] == "lane_1"
    profile = next(
        item for item in synced.scene_profiles
        if item.scene_profile_id == synced.active_scene_profile_id
    )
    assert profile.collections[0].items[0].resource_id == "lane_1"


def test_annotation_projection_refreshes_stale_run_blockers(tmp_path):
    controller = _controller(tmp_path)
    base = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")
    stale = controller._editor_document(base, "", source_type="preset")
    assert stale.validation_report["resource_blockers"]

    annotated_json, _, _ = controller.bind_annotation(
        base,
        "video",
        "lane_regions",
        "rectangle",
        json.dumps([[0.1, 0.1], [0.4, 0.9]]),
        "lane_1",
        "车道1",
    )
    refreshed = controller._editor_document(
        annotated_json, controller._dump(stale), source_type="preset"
    )

    assert refreshed.validation_report["resource_blockers"] == []
    assert refreshed.validation_report["can_run"] is True

    prepared_json = controller.prepare_run_editor_document(
        annotated_json, controller._dump(stale)
    )
    prepared = controller._parse_editor_json(prepared_json)
    assert prepared.validation_report["resource_blockers"] == []
    assert prepared.validation_report["can_run"] is True


def test_two_named_natural_language_regions_project_to_run_resources(tmp_path):
    from core.business_capabilities import build_business_capability_registry
    from core.business_rule_draft import apply_business_rule_draft
    from tests.test_business_rule_draft import _base, _image_draft

    registry, document, _ = _base(("image",))
    draft = _image_draft()
    draft["resources"] = [
        {"key": "region1", "name": "区域1", "resource_type": "region", "semantic_role": "region1", "media_types": ["image"]},
        {"key": "region2", "name": "区域2", "resource_type": "region", "semantic_role": "region2", "media_types": ["image"]},
    ]
    draft["branches"][0]["conditions"].append({
        "key": "inside1",
        "name": "区域1内",
        "capability_id": "spatial.membership",
        "parameters": {"source": "condition:people", "scope": "resource:region1"},
    })
    draft["branches"][1]["conditions"][1]["parameters"]["scope"] = "resource:region2"
    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    controller = _controller(tmp_path)
    converted_json, effective, _ = controller.unified_validate_apply(controller._dump(converted))
    converted = controller._parse_editor_json(converted_json)
    pending_editor = controller._editor_document(
        effective, controller._dump(converted), source_type="natural_language"
    )
    blocker_message = controller.run_configuration_blocker_message(pending_editor)
    assert "区域1" in blocker_message
    assert "区域2" in blocker_message
    assert "02 标注" in blocker_message
    assert "resource_region1" not in blocker_message
    for slot_id, points, label in (
        ("slot_resource_region1", [[0.05, 0.05], [0.4, 0.4]], "区域1"),
        ("slot_resource_region2", [[0.5, 0.5], [0.9, 0.9]], "区域2"),
    ):
        effective, _, _ = controller.bind_annotation(
            effective, "image", slot_id, "rectangle", json.dumps(points), slot_id, label
        )

    editor = controller._editor_document(
        effective, controller._dump(converted), source_type="natural_language"
    )
    profile = next(
        item for item in editor.scene_profiles
        if item.scene_profile_id == editor.active_scene_profile_id
    )
    assert [(item.requirement_id, item.completed) for item in profile.collections] == [
        ("resource_region1", True),
        ("resource_region2", True),
    ]
    assert editor.validation_report["resource_blockers"] == []
    assert editor.validation_report["can_run"] is True


def test_regenerating_the_same_task_reuses_saved_named_regions(tmp_path):
    """Rule regeneration must not discard scene configuration for the same task."""
    from core.business_capabilities import build_business_capability_registry
    from core.business_rule_draft import apply_business_rule_draft
    from core.configuration import configuration_status
    from core.editor_service import EditorService
    from tests.test_business_rule_draft import _base, _image_draft

    instruction = (
        "区域1有穿红色上衣、灰色裤子的人，区域2有至少2个人，"
        "则发出区域告警事件。"
    )
    registry, document, _ = _base(("image",))
    draft = _image_draft()
    draft["resources"] = [
        {"key": "region1", "name": "区域1", "resource_type": "region", "semantic_role": "region1", "media_types": ["image"]},
        {"key": "region2", "name": "区域2", "resource_type": "region", "semantic_role": "region2", "media_types": ["image"]},
    ]
    draft["branches"][0]["conditions"].append({
        "key": "inside1",
        "name": "区域1内",
        "capability_id": "spatial.membership",
        "parameters": {"source": "condition:people", "scope": "resource:region1"},
    })
    draft["branches"][1]["conditions"][1]["parameters"]["scope"] = "resource:region2"
    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    package = EditorService(registry).apply(converted).effective_skill_package
    data = package.model_dump(mode="json")
    data["skill_id"] = "two_region_alert"
    data["display_name"] = "双区域告警"
    data["original_instruction"] = instruction
    package = SkillPackage.model_validate(data)

    planner = Planner(package)
    controller = _controller(tmp_path, planner=planner)
    previous = controller._dump(package)
    for slot_id, points, label in (
        ("slot_resource_region1", [[0.05, 0.05], [0.4, 0.4]], "区域1"),
        ("slot_resource_region2", [[0.5, 0.5], [0.9, 0.9]], "区域2"),
    ):
        previous, _, _ = controller.bind_annotation(
            previous,
            "image",
            slot_id,
            "rectangle",
            json.dumps(points),
            slot_id,
            label,
        )

    _, effective, _, status, _ = controller.compile_skill(
        instruction,
        "仅图片",
        "two_region_alert",
        "双区域告警",
        previous,
    )

    rows = [
        item for item in configuration_status(SkillPackage.model_validate_json(effective))
        if item["media_type"] == "image"
    ]
    assert [(item["label"], item["configured"]) for item in rows] == [
        ("区域1", True),
        ("区域2", True),
    ]
    assert "已复用当前任务的 2 个已保存场景标注" in status


def test_scene_annotations_are_not_reused_for_a_different_instruction(tmp_path):
    controller = _controller(tmp_path)
    package = _package()
    previous_data = package.model_dump(mode="json")
    previous_data["original_instruction"] = "检测区域1内的人"
    current_data = package.model_dump(mode="json")
    current_data["original_instruction"] = "检测区域1内的车辆"

    current, reused = controller._reuse_matching_manual_annotations(
        SkillPackage.model_validate(current_data),
        controller._dump(SkillPackage.model_validate(previous_data)),
    )

    assert current.original_instruction == "检测区域1内的车辆"
    assert reused == 0


def test_branch_overview_cards_are_dynamic_click_targets():
    from ui.event_rule_editor import render_branch_overview

    html = render_branch_overview(
        [
            {
                "branch_id": "branch_a",
                "display_name": "区域1着装人员",
                "summary": "区域1内满足着装条件",
                "condition_count": 2,
                "enabled": True,
            },
            {
                "branch_id": "branch_b",
                "display_name": "区域2人数",
                "summary": "区域2人数大于2",
                "condition_count": 1,
                "enabled": True,
            },
            {
                "branch_id": "branch_c",
                "display_name": "区域3车辆",
                "summary": "区域3车辆存在",
                "condition_count": 1,
                "enabled": False,
            },
        ],
        "branch_b",
    )

    assert html.count("data-vs-branch-id=") == 3
    assert html.count("data-vs-branch-index=") == 3
    assert 'data-vs-branch-id="branch_b"' in html
    assert 'aria-pressed="true"' in html
    assert html.endswith("</section>")


def test_event_rule_can_bind_each_condition_to_a_named_region(tmp_path):
    controller = _controller(tmp_path)
    data = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "presets_v2"
            / "P04_highway_congestion.json"
        ).read_text(encoding="utf-8")
    )
    lanes = next(
        node for node in data["variants"]["video"]["nodes"]
        if node["id"] == "lane_regions"
    )
    lanes["params"]["regions"] = [
        {"id": "northbound", "label": "北向车道", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
        {"id": "southbound", "label": "南向车道", "shape": "rectangle", "points": [[0.6, 0.1], [0.9, 0.9]]},
    ]
    effective = json.dumps(data, ensure_ascii=False)

    control = controller.read_event_rule_controls(effective, "video")[0]
    assert [item["region_id"] for item in control["comparisons"]] == [None]
    assert control["comparisons"][0]["region_choices"] == [
        {"id": "northbound", "label": "北向车道"},
        {"id": "southbound", "label": "南向车道"},
    ]

    updated = controller.apply_event_rule_control(
        effective, "video", "events", "vehicles_raw", ["车辆"],
        ["many"], [">="], [4], "all", 1, 0.6,
        "once", "高速车辆拥堵", region_bindings=["northbound"],
    )
    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]}
    assert nodes["many"]["params"]["key_filter"] == "northbound"


def test_event_rule_cards_can_add_a_second_range_and_another_named_region(tmp_path):
    """A card is an executable comparison atom, rather than a UI-only row."""
    controller = _controller(tmp_path)
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json")
        .read_text(encoding="utf-8")
    )
    lanes = next(node for node in data["variants"]["video"]["nodes"] if node["id"] == "lane_regions")
    lanes["params"]["regions"] = [
        {"id": "northbound", "label": "北向", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
        {"id": "southbound", "label": "南向", "shape": "rectangle", "points": [[0.6, 0.1], [0.9, 0.9]]},
    ]

    updated = controller.apply_event_rule_cards(
        json.dumps(data, ensure_ascii=False),
        "video",
        "events",
        [
            {"template_id": "many", "region_id": "northbound", "categories": ["车辆"], "operator": ">", "value": 2},
            {"template_id": "many", "region_id": "northbound", "categories": ["车辆"], "operator": "<", "value": 5},
            {"template_id": "many", "region_id": "southbound", "categories": ["车辆"], "operator": ">", "value": 2},
        ],
        "all",
        1.0,
        0.5,
        "once",
        "区域拥堵",
    )

    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]}
    event_logic = nodes[nodes["events"]["inputs"]["condition"][1:]]
    assert event_logic["op"] == "logic.all@1.0"
    assert event_logic["params"]["combine_scope"] == "frame_any"
    comparisons = [nodes[reference[1:]] for reference in event_logic["inputs"]["conditions"]]
    assert [(item["params"]["operator"], item["params"]["value"], item["params"].get("key_filter")) for item in comparisons] == [
        (">", 2.0, "northbound"),
        ("<", 5.0, "northbound"),
        (">", 2.0, "southbound"),
    ]
    assert len({item["id"] for item in comparisons}) == 3


def test_event_cards_keep_independent_fixed_regions_on_the_same_frame(tmp_path):
    from core.semantic import SemanticNormalizer, WorkflowCompiler

    instruction = "区域1有不少于1辆车，区域2有不少于2辆车，则发出告警"
    semantic_ir = SemanticNormalizer().normalize_ledger({
        "mode": "workflow",
        "target": {"concept": "vehicle", "source_span": "车", "phrases": ["vehicle"]},
        "constraints": [
            {
                "kind": "quantity",
                "value": {"measure": "count", "operator": ">=", "value": 1,
                          "group_by": "named_region", "region_role": "region_1"},
                "source": instruction,
                "source_span": "区域1有不少于1辆车",
            },
            {
                "kind": "quantity",
                "value": {"measure": "count", "operator": ">=", "value": 2,
                          "group_by": "named_region", "region_role": "region_2"},
                "source": instruction,
                "source_span": "区域2有不少于2辆车",
            },
            {
                "kind": "region_requirement",
                "value": {"source": "manual", "cardinality": "one",
                          "semantic_role": "region_1",
                          "allowed_shapes": ["rectangle", "polygon"]},
                "source": instruction,
                "source_span": "区域1",
            },
            {
                "kind": "region_requirement",
                "value": {"source": "manual", "cardinality": "one",
                          "semantic_role": "region_2",
                          "allowed_shapes": ["rectangle", "polygon"]},
                "source": instruction,
                "source_span": "区域2",
            },
        ],
        "logic": "all",
    }, instruction)
    package = WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=instruction,
        requested_accept=["video"],
        skill_id="two_regions",
        display_name="双区域告警",
    )
    controller = _controller(tmp_path)

    updated = controller.apply_event_rule_cards(
        controller._dump(package),
        "video",
        "condition_event",
        [
            {"template_id": "constraint_1_compare", "categories": [], "operator": ">=", "value": 1},
            {"template_id": "constraint_2_compare", "categories": [], "operator": ">=", "value": 2},
        ],
        "all",
        2.0,
        1.0,
        "once",
        "双区域告警",
    )

    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]}
    assert nodes["stream_conditions"]["params"]["combine_scope"] == "frame_any"


def test_event_rule_apply_callback_maps_each_named_region_table_row(tmp_path):
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json")
        .read_text(encoding="utf-8")
    )
    lanes = next(
        node for node in data["variants"]["video"]["nodes"]
        if node["id"] == "lane_regions"
    )
    lanes["params"]["regions"] = [
        {
            "id": "northbound",
            "label": "北向车道",
            "shape": "rectangle",
            "points": [[0.1, 0.1], [0.4, 0.9]],
        },
        {
            "id": "southbound",
            "label": "南向车道",
            "shape": "rectangle",
            "points": [[0.6, 0.1], [0.9, 0.9]],
        },
    ]
    callback = next(
        item.fn for item in build_v2_app(controller).fns.values()
        if item.fn.__name__ == "_apply_event_rule"
    )

    updated = callback(
        controller._dump(controller._editor_document(json.dumps(data, ensure_ascii=False), "")),
        json.dumps(data, ensure_ascii=False), "video variant", "events", "vehicles_raw",
        ["车辆"], "region", "many", ">=", 4, None, None, None, "all", 1,
        0.6, "once", "高速车辆拥堵", [
            ["北向车道 (northbound)", 2],
            ["南向车道 (southbound)", 6],
        ],
    )

    nodes = {
        node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]
    }
    assert nodes["many"]["params"]["overrides"] == {
        "northbound": 2.0,
        "southbound": 6.0,
    }


def test_event_rule_apply_callback_maps_region_operators_and_thresholds(tmp_path):
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json")
        .read_text(encoding="utf-8")
    )
    lanes = next(node for node in data["variants"]["video"]["nodes"] if node["id"] == "lane_regions")
    lanes["params"]["regions"] = [
        {"id": "northbound", "label": "北向车道", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
        {"id": "southbound", "label": "南向车道", "shape": "rectangle", "points": [[0.6, 0.1], [0.9, 0.9]]},
    ]
    callback = next(
        item.fn for item in build_v2_app(controller).fns.values()
        if item.fn.__name__ == "_apply_event_rule"
    )

    updated = callback(
        controller._dump(controller._editor_document(json.dumps(data, ensure_ascii=False), "")),
        json.dumps(data, ensure_ascii=False), "video variant", "events", "vehicles_raw",
        ["车辆"], "region", "many", ">=", 4, None, None, None, "all", 1,
        0.6, "once", "高速车辆拥堵", [
            ["北向车道 (northbound)", ">", 2],
            ["南向车道 (southbound)", None, None, None, None],
        ],
    )
    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]}
    assert nodes["many"]["params"]["operator_overrides"] == {"northbound": ">"}
    assert nodes["many"]["params"]["overrides"] == {"northbound": 2.0}


def test_event_rule_apply_callback_maps_condition_region_choices(tmp_path):
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json")
        .read_text(encoding="utf-8")
    )
    lanes = next(node for node in data["variants"]["video"]["nodes"] if node["id"] == "lane_regions")
    lanes["params"]["regions"] = [
        {"id": "northbound", "label": "北向车道", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
        {"id": "southbound", "label": "南向车道", "shape": "rectangle", "points": [[0.6, 0.1], [0.9, 0.9]]},
    ]
    callback = next(
        item.fn for item in build_v2_app(controller).fns.values()
        if item.fn.__name__ == "_apply_event_rule"
    )

    updated = callback(
        controller._dump(controller._editor_document(json.dumps(data, ensure_ascii=False), "")),
        json.dumps(data, ensure_ascii=False), "video variant", "events", "vehicles_raw",
        ["车辆"], "region", "many@@northbound", ">=", 4,
        None, None, None, "all", 1, 0.6, "once",
        "高速车辆拥堵", [],
    )
    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]}
    assert nodes["many"]["params"]["key_filter"] == "northbound"


def test_event_rule_controls_keep_explicit_named_regions_bound_to_the_event(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")

    with pytest.raises(gr.Error, match="不能切换"):
        controller.apply_event_rule_control(
            effective,
            "video",
            "events",
            "vehicles_raw",
            ["车辆"],
            ["many"],
            [">="],
            [4],
            "all",
            1,
            0.6,
            "once",
            "高速车辆拥堵",
            scope="global",
        )


def test_event_rule_apply_refreshes_annotation_slots_after_rule_change(tmp_path):
    """Editing a regional event refreshes its still-required annotation UI."""

    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    components = {component["id"]: component for component in config["components"]}
    labels = {
        component_id: component.get("props", {}).get("label")
        for component_id, component in components.items()
    }
    apply_button_id = next(
        component_id
        for component_id, component in components.items()
        if component["type"] == "button"
        and component.get("props", {}).get("value") == "应用事件规则"
    )
    apply_dependency = next(
        dependency
        for dependency in config["dependencies"]
        if (apply_button_id, "click") in dependency["targets"]
    )

    reachable = {apply_dependency["id"]}
    changed = True
    while changed:
        changed = False
        for dependency in config["dependencies"]:
            if (
                dependency.get("trigger_after") in reachable
                and dependency["id"] not in reachable
            ):
                reachable.add(dependency["id"])
                changed = True
    refreshed_labels = {
        labels.get(component_id)
        for dependency in config["dependencies"]
        if dependency["id"] in reachable
        for component_id in dependency["outputs"]
    }

    assert "要绘制的区域/方向（技能需要几个就画几个）" in refreshed_labels
    assert "配置槽状态（当前选择已标记）" in refreshed_labels


def test_annotation_save_refreshes_event_condition_choices(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    components = {component["id"]: component for component in config["components"]}
    labels = {
        component_id: component.get("props", {}).get("label")
        for component_id, component in components.items()
    }
    bind_button_id = next(
        component_id
        for component_id, component in components.items()
        if component["type"] == "button"
        and component.get("props", {}).get("value") == "保存并继续下一项"
    )
    bind_dependency = next(
        dependency
        for dependency in config["dependencies"]
        if (bind_button_id, "click") in dependency["targets"]
    )
    reachable = {bind_dependency["id"]}
    changed = True
    while changed:
        changed = False
        for dependency in config["dependencies"]:
            if dependency.get("trigger_after") in reachable and dependency["id"] not in reachable:
                reachable.add(dependency["id"])
                changed = True

    refreshed_labels = {
        labels.get(component_id)
        for dependency in config["dependencies"]
        if dependency["id"] in reachable
        for component_id in dependency["outputs"]
    }
    assert "条件 1：区域与统计量" in refreshed_labels
    assert "条件 2：区域与统计量" in refreshed_labels
    assert any(
        dependency.get("trigger_after") == bind_dependency["id"]
        and "条件 1：区域与统计量" in {
            labels.get(component_id) for component_id in dependency["outputs"]
        }
        for dependency in config["dependencies"]
    )


def test_event_condition_dropdowns_are_user_selectable(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    condition_components = [
        component for component in config["components"]
        if component.get("props", {}).get("label") in {
            "条件 1：区域与统计量", "条件 2：区域与统计量"
        }
    ]
    assert len(condition_components) == 2
    assert all(component.get("props", {}).get("interactive") is True for component in condition_components)


def test_event_rule_editor_exposes_addable_atomic_condition_cards(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    values = [component.get("props", {}).get("value") for component in config["components"]]
    labels = [component.get("props", {}).get("label") for component in config["components"]]

    assert "添加条件" in values
    assert "条件 1：区域与统计量" in labels
    assert "条件 1：目标类别" in labels


def test_legacy_rule_reader_does_not_write_visible_condition_cards(tmp_path):
    """Legacy compatibility refreshes must not race the card-specific refresh."""
    from app_v2 import build_v2_app

    app = build_v2_app(_controller(tmp_path))
    config = app.get_config_file()
    visible_card_source_ids = {
        component["id"]
        for component in config["components"]
        if component.get("props", {}).get("label") in {
            "条件 1：区域与统计量", "条件 2：区域与统计量"
        }
    }
    legacy_reader = next(
        item for item in app.fns.values() if item.fn.__name__ == "_read_event_rule_updates"
    )

    assert visible_card_source_ids.isdisjoint({component._id for component in legacy_reader.outputs})


def test_event_condition_choices_disambiguate_duplicate_region_names(tmp_path):
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json")
        .read_text(encoding="utf-8")
    )
    lanes = next(node for node in data["variants"]["video"]["nodes"] if node["id"] == "lane_regions")
    lanes["params"]["regions"] = [
        {"id": "region_a", "label": "区域", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
        {"id": "region_b", "label": "区域", "shape": "rectangle", "points": [[0.6, 0.1], [0.9, 0.9]]},
    ]
    callback = next(
        item.fn for item in build_v2_app(controller).fns.values()
        if item.fn.__name__ == "_read_event_rule_updates"
    )

    values = callback(json.dumps(data, ensure_ascii=False), "video variant", "events")
    choices = values[4]["choices"]
    labels = [label for label, value in choices if "@@" in str(value)]
    assert labels == [
        "每个命名区域内目标数量 · 区域1：区域 (region_a)",
        "每个命名区域内目标数量 · 区域2：区域 (region_b)",
    ]
    assert (
        "每个命名区域内目标数量 · 全部手工标注区域",
        "many",
    ) in choices


def test_condition_cards_refresh_with_global_and_newly_annotated_region_choices(tmp_path):
    """Saving a region must refresh every card's real executable scope choices."""
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json")
        .read_text(encoding="utf-8")
    )
    callback = next(
        item.fn for item in build_v2_app(controller).fns.values()
        if item.fn.__name__ == "_event_card_updates"
    )
    before_annotation = callback(json.dumps(data, ensure_ascii=False), "video variant", "events")
    assert (
        "每个命名区域内目标数量 · 全部手工标注区域（请先在“02 标注”绘制）",
        "many",
    ) in before_annotation[3]["choices"]
    assert not any(
        value == "many@@__global__"
        for _, value in before_annotation[3]["choices"]
    )

    lanes = next(node for node in data["variants"]["video"]["nodes"] if node["id"] == "lane_regions")
    lanes["params"]["regions"] = [
        {"id": "region_a", "label": "入口区域", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
    ]
    values = callback(json.dumps(data, ensure_ascii=False), "video variant", "events")
    first_source_update = values[3]

    assert (
        "全画面目标数量",
        "many@@__global__",
    ) in first_source_update["choices"]
    assert (
        "每个命名区域内目标数量 · 区域1：入口区域 (region_a)",
        "many@@region_a",
    ) in first_source_update["choices"]
    assert (
        "每个命名区域内目标数量 · 全部手工标注区域",
        "many",
    ) in first_source_update["choices"]
    assert not any(
        value == "slow@@__global__"
        for _, value in first_source_update["choices"]
    )


def test_condition_cards_list_each_saved_single_region_source(tmp_path):
    """Two independent manual region slots must not collapse into one fallback source."""
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json")
        .read_text(encoding="utf-8")
    )
    variant = data["variants"]["video"]
    nodes = {node["id"]: node for node in variant["nodes"]}
    nodes["lane_regions"].update({
        "op": "region.manual@1.0",
        "params": {"shape": "polygon", "points": []},
    })
    variant["configuration_slots"] = [{
        **variant["configuration_slots"][0],
        "kind": "region",
        "label": "区域一",
        "binding": {"node_id": "lane_regions", "parameter": "points"},
    }, {
        "slot_id": "second_region",
        "kind": "region",
        "label": "区域二",
        "required": True,
        "binding": {"node_id": "second_region", "parameter": "points"},
        "allowed_shapes": ["rectangle", "polygon"],
        "minimum_items": 1,
        "source_atom_ids": ["atom_2"],
        "help_text": "在原图或视频标注帧上绘制区域二",
    }]
    variant["nodes"].extend([
        {
            "id": "second_region",
            "op": "region.manual@1.0",
            "inputs": {},
            "params": {"shape": "polygon", "points": []},
        },
        {
            "id": "second_count",
            "op": "measure.region_count@1.0",
            "inputs": {
                "objects": "$vehicles",
                "regions": "$second_region",
                "frames": "$resized",
            },
            "params": {"membership_mode": "center"},
        },
    ])
    nodes["slow"] = {
        **nodes["many"],
        "id": "slow",
        "inputs": {"left": "$second_count"},
    }
    variant["nodes"].extend([
        nodes["slow"],
        {
            "id": "congested",
            "op": "logic.all@1.0",
            "inputs": {"conditions": ["$many", "$slow"]},
            "params": {},
        },
    ])
    nodes["events"]["inputs"]["condition"] = "$congested"

    effective = json.dumps(data, ensure_ascii=False)
    effective, _, _ = controller.bind_annotation(
        effective, "video", "lane_regions", "rectangle",
        json.dumps([[0.1, 0.1], [0.4, 0.9]]), "区域一", "区域一",
    )
    effective, _, _ = controller.bind_annotation(
        effective, "video", "second_region", "polygon",
        json.dumps([[0.6, 0.1], [0.9, 0.1], [0.8, 0.9]]), "区域二", "区域二",
    )
    card_callback = next(
        item.fn for item in build_v2_app(controller).fns.values()
        if item.fn.__name__ == "_event_card_updates"
    )

    choices = card_callback(effective, "video variant", "events")[3]["choices"]

    assert choices == [
        ("每个命名区域内目标数量 · 区域一 (lane_regions)", "many"),
        ("每个命名区域内目标数量 · 区域二 (second_region)", "slow"),
    ]


def test_condition_cards_deduplicate_same_measure_and_hide_legacy_region_overrides(tmp_path):
    """One metric is selected once per card; legacy override UI must not reappear."""
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json")
        .read_text(encoding="utf-8")
    )
    nodes = {node["id"]: node for node in data["variants"]["video"]["nodes"]}
    nodes["lane_regions"]["params"]["regions"] = [
        {"id": "region_a", "label": "入口", "shape": "rectangle", "points": [[0.1, 0.1], [0.4, 0.9]]},
    ]
    # Two range checks using the same regional-count metric must not create
    # two visually identical source option groups.
    nodes["slow"] = {
        **nodes["many"],
        "id": "slow",
        "inputs": dict(nodes["many"]["inputs"]),
    }
    data["variants"]["video"]["nodes"].extend([
        nodes["slow"],
        {
            "id": "congested",
            "op": "logic.all@1.0",
            "inputs": {"conditions": ["$many", "$slow"]},
            "params": {},
        },
    ])
    nodes["events"]["inputs"]["condition"] = "$congested"
    app = build_v2_app(controller)
    card_callback = next(item.fn for item in app.fns.values() if item.fn.__name__ == "_event_card_updates")
    legacy_callback = next(item.fn for item in app.fns.values() if item.fn.__name__ == "_read_event_rule_updates")

    effective = json.dumps(data, ensure_ascii=False)
    card_values = card_callback(effective, "video variant", "events")
    choices = card_values[3]["choices"]

    assert [value for _, value in choices] == ["many@@__global__", "many@@region_a", "many"]
    assert card_values[9]["value"] == "many"
    assert legacy_callback(effective, "video variant", "events")[-1]["visible"] is False


def test_event_rule_card_global_selection_creates_a_real_full_frame_measurement(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1] / "presets_v2" / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")

    updated = controller.apply_event_rule_cards(
        effective,
        "video",
        "events",
        [{
            "template_id": "many", "region_id": "__global__",
            "categories": ["车辆"], "operator": ">=", "value": 3,
        }],
        "all", 1.0, 0.6, "once", "全画面车辆告警",
    )

    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]}
    comparison = nodes["many"]
    measurement = nodes[comparison["inputs"]["left"][1:]]
    assert measurement["op"] == "measure.count@1.0"
    assert measurement["params"] == {"scope": "frame", "group_by": "none"}
    assert "key_filter" not in comparison["params"]


def test_empty_event_rule_refresh_keeps_dataframe_output_type(tmp_path):
    from app_v2 import build_v2_app

    callback = next(
        item.fn for item in build_v2_app(_controller(tmp_path)).fns.values()
        if item.fn.__name__ == "_read_event_rule_updates"
    )
    values = callback("", "video variant", None)
    assert isinstance(values[-1], dict)
    assert values[-1].get("visible") is False


def test_annotation_callbacks_ignore_empty_skill_state(tmp_path):
    from app_v2 import build_v2_app

    functions = {
        item.fn.__name__: item.fn
        for item in build_v2_app(_controller(tmp_path)).fns.values()
        if item.fn.__name__ in {
            "_prepare_annotation", "_change_annotation_tool", "_select_annotation_slot"
        }
    }
    prepared = functions["_prepare_annotation"]("", "video", None, 0, {})
    changed = functions["_change_annotation_tool"](
        "", "video", None, None, 0, "polygon", {}
    )
    selected = functions["_select_annotation_slot"](
        "", "video", None, None, 0, {}
    )
    assert len(prepared) == 10
    assert len(changed) == 11
    assert len(selected) == 9


def test_explicit_named_region_event_keeps_annotation_slot_options(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")
    choices, value = controller.annotation_slot_options(effective, "video")

    assert choices == [("命名车道区域 · region_set · 当前待配置", "lane_regions")]
    assert value == "lane_regions"


def test_annotation_slot_reacts_only_to_user_input(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    annotation_slot_id = next(
        component["id"]
        for component in config["components"]
        if component.get("props", {}).get("label")
        == "要绘制的区域/方向（技能需要几个就画几个）"
    )
    slot_events = {
        event
        for dependency in config["dependencies"]
        for component_id, event in dependency["targets"]
        if component_id == annotation_slot_id
    }

    assert "input" in slot_events
    assert "change" not in slot_events


def test_preferred_executable_variant_uses_video_for_a_temporal_skill(tmp_path):
    controller = _controller(tmp_path)
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P06_highway_person_dwell.json"
    ).read_text(encoding="utf-8")

    assert controller.preferred_executable_variant(effective, "image") == "video"


def test_effective_change_readers_ignore_a_stale_unsupported_variant(tmp_path):
    """A new image-only package can arrive before the old video UI value updates."""
    from app_v2 import build_v2_app
    from core.semantic import WorkflowCompiler

    base = _package()
    package = WorkflowCompiler(build_default_registry()).compile(
        base.semantic_ir,
        original_instruction=base.original_instruction,
        requested_accept=["image"],
        skill_id="image_only_person",
        display_name="图片人员检测",
    )
    controller = _controller(tmp_path)
    effective = controller._dump(package)
    editor = controller._dump(
        controller._editor_document(effective, "", source_type="natural_language")
    )
    callbacks = {
        item.fn.__name__: item.fn
        for item in build_v2_app(controller).fns.values()
        if item.fn.__name__ in {"_read_execution_updates", "_read_atomic_updates"}
    }

    execution = callbacks["_read_execution_updates"](effective, "video variant")
    atomic = callbacks["_read_atomic_updates"](
        effective, editor, "video variant", "自然语言生成"
    )

    assert len(execution) == 21
    assert execution[-1] == "已读取当前 Effective 配置的真实参数。"
    assert "规则图" in atomic[1]


def test_empty_generation_output_does_not_cascade_into_json_parse_errors(tmp_path):
    controller = _controller(tmp_path)

    assert controller.preferred_executable_variant("", "image") == "image"
    with pytest.raises(ValueError, match="请先生成或加载技能"):
        controller._parse_editor_json("")


def test_natural_generation_syncs_the_executable_variant_to_the_run_control(tmp_path):
    """A video-only natural skill must not leave the run page on image."""
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    components = {component["id"]: component for component in config["components"]}
    run_variant_id = next(
        component_id
        for component_id, component in components.items()
        if component.get("props", {}).get("label") == "实际执行 variant"
    )
    compile_button_id = next(
        component_id
        for component_id, component in components.items()
        if component["type"] == "button"
        and component.get("props", {}).get("value") == "生成技能并继续"
    )
    compile_chain = {
        index
        for index, dependency in enumerate(config["dependencies"])
        if (compile_button_id, "click") in dependency.get("targets", [])
    }
    while True:
        descendants = {
            index
            for index, dependency in enumerate(config["dependencies"])
            if dependency.get("trigger_after") in compile_chain
        }
        expanded = compile_chain | descendants
        if expanded == compile_chain:
            break
        compile_chain = expanded

    assert any(
        config["dependencies"][index].get("outputs", []) == [run_variant_id]
        for index in compile_chain
    )


def test_natural_generation_refreshes_the_review_document_after_compile(tmp_path):
    """03 审核 must receive the document created by the current generation."""
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    components = {component["id"]: component for component in config["components"]}
    editor_document_id = next(
        component_id
        for component_id, component in components.items()
        if component.get("props", {}).get("label")
        == "SkillEditorDocument@3.0（当前唯一配置源）"
    )
    compile_button_id = next(
        component_id
        for component_id, component in components.items()
        if component["type"] == "button"
        and component.get("props", {}).get("value") == "生成技能并继续"
    )
    compile_chain = {
        index
        for index, dependency in enumerate(config["dependencies"])
        if (compile_button_id, "click") in dependency.get("targets", [])
    }
    while True:
        descendants = {
            index
            for index, dependency in enumerate(config["dependencies"])
            if dependency.get("trigger_after") in compile_chain
        }
        expanded = compile_chain | descendants
        if expanded == compile_chain:
            break
        compile_chain = expanded

    assert any(
        editor_document_id in config["dependencies"][index].get("outputs", [])
        for index in compile_chain
    )


def test_clear_existing_annotations_button_updates_package_and_refreshes_slots(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    components = {component["id"]: component for component in config["components"]}
    clear_button_id = next(
        component_id
        for component_id, component in components.items()
        if component["type"] == "button"
        and component.get("props", {}).get("value") == "清空已有标注"
    )
    effective_id = next(
        component_id
        for component_id, component in components.items()
        if component.get("props", {}).get("label")
        == "Effective SkillPackage（唯一执行配置，可手动修改）"
    )
    clear_dependency = next(
        dependency
        for dependency in config["dependencies"]
        if (clear_button_id, "click") in dependency.get("targets", [])
    )
    assert effective_id in clear_dependency["outputs"]

    reachable = {clear_dependency["id"]}
    changed = True
    while changed:
        changed = False
        for dependency in config["dependencies"]:
            if (
                dependency.get("trigger_after") in reachable
                and dependency["id"] not in reachable
            ):
                reachable.add(dependency["id"])
                changed = True
    labels = {
        component_id: component.get("props", {}).get("label")
        for component_id, component in components.items()
    }
    refreshed_labels = {
        labels.get(component_id)
        for dependency in config["dependencies"]
        if dependency["id"] in reachable
        for component_id in dependency.get("outputs", [])
    }
    assert "配置槽状态（当前选择已标记）" in refreshed_labels


def test_pose_only_guidance_does_not_claim_to_prove_a_fall_action(tmp_path):
    from core.schema import CanonicalSemanticIR
    from core.semantic import WorkflowCompiler

    ir = CanonicalSemanticIR.model_validate({
        "schema_version": "1.0",
        "mode": "entity_query",
        "target": {
            "concept": "person",
            "source_span": "有人摔倒",
            "phrases": ["person"],
        },
        "constraints": [{
            "atom_id": "atom_1",
            "kind": "pose",
            "value": "fallen",
            "source_span": "摔倒",
            "phrases": ["person fallen"],
            "temporal": False,
        }],
        "logic": "all",
        "unresolved": [],
        "semantic_hash": "f" * 64,
    })
    package = WorkflowCompiler(build_default_registry()).compile(
        ir,
        original_instruction="检测视频中是否有人摔倒",
        requested_accept=["video"],
        skill_id="fall_check",
        display_name="人员摔倒检查",
    )

    guidance = _controller(tmp_path).configuration_guidance_markdown(
        package.model_dump_json(), "video"
    )

    assert "倒地/躺卧可见状态" in guidance
    assert "不会推断站立或行走到倒地的动作过程" in guidance


def test_editor_variant_follows_uploaded_media_type(tmp_path):
    controller = _controller(tmp_path)

    assert controller.editor_variant_for_media("video") == "video variant"
    assert controller.editor_variant_for_media("image") == "image variant"


def test_clearing_task_media_resets_only_media_bound_ui_state(tmp_path):
    controller = _controller(tmp_path)

    state = controller.cleared_task_media_state()

    assert state[0] == ""
    assert state[1] == {}
    assert state[2] is None
    assert state[3] == {}
    assert state[5:7] == ("image", "image")
    assert state[8] == "image variant"
    assert "尚未选择" in state[7]


def test_empty_skill_has_a_safe_annotation_draft_after_media_is_cleared(tmp_path):
    """A stale slot-change event must not poison the upload control after clear."""
    controller = _controller(tmp_path)

    assert controller.annotation_selection_defaults("", "image", None) == (
        "rectangle",
        "",
        "",
        {"tool": "rectangle", "points": []},
    )


def _package() -> SkillPackage:
    from core.schema import CanonicalSemanticIR
    from core.semantic import WorkflowCompiler

    ir = CanonicalSemanticIR.model_validate(
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
            "semantic_hash": "c" * 64,
        }
    )
    return WorkflowCompiler(build_default_registry()).compile(
        ir,
        original_instruction="检测人",
        requested_accept=["image", "video"],
        skill_id="person_demo",
        display_name="人员检测",
    )


class Planner:
    def __init__(self, package):
        self.package = package
        self.calls = []

    def compile(self, instruction, **kwargs):
        self.calls.append((instruction, kwargs))
        return SimpleNamespace(
            package=self.package,
            attempts=1,
            strategy="semantic_ir+deterministic_workflow",
            errors=[],
            raw_outputs=["{}"],
        )


class OneBoxRex:
    def detect(self, image, phrases):
        return [{"phrase": phrases[0], "bbox": [0.1, 0.2, 0.5, 0.8]}]


def _controller(tmp_path: Path, *, planner=None, rex=None):
    from app_v2 import V2AppController

    return V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=planner,
        rex=rex,
    )


def test_preset_default_media_is_loaded_but_upload_replacement_is_transient(tmp_path):
    from core.preset_media import seed_builtin_preset_media

    controller = _controller(tmp_path)
    seed_builtin_preset_media(controller.preset_media_catalog, Path(__file__).resolve().parents[1])
    preset_name = "P09_no_helmet"
    initial_path, media_type, metadata, candidates, status = (
        controller.preset_default_media(preset_name, "image")
    )
    assert media_type == "image"
    assert Path(initial_path).is_file()
    assert metadata["media_type"] == "image"
    assert any(row["is_default"] for row in candidates)
    assert "默认素材" in status

    replacement = tmp_path / "replacement.png"
    Image.new("RGB", (64, 32), "green").save(replacement)
    stored_path, *_ = controller.ingest_media(str(replacement), 0.0)
    still_default, *_ = controller.preset_default_media(preset_name, "image")
    assert still_default == initial_path

    changed_path, changed_candidates, changed_status = controller.set_preset_default_media(
        preset_name, stored_path
    )
    assert changed_path == stored_path
    assert any(
        row["stored_path"] == stored_path and row["is_default"]
        for row in changed_candidates
    )
    assert "已显式设为默认" in changed_status


def test_p05_demo_default_uses_the_unpadded_road_video(tmp_path):
    """The padded acceptance clip makes lane overlays look offset and broken."""
    from core.preset_media import seed_builtin_preset_media

    controller = _controller(tmp_path)
    seed_builtin_preset_media(controller.preset_media_catalog, Path(__file__).resolve().parents[1])

    path, media_type, metadata, _, _ = controller.preset_default_media(
        "P05_highway_wrong_way", "video"
    )

    assert Path(path).is_file()
    assert media_type == "video"
    assert metadata["original_name"] == "P05.mp4"
    assert (metadata["width"], metadata["height"]) == (720, 960)


def test_p12_demo_default_keeps_the_standard_media_path(tmp_path):
    from core.preset_media import seed_builtin_preset_media

    controller = _controller(tmp_path)
    seed_builtin_preset_media(
        controller.preset_media_catalog, Path(__file__).resolve().parents[1]
    )

    path, media_type, metadata, _, _ = controller.preset_default_media(
        "P12_person_fall", "video"
    )

    assert Path(path).is_file()
    assert media_type == "video"
    assert metadata["original_name"] == "P12.mp4"


def test_p13_demo_default_uses_the_rebar_image_in_the_standard_location(tmp_path):
    from core.preset_media import seed_builtin_preset_media

    controller = _controller(tmp_path)
    seed_builtin_preset_media(
        controller.preset_media_catalog, Path(__file__).resolve().parents[1]
    )

    path, media_type, metadata, _, _ = controller.preset_default_media(
        "P13_bridge_damage", "image"
    )

    assert Path(path).is_file()
    assert media_type == "image"
    assert metadata["original_name"] == "P13.png"
    assert metadata["width"] == 2432
    assert metadata["height"] == 1728
    assert metadata["asset_id"] == (
        "458c8f88e1a867651803eaef0bf5b06f43333baf146968450b0e7cffac727736"
    )


def test_loading_a_preset_bundle_selects_supported_variant_and_its_default_media(tmp_path):
    from core.preset_media import seed_builtin_preset_media

    controller = _controller(tmp_path)
    seed_builtin_preset_media(
        controller.preset_media_catalog, Path(__file__).resolve().parents[1]
    )

    # P04 is video-only: selection must not leave the UI on the image default.
    bundle = controller.load_preset_bundle("P04_highway_congestion", 0.0)

    assert bundle[5] == "video"
    assert bundle[6] == "video"
    assert bundle[7].endswith(".mp4")
    assert bundle[10] == bundle[7]
    assert "拥堵" in bundle[11]
    assert Path(bundle[7]).is_file()
    assert "自动加载" in bundle[3]
    assert "本次将运行" in bundle[17]
    assert "01 创建技能" in bundle[17]


def test_loading_dual_media_preset_prefers_image_default_deterministically(tmp_path):
    from core.preset_media import seed_builtin_preset_media

    controller = _controller(tmp_path)
    seed_builtin_preset_media(
        controller.preset_media_catalog, Path(__file__).resolve().parents[1]
    )

    bundle = controller.load_preset_bundle("P09_no_helmet", 0.0)

    assert bundle[5] == "image"
    assert bundle[6] == "image"
    assert bundle[7].endswith(".png")


def test_annotation_overview_only_requests_scene_work_when_the_skill_declares_slots(tmp_path):
    controller = _controller(tmp_path)
    no_slot = controller._dump(_package())
    assert "无需标注" in controller.annotation_overview(no_slot, "image")

    parking = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P07_illegal_parking.json"
    ).read_text(encoding="utf-8")
    overview = controller.annotation_overview(parking, "video")
    assert "需要场景标注" in overview
    assert "禁停区域" in overview


def test_runtime_media_summary_points_to_the_single_task_media(tmp_path):
    controller = _controller(tmp_path)

    assert "尚未选择" in controller.runtime_media_summary("", "image")
    summary = controller.runtime_media_summary(
        r"C:\\demo\\camera_clip.mp4", "video"
    )
    assert "camera_clip.mp4" in summary
    assert "01 创建技能" in summary
    assert "video" in summary


def test_compile_maps_three_ui_media_choices_to_explicit_requested_accept(tmp_path):
    for choice, expected in [
        ("仅图片", ["image"]),
        ("仅视频", ["video"]),
        ("图片和视频", ["image", "video"]),
    ]:
        package = _package()
        data = package.model_dump(mode="json")
        data["input"]["requested_accept"] = expected
        data["input"]["accept"] = expected
        data["variants"] = {key: value for key, value in data["variants"].items() if key in expected}
        planner = Planner(SkillPackage.model_validate(data))
        controller = _controller(tmp_path / choice, planner=planner)

        generated, effective, semantic, status, source = controller.compile_skill(
            "检测人", choice, "my_person", "我的人员技能"
        )

        assert planner.calls[0][1]["requested_accept"] == expected
        assert planner.calls[0][1]["skill_id"] == "my_person"
        assert json.loads(generated)["input"]["requested_accept"] == expected
        assert json.loads(effective)["input"]["accept"] == expected
        assert json.loads(semantic)["target"]["concept"] == "person"
        assert "自然语言生成" in source
        assert "Semantic IR" in status


def test_media_choice_must_be_explicit_and_auto_choice_is_rejected(tmp_path):
    package = _package()
    planner = Planner(package)
    controller = _controller(tmp_path, planner=planner)

    with pytest.raises(gr.Error, match="请选择媒体能力"):
        controller.compile_skill(
            "检测人", "自动判断（推荐）", "auto_person", "自动人员检测"
        )

    assert planner.calls == []


def test_natural_business_draft_is_cached_as_the_single_03_document(tmp_path):
    package = _package()
    data = package.model_dump(mode="json")
    data["input"]["requested_accept"] = ["image"]
    data["input"]["accept"] = ["image"]
    data["variants"] = {"image": data["variants"]["image"]}
    package = SkillPackage.model_validate(data)
    planner = Planner(package)
    planner_draft = {
        "schema_version": "1.0",
        "media_requirement": "image",
        "branches": [
            {
                "key": "people",
                "name": "人员检测",
                "media_type": "image",
                "conditions": [
                    {
                        "key": "detect",
                        "name": "检测人员",
                        "capability_id": "target.detect",
                        "parameters": {
                            "targets": ["person"],
                            "phrases": "person",
                            "business_label": "人员",
                        },
                    }
                ],
            }
        ],
        "final_decision": {
            "name": "人员检测结果",
            "decision_type": "detection_summary",
            "source_refs": ["branch:people"],
        },
        "results": [
            {
                "key": "people_boxes",
                "name": "人员框",
                "source_ref": "condition:people.detect",
                "result_kind": "entities",
            },
            {
                "key": "decision",
                "name": "人员检测结果",
                "source_ref": "final:primary",
                "result_kind": "decision",
            },
        ],
    }

    def compile_with_draft(instruction, **kwargs):
        result = Planner.compile(planner, instruction, **kwargs)
        result.business_draft = planner_draft
        return result

    planner.compile = compile_with_draft
    controller = _controller(tmp_path, planner=planner)
    _, effective, _, status, _ = controller.compile_skill(
        "检测人员并输出人员框", "仅图片", "people_draft", "人员检测"
    )
    document = controller._editor_document(
        effective, "", source_type="natural_language"
    )

    assert document.skill_template.business_branches[0].display_name == "人员检测"
    assert (
        document.skill_template.business_branches[0].condition_root.capability_id
        == "target.detect"
    )
    assert document.skill_template.final_decision.display_name == "人员检测结果"
    assert controller.business_secondary_controls(
        controller._dump(document), "image"
    )[10] == 1
    assert "final_primary" in json.loads(effective)["variants"]["image"]["outputs"]
    assert "业务分支" in status


def test_natural_complex_event_draft_compiles_time_sequence_outputs_and_media(tmp_path):
    data = _package().model_dump(mode="json")
    data["input"]["requested_accept"] = ["video"]
    data["input"]["accept"] = ["video"]
    data["variants"] = {"video": data["variants"]["video"]}
    planner = Planner(SkillPackage.model_validate(data))
    planner_draft = {
        "schema_version": "1.0",
        "media_requirement": "video",
        "branches": [
            {
                "key": "congestion",
                "name": "车辆数量持续超限",
                "media_type": "video",
                "conditions": [
                    {
                        "key": "vehicles",
                        "name": "检测车辆",
                        "capability_id": "target.detect",
                        "parameters": {"targets": ["vehicle"], "phrases": "vehicle"},
                    },
                    {
                        "key": "count",
                        "name": "车辆数大于2",
                        "capability_id": "measure.count",
                        "parameters": {
                            "source": "condition:vehicles",
                            "scope": "full_frame",
                            "operator": ">",
                            "threshold": 2,
                        },
                    },
                ],
                "time": {
                    "mode": "continuous",
                    "duration_seconds": 2,
                    "identity_scope": "global",
                },
            },
            {
                "key": "accident",
                "name": "交通事故",
                "media_type": "video",
                "conditions": [
                    {
                        "key": "detect",
                        "name": "检测交通事故",
                        "capability_id": "target.detect",
                        "parameters": {
                            "targets": ["traffic_accident"],
                            "phrases": "traffic accident",
                            "business_label": "交通事故",
                        },
                    },
                    {
                        "key": "event",
                        "name": "交通事故事件",
                        "capability_id": "event.detect_or_compose",
                        "parameters": {
                            "source": "condition:detect",
                            "scope": "full_frame",
                            "method": "visible_detection",
                            "event_label": "交通事故",
                        },
                    },
                ],
            },
            {
                "key": "smoke",
                "name": "烟火爆炸持续",
                "media_type": "video",
                "conditions": [
                    {
                        "key": "detect",
                        "name": "检测烟火爆炸",
                        "capability_id": "target.detect",
                        "parameters": {
                            "targets": ["fire_smoke_explosion"],
                            "phrases": "fire smoke explosion",
                            "business_label": "烟火爆炸",
                        },
                    }
                ],
                "time": {
                    "mode": "continuous",
                    "duration_seconds": 3,
                    "identity_scope": "global",
                },
            },
        ],
        "patterns": [
            {
                "key": "accident_then_smoke",
                "name": "事故后30秒内发生烟火爆炸",
                "media_type": "video",
                "mode": "sequence",
                "branch_keys": ["accident", "smoke"],
                "window_seconds": 30,
            }
        ],
        "final_decision": {
            "name": "复杂事件告警",
            "decision_type": "timeline_summary",
            "source_refs": ["branch:congestion", "event:accident_then_smoke"],
            "combination": "AND",
        },
        "results": [
            {
                "key": "vehicle_count",
                "name": "实际车辆数量",
                "source_ref": "condition:congestion.count",
                "result_kind": "count",
                "unit": "辆",
            },
            {
                "key": "smoke_boxes",
                "name": "烟火爆炸框",
                "source_ref": "condition:smoke.detect",
                "result_kind": "entities",
                "evidence_policy": "required",
            },
            {
                "key": "timeline",
                "name": "事故后烟火时间线",
                "source_ref": "event:accident_then_smoke",
                "result_kind": "timeline",
            },
            {
                "key": "decision",
                "name": "复杂事件告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
            },
        ],
        "trigger_policy": {
            "mode": "once",
            "cooldown_seconds": 30,
            "severity": "high",
            "outputs": ["event_record", "annotated_media"],
        },
    }

    def compile_with_draft(instruction, **kwargs):
        result = Planner.compile(planner, instruction, **kwargs)
        result.business_draft = planner_draft
        return result

    planner.compile = compile_with_draft
    controller = _controller(tmp_path, planner=planner)
    _, effective, _, status, _ = controller.compile_skill(
        "车辆数持续超限，并且事故后30秒内出现持续烟火，则告警并输出数量、时间线和框",
        "仅视频",
        "complex_event_draft",
        "复杂事件告警",
    )
    package = SkillPackage.model_validate_json(effective)
    operators = {item.op for item in package.variants["video"].nodes}
    document = controller._editor_document(
        effective, "", source_type="natural_language"
    )

    assert "measure.count@1.0" in operators
    assert "temporal.qualify@1.0" in operators
    assert "temporal.sequence@2.0" in operators
    assert "output.draw@1.0" in operators
    assert "media" in package.variants["video"].outputs
    assert len(document.skill_template.event_patterns) == 1
    assert {item.display_name for item in document.skill_template.result_specs} == {
        "实际车辆数量",
        "烟火爆炸框",
        "事故后烟火时间线",
        "复杂事件告警",
    }
    assert "业务分支" in status


def test_effective_variant_can_be_extracted_edited_and_written_back(tmp_path):
    controller = _controller(tmp_path)
    package_json = controller._dump(_package())

    image_json, image_status = controller.select_variant(package_json, "image")
    video_json, video_status = controller.select_variant(package_json, "video")
    assert "可执行" in image_status
    assert "可执行" in video_status
    image = json.loads(image_json)
    video = json.loads(video_json)
    assert image["media_type"] == "image"
    assert video["media_type"] == "video"
    sample = next(node for node in video["nodes"] if node["op"] == "video.sample@1.1")
    sample["params"] = {
        "mode": "interval",
        "interval_seconds": 0.75,
        "start_seconds": 2.0,
        "end_seconds": 12.0,
        "max_frames": 20,
    }

    updated = controller.apply_variant_json(
        package_json, "video", json.dumps(video, ensure_ascii=False)
    )
    saved = json.loads(updated)["variants"]["video"]
    saved_sample = next(node for node in saved["nodes"] if node["op"] == "video.sample@1.1")
    assert saved_sample["params"]["mode"] == "interval"
    assert saved_sample["params"]["interval_seconds"] == 0.75
    assert saved_sample["params"]["end_seconds"] == 12.0
    assert controller.validate_json(updated).startswith("✅")


def test_preprocess_controls_mutate_real_variant_nodes_and_keep_dedup_explicit(tmp_path):
    controller = _controller(tmp_path)
    updated = controller.apply_preprocessing(
        controller._dump(_package()),
        "image",
        "contain",
        1280,
        640,
        640,
        True,
        320,
        256,
        0.25,
        0.10,
        True,
        "iou",
        0.65,
        "bicubic",
    )
    variant = json.loads(updated)["variants"]["image"]
    resize = next(node for node in variant["nodes"] if node["op"] == "image.resize@1.1")
    tile = next(node for node in variant["nodes"] if node["op"] == "image.tile@1.1")
    dedup_nodes = [node for node in variant["nodes"] if node["op"] == "objects.deduplicate@1.0"]
    assert resize["params"] == {
        "mode": "contain",
        "long_side": 1280,
        "width": 640,
        "height": 640,
        "interpolation": "bicubic",
    }
    assert tile["params"] == {
        "tile_width": 320,
        "tile_height": 256,
        "overlap_x": 0.25,
        "overlap_y": 0.10,
        "include_full_frame": True,
    }
    assert all(
        node["params"] == {
            "metric": "iou",
            "threshold": 0.65,
            "keep": "best_localization",
        }
        for node in dedup_nodes
    )
    assert controller.validate_json(updated).startswith("✅")


def test_preprocess_controls_accept_empty_hidden_numbers_and_use_safe_defaults(tmp_path):
    controller = _controller(tmp_path)
    updated = controller.apply_preprocessing(
        controller._dump(_package()),
        "image",
        "long_side",
        1280,
        None,
        None,
        True,
        None,
        None,
        None,
        None,
        True,
        "ios",
        None,
        "bilinear",
    )
    variant = json.loads(updated)["variants"]["image"]
    resize = next(node for node in variant["nodes"] if node["op"] == "image.resize@1.1")
    tile = next(node for node in variant["nodes"] if node["op"] == "image.tile@1.1")
    assert resize["params"]["width"] == 1280
    assert resize["params"]["height"] == 720
    assert tile["params"] == {
        "tile_width": 640,
        "tile_height": 640,
        "overlap_x": 0.2,
        "overlap_y": 0.2,
        "include_full_frame": True,
    }
    assert controller.validate_json(updated).startswith("✅")


def test_preprocess_controls_can_disable_and_reenable_a_preset_named_tile(tmp_path):
    controller = _controller(tmp_path)
    package = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P04_highway_congestion.json"
    ).read_text(encoding="utf-8")
    controls = controller.read_execution_controls(package, "video")
    assert controls["tile_enabled"] is True
    assert controls["tile_width"] == 512

    disabled = controller.apply_preprocessing(
        package, "video", "long_side", 1280, 1280, 720, False,
        512, 512, 0.25, 0.25, True, "ios", 0.7, "bilinear",
    )
    disabled_variant = json.loads(disabled)["variants"]["video"]
    assert not [
        node for node in disabled_variant["nodes"]
        if node["op"].startswith("image.tile@")
    ]
    ground = next(
        node for node in disabled_variant["nodes"]
        if node["id"] == "vehicles_raw"
    )
    assert ground["inputs"]["frames"] == "$resized"

    enabled = controller.apply_preprocessing(
        disabled, "video", "long_side", 1280, 1280, 720, True,
        448, 448, 0.2, 0.2, True, "ios", 0.7, "bilinear",
    )
    enabled_variant = json.loads(enabled)["variants"]["video"]
    tile = next(
        node for node in enabled_variant["nodes"]
        if node["op"].startswith("image.tile@")
    )
    ground = next(
        node for node in enabled_variant["nodes"]
        if node["id"] == "vehicles_raw"
    )
    assert tile["params"]["tile_width"] == 448
    assert ground["inputs"]["frames"] == f"${tile['id']}"


def test_p11_projects_generic_detection_and_count_controls(tmp_path):
    controller = _controller(tmp_path)
    package = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P11_service_area_garbage.json"
    ).read_text(encoding="utf-8")

    execution = controller.read_execution_controls(package, "image")
    confirmation = controller.context_confirmation_control_values(
        package, "image variant"
    )

    assert execution["tile_enabled"] is False
    assert confirmation["enabled"] is False
    assert set(confirmation["labels"]) == {
        "垃圾容器", "溢出垃圾", "垃圾堆", "散落垃圾"
    }
    assert "整齐包装货物" not in confirmation["labels"]


def test_context_confirmation_projection_can_be_enabled_for_generic_labels(tmp_path):
    controller = _controller(tmp_path)
    package = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P11_service_area_garbage.json"
    ).read_text(encoding="utf-8")
    values = controller.context_confirmation_control_values(package, "image variant")
    assert values["enabled"] is False
    assert set(values["labels"]) == {
        "垃圾容器", "溢出垃圾", "垃圾堆", "散落垃圾"
    }


def test_effective_change_auto_projects_execution_and_confirmation_controls(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    effective_id = next(
        item["id"] for item in config["components"]
        if item.get("props", {}).get("label") == "Effective SkillPackage（唯一执行配置，可手动修改）"
    )
    tile_enabled_id = next(
        item["id"] for item in config["components"]
        if item.get("props", {}).get("label") == "启用切片增强（小目标场景打开）"
    )
    context_enabled_id = next(
        item["id"] for item in config["components"]
        if item.get("props", {}).get("label") == "启用候选框二次可见性确认"
    )
    change_dependencies = [
        item for item in config["dependencies"]
        if any(trigger[0] == effective_id and trigger[1] == "change" for trigger in item.get("targets", []))
    ]

    projected_outputs = {
        output
        for item in change_dependencies
        for output in item.get("outputs", [])
    }
    assert tile_enabled_id in projected_outputs
    assert context_enabled_id in projected_outputs


def test_tile_deduplication_help_is_available_on_demand(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    labels = {
        item.get("props", {}).get("label")
        for item in config["components"]
    }
    assert "查看：实例级融合、IoS、IoU 有什么区别" in labels


def test_identity_and_original_fps_are_explicit_execution_controls(tmp_path):
    controller = _controller(tmp_path)
    original = controller._dump(_package())

    identity_json = controller.apply_preprocessing(
        original,
        "image",
        "identity",
        1280,
        1280,
        720,
        False,
        640,
        640,
        0.2,
        0.2,
        True,
        "ios",
        0.5,
        "bilinear",
    )
    identity_package = json.loads(identity_json)
    resize = next(
        node
        for node in identity_package["variants"]["image"]["nodes"]
        if node["op"] == "image.resize@1.1"
    )
    assert resize["params"]["mode"] == "identity"
    assert identity_package["semantic_ir"] == json.loads(original)["semantic_ir"]

    source_fps_json = controller.apply_video_sampling(
        original,
        "original_fps",
        2.0,
        1.0,
        9,
        0.0,
        None,
        None,
    )
    source_fps_package = json.loads(source_fps_json)
    sample = next(
        node
        for node in source_fps_package["variants"]["video"]["nodes"]
        if node["op"] == "video.sample@1.1"
    )
    assert sample["params"]["mode"] == "frame_step"
    assert sample["params"]["frame_step"] == 1
    assert source_fps_package["semantic_ir"] == json.loads(original)["semantic_ir"]


def test_zero_max_frames_means_unlimited_in_video_sampling(tmp_path):
    controller = _controller(tmp_path)

    updated = controller.apply_video_sampling(
        controller._dump(_package()),
        "fps",
        2.0,
        1.0,
        1,
        0.0,
        None,
        0,
    )

    sample = next(
        node
        for node in json.loads(updated)["variants"]["video"]["nodes"]
        if node["op"] == "video.sample@1.1"
    )
    assert sample["params"]["max_frames"] is None


def test_zero_end_seconds_means_unlimited_in_video_sampling(tmp_path):
    controller = _controller(tmp_path)

    updated = controller.apply_video_sampling(
        controller._dump(_package()),
        "fps",
        2.0,
        1.0,
        1,
        0.0,
        0.0,
        None,
    )

    sample = next(
        node
        for node in json.loads(updated)["variants"]["video"]["nodes"]
        if node["op"] == "video.sample@1.1"
    )
    assert sample["params"]["end_seconds"] is None
    assert controller.read_execution_controls(updated, "video")["end_seconds"] is None


def test_execution_controls_round_trip_from_effective_variant_without_touching_semantics(tmp_path):
    controller = _controller(tmp_path)
    original = controller._dump(_package())
    updated = controller.apply_preprocessing(
        original,
        "video",
        "contain",
        1536,
        960,
        540,
        True,
        480,
        320,
        0.25,
        0.15,
        True,
        "iou",
        0.6,
        "bicubic",
    )
    updated = controller.apply_video_sampling(
        updated,
        "original_fps",
        2.0,
        1.0,
        7,
        1.5,
        12.0,
        50,
    )

    controls = controller.read_execution_controls(updated, "video")

    assert controls == {
        "resize_mode": "contain",
        "long_side": 1536,
        "width": 960,
        "height": 540,
        "interpolation": "bicubic",
        "tile_enabled": True,
        "tile_width": 480,
        "tile_height": 320,
        "overlap_x": 0.25,
        "overlap_y": 0.15,
        "include_full_frame": True,
        "dedup_metric": "iou",
        "dedup_threshold": 0.6,
        "sample_mode": "original_fps",
        "fps": 2.0,
        "interval_seconds": 1.0,
        "frame_step": 1,
        "start_seconds": 1.5,
        "end_seconds": 12.0,
        "max_frames": 50,
    }
    assert json.loads(updated)["semantic_ir"] == json.loads(original)["semantic_ir"]


def test_review_control_reads_return_no_values_before_a_skill_is_available(tmp_path):
    """The review form must remain usable before generation or loading finishes."""
    controller = _controller(tmp_path)

    assert controller.read_execution_controls("", "image") is None
    assert controller.context_confirmation_control_values("", "image variant") is None


def test_execution_read_callback_keeps_video_only_fields_unchanged_for_image_variants(tmp_path):
    """Reading image resize controls must not require video sampling parameters."""
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    demo = build_v2_app(controller)
    callback = next(
        item.fn for item in demo.fns.values()
        if item.fn.__name__ == "_read_execution_updates"
    )
    effective = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P01_fire_smoke.json"
    ).read_text(encoding="utf-8")

    values = callback(effective, "image variant")

    assert len(values) == 21
    assert values[:5] == ("identity", 1280, None, None, "bilinear")


def test_preprocess_switch_rewires_only_primary_grounding_branch(tmp_path):
    controller = _controller(tmp_path)
    data = json.loads(controller._dump(_package()))
    variant = data["variants"]["image"]
    draw_index = next(
        index for index, node in enumerate(variant["nodes"])
        if node["op"] == "output.draw@1.0"
    )
    variant["nodes"][draw_index:draw_index] = [
        {
            "id": "evidence_raw",
            "op": "rex.ground@1.1",
            "inputs": {"frames": "$resized"},
            "params": {
                "targets": [{"label": "证据", "phrases": ["visible evidence"]}]
            },
            "enabled": True,
        },
        {
            "id": "evidence",
            "op": "objects.deduplicate@1.0",
            "inputs": {"objects": "$evidence_raw"},
            "params": {"metric": "ios", "threshold": 0.5, "keep": "first"},
            "enabled": True,
        },
    ]
    variant["outputs"]["evidence"] = "$evidence"
    original = json.dumps(data, ensure_ascii=False)

    updated = controller.apply_preprocessing(
        original,
        "image",
        "identity",
        1280,
        1280,
        720,
        True,
        640,
        640,
        0.2,
        0.2,
        True,
        "ios",
        0.5,
        "bilinear",
    )
    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["image"]["nodes"]}

    assert nodes["candidates_raw"]["inputs"]["frames"] == "$preprocess_tiles"
    assert nodes["evidence_raw"]["inputs"]["frames"] == "$resized"


def test_output_media_configuration_mutates_only_draw_execution_params(tmp_path):
    controller = _controller(tmp_path)
    original = controller._dump(_package())

    updated = controller.apply_output_configuration(
        original,
        "video",
        "fixed",
        960,
        540,
        "fixed",
        12.5,
    )

    data = json.loads(updated)
    draw = next(
        node
        for node in data["variants"]["video"]["nodes"]
        if node["op"] == "output.draw@1.0"
    )
    assert draw["params"]["output_size_mode"] == "fixed"
    assert draw["params"]["output_width"] == 960
    assert draw["params"]["output_height"] == 540
    assert draw["params"]["output_fps_mode"] == "fixed"
    assert draw["params"]["output_fps"] == 12.5
    assert data["semantic_ir"] == json.loads(original)["semantic_ir"]
    assert controller.validate_json(updated).startswith("✅")


def test_annotated_video_uses_a_browser_playable_codec(tmp_path):
    from operators.output import _write_browser_playable_video

    output = tmp_path / "annotated.mp4"
    _write_browser_playable_video(
        output,
        [Image.new("RGB", (64, 48), "red"), Image.new("RGB", (64, 48), "blue")],
        2.0,
        (64, 48),
    )

    data = output.read_bytes()
    assert b"avc1" in data
    assert b"mp4v" not in data


def test_media_inspection_and_run_return_task_target_tables_and_trace(tmp_path):
    controller = _controller(tmp_path, rex=OneBoxRex())
    package_json = controller._dump(_package())
    media = tmp_path / "person.jpg"
    Image.new("RGB", (80, 40), "white").save(media)

    policy_text, policy = controller.inspect_media(package_json, "image", str(media))
    assert "预计 Rex 调用 1 次" in policy_text
    assert policy["sampled_frame_count"] == 1
    result = controller.run_skill(package_json, package_json, "image", str(media))

    (
        annotated_image,
        annotated_video,
        detections,
        tracks,
        events,
        measurements,
        regions,
        directions,
        constraints,
        trace,
        run_dir,
        status,
    ) = result
    assert Path(annotated_image).is_file()
    assert annotated_video is None
    assert detections["status"] == "适用 · 本次 1 条"
    assert len(detections["items"]) == 1
    assert tracks["status"].startswith("不适用")
    assert events["status"].startswith("不适用")
    assert measurements["status"].startswith("不适用")
    assert regions["status"].startswith("不适用")
    assert directions["status"].startswith("不适用")
    assert constraints["status"] == "适用 · 本次 0 条"
    assert trace["items"]
    assert Path(run_dir, "result.json").is_file()
    assert Path(run_dir, "result_contract.json").is_file()
    assert "检测人" in status
    assert "image" in status
    assert "运行完成" in status


def test_media_inspection_uses_actual_media_type_when_ui_variant_is_stale(tmp_path):
    controller = _controller(tmp_path)
    media = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "acceptance_media"
        / "v2"
        / "摔倒.mp4"
    )

    policy_text, policy = controller.inspect_media(
        controller._dump(_package()), "image", str(media)
    )

    assert policy["media_type"] == "video"
    assert "抽样" in policy_text


def test_run_uses_actual_media_type_when_ui_variant_is_stale(tmp_path):
    controller = _controller(tmp_path, rex=OneBoxRex())
    package_json = controller._dump(_package())
    media = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "acceptance_media"
        / "v2"
        / "摔倒.mp4"
    )

    result = controller.run_skill(package_json, package_json, "image", str(media))

    assert result[0] is None
    assert Path(result[1]).is_file()
    assert "variant：video" in result[-1]


def test_result_contract_distinguishes_not_applicable_from_empty_result(tmp_path):
    controller = _controller(tmp_path)
    contract = controller.result_contract(controller._dump(_package()), "image")

    assert contract["detections"]["applicable"] is True
    assert contract["tracks"]["applicable"] is False
    assert contract["events"]["applicable"] is False
    assert contract["measurements"]["applicable"] is False
    assert contract["regions"]["applicable"] is False
    assert contract["directions"]["applicable"] is False
    assert contract["constraints"]["applicable"] is True
    assert contract["trace"]["applicable"] is True

    rendered = controller.format_result_sections(
        contract,
        {
            "detections": [],
            "tracks": [],
            "events": [],
            "measurements": [],
            "regions": [],
            "directions": [],
            "constraints": [],
            "trace": [],
        },
    )
    assert rendered["detections"]["status"] == "适用 · 本次 0 条"
    assert rendered["tracks"]["status"].startswith("不适用")


def test_track_outputs_are_also_exposed_as_per_frame_detection_boxes(tmp_path):
    controller = _controller(tmp_path)
    preset = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P12_person_fall.json"
    ).read_text(encoding="utf-8")
    contract = controller.result_contract(preset, "video")
    sample = {
        "id": "frame_24_person_1",
        "bbox": [0.1, 0.2, 0.5, 0.8],
        "frame_index": 24,
        "timestamp": 1.0,
        "track_id": "track_1",
    }

    rendered = controller.format_result_sections(
        contract,
        {
            "detections": [],
            "tracks": [{"id": "track_1", "history": [sample]}],
            "events": [],
        },
    )

    assert contract["detections"]["applicable"] is True
    assert rendered["detections"]["status"] == "适用 · 本次 1 条"
    assert rendered["detections"]["items"] == [sample]


def test_event_result_includes_diagnostic_when_declared_event_does_not_trigger(tmp_path):
    controller = _controller(tmp_path)
    rendered = controller.format_result_sections(
        {"events": {"applicable": True, "reason": "工作流声明了事件输出"}},
        {
            "events": [],
            "event_diagnostics": [{
                "event_id": "congestion_event",
                "label": "区域拥堵",
                "reason": "条件在 241 个采样点中从未成立",
                "matched_samples": 0,
                "sample_count": 241,
            }],
        },
    )

    assert rendered["events"]["status"] == "适用 · 本次 0 条"
    assert rendered["events"]["diagnostics"] == [{
        "event_id": "congestion_event",
        "label": "区域拥堵",
        "reason": "条件在 241 个采样点中从未成立",
        "matched_samples": 0,
        "sample_count": 241,
    }]


def test_result_contract_resolves_filtered_entity_sets_as_object_results(tmp_path):
    controller = _controller(tmp_path)
    preset = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P11_service_area_garbage.json"
    ).read_text(encoding="utf-8")

    contract = controller.result_contract(preset, "image")

    assert contract["detections"]["applicable"] is True
    assert contract["tracks"]["applicable"] is False


def test_service_area_garbage_result_contract_includes_detection_and_count(tmp_path):
    controller = _controller(tmp_path)
    preset = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P11_service_area_garbage.json"
    ).read_text(encoding="utf-8")

    contract = controller.result_contract(preset, "image")

    assert contract["detections"]["applicable"] is True
    assert contract["measurements"]["applicable"] is True


def test_event_rule_change_does_not_rewrite_its_own_dropdown(tmp_path):
    """Changing the selected event must not race with preset/variant refreshes."""

    from app_v2 import build_v2_app

    demo = build_v2_app(_controller(tmp_path))
    config = demo.get_config_file()
    labels = {
        component["id"]: component.get("props", {}).get("label")
        for component in config["components"]
    }

    event_rule_input = next(
        dependency
        for dependency in config["dependencies"]
        if any(
            event == "input" and labels.get(component_id) == "要编辑的事件规则"
            for component_id, event in dependency.get("targets", [])
        )
    )
    output_labels = [labels.get(component_id) for component_id in event_rule_input["outputs"]]

    assert "要编辑的事件规则" not in output_labels
    assert not any(
        event == "change" and labels.get(component_id) == "要编辑的事件规则"
        for dependency in config["dependencies"]
        for component_id, event in dependency.get("targets", [])
    )

    variant_change = next(
        dependency
        for dependency in config["dependencies"]
        if any(
            event == "change"
            and labels.get(component_id) == "当前编辑的执行流程（variant）"
            for component_id, event in dependency.get("targets", [])
        )
        and "要编辑的事件规则"
        in [labels.get(component_id) for component_id in dependency["outputs"]]
    )
    input_labels = [labels.get(component_id) for component_id in variant_change["inputs"]]

    assert "要编辑的事件规则" not in input_labels


def test_event_rule_editor_is_the_single_duration_configuration_surface(tmp_path):
    from app_v2 import build_v2_app

    config = json.dumps(build_v2_app(_controller(tmp_path)).get_config_file(), ensure_ascii=False)

    assert config.count("事件规则编辑") == 1
    assert "持续时间（秒）" in config
    assert "允许中断（秒）" in config
    assert "触发方式" in config
    assert "事件持续时间阈值 ｜" not in config
    assert "持续事件规则" not in config


def test_v2_app_exposes_media_variants_semantics_preprocessing_and_results(tmp_path):
    from app_v2 import build_v2_app

    demo = build_v2_app(_controller(tmp_path))
    assert isinstance(demo, gr.Blocks)
    config = json.dumps(demo.get_config_file(), ensure_ascii=False)
    assert "自动判断（推荐）" not in config
    assert "最终结果类型" not in config
    for label in [
        "按五步完成一次视觉任务",
        "01 创建技能",
        "02 标注场景",
        "03 审核配置",
        "04 运行与结果",
        "05 技能资产",
        "生成后如需区域或方向，先进入“02 标注”",
        "高级审计与手动编辑",
            "执行当前技能并查看结果",
            "01 创建",
        "确认并调优",
        "运行与结果",
            "05 资产",
        "仅图片",
        "仅视频",
        "图片和视频",
        "Semantic IR",
        "未解析条件",
        "image variant",
        "video variant",
        "图像缩放 resize",
        "identity",
        "保持原始 FPS",
            "手工区域 / 方向",
        "原始媒体元数据",
        "矩形",
        "多边形",
        "方向箭头",
        "数值结果",
        "区域结果",
        "方向结果",
        "结果媒体尺寸",
        "结果视频 FPS",
        "视频抽帧",
        "事件规则编辑",
        "要编辑的事件规则",
        "条件设置",
        "统计范围",
        "条件 1：区域与统计量",
        "条件 1：目标类别",
        "添加条件",
        "条件关系",
        "告警名称",
        "应用事件规则",
        "切片增强",
        "候选框二次可见性确认",
        "待复核检测类别",
        "确认可见证据提示词",
        "上下文边距比例",
        "复核裁剪长边",
        "保留全图",
        "IoS",
        "IoU",
        "调用估算",
        "任务目标",
        "检测结果",
        "轨迹结果",
        "事件结果",
        "语义原子解释",
        "逐节点 Trace",
        "当前任务媒体（图片或视频）",
        "此技能无需标注场景，可直接去“04 运行与结果”",
    ]:
        assert label in config
    assert "保存并继续下一项" in config
    assert "点击结果媒体可查看原尺寸" in config
    assert "规则要求一个或多个命名区域" in config
    assert "上传图片或视频（保留原始字节）" not in config
    assert "不会自动生成左右车道" not in config


def test_v2_app_refreshes_atomic_guidance_for_every_skill_source(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    components = {component["id"]: component for component in config["components"]}
    guidance_id = next(
        component_id
        for component_id, component in components.items()
        if component["type"] == "markdown"
        and "识别出的原子能力" in component.get("props", {}).get("value", "")
    )
    button_values = {
        component.get("props", {}).get("value")
        for component in components.values()
        if component["type"] == "button"
    }
    assert {"生成技能并继续", "加载预置", "加载保存版本", "加载选中版本"} <= button_values

    guidance_dependencies = [
        dependency for dependency in config["dependencies"]
        if guidance_id in dependency["outputs"]
    ]
    assert len(guidance_dependencies) >= 4


def test_task_media_uses_upload_event_for_post_upload_ingestion(tmp_path):
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    components = {component["id"]: component for component in config["components"]}
    media_id = next(
        component_id
        for component_id, component in components.items()
        if component["type"] == "file"
        and component.get("props", {}).get("label") == "当前任务媒体（图片或视频）"
    )
    media_events = {
        event
        for dependency in config["dependencies"]
        for component_id, event in dependency.get("targets", [])
        if component_id == media_id
    }

    assert "upload" in media_events
    assert "change" not in media_events


def test_canvas_and_context_buttons_keep_their_own_callback_inputs(tmp_path):
    """Prevent config JSON from being routed through Gradio's FileData parser."""
    from app_v2 import build_v2_app

    config = build_v2_app(_controller(tmp_path)).get_config_file()
    components = {component["id"]: component for component in config["components"]}

    def button_id(value):
        return next(
            component_id
            for component_id, component in components.items()
            if component["type"] == "button"
            and component.get("props", {}).get("value") == value
        )

    def dependency_for(value):
        target = button_id(value)
        return next(
            dependency
            for dependency in config["dependencies"]
            if any(
                component_id == target and event == "click"
                for component_id, event in dependency.get("targets", [])
            )
        )

    canvas = dependency_for("加载画布")
    context_read = dependency_for("读取当前确认配置")
    context_apply = dependency_for("应用二次确认配置")

    assert canvas["api_name"] == "_prepare_annotation"
    assert components[canvas["inputs"][0]]["type"] != "file"
    assert context_read["api_name"] == "_read_context_confirmation"
    assert context_apply["api_name"] == "apply_context_confirmation_control"


def test_v2_app_exposes_actual_skill_asset_save_load_and_delete_controls(tmp_path):
    from app_v2 import build_v2_app

    app_config = build_v2_app(_controller(tmp_path)).get_config_file()
    config = json.dumps(app_config, ensure_ascii=False)

    for label in [
        "保存为独立版本",
        "资产保存技能标识",
        "资产保存显示名称",
        "资产保存目录（可修改）",
        "本次保存结果",
        "已保存版本",
        "加载选中版本",
        "删除选中版本",
    ]:
        assert label in config

    components = {item["id"]: item for item in app_config["components"]}
    save_root_id = next(
        component_id
        for component_id, component in components.items()
        if component.get("props", {}).get("label") == "资产保存目录（可修改）"
    )
    save_button_id = next(
        component_id
        for component_id, component in components.items()
        if component["type"] == "button"
        and component.get("props", {}).get("value") == "保存为独立版本"
    )
    save_dependency = next(
        item
        for item in app_config["dependencies"]
        if any(
            component_id == save_button_id and event == "click"
            for component_id, event in item.get("targets", [])
        )
    )
    assert components[save_root_id]["props"]["interactive"] is True
    assert save_root_id in save_dependency["inputs"]


def test_natural_language_skill_bundle_saves_to_editable_asset_root(tmp_path):
    controller = _controller(tmp_path)
    effective = controller._dump(_package())
    document = controller._editor_document(
        effective, "", source_type="natural_language"
    )
    custom_root = tmp_path / "用户选择的资产目录"

    result = controller.save_skill_bundle(
        effective,
        controller._dump(document),
        "saved_natural_skill",
        "自然语言技能",
        str(custom_root),
    )

    package_path = custom_root / "generated_packages" / "saved_natural_skill" / "1.json"
    document_path = custom_root / "skill_documents" / "saved_natural_skill" / "1.json"
    assert package_path.is_file()
    assert document_path.is_file()
    assert str(package_path) in result
    assert str(document_path) in result
    assert controller.saved_skill_choices(str(custom_root)) == [
        "saved_natural_skill/v1"
    ]
    _, loaded, _, status, source = controller.load_saved_skill(
        "saved_natural_skill/v1", str(custom_root)
    )
    assert SkillPackage.model_validate_json(loaded).display_name == "自然语言技能"
    assert "已加载 saved_natural_skill/v1" in status
    assert "已保存技能" in source
