"""Regressions for the four high-priority event-editor audit findings."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_business_rule_compiler import _condition, _document
from test_generic_editor_ui import _controller, _package

from core.business_rule_editor import BusinessRuleEditError
from core.context import ConditionSet, TimedValue
from core.editor_schema import BusinessBranch
from core.editor_service import EditorService
from operators.pattern import temporal_qualify


def _qualify(items: list[TimedValue], scope: str = "source", timeline=None):
    services = SimpleNamespace(state={"sample_timeline": timeline or []})
    return temporal_qualify(
        {"condition": ConditionSet(items)},
        {
            "mode": "continuous",
            "duration_seconds": 2,
            "allowed_gap_seconds": 0,
            "window_seconds": None,
            "required_ratio": 1,
            "trigger_mode": "once",
            "identity_scope": scope,
        },
        services,
        "audit",
    )


@pytest.mark.parametrize("interval", [1.0, 0.5, 0.04])
def test_zero_gap_accepts_normal_sampling(interval: float):
    items = [
        TimedValue("t1", index * interval, True, index)
        for index in range(round(3 / interval) + 1)
    ]
    assert len(_qualify(items).items) == 1


def test_zero_gap_uses_real_variable_sampling_schedule_and_detects_missing_samples():
    timeline = [(0, 0.0), (3, 0.7), (6, 1.6), (9, 2.4)]
    items = [TimedValue("t1", time, True, frame) for frame, time in timeline]
    assert len(_qualify(items, timeline=timeline).items) == 1
    assert not _qualify([items[0], items[2], items[3]], timeline=timeline).items


def test_explicit_false_resets_continuity_at_zero_gap():
    items = [TimedValue("t1", t, t != 1, t) for t in range(4)]
    assert not _qualify(items).items


@pytest.mark.parametrize(
    "scope,field",
    [
        ("object", "object_id"),
        ("track", "track_id"),
        ("region", "region_id"),
        ("pair", "pair_id"),
    ],
)
def test_identity_scope_changes_grouping_without_stitching_subjects(
    scope: str, field: str
):
    items = [
        TimedValue("opaque", t, True, t, {field: "a" if t < 2 else "b"})
        for t in range(4)
    ]
    assert len(_qualify(items, "global").items) == 1
    assert not _qualify(items, scope).items
    stable = [TimedValue("opaque", t, True, t, {field: "a"}) for t in range(4)]
    event = _qualify(stable, scope).items[0]
    assert event.entity_id == "a"
    assert event.metadata[field] == "a"


@pytest.mark.parametrize("scope", ["object", "track", "region", "pair"])
def test_explicit_identity_never_falls_back_to_an_untyped_key(scope: str):
    with pytest.raises(ValueError, match="身份"):
        _qualify([TimedValue("global", t, True, t) for t in range(4)], scope)


def _branches():
    registry, editor, document = _document("video")
    document.skill_template.business_branches = [
        BusinessBranch(branch_id=name, display_name=name, media_type="video")
        for name in ("a", "b", "c")
    ]
    for name in ("a", "b", "c"):
        document, _ = _condition(
            editor,
            document,
            name,
            "target.detect",
            name,
            {"targets": ["person"], "phrases": "person", "business_label": "person"},
        )
    document = editor.set_final_decision(
        document, "audit", "event_decision", "branch:a"
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "audit",
                "source_ref": "final:primary",
                "result_kind": "decision",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            }
        ],
    )
    return registry, editor, document


def test_temporal_compiler_carries_the_selected_identity_scope():
    registry, editor, document = _branches()
    for scope in ("global", "object", "track", "region", "pair"):
        updated = editor.set_branch_time_policy(
            document, "a", mode="continuous", duration_seconds=2, identity_scope=scope
        )
        compiled = EditorService(registry).apply(updated)
        qualifier = next(
            node
            for node in compiled.effective_skill_package.variants["video"].nodes
            if node.op == "temporal.qualify@1.0"
        )
        assert qualifier.params["identity_scope"] == scope
        exists = [
            node
            for node in compiled.effective_skill_package.variants["video"].nodes
            if node.op == "reduce.exists@1.0"
            and node.id == qualifier.inputs["condition"].lstrip("$")
        ]
        if exists and scope != "global":
            assert exists[0].params["scope"] == "entity"


def test_updating_child_group_preserves_parent_and_final_references():
    registry, editor, document = _branches()
    document = editor.set_complex_pattern(
        document, "video", "sequence", ["a", "b"], window_seconds=10
    )
    child = document.skill_template.event_patterns[-1].pattern_id
    document = editor.set_complex_pattern(
        document, "video", "all_completed", [f"event:{child}", "branch:c"]
    )
    parent = document.skill_template.event_patterns[-1].pattern_id
    document = editor.set_final_decision(
        document, "audit", "timeline_summary", f"event:{parent}"
    )
    updated = editor.set_complex_pattern(
        document, "video", "sequence", ["a", "b"], window_seconds=20
    )
    assert {item.pattern_id for item in updated.skill_template.event_patterns} == {
        child,
        parent,
    }
    assert (
        next(
            item
            for item in updated.skill_template.event_patterns
            if item.pattern_id == child
        )
        .transitions[0]
        .maximum_delay_seconds.value
        == 20
    )
    assert EditorService(registry).apply(updated).effective_skill_package is not None
    assert (
        next(
            item
            for item in document.skill_template.event_patterns
            if item.pattern_id == child
        )
        .transitions[0]
        .maximum_delay_seconds.value
        == 10
    )


def test_removing_one_group_cannot_clear_others_or_leave_dependencies():
    _, editor, document = _branches()
    document = editor.set_complex_pattern(document, "video", "sequence", ["a", "b"])
    child = document.skill_template.event_patterns[-1].pattern_id
    document = editor.set_complex_pattern(
        document, "video", "all_completed", [f"event:{child}", "branch:c"]
    )
    with pytest.raises(BusinessRuleEditError, match="引用"):
        editor.set_complex_pattern(document, "video", "none", ["a", "b"])
    with pytest.raises(BusinessRuleEditError, match="选择"):
        editor.set_complex_pattern(document, "video", "none", [])
    updated = editor.set_complex_pattern(
        document, "video", "none", [f"event:{child}", "branch:c"]
    )
    assert [item.pattern_id for item in updated.skill_template.event_patterns] == [
        child
    ]


def test_explicit_group_edit_can_change_members_without_changing_identity():
    _, editor, document = _branches()
    document = editor.set_complex_pattern(document, "video", "sequence", ["a", "b"])
    child = document.skill_template.event_patterns[-1].pattern_id
    changed = editor.set_complex_pattern(
        document, "video", "sequence", ["a", "c"], pattern_id=child
    )
    assert len(changed.skill_template.event_patterns) == 1
    assert changed.skill_template.event_patterns[0].pattern_id == child
    document = editor.set_complex_pattern(
        document, "video", "all_completed", [f"event:{child}", "branch:c"]
    )
    parent = document.skill_template.event_patterns[-1].pattern_id
    with pytest.raises(BusinessRuleEditError, match="循环引用"):
        editor.set_complex_pattern(
            document,
            "video",
            "sequence",
            [f"event:{parent}", "branch:a"],
            pattern_id=child,
        )


def test_identity_survives_entity_projection_and_boolean_logic():
    from core.context import ObjectSet, VisualObject
    from operators.logic import logic_all, logic_not
    from operators.reduce import reduce_exists

    objects = ObjectSet(
        [
            VisualObject(
                f"box_{t}", "item", "item", (0, 0, 1, 1), t, t, "audit", track_id="t1"
            )
            for t in range(4)
        ]
    )
    condition = reduce_exists({"sets": objects}, {"scope": "entity"}, None, "exists")
    inverted = logic_not({"condition": condition}, {}, None, "not")
    original = logic_not({"condition": inverted}, {}, None, "not_again")
    combined = logic_all(
        {"conditions": [condition, original]}, {"combine_scope": "by_key"}, None, "all"
    )
    event = _qualify(combined.items, "track").items[0]
    assert event.entity_id == "t1"
    assert event.metadata["track_id"] == "t1"


def test_pair_projection_and_missing_identity_are_not_confused():
    from core.context import Pair, PairSet
    from operators.condition_identity import bind_condition_identity
    from operators.reduce import reduce_exists

    pairs = PairSet([Pair("s1", "o1", t, t) for t in range(4)])
    condition = reduce_exists({"sets": pairs}, {"scope": "entity"}, None, "pairs")
    assert len(_qualify(condition.items, "pair").items) == 1
    assert not bind_condition_identity(ConditionSet([]), "region").items
    with pytest.raises(ValueError, match="不支持"):
        bind_condition_identity(condition, "unknown")


def test_frame_local_ids_do_not_expand_into_a_video_wide_cartesian_product():
    from operators.condition_identity import bind_condition_identity

    condition = ConditionSet(
        [TimedValue(str(t), t, True, t, {"object_id": str(t)}) for t in range(1000)]
    )
    scoped = bind_condition_identity(condition, "object")
    assert len(scoped.items) == 1000


def test_business_restore_is_the_same_staged_transaction_as_advanced_restore(
    tmp_path: Path,
):
    from app_v2 import build_v2_app

    controller = _controller(tmp_path)
    package = _package()
    baseline = controller._editor_document(controller._dump(package), "")
    original = baseline.model_copy(deep=True)
    original.validation_report.pop("configuration_publication", None)
    controller._generated_editor_documents[package.skill_id] = original
    branch = baseline.skill_template.business_branches[0]
    draft = controller.business_branch_action(
        controller._dump(baseline), branch.branch_id, "重命名", "changed"
    )[0]
    applied_json, effective_json, _ = controller.unified_validate_apply(draft)
    app = build_v2_app(controller)
    try:
        config = app.get_config_file()
        button = next(
            item["id"]
            for item in config["components"]
            if item["type"] == "button"
            and item["props"].get("value") == "还原本次生成/加载的默认规则"
        )
        dependency = next(
            item
            for item in config["dependencies"]
            if [button, "click"] in [list(target) for target in item["targets"]]
        )
        callback = app.fns[dependency["id"]].fn
        restored_json, _, history = callback(
            effective_json, applied_json, {"undo": [], "redo": []}, "已保存技能"
        )
        restored = controller._parse_editor_json(restored_json)
        assert restored.validation_report["dirty"] is True
        assert restored.effective_skill_package is None
        assert controller.configuration_service.publication(restored)["revision"] == 2
        assert history["undo"] == [applied_json]
        reapplied_json, _, _ = controller.unified_validate_apply(restored_json)
        reapplied = controller._parse_editor_json(reapplied_json)
        assert controller.configuration_service.publication(reapplied)["revision"] == 3
        assert (
            reapplied.skill_template.business_branches[0].display_name
            == branch.display_name
        )
    finally:
        app.close()
