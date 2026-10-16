"""Draft/activation transactions and prevention of stale-version execution."""

from __future__ import annotations

import json

import gradio as gr
import pytest
from test_generic_editor_ui import _controller, _package

from application.v2.support import ApplicationError
from core.editor_schema import PendingDecision, ResolvableValue


@pytest.fixture
def configuration(tmp_path):
    controller = _controller(tmp_path)
    package = _package()
    document = controller.business_rule_editor.prepare(
        controller._editor_document(controller._dump(package), "")
    )
    return controller, package, document


@pytest.mark.parametrize(
    "kind", ["condition", "branch", "time", "output", "trigger", "atomic"]
)
def test_all_editor_sections_stage_without_replacing_running_package(
    configuration, kind
):
    controller, package, document = configuration
    content = controller._dump(document)
    before = document.model_dump_json()
    branch = document.skill_template.business_branches[0]
    if kind == "branch":
        updated = controller.business_branch_action(
            content, branch.branch_id, "重命名", "新的分支名称"
        )[0]
    elif kind == "condition":
        root = branch.condition_root
        updated = controller.business_apply_condition(
            content, branch.branch_id, root.expression_id, "新的条件名称", [], False
        )[0]
    elif kind == "time":
        updated = controller.business_apply_branch_time(
            content,
            branch.branch_id,
            "immediate",
            None,
            None,
            100,
            0,
            "global",
            "first_only",
            "hold_for",
            3,
        )[0]
    elif kind == "output":
        specs = [
            item.model_dump(mode="json")
            for item in document.skill_template.result_specs
        ]
        specs[0]["display_name"] = "新的输出名称"
        updated = controller.unified_apply_results(content, json.dumps(specs))[0]
    elif kind == "trigger":
        updated = controller.business_apply_trigger(
            content, "once", 4, "high", ["event_record"]
        )[0]
    else:
        node = next(
            item
            for item in package.variants["image"].nodes
            if item.op.startswith("rex.ground")
        )
        updated = controller.unified_apply_parameter(
            content, node.id, "query_prompt", '"Detect person"'
        )[0]
    staged = controller._parse_editor_json(updated)
    assert staged.validation_report["dirty"] is True
    assert staged.effective_skill_package is None
    assert document.model_dump_json() == before
    assert "有未应用修改" in controller.configuration_state_view(
        controller._dump(package), updated
    )
    # The refresh used immediately before execution must not resurrect the old package.
    refreshed = controller._editor_document(controller._dump(package), updated)
    assert refreshed.effective_skill_package is None
    assert refreshed.validation_report["can_run"] is False
    with pytest.raises(ApplicationError, match="有未应用修改"):
        controller.configuration_service.require_current(refreshed, package)


def test_activation_is_atomic_and_retains_previous_revision_on_failure(configuration):
    controller, package, document = configuration
    first_json, first_package, _ = controller.unified_validate_apply(
        controller._dump(document)
    )
    first = controller._parse_editor_json(first_json)
    assert controller.configuration_service.publication(first)["revision"] == 2
    branch = first.skill_template.business_branches[0]
    edited = controller.business_branch_action(
        first_json, branch.branch_id, "重命名", "已修改分支"
    )[0]
    staged = controller._parse_editor_json(edited)
    assert controller.configuration_service.publication(staged)["revision"] == 2
    compiled_json, compiled_package, _ = controller.unified_validate_apply(edited)
    compiled = controller._parse_editor_json(compiled_json)
    assert controller.configuration_service.publication(compiled)["revision"] == 3
    controller.configuration_service.require_current(
        compiled, compiled.effective_skill_package
    )
    assert "已应用" in controller.configuration_state_view(
        compiled_package, compiled_json
    )

    invalid = compiled.model_copy(deep=True)
    invalid.skill_template.pending_decisions.append(
        PendingDecision(
            decision_id="needs_confirmation",
            parameter_kind="generic",
            prompt="确认阈值",
            resolution=ResolvableValue(
                state="unresolved",
                source="user",
                required_before="run",
                reason="需要用户确认",
            ),
        )
    )
    invalid = controller.configuration_service.stage(compiled, invalid)
    saved = invalid.model_dump_json()
    with pytest.raises(gr.Error, match="配置不能应用"):
        controller.unified_validate_apply(controller._dump(invalid))
    assert invalid.model_dump_json() == saved
    assert controller.configuration_service.publication(invalid)["revision"] == 3
    assert json.loads(first_package)["skill_id"] == package.skill_id


