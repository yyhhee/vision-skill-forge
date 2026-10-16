"""Configuration page event registration; preserves callback order and signatures."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

import gradio as gr

from ui.v2.bindings.business import BusinessBindings
from ui.v2.workspace import Workspace


def bind_configuration(
    controller: V2AppController, workspace: Workspace, business: BusinessBindings
) -> None:
    def _read_context_confirmation(effective_json, variant_name):
        values = controller.context_confirmation_control_values(
            effective_json, variant_name
        )
        if values is None:
            return (
                *(gr.skip() for _ in range(5)),
                "请先生成或加载技能，再读取确认配置。",
            )
        return (
            gr.update(choices=values["labels"], value=values["selected_labels"]),
            values["enabled"],
            values["confirmation_phrases"],
            values["padding_fraction"],
            values["crop_long_side"],
            values["status"],
        )

    _context_outputs = [
        workspace.review.context_targets,
        workspace.review.context_enabled,
        workspace.review.context_phrases,
        workspace.review.context_padding,
        workspace.review.context_long_side,
        workspace.review.context_status,
    ]
    workspace.review.context_read_button.click(
        _read_context_confirmation,
        [workspace.review.effective, workspace.review.variant_choice],
        _context_outputs,
    )
    workspace.review.effective.change(
        _read_context_confirmation,
        [workspace.review.effective, workspace.review.variant_choice],
        _context_outputs,
    )
    workspace.review.context_apply_button.click(
        controller.apply_context_confirmation_control,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.context_enabled,
            workspace.review.context_targets,
            workspace.review.context_phrases,
            workspace.review.context_padding,
            workspace.review.context_long_side,
        ],
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    ).then(
        _read_context_confirmation,
        [workspace.review.effective, workspace.review.variant_choice],
        _context_outputs,
    )
    workspace.review.variant_choice.change(
        _read_context_confirmation,
        [workspace.review.effective, workspace.review.variant_choice],
        _context_outputs,
    )

    def _read_grounding_prompt_updates(
        effective_json, variant_name, selected_node_id=None
    ):
        media_type = "video" if variant_name.startswith("video") else "image"
        controls = controller.grounding_prompt_controls(effective_json, media_type)
        if not controls:
            return (
                gr.update(choices=[], value=None),
                "",
                "当前 variant 没有可编辑的 Rex 模型检测节点。",
            )
        selected = next(
            (item for item in controls if item["node_id"] == selected_node_id),
            controls[0],
        )
        choices = [
            (
                f"{item['label']}（{item['node_id']}） · "  # noqa: ISC004 — preserved V2 behavior
                f"{'已覆盖' if item['is_override'] else '默认短语'}",
                item["node_id"],
            )
            for item in controls
        ]
        status = (
            f"当前编辑 {selected['label']}（{selected['node_id']}）。"
            + (
                "已使用自定义视觉查询；"
                if selected["is_override"]
                else "当前为 targets 自动生成的默认短语；"
            )
            + "系统运行时仍会追加固定的框坐标输出协议。"
        )
        return (
            gr.update(choices=choices, value=selected["node_id"]),
            selected["prompt"],
            status,
        )

    _grounding_prompt_outputs = [
        workspace.review.grounding_prompt_node,
        workspace.review.grounding_prompt_text,
        workspace.review.grounding_prompt_status,
    ]
    workspace.review.grounding_prompt_read_button.click(
        _read_grounding_prompt_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.grounding_prompt_node,
        ],
        _grounding_prompt_outputs,
    )
    workspace.review.grounding_prompt_node.input(
        _read_grounding_prompt_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.grounding_prompt_node,
        ],
        _grounding_prompt_outputs,
    )
    workspace.review.grounding_prompt_apply_button.click(
        controller.apply_grounding_prompt_control,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.grounding_prompt_node,
            workspace.review.grounding_prompt_text,
        ],
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    ).then(
        _read_grounding_prompt_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.grounding_prompt_node,
        ],
        _grounding_prompt_outputs,
    )
    workspace.review.grounding_prompt_reset_button.click(
        controller.reset_grounding_prompt_control,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.grounding_prompt_node,
        ],
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    ).then(
        _read_grounding_prompt_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.grounding_prompt_node,
        ],
        _grounding_prompt_outputs,
    )
    workspace.review.variant_choice.change(
        _read_grounding_prompt_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.grounding_prompt_node,
        ],
        _grounding_prompt_outputs,
    )
    _preprocess_inputs = [
        workspace.review.effective,
        workspace.review.variant_choice,
        workspace.review.resize_mode,
        workspace.review.long_side,
        workspace.review.resize_width,
        workspace.review.resize_height,
        workspace.review.tile_enabled,
        workspace.review.tile_width,
        workspace.review.tile_height,
        workspace.review.overlap_x,
        workspace.review.overlap_y,
        workspace.review.include_full,
        workspace.review.dedup_metric,
        workspace.review.dedup_threshold,
        workspace.review.resize_interpolation,
    ]
    workspace.review.resize_apply_button.click(
        controller.apply_preprocessing,
        _preprocess_inputs,
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    )
    workspace.review.preprocess_button.click(
        controller.apply_preprocessing,
        _preprocess_inputs,
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    )
    workspace.review.sample_button.click(
        controller.apply_video_sampling,
        [
            workspace.review.effective,
            workspace.review.sample_mode,
            workspace.review.sample_fps,
            workspace.review.interval_seconds,
            workspace.review.frame_step,
            workspace.review.start_seconds,
            workspace.review.end_seconds,
            workspace.review.max_frames,
        ],
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    )
    workspace.review.output_config_button.click(
        controller.apply_output_configuration,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.output_size_mode,
            workspace.review.output_width,
            workspace.review.output_height,
            workspace.review.output_fps_mode,
            workspace.review.output_fps,
        ],
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    )
