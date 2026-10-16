"""Create page layout; callbacks live in ui.v2.bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

from dataclasses import dataclass

import gradio as gr


@dataclass(frozen=True)
class CreatePage:
    """Explicit page handles consumed by event registration."""

    clear_task_media_button: gr.Button
    compile_button: gr.Button
    configuration_guidance: gr.Markdown
    delete_button: gr.Button
    display_name: gr.Textbox
    instruction: gr.Textbox
    media: gr.File
    media_choice: gr.Radio
    natural_group: object
    preset: gr.Dropdown
    preset_button: gr.Button
    preset_group: object
    run_variant: gr.Radio
    saved: gr.Dropdown
    saved_button: gr.Button
    saved_group: object
    saved_refresh_button: gr.Button
    saved_root: gr.Textbox
    skill_id: gr.Textbox
    source_mode: gr.Radio
    source_status: gr.Textbox
    task_target: gr.Textbox


def build_create_page(controller: V2AppController) -> CreatePage:
    with gr.Tab("01 创建"):
        gr.HTML(
            """
                    <section class="vs-source-card">
                      <strong>从这里开始。生成后如需区域或方向，先进入“02 标注”；再在“03 审核”关联区域并调整事件规则。</strong>
                      <span> 新任务：用一句话创建。先体验：加载预置示例。已有经验：打开保存版本继续修改。</span>
                    </section>
                    <div class="vs-quick-path">
                      <div class="vs-path"><b>新建技能</b><p>描述目标、属性、关系或事件，系统生成可修改的执行规则。</p></div>
                      <div class="vs-path"><b>运行预置示例</b><p>加载已验证技能和默认素材，最快看到图片或视频结果。</p></div>
                      <div class="vs-path"><b>复用已有版本</b><p>加载自己的保存版本，改好后另存，新旧版本互不覆盖。</p></div>
                    </div>
                    """,
            padding=False,
        )
        source_mode = gr.Radio(
            ["自然语言生成", "预置演示技能", "已保存技能"],
            value="自然语言生成",
            label="选择开始方式（互斥）",
            elem_classes="vs-source-mode",
        )
        with gr.Group(visible=True, elem_classes="vs-section") as natural_group:
            gr.Markdown(
                "### 用一句话创建\n只写要识别的目标、属性、关系或事件；ROI、切片和抽帧在下一步按需配置。"
            )
            gr.Markdown(
                "**示例 1：** 识别未带安全帽的人。  \n"
                "**示例 2：** 区域1有穿红色上衣、灰色裤子的人，区域2有至少2个人，则发出区域告警事件。"
            )
            instruction = gr.Textbox(
                label="一句自然语言",
                lines=3,
                placeholder="输入一句话描述你要创建的视觉技能",
            )
            with gr.Row():
                skill_id = gr.Textbox(
                    "my_visual_skill",
                    label="技能标识（英文，字母开头，可含数字、_、-）",
                )
                display_name = gr.Textbox("我的视觉技能", label="显示名称")
            media_choice = gr.Radio(
                ["仅图片", "仅视频", "图片和视频"],
                value="仅图片",
                label="媒体能力",
                info="由用户明确选择。系统会校验规则能否在所选媒体上执行，不会自动改成其它类型。",
            )
            compile_button = gr.Button("生成技能并继续", variant="primary")
        with gr.Group(visible=False, elem_classes="vs-section") as preset_group:
            gr.Markdown(
                "### 加载预置演示\n系统会一并加载已验证技能和对应的默认媒体，随后直接去“04 运行与结果”。"
            )
            preset = gr.Dropdown(controller.preset_names(), label="预置演示技能")
            preset_button = gr.Button("加载预置", variant="primary")
        with gr.Group(visible=False, elem_classes="vs-section") as saved_group:
            gr.Markdown("### 打开保存版本\n仅自定义版本可以删除；预置技能不可删除。")
            saved_root = gr.Textbox(
                label="技能资产目录",
                value=controller.asset_save_root(),
                interactive=True,
                info="从此目录下的 generated_packages 和 skill_documents 读取；可与 05 的保存目录保持一致。",
            )
            saved = gr.Dropdown(controller.saved_skill_choices(), label="已保存技能")
            with gr.Row():
                saved_button = gr.Button("加载保存版本", variant="primary")
                saved_refresh_button = gr.Button("刷新列表", variant="secondary")
                delete_button = gr.Button("删除选中自定义版本", variant="stop")
        source_status = gr.Textbox(
            label="生成/加载状态", interactive=False, elem_classes="vs-status-output"
        )
        configuration_guidance = gr.Markdown(
            "### 识别出的原子能力\n生成或加载技能后，这里会说明原文约束、当前配置和下一步。",
            elem_classes="status-card",
        )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### 当前任务媒体\n预置演示会自动带入默认素材；自定义技能在这里上传一次，后续标注和运行都使用这同一份媒体。"
            )
            task_target = gr.Textbox(label="任务目标", interactive=False)
            with gr.Row():
                run_variant = gr.Radio(
                    ["image", "video"], value="image", label="实际执行 variant"
                )
                media = gr.File(
                    label="当前任务媒体（图片或视频）",
                    type="filepath",
                )
            clear_task_media_button = gr.Button("清除任务媒体", variant="secondary")

    return CreatePage(
        clear_task_media_button=clear_task_media_button,
        compile_button=compile_button,
        configuration_guidance=configuration_guidance,
        delete_button=delete_button,
        display_name=display_name,
        instruction=instruction,
        media=media,
        media_choice=media_choice,
        natural_group=natural_group,
        preset=preset,
        preset_button=preset_button,
        preset_group=preset_group,
        run_variant=run_variant,
        saved=saved,
        saved_button=saved_button,
        saved_group=saved_group,
        saved_refresh_button=saved_refresh_button,
        saved_root=saved_root,
        skill_id=skill_id,
        source_mode=source_mode,
        source_status=source_status,
        task_target=task_target,
    )
