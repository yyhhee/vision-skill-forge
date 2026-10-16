"""Explicit group selection, form-only moves and dependency-safe saves."""

from pathlib import Path

import gradio as gr
import pytest
from test_event_editor_fixes import _branches
from test_generic_editor_ui import _controller

from core.editor_schema import ResolvableValue
from core.editor_service import EditorService
from ui.v2.controllers.pattern_editor import (
    NEW_GROUP,
    pattern_consumers,
)


def _groups():
    registry, editor, document = _branches()
    document = editor.set_complex_pattern(
        document,
        "video",
        "sequence",
        ["a", "b"],
        window_seconds=10,
        display_name="先A后B",
    )
    child = document.skill_template.event_patterns[-1].pattern_id
    document = editor.set_complex_pattern(
        document, "video", "all_completed", [f"event:{child}", "c"], display_name="父组"
    )
    parent = document.skill_template.event_patterns[-1].pattern_id
    document = editor.set_final_decision(
        document, "最终告警", "timeline_summary", f"event:{parent}"
    )
    return registry, editor, document, child, parent


def _save(c, document, selected, **changes):
    args = {
        "editor_json": c._dump(document),
        "media_type": "video",
        "selected": selected,
        "name": "修改后的组",
        "mode": "sequence",
        "members": ["branch:b", "branch:a"],
        "window": 10,
        "required": 1,
        "scope": "global",
    }
    args.update(changes)
    return c.save_pattern_group(**args)


