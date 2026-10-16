"""Time editing has an explicit owner, conditional fields and no hidden stacking."""

from pathlib import Path

import gradio as gr
import pytest
from test_business_rule_compiler import _condition, _document
from test_generic_editor_ui import _controller

from core.editor_schema import BusinessBranch, ConditionExpression
from core.editor_service import EditorService
from core.legacy_importer import import_skill_package
from core.schema import SkillPackage
from ui.v2.controllers.time_configuration import time_field_updates


def _timed_document():
    registry, editor, document = _document("video")
    document.skill_template.business_branches = [
        BusinessBranch(branch_id="b", display_name="条件分支", media_type="video")
    ]
    document, detected = _condition(
        editor,
        document,
        "b",
        "target.detect",
        "检测目标",
        {"targets": ["car"], "phrases": "car", "business_label": "车辆"},
    )
    document.skill_template.business_branches[0].condition_root = ConditionExpression(
        expression_id="detected_condition",
        operator="NOT",
        display_name="目标未出现",
        capability_id="logic.group",
        children=[document.skill_template.business_branches[0].condition_root],
    )
    detected = "detected_condition"
    document, timer = _condition(
        editor,
        document,
        "b",
        "temporal.persist",
        "目标持续出现",
        {
            "source": f"condition:{detected}",
            "mode": "continuous",
            "duration": 5,
            "identity_scope": "global",
            "allowed_gap": 0,
        },
    )
    document = editor.set_final_decision(
        document, "时间判断", "event_decision", "branch:b"
    )
    return registry, editor, document, timer


def _save(controller, document, target, **overrides):
    values = {
        "editor_json": controller._dump(document),
        "branch_id": "b",
        "target": target,
        "mode": "continuous",
        "duration": 3,
        "window": None,
        "ratio": 100,
        "gap": 0,
        "identity": "global",
        "emission": "first",
        "validity": "current_frame",
        "hold": None,
        "confirm_layering": False,
    }
    values.update(overrides)
    return controller.save_time_configuration(**values)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("immediate", [False, False, False, False, False, False, True, False]),
        ("continuous", [True, False, False, True, True, True, False, False]),
        ("cumulative", [True, True, False, False, True, True, False, False]),
        ("ratio", [False, True, True, False, True, True, False, False]),
    ],
)
def test_only_consumed_fields_are_visible(mode, expected):
    assert [
        u["visible"] for u in time_field_updates(mode, "current_frame", "branch:b")
    ] == expected
    condition = time_field_updates(mode, "hold_for", "timer")
    assert not any(condition[i]["visible"] for i in (5, 6, 7))


def test_hold_field_requires_immediate_branch_and_hold_choice():
    assert time_field_updates("immediate", "hold_for", "branch:b")[-1]["visible"]
    assert not time_field_updates("continuous", "hold_for", "branch:b")[-1]["visible"]


def test_existing_condition_is_the_default_target_and_edits_in_place(tmp_path):
    c = _controller(tmp_path)
    _, _, d, timer = _timed_document()
    selection, inventory = c.time_configuration_targets(c._dump(d), "b", None)
    assert selection["value"] == timer
    assert "5 秒" in inventory
    controls = c.time_configuration_controls(c._dump(d), "b", timer)
    assert controls[1]["value"] == 5
    after, status = _save(c, d, timer)
    updated = c._parse_editor_json(after)
    branch = updated.skill_template.business_branches[0]
    rows = c.business_rule_editor.parameter_rows(updated, "b", timer)
    assert next(r["value"] for r in rows if r["parameter_id"] == "duration") == 3
    assert not branch.temporal_qualifiers
    assert "草稿" in status
    assert updated.effective_skill_package is None


