"""Controlled choices, stable edits, and actual execution type contracts."""

from __future__ import annotations

import gradio as gr
import pytest
from test_business_rule_compiler import _condition
from test_event_editor_fixes import _branches
from test_generic_editor_ui import _controller, _package

from app_v2 import build_v2_app
from core.business_output_editor import delete_output, output_sources, save_output
from core.business_rule_editor import BusinessRuleEditError
from core.editor_schema import SkillEditorDocument
from core.editor_service import EditorService
from core.legacy_importer import import_skill_package
from ui.v2.controllers.output_editor import NEW_OUTPUT


def _save(d, e, **overrides):
    values = {
        "result_id": None,
        "display_name": "目标列表",
        "source_ref": f"condition:{d.skill_template.business_branches[0].condition_root.expression_id}",
        "kind": "entities",
        "unit": "",
        "evidence": "optional",
        "save_policy": "always",
        "show": True,
    }
    values.update(overrides)
    return save_output(d, e, **values)


def test_named_sources_derive_from_actual_lowering_and_do_not_mutate():
    _, e, d = _branches()
    before = d.model_dump(mode="json")
    choices = output_sources(d, e)
    assert d.model_dump(mode="json") == before
    condition = next(s for s in choices if s.ref.startswith("condition:"))
    branch = next(s for s in choices if s.ref == "branch:a")
    assert {"entities", "count"} <= set(condition.kinds)
    assert "entities" not in branch.kinds and "events" not in branch.kinds
    assert any(s.kinds == ("media",) for s in choices)
    assert all(s.ref not in s.label for s in choices)


def test_count_condition_can_publish_measurement_not_just_boolean():
    _, e, d = _branches()
    ref = f"condition:{d.skill_template.business_branches[0].condition_root.expression_id}"
    d, cid = _condition(
        e,
        d,
        "a",
        "measure.count",
        "人数",
        {"source": ref, "operator": ">=", "threshold": 2},
    )
    source = next(s for s in output_sources(d, e) if s.ref == f"condition:{cid}")
    assert {"count", "value"} <= set(source.kinds)
    assert "duration" not in source.kinds


def test_event_final_exposes_event_projections_only_with_alert():
    _, e, d = _branches()
    d = e.set_trigger_policy(
        d,
        mode="on_change",
        cooldown_seconds=0,
        severity="medium",
        outputs=["event_record"],
    )
    final = next(s for s in output_sources(d, e) if s.ref == "final:primary")
    assert {"events", "duration", "timeline"} <= set(final.kinds)


def test_imported_skill_exposes_object_sources_without_typing_ids():
    _, e, _ = _branches()
    d = e.prepare(import_skill_package(_package()))
    sources = output_sources(d, e)
    assert any("entities" in s.kinds for s in sources)
    assert all("branch:" not in s.label for s in sources)


def test_edit_preserves_id_hidden_policies_other_outputs_and_presentation():
    _, e, d = _branches()
    d, rid = _save(d, e)
    spec = next(s for s in d.skill_template.result_specs if s.result_id == rid)
    spec.label_policy.business_label = "业务目标"
    spec.grouping = ["category"]
    spec.empty_policy = "hide"
    spec.projection.parameters = {"selection": "last"}
    p = next(p for p in d.skill_template.presentation_specs if p.result_id == rid)
    p.preferred_renderer = "entity.gallery"
    other = d.skill_template.result_specs[0].model_dump(mode="json")
    before = d.model_dump(mode="json")
    updated, kept = _save(
        d, e, result_id=rid, display_name="改名", unit="个", show=False
    )
    assert d.model_dump(mode="json") == before and kept == rid
    assert updated.skill_template.result_specs[0].model_dump(mode="json") == other
    saved = next(s for s in updated.skill_template.result_specs if s.result_id == rid)
    assert saved.label_policy.business_label == "业务目标"
    assert saved.grouping == ["category"] and saved.empty_policy == "hide"
    assert saved.projection.parameters == {"selection": "last"}
    presentation = next(
        p for p in updated.skill_template.presentation_specs if p.result_id == rid
    )
    assert (
        presentation.preferred_renderer == "entity.gallery"
        and not presentation.show_in_overview
    )


@pytest.mark.parametrize(
    "values,message",
    [
        ({"source_ref": "node:missing"}, "可用的结果来源"),
        ({"source_ref": "branch:a", "kind": "entities"}, "不兼容"),
        ({"kind": "made_up_type"}, "不兼容"),
        ({"display_name": ""}, "输出名称"),
        ({"display_name": "audit"}, "不能重复"),
        ({"result_id": "missing"}, "已不存在"),
    ],
)
def test_save_rejects_invalid_or_stale_values(values, message):
    _, e, d = _branches()
    with pytest.raises(BusinessRuleEditError, match=message):
        _save(d, e, **values)