def test_selecting_child_loads_child_not_the_latest_parent(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, parent = _groups()
    assert c.pattern_group_choices(c._dump(d), "video", None)["value"] == parent
    assert c.pattern_group_choices(c._dump(d), "video", child)["value"] == child
    fields = c.pattern_group_controls(c._dump(d), "video", child)
    assert fields[0] == "先A后B"
    assert fields[1]["value"] == "sequence"
    assert fields[2]["value"] == ["branch:a", "branch:b"]
    assert fields[3] == 10
    assert "父组" in fields[8]
    assert "本组使用的输入" in fields[8]


def test_group_input_choices_exclude_self_and_transitive_consumers(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, parent = _groups()
    choices = c.pattern_group_controls(c._dump(d), "video", child)[2]["choices"]
    refs = {value for _, value in choices}
    assert f"event:{child}" not in refs
    assert f"event:{parent}" not in refs
    assert "branch:c" in refs


@pytest.mark.parametrize(
    "ordered,step,direction,expected",
    [
        (["a", "b", "c"], "b", "up", ["b", "a", "c"]),
        (["a", "b", "c"], "b", "down", ["a", "c", "b"]),
        (["a", "b"], "a", "up", ["a", "b"]),
        (["a", "b"], "b", "down", ["a", "b"]),
    ],
)
def test_step_moves_are_form_only_and_preserve_selection(
    tmp_path: Path, ordered, step, direction, expected
):
    c = _controller(tmp_path)
    before = list(ordered)
    update, selection = c.pattern_move_step(ordered, step, direction)
    assert update["value"] == expected
    assert selection["value"] == step
    assert ordered == before


def test_preview_follows_reordered_steps_without_mutating_document(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, _ = _groups()
    original = c._dump(d)
    formula, steps, deps = c.pattern_form_preview(
        original,
        "video",
        child,
        "sequence",
        ["branch:b", "branch:a"],
        10,
        1,
        "global",
        "branch:b",
    )
    assert "编辑预览" in formula
    assert steps["choices"][0][1] == "branch:b"
    assert deps.index("步骤 1：分支「b」") < deps.index("步骤 2：分支「a」")
    assert c._dump(d) == original


def test_save_selected_group_retains_ids_order_parent_and_final(tmp_path: Path):
    c = _controller(tmp_path)
    registry, _, d, child, _ = _groups()
    ids_before = [p.pattern_id for p in d.skill_template.event_patterns]
    parent_before = d.skill_template.event_patterns[1].model_dump()
    final_before = d.skill_template.final_decision.model_dump()
    stage_ids = {
        s.source_ref: s.stage_id for s in d.skill_template.event_patterns[0].stages
    }
    after, status, selected = _save(c, d, child)
    updated = c._parse_editor_json(after)
    assert selected["value"] == child
    assert "草稿" in status
    assert [p.pattern_id for p in updated.skill_template.event_patterns] == ids_before
    assert updated.skill_template.event_patterns[1].model_dump() == parent_before
    assert updated.skill_template.final_decision.model_dump() == final_before
    changed = updated.skill_template.event_patterns[0]
    assert [s.source_ref for s in changed.stages] == ["branch:b", "branch:a"]
    assert {s.source_ref: s.stage_id for s in changed.stages} == stage_ids
    assert changed.transitions[0].source_stage_id == stage_ids["branch:b"]
    assert changed.transitions[0].target_stage_id == stage_ids["branch:a"]
    assert updated.effective_skill_package is None
    assert EditorService(registry).apply(updated).effective_skill_package


def test_new_group_does_not_replace_existing_group_with_same_members(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, parent = _groups()
    after, _, selected = _save(
        c,
        d,
        NEW_GROUP,
        members=["branch:a", "branch:b"],
        mode="any",
        name="相同成员不同关系",
        window=-99,
    )
    updated = c._parse_editor_json(after)
    assert selected["value"] not in {child, parent, NEW_GROUP}
    assert len(updated.skill_template.event_patterns) == 3
    assert updated.skill_template.event_patterns[0].pattern_type == "sequence"
    assert (
        c.pattern_group_choices(after, "video", selected["value"])["value"]
        == selected["value"]
    )
    assert selected["value"] in {value for _, value in selected["choices"]}
    # Gradio validates downstream inputs against the updated choice list.
    dropdown = gr.Dropdown(choices=selected["choices"], value=selected["value"])
    assert dropdown.preprocess(selected["value"]) == selected["value"]


def test_cycles_are_rejected_even_if_submitted_outside_filtered_choices(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, parent = _groups()
    with pytest.raises(gr.Error, match="循环引用"):
        _save(c, d, child, members=[f"event:{parent}", "branch:a"])


def test_dependency_readout_includes_final_media_refs_and_business_outputs(
    tmp_path: Path,
):
    c = _controller(tmp_path)
    _, editor, d, _, parent = _groups()
    d.skill_template.final_decision.media_source_refs = {"video": [f"event:{parent}"]}
    d = editor.set_result_rows(
        d,
        [
            {
                "display_name": "事件列表",
                "source_ref": f"event:{parent}",
                "result_kind": "events",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            }
        ],
    )
    assert "最终判定「最终告警」" in pattern_consumers(d, parent)
    assert "业务输出「事件列表」" in pattern_consumers(d, parent)
    assert "最终告警" in c.pattern_group_controls(c._dump(d), "video", parent)[8]


def test_advanced_stage_timing_is_read_only_and_cannot_be_flattened(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, _ = _groups()
    d.skill_template.event_patterns[0].stages[0].persist_mode = "continuous"
    d.skill_template.event_patterns[0].stages[0].duration = ResolvableValue(
        state="explicit", value=3, source="user"
    )
    original = c._dump(d)
    controls = c.pattern_group_controls(original, "video", child)
    assert not controls[-1]["interactive"]
    assert "步骤独立计时" in controls[6]
    preview = c.pattern_form_preview(
        original,
        "video",
        child,
        "sequence",
        ["branch:b", "branch:a"],
        10,
        1,
        "global",
        "branch:b",
    )
    assert "普通表单只读" in preview[0]
    with pytest.raises(gr.Error, match="高级约束"):
        _save(c, d, child)
    assert c._dump(d) == original


def test_new_stage_id_does_not_collide_after_reordering_members(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, _ = _groups()
    after, _, _ = _save(c, d, child, members=["branch:b", "branch:c", "branch:a"])
    stages = c._parse_editor_json(after).skill_template.event_patterns[0].stages
    assert len({s.stage_id for s in stages}) == 3


def test_stale_selection_cannot_overwrite_another_group(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, _, _ = _groups()
    with pytest.raises(gr.Error, match="已不存在"):
        _save(c, d, "missing")


def test_secondary_refresh_no_longer_overwrites_selected_group_form(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, _, _ = _groups()
    updates = c.pattern_secondary_controls(c._dump(d), "video")
    assert all(update == gr.skip() for update in updates[:6])
    assert updates[-1] == gr.skip()
    assert updates[6] == "最终告警"


def test_same_named_sources_are_distinguishable_in_members_and_steps(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, _ = _groups()
    for branch in d.skill_template.business_branches:
        branch.display_name = "同名分支"
    fields = c.pattern_group_controls(c._dump(d), "video", child)
    choices = [
        label for label, ref in fields[2]["choices"] if ref.startswith("branch:")
    ]
    assert len(set(choices)) == 3
    assert "分支 1「同名分支」" in choices
    assert "分支 2「同名分支」" in choices


def test_zero_sequence_gap_means_unlimited_not_a_failed_save(tmp_path: Path):
    c = _controller(tmp_path)
    _, _, d, child, _ = _groups()
    after, _, _ = _save(c, d, child, window=0)
    transition = (
        c._parse_editor_json(after).skill_template.event_patterns[0].transitions[0]
    )
    assert transition.maximum_delay_seconds.state == "not_applicable"
