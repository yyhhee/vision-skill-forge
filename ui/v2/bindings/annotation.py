"""Annotation page event registration; preserves callback order and signatures."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

import gradio as gr

from application.v2.support import _variant_key
from core.schema import SkillPackage
from ui.v2.bindings.business import BusinessBindings
from ui.v2.bindings.creation import CreationBindings
from ui.v2.bindings.events import EventsBindings
from ui.v2.controllers.configuration import runtime_edit
from ui.v2.workspace import Workspace


def bind_annotation(
    controller: V2AppController,
    workspace: Workspace,
    business: BusinessBindings,
    creation: CreationBindings,
    events: EventsBindings,
) -> None:
    def _canvas_click(
        effective_json, media_type, path, timestamp, tool, state, evt: gr.SelectData
    ):
        x, y = evt.index
        if tool != "polygon":
            return controller._render_annotation_state(
                effective_json, media_type, path, timestamp, dict(state or {})
            )
        return controller.add_annotation_point(
            effective_json,
            media_type,
            path,
            timestamp,
            tool,
            state,
            x,
            y,
        )

    def _bind_and_refresh(
        effective_json,
        media_type,
        slot_id,
        tool,
        points_json,
        item_id,
        item_label,
        path,
        timestamp,
        state,
    ):
        updated_json, rows, status = controller.bind_annotation(
            effective_json,
            media_type,
            slot_id,
            tool,
            points_json,
            item_id,
            item_label,
        )
        current = dict(state or {})
        current["tool"] = tool
        current["points"] = []
        (
            preview,
            current,
            _,
        ) = controller.refresh_annotation_preview(
            updated_json, media_type, path, timestamp, current
        )
        choices, rows = controller.annotation_slots(updated_json, media_type)  # noqa: RUF059 — preserved V2 behavior
        wizard = controller.annotation_wizard_state(updated_json, media_type)
        selected = (
            wizard["current_slot"] or slot_id or (choices[0][1] if choices else None)
        )
        next_tool, next_item_id, next_item_label = (
            controller.annotation_wizard_defaults(updated_json, media_type, selected)
        )
        delete_choices = controller.named_item_choices(
            updated_json, media_type, selected
        )
        return (
            updated_json,
            controller.annotation_slots_with_selection(
                updated_json, media_type, selected
            ),
            status,
            preview,
            current,
            "[]",
            gr.update(choices=choices, value=selected),
            controller.annotation_wizard_markdown(updated_json, media_type),
            gr.update(
                choices=controller.annotation_tool_choices(
                    updated_json, media_type, selected
                ),
                value=next_tool,
            ),
            gr.update(value=next_item_id),
            gr.update(value=next_item_label),
            gr.update(choices=delete_choices, value=None),
        )

    def _add_another_named_region(
        effective_json, media_type, selected_slot, path, timestamp, state
    ):
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        slots = package.variants[key].configuration_slots
        selected = next((slot for slot in slots if slot.slot_id == selected_slot), None)
        if selected is None or selected.kind != "region_set":
            selected = next((slot for slot in slots if slot.kind == "region_set"), None)
        if selected is None:
            raise gr.Error("当前技能没有可重复添加的命名区域")
        tool, item_id, item_label, draft = controller.annotation_selection_defaults(
            effective_json, media_type, selected.slot_id
        )
        delete_choices = controller.named_item_choices(
            effective_json, media_type, selected.slot_id
        )
        preview, draft, points_json, _ = controller._render_annotation_state(
            effective_json, media_type, path, timestamp, draft
        )
        return (
            gr.update(value=selected.slot_id),
            gr.update(
                choices=controller.annotation_tool_choices(
                    effective_json, media_type, selected.slot_id
                ),
                value=tool,
            ),
            gr.update(value=item_id),
            gr.update(value=item_label),
            preview,
            draft,
            points_json,
            f"请在画布上绘制 `{item_label}`，然后保存并继续。",
            gr.update(choices=delete_choices, value=None),
            controller.annotation_slots_with_selection(
                effective_json, media_type, selected.slot_id
            ),
        )

    def _select_annotation_slot(
        effective_json, media_type, slot_id, path, timestamp, state
    ):
        if not effective_json:
            return (
                gr.update(
                    choices=[("矩形", "rectangle"), ("多边形", "polygon")],
                    value="rectangle",
                ),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(choices=[], value=None),
                gr.update(value=None),
                dict(state or {}),
                "[]",
                "请先加载技能和任务媒体，再开始标注。",
                [],
            )
        tool, item_id, item_label, draft = controller.annotation_selection_defaults(
            effective_json, media_type, slot_id, state
        )
        if not effective_json or not path:
            return (
                gr.update(
                    choices=[("矩形", "rectangle"), ("多边形", "polygon")],
                    value=tool,
                ),
                gr.update(value=item_id),
                gr.update(value=item_label),
                gr.update(choices=[], value=None),
                gr.update(value=None),
                draft,
                "[]",
                "请先加载技能和任务媒体，再开始标注。",
                [],
            )
        preview, draft, points_json, _ = controller._render_annotation_state(
            effective_json, media_type, path, timestamp, draft
        )
        return (
            gr.update(
                choices=controller.annotation_tool_choices(
                    effective_json, media_type, slot_id
                ),
                value=tool,
            ),
            gr.update(value=item_id),
            gr.update(value=item_label),
            gr.update(
                choices=controller.named_item_choices(
                    effective_json, media_type, slot_id
                ),
                value=None,
            ),
            preview,
            draft,
            points_json,
            f"已切换到 `{slot_id}`；请重新绘制后再保存。",
            controller.annotation_slots_with_selection(
                effective_json, media_type, slot_id
            ),
        )

    def _change_annotation_tool(
        effective_json, media_type, slot_id, path, timestamp, tool, state
    ):
        if not effective_json:
            selected_tool = tool or "rectangle"
            return (
                gr.update(value=slot_id),
                gr.update(
                    choices=[("矩形", "rectangle"), ("多边形", "polygon")],
                    value=selected_tool,
                ),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(choices=[], value=None),
                gr.update(),
                dict(state or {}),
                "[]",
                "请先加载技能和任务媒体，再开始标注。",
                _tool_hints.get(selected_tool, _tool_hints["rectangle"]),
                [],
            )
        (
            target_slot_id,
            selected_tool,
            item_id,
            item_label,
            draft,
        ) = controller.annotation_tool_selection_defaults(
            effective_json, media_type, slot_id, tool
        )
        if path:
            preview, draft, points_json, status = controller._render_annotation_state(
                effective_json, media_type, path, timestamp, draft
            )
        else:
            preview = gr.update()
            points_json = "[]"
            status = "已切换标注工具；请加载画布后重新绘制。"
        package = SkillPackage.model_validate_json(effective_json)
        key = _variant_key(media_type)
        target_slot = next(
            (
                item
                for item in package.variants[key].configuration_slots
                if item.slot_id == target_slot_id
            ),
            None,
        )
        if (
            selected_tool == "direction"
            and target_slot is not None
            and target_slot.kind == "direction_set"
            and not item_id
        ):
            status = "请先绘制并保存至少一个命名区域，再绘制方向箭头。"
        return (
            gr.update(value=target_slot_id),
            gr.update(
                choices=controller.annotation_tool_choices(
                    effective_json, media_type, target_slot_id
                ),
                value=selected_tool,
            ),
            gr.update(value=item_id),
            gr.update(value=item_label),
            gr.update(
                choices=controller.named_item_choices(
                    effective_json, media_type, target_slot_id
                ),
                value=None,
            ),
            preview,
            draft,
            points_json,
            status,
            _tool_hints.get(selected_tool, _tool_hints["rectangle"]),
            controller.annotation_slots_with_selection(
                effective_json, media_type, target_slot_id
            ),
        )

    def _delete_and_refresh(
        effective_json,
        media_type,
        slot_id,
        item_id,
        path,
        timestamp,
        state,
    ):
        updated_json, rows, status = controller.delete_named_annotation(
            effective_json, media_type, slot_id, item_id
        )
        preview, state, _ = controller.refresh_annotation_preview(
            updated_json, media_type, path, timestamp, state
        )
        choices, rows = controller.annotation_slots(updated_json, media_type)  # noqa: RUF059 — preserved V2 behavior
        wizard = controller.annotation_wizard_state(updated_json, media_type)
        selected = (
            wizard["current_slot"] or slot_id or (choices[0][1] if choices else None)
        )
        delete_choices = controller.named_item_choices(
            updated_json, media_type, slot_id
        )
        return (
            updated_json,
            controller.annotation_slots_with_selection(
                updated_json, media_type, selected
            ),
            status,
            preview,
            state,
            gr.update(
                choices=choices,
                value=selected,
            ),
            controller.annotation_wizard_markdown(updated_json, media_type),
            gr.update(choices=delete_choices, value=None),
        )

    # File.change can race Gradio's internal upload event and dispatch the
    # next dependency with the file payload (observed as apply_preprocessing
    # receiving only [file, timestamp]).  Bind ingestion to the explicit
    # upload lifecycle so selecting a replacement video always reaches the
    # media-ingest callback before downstream controls refresh.
    workspace.create.media.upload(
        creation._ingest_task_media,
        [workspace.create.media, workspace.annotation.annotation_timestamp],
        [
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_metadata,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_status,
            workspace.annotation.annotation_variant,
            workspace.create.run_variant,
            workspace.run.run_media_summary,
            workspace.review.variant_choice,
        ],
    )
    workspace.create.clear_task_media_button.click(
        lambda: (gr.update(value=None), *controller.cleared_task_media_state()),
        None,
        [
            workspace.create.media,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_metadata,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_status,
            workspace.annotation.annotation_variant,
            workspace.create.run_variant,
            workspace.run.run_media_summary,
            workspace.review.variant_choice,
        ],
    )
    workspace.annotation.prepare_annotation_button.click(
        creation._prepare_annotation,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation_state,
        ],
        [
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.configuration_slots_view,
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_overview,
            workspace.annotation.annotation_wizard,
            workspace.annotation.annotation_tool,
            workspace.annotation.annotation_item_id,
            workspace.annotation.annotation_item_label,
            workspace.annotation.annotation_delete_target,
        ],
    )
    workspace.annotation.annotation_canvas.select(
        _canvas_click,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation.annotation_tool,
            workspace.annotation_state,
        ],
        [
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_status,
        ],
    )
    workspace.annotation.annotation_drag.input(
        controller.set_annotation_drag,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation.annotation_tool,
            workspace.annotation_state,
            workspace.annotation.annotation_drag,
        ],
        [
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_status,
        ],
    )
    _tool_hints = {
        "rectangle": "**矩形**：在画布上按住左键拖拽，松开后点击「保存并继续下一项」。",
        "polygon": "**多边形**：沿区域边界逐点点击，可用「撤销上一步」修正；点完后点击「保存并继续下一项」。",
        "direction": "**方向箭头**：按住鼠标**顺着车辆正常行驶方向**拖拽（从车尾拖到车头）定义正常方向；与箭头相反的轨迹判为逆行。方向反了可点「反转方向（方向箭头）」。",
    }
    workspace.annotation.annotation_slot.input(
        _select_annotation_slot,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation_state,
        ],
        [
            workspace.annotation.annotation_tool,
            workspace.annotation.annotation_item_id,
            workspace.annotation.annotation_item_label,
            workspace.annotation.annotation_delete_target,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_status,
            workspace.annotation.configuration_slots_view,
        ],
    )
    workspace.annotation.annotation_tool.change(
        _change_annotation_tool,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation.annotation_tool,
            workspace.annotation_state,
        ],
        [
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_tool,
            workspace.annotation.annotation_item_id,
            workspace.annotation.annotation_item_label,
            workspace.annotation.annotation_delete_target,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_status,
            workspace.annotation.tool_hint,
            workspace.annotation.configuration_slots_view,
        ],
    )
    workspace.annotation.undo_annotation_button.click(
        controller.undo_annotation_point,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation_state,
        ],
        [
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_status,
        ],
    )
    workspace.annotation.clear_annotation_button.click(
        runtime_edit(controller, controller.clear_saved_annotations),
        [
            workspace.review.editor_document,
            *[
                workspace.review.effective,
                workspace.annotation.annotation_variant,
                workspace.annotation.annotation_asset_path,
                workspace.annotation.annotation_timestamp,
                workspace.annotation_state,
            ],
        ],
        [
            workspace.review.effective,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_status,
        ],
    ).then(
        creation._prepare_annotation,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation_state,
        ],
        [
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.configuration_slots_view,
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_overview,
            workspace.annotation.annotation_wizard,
            workspace.annotation.annotation_tool,
            workspace.annotation.annotation_item_id,
            workspace.annotation.annotation_item_label,
            workspace.annotation.annotation_delete_target,
        ],
    )
    workspace.annotation.reverse_direction_button.click(
        controller.reverse_annotation_direction,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation_state,
        ],
        [
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_status,
        ],
    )
    workspace.annotation.bind_annotation_button.click(
        runtime_edit(controller, _bind_and_refresh),
        [
            workspace.review.editor_document,
            *[
                workspace.review.effective,
                workspace.annotation.annotation_variant,
                workspace.annotation.annotation_slot,
                workspace.annotation.annotation_tool,
                workspace.annotation.annotation_points,
                workspace.annotation.annotation_item_id,
                workspace.annotation.annotation_item_label,
                workspace.annotation.annotation_asset_path,
                workspace.annotation.annotation_timestamp,
                workspace.annotation_state,
            ],
        ],
        [
            workspace.review.effective,
            workspace.annotation.configuration_slots_view,
            workspace.annotation.annotation_status,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_wizard,
            workspace.annotation.annotation_tool,
            workspace.annotation.annotation_item_id,
            workspace.annotation.annotation_item_label,
            workspace.annotation.annotation_delete_target,
        ],
    ).then(
        # Refresh the visible condition cards immediately from the saved
        # annotation JSON.  Do not make this dependent on the legacy rule
        # reader, whose auxiliary updates can be delayed independently.
        events._event_card_updates,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.review.event_rule_event,
        ],
        events.event_rule_card_outputs,
    ).then(
        events._read_event_rule_updates,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.review.event_rule_event,
        ],
        events.event_rule_outputs,
    ).then(
        business._read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.annotation.annotation_variant,
            workspace.create.source_mode,
        ],
        business._unified_editor_outputs,
    )
    workspace.annotation.add_region_button.click(
        _add_another_named_region,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_timestamp,
            workspace.annotation_state,
        ],
        [
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_tool,
            workspace.annotation.annotation_item_id,
            workspace.annotation.annotation_item_label,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_points,
            workspace.annotation.annotation_status,
            workspace.annotation.annotation_delete_target,
            workspace.annotation.configuration_slots_view,
        ],
    )
    workspace.annotation.delete_annotation_button.click(
        runtime_edit(controller, _delete_and_refresh),
        [
            workspace.review.editor_document,
            *[
                workspace.review.effective,
                workspace.annotation.annotation_variant,
                workspace.annotation.annotation_slot,
                workspace.annotation.annotation_delete_target,
                workspace.annotation.annotation_asset_path,
                workspace.annotation.annotation_timestamp,
                workspace.annotation_state,
            ],
        ],
        [
            workspace.review.effective,
            workspace.annotation.configuration_slots_view,
            workspace.annotation.annotation_status,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_slot,
            workspace.annotation.annotation_wizard,
            workspace.annotation.annotation_delete_target,
        ],
    ).then(
        events._read_event_rule_updates,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.review.event_rule_event,
        ],
        events.event_rule_outputs,
    ).then(
        events._event_card_updates,
        [
            workspace.review.effective,
            workspace.annotation.annotation_variant,
            workspace.review.event_rule_event,
        ],
        events.event_rule_card_outputs,
    ).then(
        business._read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.annotation.annotation_variant,
            workspace.create.source_mode,
        ],
        business._unified_editor_outputs,
    )
    workspace.annotation.set_default_media_button.click(
        controller.set_preset_default_media,
        [workspace.current_preset_state, workspace.annotation.annotation_asset_path],
        [
            workspace.annotation.annotation_asset_path,
            workspace.annotation.preset_media_candidates,
            workspace.annotation.annotation_status,
        ],
    )
    workspace.run.inspect_button.click(
        controller.inspect_media,
        [
            workspace.review.effective,
            workspace.create.run_variant,
            workspace.create.media,
        ],
        [workspace.run.policy_text, workspace.run.policy_json],
    )