def test_run_application_rejects_unapplied_edits_before_model_call(
    configuration, tmp_path
):
    controller, package, document = configuration
    branch = document.skill_template.business_branches[0]
    edited = controller.business_branch_action(
        controller._dump(document), branch.branch_id, "重命名", "待应用"
    )[0]
    controller.rex = object()
    with pytest.raises(gr.Error, match="有未应用修改"):
        controller.run_skill(
            controller._dump(package),
            controller._dump(package),
            "image",
            str(tmp_path / "unused.png"),
            edited,
        )


def test_publication_round_trip_and_direct_runtime_update(configuration):
    controller, _package, document = configuration
    published = controller.configuration_service.publish(document)
    copied = controller._parse_editor_json(controller._dump(published))
    changed = copied.model_copy(deep=True)
    changed.effective_skill_package.display_name = "已应用参数卡更新"
    adopted = controller.configuration_service.accept_runtime_update(copied, changed)
    assert controller.configuration_service.publication(adopted)["revision"] == 3
    controller.configuration_service.require_current(
        adopted, adopted.effective_skill_package
    )
    assert controller.configuration_service.publication(copied)["revision"] == 2


def test_manual_document_edit_cannot_be_resurrected_as_applied(configuration):
    controller, package, document = configuration
    changed = document.model_copy(deep=True)
    changed.skill_template.business_branches[0].display_name = "手工 JSON 修改"
    refreshed = controller._editor_document(
        controller._dump(package), controller._dump(changed)
    )
    assert refreshed.validation_report["dirty"] is True
    assert refreshed.effective_skill_package is None


def test_gradio_activation_and_runtime_edit_gates(configuration):
    from app_v2 import build_v2_app

    controller, package, document = configuration
    content = controller._dump(document)
    branch = document.skill_template.business_branches[0]
    dirty = controller.business_branch_action(
        content, branch.branch_id, "重命名", "未应用"
    )[0]
    app = build_v2_app(controller)
    try:
        refresh = next(
            item.fn
            for item in app.fns.values()
            if item.fn.__name__ == "_refresh_configuration_state"
        )
        state = refresh(controller._dump(package), dirty)
        assert state[0] == state[1] and "有未应用修改" in state[0]
        assert state[2]["interactive"] is False
        clean = refresh(controller._dump(package), content)
        assert clean[2]["interactive"] is True
        apply_callbacks = [
            item.fn
            for item in app.fns.values()
            if item.fn == controller.unified_validate_apply
        ]
        assert len(apply_callbacks) == 3
        guarded = [
            item.fn
            for item in app.fns.values()
            if getattr(item.fn, "configuration_guard", False)
        ]
        assert len(guarded) == 14
        # Reject before reading any card values, mutating packages or calling models.
        for callback in guarded:
            with pytest.raises(gr.Error, match="有未应用修改"):
                callback(dirty, controller._dump(package))
        undo = next(
            item.fn for item in app.fns.values() if item.fn.__name__ == "_undo_editor"
        )
        compiled_json, _, _ = controller.unified_validate_apply(dirty)
        restored, _, _ = undo(compiled_json, {"undo": [content], "redo": []})
        restored_document = controller._parse_editor_json(restored)
        assert restored_document.validation_report["dirty"] is True
        assert (
            controller.configuration_service.publication(restored_document)["revision"]
            == 2
        )
    finally:
        app.close()


def test_explicit_saved_load_starts_from_loaded_version(configuration):
    controller, package, document = configuration
    controller.save_skill_bundle(
        controller._dump(package),
        controller._dump(document),
        "saved_rule",
        "保存的技能",
    )
    _, loaded_package, _, _, _ = controller.load_saved_skill("saved_rule/v1")
    loaded = controller.load_editor_configuration(loaded_package, "已保存技能")
    parsed = controller._parse_editor_json(loaded)
    assert parsed.skill_template.skill_id == "saved_rule"
    assert "有未应用修改" not in controller.configuration_state_view(
        loaded_package, loaded
    )
    controller.configuration_service.require_current(
        parsed, parsed.effective_skill_package
    )


def test_malformed_publication_is_not_reinterpreted_as_a_clean_baseline(configuration):
    controller, package, document = configuration
    document.validation_report["configuration_publication"]["revision"] = (
        "<script>bad</script>"
    )
    with pytest.raises(ApplicationError, match="版本记录无效"):
        controller.configuration_service.require_current(document, package)
    assert "bad</script>" not in controller.configuration_state_view(
        controller._dump(package), controller._dump(document)
    )