def test_branch_timer_requires_explicit_confirmation_of_layering(tmp_path):
    c = _controller(tmp_path)
    _, _, d, _ = _timed_document()
    original = c._dump(d)
    with pytest.raises(gr.Error, match="已有计时条件"):
        _save(c, d, "branch:b")
    assert c._dump(d) == original
    after, _ = _save(c, d, "branch:b", confirm_layering=True)
    after, _ = _save(
        c, c._parse_editor_json(after), "branch:b", duration=4, confirm_layering=True
    )
    branch = c._parse_editor_json(after).skill_template.business_branches[0]
    assert len(branch.temporal_qualifiers) == 1
    assert branch.temporal_qualifiers[0].duration_seconds.value == 4
    assert branch.validity_policy.mode == "event_interval"


@pytest.mark.parametrize(
    "mode,changes,error",
    [
        ("continuous", {"duration": 0}, "大于 0"),
        ("continuous", {"duration": float("nan")}, "大于 0"),
        ("cumulative", {"window": None}, "大于 0"),
        ("cumulative", {"duration": 4, "window": 2}, "不能超过"),
        ("ratio", {"window": 5, "ratio": 101}, "100%"),
        ("continuous", {"gap": -1}, "不能小于"),
    ],
)
def test_invalid_time_is_not_saved(tmp_path, mode, changes, error):
    c = _controller(tmp_path)
    _, _, d, timer = _timed_document()
    with pytest.raises(gr.Error, match=error):
        _save(c, d, timer, mode=mode, **changes)


@pytest.mark.parametrize("mode", ["cumulative", "ratio"])
def test_condition_window_modes_lower_to_real_window_operator(tmp_path, mode):
    c = _controller(tmp_path)
    registry, _, d, timer = _timed_document()
    after, _ = _save(c, d, timer, mode=mode, window=10, duration=3, ratio=60, gap=99)
    compiled = EditorService(registry).apply(c._parse_editor_json(after))
    nodes = compiled.effective_skill_package.variants["video"].nodes
    timed = [n for n in nodes if n.op.startswith("temporal.")]
    assert len(timed) == 1
    assert timed[0].op == "temporal.qualify@1.0"
    assert timed[0].params["mode"] == mode
    assert timed[0].params["window_seconds"] == 10
    assert timed[0].params["allowed_gap_seconds"] == 0
    assert timed[0].params["required_ratio"] == (0.6 if mode == "ratio" else 1)


def test_imported_timer_reads_real_scope_and_updates_without_new_nodes(tmp_path):
    c = _controller(tmp_path)
    package = SkillPackage.model_validate_json(
        (
            Path(__file__).parents[1] / "presets_v2/P06_highway_person_dwell.json"
        ).read_text("utf-8")
    )
    d = c.business_rule_editor.prepare(import_skill_package(package))
    branch = d.skill_template.business_branches[0]
    selected, _ = c.time_configuration_targets(c._dump(d), branch.branch_id, None)
    assert selected["value"] == "existing_node:events"
    controls = c.time_configuration_controls(
        c._dump(d), branch.branch_id, selected["value"]
    )
    assert controls[1]["value"] == 10
    assert controls[5]["value"] == "track"
    before_count = len(d.skill_template.rule_graphs["video"].nodes)
    after, _ = _save(
        c,
        d,
        selected["value"],
        branch_id=branch.branch_id,
        duration=7,
        gap=1.1,
        identity="track",
    )
    graph = c._parse_editor_json(after).skill_template.rule_graphs["video"]
    assert len(graph.nodes) == before_count
    event = next(n for n in graph.nodes if n.node_id == "events")
    assert event.params["seconds"] == 7
    assert event.params["scope"] == "track"


def test_immediate_ignores_hidden_values_and_preserves_condition_timer(tmp_path):
    c = _controller(tmp_path)
    _, _, d, timer = _timed_document()
    after, _ = _save(
        c, d, "branch:b", mode="immediate", duration=-10, window=-5, ratio=-1, gap=-2
    )
    updated = c._parse_editor_json(after)
    assert not updated.skill_template.business_branches[0].temporal_qualifiers
    assert any(
        r["condition_id"] == timer
        for r in c.business_rule_editor.condition_rows(updated, "b")
    )