def test_final_output_cycle_and_referenced_deletion_are_rejected():
    _, e, d = _branches()
    d, rid = _save(d, e)
    d = e.set_final_decision(d, "总结", "detection_summary", f"result:{rid}")
    assert "final:primary" not in {s.ref for s in output_sources(d, e, result_id=rid)}
    with pytest.raises(BusinessRuleEditError, match="可用的结果来源"):
        _save(d, e, result_id=rid, source_ref="final:primary", kind="decision")
    with pytest.raises(BusinessRuleEditError, match="最终判定"):
        delete_output(d, e, rid)


def test_delete_keeps_last_output_and_does_not_rebind_final():
    _, e, d = _branches()
    with pytest.raises(BusinessRuleEditError, match="至少需要保留"):
        delete_output(d, e, d.skill_template.result_specs[0].result_id)
    d, rid = _save(d, e)
    final_before = d.skill_template.final_decision.model_dump(mode="json")
    updated = delete_output(d, e, rid)
    assert all(p.result_id != rid for p in updated.skill_template.presentation_specs)
    assert updated.skill_template.final_decision.model_dump(mode="json") == final_before


def test_form_uses_stable_ids_and_never_silently_rebinds(tmp_path):
    c = _controller(tmp_path)
    _, e, d = _branches()
    d, rid = _save(d, e)
    spec = next(s for s in d.skill_template.result_specs if s.result_id == rid)
    spec.display_name = "audit"  # imported same-name outputs stay distinguishable
    dumped = c._dump(d)
    choices = c.output_editor_choices(dumped, rid)
    assert choices["value"] == rid
    assert len({label for label, _ in choices["choices"]}) == 3
    controls = c.output_editor_controls(dumped, rid)
    assert controls[0] == "audit" and controls[1]["value"] == spec.source_ref
    assert controls[2]["value"] == "entities"
    kind, _ = c.output_editor_kinds(dumped, "branch:a", "entities", rid)
    assert kind["value"] is None and "entities" not in {v for _, v in kind["choices"]}
    spec.source_ref = "node:missing"
    controls = c.output_editor_controls(c._dump(d), rid)
    assert controls[1]["value"] is None and "不可用" in controls[7]


def test_form_save_stages_a_draft_and_compiles_the_selected_projection(tmp_path):
    c = _controller(tmp_path)
    registry, _, d = _branches()
    base = c.configuration_service.initialize(EditorService(registry).apply(d))
    ref = f"condition:{d.skill_template.business_branches[0].condition_root.expression_id}"
    changed, status, selector = c.save_output_form(
        c._dump(base),
        NEW_OUTPUT,
        "人数",
        ref,
        "count",
        "人",
        "optional",
        "on_change",
        True,
    )
    draft = SkillEditorDocument.model_validate_json(changed)
    assert selector["value"] in {s.result_id for s in draft.skill_template.result_specs}
    assert draft.effective_skill_package is None
    assert base.effective_skill_package is not None and "草稿" in status
    applied = c.editor_service.apply(draft)
    spec = next(
        s
        for s in applied.skill_template.result_specs
        if s.result_id == selector["value"]
    )
    assert spec.media_types == ["video"] and spec.projection.kind == "count"
    assert spec.required_outputs


def test_empty_form_and_invalid_save_are_clear(tmp_path):
    c = _controller(tmp_path)
    assert len(c.output_editor_controls("", None)) == 10
    assert c.output_editor_kinds("", None, None)[0]["choices"] == []
    _, _, d = _branches()
    with pytest.raises(gr.Error, match="结果来源"):
        c.save_output_form(
            c._dump(d), NEW_OUTPUT, "输出", None, None, "", "optional", "always", True
        )


def test_ui_choices_are_controlled_and_overview_is_readonly(tmp_path):
    app = build_v2_app(_controller(tmp_path))
    try:
        components = app.get_config_file()["components"]
        for name in (
            "output-editor-source",
            "output-editor-kind",
            "output-editor-selector",
        ):
            item = next(c for c in components if c["props"].get("elem_id") == name)
            assert item["type"] == "dropdown"
            assert item["props"]["allow_custom_value"] is False
            assert item["props"]["filterable"] is False
        table = next(c for c in components if c["props"].get("label") == "业务输出规格")
        assert table["props"]["interactive"] is False
        save = next(
            fn
            for fn in app.fns.values()
            if getattr(fn.fn, "__name__", "") == "save_output_form"
        )
        assert len(save.inputs) == 9 and len(save.outputs) == 3
    finally:
        app.close()
