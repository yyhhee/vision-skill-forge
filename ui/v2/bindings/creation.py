"""Creation page event registration; preserves callback order and signatures."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

from dataclasses import dataclass

import gradio as gr

from application.v2.support import json_object_or_empty
from ui.v2.workspace import Workspace


@dataclass(frozen=True)
class CreationBindings:
    _configuration_guidance: Callable[..., Any]
    _ingest_task_media: Callable[..., Any]
    _load_asset: Callable[..., Any]
    _mirror_asset_root: Callable[..., Any]
    _prepare_annotation: Callable[..., Any]
    _refresh_saved_choices: Callable[..., Any]
    _slot_updates: Callable[..., Any]
    _sync_run_variant: Callable[..., Any]
    _temporal_summary: Callable[..., Any]
    _unresolved_of: Callable[..., Any]


def bind_creation(
    controller: V2AppController, workspace: Workspace
) -> CreationBindings:
    def _switch_source(mode):
        return (
            gr.update(visible=mode == "自然语言生成"),
            gr.update(visible=mode == "预置演示技能"),
            gr.update(visible=mode == "已保存技能"),
            "",
            "",
            "",
            {},
            "### 当前实际执行来源\n尚未生成或加载技能。",
        )

    def _expand_loaded(generated, effective_json, semantic_json, status, source):
        semantic_data = json_object_or_empty(semantic_json)
        package_data = json_object_or_empty(effective_json)
        return (
            generated,
            effective_json,
            semantic_json,
            semantic_data.get("unresolved", []),
            status,
            source,
            package_data.get("original_instruction", ""),
        )

    def _unresolved_of(semantic_json):
        return json_object_or_empty(semantic_json).get("unresolved", [])

    def _load_asset(selection, save_root_value):
        generated, effective_json, semantic_json, status, source = (
            controller.load_saved_skill(selection, save_root_value)
        )
        return (
            generated,
            effective_json,
            semantic_json,
            status,
            source,
            _instruction_of(effective_json),
        )

    def _refresh_saved_choices(saved_root_value, asset_root_value):
        saved_choices = controller.saved_skill_choices(saved_root_value)
        asset_choices = controller.saved_skill_choices(asset_root_value)
        return (
            gr.update(choices=saved_choices, value=None),
            gr.update(choices=asset_choices, value=None),
        )

    def _mirror_asset_root(asset_root_value):
        choices = controller.saved_skill_choices(asset_root_value)
        return (
            gr.update(value=asset_root_value),
            gr.update(choices=choices, value=None),
            gr.update(choices=choices, value=None),
        )

    def _instruction_of(effective_json):
        return json_object_or_empty(effective_json).get("original_instruction", "")

    def _temporal_summary(effective_json, media_type):
        return controller.temporal_rules_markdown(effective_json, media_type)

    def _configuration_guidance(effective_json, media_type):
        return controller.configuration_guidance_markdown(effective_json, media_type)

    def _slot_updates(effective_json, media_type):
        if not effective_json:
            return (
                gr.update(choices=[], value=None),
                [],
                "尚未生成或加载技能。",
                "### 配置向导\n请先创建或加载技能。",
            )
        try:
            choices, rows = controller.annotation_slots(effective_json, media_type)
        except (ValueError, TypeError):
            return (
                gr.update(choices=[], value=None),
                [],
                "技能尚未生成成功，无法读取场景标注配置。",
                "### 配置向导\n暂时无法读取配置槽。",
            )
        choices, value = controller.annotation_slot_options(effective_json, media_type)
        return (
            gr.update(choices=choices, value=value, interactive=bool(rows)),
            controller.annotation_slots_with_selection(
                effective_json, media_type, value
            ),
            controller.annotation_overview(effective_json, media_type),
            controller.annotation_wizard_markdown(effective_json, media_type),
        )

    def _prepare_annotation(effective_json, media_type, path, timestamp, state):
        if not effective_json or not path:
            return (
                gr.update(),
                dict(state or {}),
                [],
                gr.update(choices=[], value=None, interactive=False),
                "请先加载技能和任务媒体，再开始标注。",
                "### 配置向导\n请先加载技能和任务媒体。",
                gr.update(
                    choices=[("矩形", "rectangle"), ("多边形", "polygon")],
                    value="rectangle",
                ),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(choices=[], value=None),
            )
        preview, new_state, rows = controller.refresh_annotation_preview(  # noqa: RUF059 — preserved V2 behavior
            effective_json, media_type, path, timestamp, state
        )
        choices, _ = controller.annotation_slots(effective_json, media_type)
        wizard = controller.annotation_wizard_state(effective_json, media_type)
        value = wizard["current_slot"] or (choices[0][1] if choices else None)
        tool, item_id, item_label = controller.annotation_wizard_defaults(
            effective_json, media_type, value
        )
        delete_choices = controller.named_item_choices(
            effective_json, media_type, value
        )
        return (
            preview,
            new_state,
            controller.annotation_slots_with_selection(
                effective_json, media_type, value
            ),
            gr.update(choices=choices, value=value),
            controller.annotation_overview(effective_json, media_type),
            controller.annotation_wizard_markdown(effective_json, media_type),
            gr.update(
                choices=controller.annotation_tool_choices(
                    effective_json, media_type, value
                ),
                value=tool,
            ),
            gr.update(value=item_id),
            gr.update(value=item_label),
            gr.update(choices=delete_choices, value=None),
        )

    def _ingest_task_media(path, timestamp):
        if not path:
            return controller.cleared_task_media_state()
        stored_path, metadata, preview, state, status = controller.ingest_media(
            path, timestamp
        )
        media_type = state["media_type"]
        return (
            stored_path,
            metadata,
            preview,
            state,
            status,
            media_type,
            media_type,
            controller.runtime_media_summary(stored_path, media_type),
            controller.editor_variant_for_media(media_type),
        )

    def _sync_run_variant(effective_json, preferred):
        return controller.preferred_executable_variant(effective_json, preferred)

    def _refresh_generated_editor_document(effective_json, source_mode_value):
        """Project the newly generated package into the 03 editor immediately.

        The generation callback updates ``effective`` first.  Keeping the
        editor document as an explicit follow-up output prevents a prior
        natural-language document from remaining visible while the new
        package is already selected in the other tabs.
        """

        if not effective_json:
            return ""
        source_type = {
            "自然语言生成": "natural_language",
            "预置演示技能": "preset",
            "已保存技能": "legacy",
        }.get(source_mode_value, "legacy")
        document = controller._editor_document(
            effective_json, "", source_type=source_type
        )
        return controller._dump(document)

    workspace.create.source_mode.change(
        _switch_source,
        workspace.create.source_mode,
        [
            workspace.create.natural_group,
            workspace.create.preset_group,
            workspace.create.saved_group,
            workspace.generated_state,
            workspace.review.effective,
            workspace.review.semantic,
            workspace.review.unresolved,
            workspace.current_source,
        ],
    )
    workspace.create.compile_button.click(
        controller.compile_skill,
        [
            workspace.create.instruction,
            workspace.create.media_choice,
            workspace.create.skill_id,
            workspace.create.display_name,
            workspace.review.effective,
        ],
        [
            workspace.generated_state,
            workspace.review.effective,
            workspace.review.semantic,
            workspace.create.source_status,
            workspace.current_source,
        ],
    ).then(
        _refresh_generated_editor_document,
        [workspace.review.effective, workspace.create.source_mode],
        workspace.review.editor_document,
    ).then(
        _unresolved_of,
        workspace.review.semantic,
        workspace.review.unresolved,
    ).then(
        _instruction_of, workspace.review.effective, workspace.create.task_target
    ).then(
        lambda choice: "video" if choice == "仅视频" else "image",
        workspace.create.media_choice,
        workspace.annotation.annotation_variant,
    ).then(
        controller.preferred_executable_variant,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.annotation.annotation_variant,
    ).then(
        _sync_run_variant,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.run_variant,
    ).then(
        controller.editor_variant_for_media,
        workspace.annotation.annotation_variant,
        workspace.review.variant_choice,
    ).then(
        _slot_updates,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        [
            workspace.annotation.annotation_slot,
            workspace.annotation.configuration_slots_view,
            workspace.annotation.annotation_overview,
            workspace.annotation.annotation_wizard,
        ],
    ).then(
        _temporal_summary,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.review.event_rule_summary,
    ).then(
        _configuration_guidance,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.configuration_guidance,
    )
    workspace.create.preset_button.click(
        controller.load_preset_bundle,
        [workspace.create.preset, workspace.annotation.annotation_timestamp],
        [
            workspace.generated_state,
            workspace.review.effective,
            workspace.review.semantic,
            workspace.create.source_status,
            workspace.current_source,
            workspace.annotation.annotation_variant,
            workspace.create.run_variant,
            workspace.annotation.annotation_asset_path,
            workspace.annotation.annotation_metadata,
            workspace.annotation.preset_media_candidates,
            workspace.create.media,
            workspace.create.task_target,
            workspace.annotation.annotation_canvas,
            workspace.annotation_state,
            workspace.annotation.annotation_status,
            workspace.current_preset_state,
            workspace.annotation.annotation_points,
            workspace.run.run_media_summary,
            workspace.review.variant_choice,
        ],
    ).then(
        controller.load_editor_configuration,
        [workspace.review.effective, workspace.create.source_mode],
        workspace.review.editor_document,
    ).then(
        _unresolved_of,
        workspace.review.semantic,
        workspace.review.unresolved,
    ).then(
        controller.preferred_executable_variant,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.annotation.annotation_variant,
    ).then(
        _sync_run_variant,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.run_variant,
    ).then(
        controller.editor_variant_for_media,
        workspace.annotation.annotation_variant,
        workspace.review.variant_choice,
    ).then(
        _slot_updates,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        [
            workspace.annotation.annotation_slot,
            workspace.annotation.configuration_slots_view,
            workspace.annotation.annotation_overview,
            workspace.annotation.annotation_wizard,
        ],
    ).then(
        _temporal_summary,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.review.event_rule_summary,
    ).then(
        _configuration_guidance,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.configuration_guidance,
    )
    workspace.create.saved_button.click(
        controller.load_saved_skill,
        [workspace.create.saved, workspace.create.saved_root],
        [
            workspace.generated_state,
            workspace.review.effective,
            workspace.review.semantic,
            workspace.create.source_status,
            workspace.current_source,
        ],
    ).then(
        controller.load_editor_configuration,
        [workspace.review.effective, workspace.create.source_mode],
        workspace.review.editor_document,
    ).then(_unresolved_of, workspace.review.semantic, workspace.review.unresolved).then(
        controller.preferred_executable_variant,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.annotation.annotation_variant,
    ).then(
        _sync_run_variant,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.run_variant,
    ).then(
        controller.editor_variant_for_media,
        workspace.annotation.annotation_variant,
        workspace.review.variant_choice,
    ).then(
        _slot_updates,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        [
            workspace.annotation.annotation_slot,
            workspace.annotation.configuration_slots_view,
            workspace.annotation.annotation_overview,
            workspace.annotation.annotation_wizard,
        ],
    ).then(
        _temporal_summary,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.review.event_rule_summary,
    ).then(
        _configuration_guidance,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.configuration_guidance,
    )
    workspace.create.delete_button.click(
        controller.delete_saved_skill,
        [workspace.create.saved, workspace.create.saved_root],
        workspace.create.source_status,
    ).then(
        lambda root: gr.update(
            choices=controller.saved_skill_choices(root), value=None
        ),
        workspace.create.saved_root,
        outputs=workspace.create.saved,
    )
    workspace.create.saved_refresh_button.click(
        lambda root: gr.update(
            choices=controller.saved_skill_choices(root), value=None
        ),
        workspace.create.saved_root,
        workspace.create.saved,
    )
    workspace.create.saved_root.change(
        lambda root: gr.update(
            choices=controller.saved_skill_choices(root), value=None
        ),
        workspace.create.saved_root,
        workspace.create.saved,
    )

    return CreationBindings(
        _configuration_guidance=_configuration_guidance,
        _ingest_task_media=_ingest_task_media,
        _load_asset=_load_asset,
        _mirror_asset_root=_mirror_asset_root,
        _prepare_annotation=_prepare_annotation,
        _refresh_saved_choices=_refresh_saved_choices,
        _slot_updates=_slot_updates,
        _sync_run_variant=_sync_run_variant,
        _temporal_summary=_temporal_summary,
        _unresolved_of=_unresolved_of,
    )