def test_image_cannot_acquire_a_timer(tmp_path):
    c = _controller(tmp_path)
    _, editor, d = _document("image")
    d.skill_template.business_branches = [
        BusinessBranch(branch_id="b", display_name="图片", media_type="image")
    ]
    d, _ = _condition(
        editor,
        d,
        "b",
        "target.detect",
        "目标",
        {"targets": ["car"], "phrases": "car", "business_label": "车辆"},
    )
    with pytest.raises(gr.Error, match="需要视频"):
        _save(c, d, "branch:b")
    with pytest.raises(gr.Error, match="不能设置时间保持"):
        _save(c, d, "branch:b", mode="immediate", validity="hold_for", hold=1)


def test_existing_timer_prevents_a_second_hidden_hold_timer(tmp_path):
    c = _controller(tmp_path)
    _, _, d, _ = _timed_document()
    fields = c.time_configuration_controls(c._dump(d), "b", "branch:b")
    assert not fields[7]["visible"]
    assert not fields[8]["visible"]
    assert not fields[-2]["visible"]
    after, _ = _save(c, d, "branch:b", mode="immediate", validity="hold_for", hold=10)
    branch = c._parse_editor_json(after).skill_template.business_branches[0]
    assert branch.validity_policy.mode == "event_interval"
    assert branch.validity_policy.hold_seconds.value is None


def test_mode_switch_does_not_reveal_hold_for_an_already_timed_branch(tmp_path):
    c = _controller(tmp_path)
    _, _, d, _ = _timed_document()
    updates = c.time_configuration_visibility(
        "immediate", "hold_for", "branch:b", c._dump(d), "b"
    )
    assert not updates[6]["visible"]
    assert not updates[7]["visible"]
    assert not updates[-1]["visible"]
    updates = c.time_configuration_visibility(
        "continuous", "current_frame", "branch:b", c._dump(d), "b"
    )
    assert updates[-1]["visible"]


def test_time_inventory_names_imported_input_condition(tmp_path):
    c = _controller(tmp_path)
    package = SkillPackage.model_validate_json(
        (
            Path(__file__).parents[1] / "presets_v2/P06_highway_person_dwell.json"
        ).read_text("utf-8")
    )
    d = c.business_rule_editor.prepare(import_skill_package(package))
    _, inventory = c.time_configuration_targets(
        c._dump(d), d.skill_template.business_branches[0].branch_id, None
    )
    assert "目标在区域内或外：人员" in inventory
    assert "该条件已选择的输入结果" not in inventory


def test_special_multiple_policies_are_not_overwritten(tmp_path):
    c = _controller(tmp_path)
    _, editor, d, timer = _timed_document()
    d = editor.set_branch_time_policy(d, "b", mode="continuous", duration_seconds=2)
    q = d.skill_template.business_branches[0].temporal_qualifiers[0]
    d.skill_template.business_branches[0].temporal_qualifiers.append(
        q.model_copy(
            update={"qualifier_id": "another", "target_ref": f"condition:{timer}"}
        )
    )
    original = c._dump(d)
    controls = c.time_configuration_controls(original, "b", "branch:b")
    assert not controls[-1]["interactive"]
    with pytest.raises(gr.Error, match="其它对象"):
        _save(c, d, "branch:b", confirm_layering=True)
    assert c._dump(d) == original


def test_condition_edit_leaves_other_branch_and_branch_timer_unchanged(tmp_path):
    c = _controller(tmp_path)
    _, editor, d, timer = _timed_document()
    d = editor.set_branch_time_policy(d, "b", mode="continuous", duration_seconds=8)
    d.skill_template.business_branches.append(
        BusinessBranch(branch_id="other", display_name="另一个分支", media_type="video")
    )
    original = d.skill_template.business_branches[1].model_dump()
    after, _ = _save(c, d, timer, duration=4)
    branches = c._parse_editor_json(after).skill_template.business_branches
    assert branches[1].model_dump() == original
    assert branches[0].temporal_qualifiers[0].duration_seconds.value == 8
