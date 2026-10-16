"""Annotation page layout; callbacks live in ui.v2.bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

from dataclasses import dataclass

import gradio as gr

from ui.v2.presentation import ANNOTATION_GUIDANCE_MARKDOWN


@dataclass(frozen=True)
class AnnotationPage:
    """Explicit page handles consumed by event registration."""

    add_region_button: gr.Button
    annotation_asset_path: gr.Textbox
    annotation_canvas: gr.Image
    annotation_delete_target: gr.Dropdown
    annotation_drag: gr.Textbox
    annotation_item_id: gr.Textbox
    annotation_item_label: gr.Textbox
    annotation_metadata: gr.JSON
    annotation_overview: gr.Markdown
    annotation_points: gr.Textbox
    annotation_slot: gr.Dropdown
    annotation_status: gr.Textbox
    annotation_timestamp: gr.Number
    annotation_tool: gr.Radio
    annotation_variant: gr.Radio
    annotation_wizard: gr.Markdown
    bind_annotation_button: gr.Button
    clear_annotation_button: gr.Button
    configuration_slots_view: gr.JSON
    delete_annotation_button: gr.Button
    prepare_annotation_button: gr.Button
    preset_media_candidates: gr.JSON
    reverse_direction_button: gr.Button
    set_default_media_button: gr.Button
    tool_hint: gr.Markdown
    undo_annotation_button: gr.Button


def build_annotation_page(controller: V2AppController) -> AnnotationPage:
    with gr.Tab("02 标注"):
        gr.HTML(ANNOTATION_GUIDANCE_MARKDOWN, padding=False)
        annotation_overview = gr.Markdown(
            "此技能无需标注场景，可直接去“04 运行与结果”。",
            elem_classes="status-card",
        )
        gr.Markdown(
            "**通用标注向导**：当规则要求一个或多个命名区域时，在当前媒体上选择矩形或多边形并点击“保存并继续下一项”；需要更多区域时点击“添加另一个区域”。区域/车道数量无需预先确定，内部 ID 由系统自动生成，用户只需按需填写显示名称。当规则还要求逐区域方向参考时，全部区域保存后，再依次绘制方向箭头。箭头的业务含义以当前技能规则为准；画反时可点「反转方向（方向箭头）」。",
            elem_classes="vs-tool-hint",
        )
        annotation_wizard = gr.Markdown(
            "### 配置向导\n当前技能没有待配置的区域或方向。",
            elem_classes="status-card",
        )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### ① 准备标注画布\n画布使用「01 创建」中选好的任务媒体；视频任务可指定取哪一秒的画面来标注。"
            )
            with gr.Row():
                annotation_timestamp = gr.Number(
                    0.0, label="视频标注帧时间（秒，图片任务忽略）"
                )
                prepare_annotation_button = gr.Button("加载画布", variant="secondary")
            annotation_status = gr.Textbox(label="标注状态", interactive=False)
            annotation_asset_path = gr.Textbox(
                label="当前内容寻址媒体路径", interactive=False, visible=False
            )
            annotation_metadata = gr.JSON(label="原始媒体元数据", visible=False)
            with gr.Row():
                annotation_variant = gr.Radio(
                    ["image", "video"], value="image", label="标注媒体类型"
                )
                annotation_slot = gr.Dropdown(
                    label="要绘制的区域/方向（技能需要几个就画几个）"
                )
            configuration_slots_view = gr.JSON(
                label="配置槽状态（当前选择已标记）", visible=True
            )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown("### ② 选择工具、在画布上绘制，然后保存")
            annotation_canvas = gr.Image(
                label="标注画布（在原图上直接绘制）",
                type="pil",
                interactive=False,
                elem_id="vs-annotation-canvas",
                elem_classes="vs-annotation-canvas",
            )
            annotation_tool = gr.Radio(
                [
                    ("矩形", "rectangle"),
                    ("多边形", "polygon"),
                    ("方向箭头", "direction"),
                ],
                value="rectangle",
                label="标注工具",
                elem_id="vs-annotation-tool",
            )
            tool_hint = gr.Markdown(
                "**矩形**：在画布上按住左键拖拽，松开后点击「保存并继续下一项」。",
                elem_classes="vs-tool-hint",
            )
            with gr.Accordion("区域显示名称（可选）", open=False):
                with gr.Row():
                    annotation_item_id = gr.Textbox(label="系统内部 ID", visible=False)
                    annotation_item_label = gr.Textbox(
                        label="显示名称（留空则自动命名）"
                    )
                preset_media_candidates = gr.JSON(label="预置素材候选", visible=False)
            annotation_points = gr.Textbox(
                "[]", visible="hidden", elem_id="vs-annotation-points"
            )
            annotation_drag = gr.Textbox(
                "", visible="hidden", elem_id="vs-annotation-drag"
            )
            with gr.Row():
                annotation_delete_target = gr.Dropdown(
                    label="删除已保存标注（先选择要删除的车道或箭头）",
                    choices=[],
                    value=None,
                    allow_custom_value=True,
                )
                delete_annotation_button = gr.Button("删除已保存标注", variant="stop")
            with gr.Row():
                undo_annotation_button = gr.Button("撤销上一步", variant="secondary")
                clear_annotation_button = gr.Button("清空已有标注", variant="stop")
                reverse_direction_button = gr.Button(
                    "反转方向（方向箭头）", variant="secondary"
                )
                bind_annotation_button = gr.Button(
                    "保存并继续下一项", variant="primary"
                )
                add_region_button = gr.Button("添加另一个区域", variant="secondary")
            with gr.Accordion("预置素材管理（高级）", open=False):
                set_default_media_button = gr.Button(
                    "将当前任务媒体设为预置默认素材", variant="secondary"
                )

    return AnnotationPage(
        add_region_button=add_region_button,
        annotation_asset_path=annotation_asset_path,
        annotation_canvas=annotation_canvas,
        annotation_delete_target=annotation_delete_target,
        annotation_drag=annotation_drag,
        annotation_item_id=annotation_item_id,
        annotation_item_label=annotation_item_label,
        annotation_metadata=annotation_metadata,
        annotation_overview=annotation_overview,
        annotation_points=annotation_points,
        annotation_slot=annotation_slot,
        annotation_status=annotation_status,
        annotation_timestamp=annotation_timestamp,
        annotation_tool=annotation_tool,
        annotation_variant=annotation_variant,
        annotation_wizard=annotation_wizard,
        bind_annotation_button=bind_annotation_button,
        clear_annotation_button=clear_annotation_button,
        configuration_slots_view=configuration_slots_view,
        delete_annotation_button=delete_annotation_button,
        prepare_annotation_button=prepare_annotation_button,
        preset_media_candidates=preset_media_candidates,
        reverse_direction_button=reverse_direction_button,
        set_default_media_button=set_default_media_button,
        tool_hint=tool_hint,
        undo_annotation_button=undo_annotation_button,
    )
