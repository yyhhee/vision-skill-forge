"""Run page layout; callbacks live in ui.v2.bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

from dataclasses import dataclass

import gradio as gr


@dataclass(frozen=True)
class RunPage:
    """Explicit page handles consumed by event registration."""

    configuration_state: gr.HTML

    annotated_image: gr.Image
    annotated_video: gr.Video
    business_results_html: gr.HTML
    constraints: gr.JSON
    detections: gr.JSON
    directions: gr.JSON
    events: gr.JSON
    inspect_button: gr.Button
    measurements: gr.JSON
    policy_json: gr.JSON
    policy_text: gr.Textbox
    regions: gr.JSON
    run_button: gr.Button
    run_dir: gr.Textbox
    run_media_summary: gr.Markdown
    run_status: gr.Textbox
    trace: gr.JSON
    tracks: gr.JSON


def build_run_page(controller: V2AppController) -> RunPage:
    with gr.Tab("04 运行"):
        configuration_state = gr.HTML(
            "<div class='status-card'><b>尚未加载运行版本</b></div>",
            elem_id="configuration-lifecycle-run",
        )
        gr.HTML(
            """
                    <section class="vs-section">
                      <h2>执行当前技能并查看结果</h2>
                      <p class="vs-section-copy">这里运行 03 已审核的当前配置。完成后先看最终结论，再看业务输出；只有需要解释或排查时才展开分支证据与运行细节。</p>
                      <div class="vs-guide">
                        <div class="vs-guide-item"><b>1. 目标与 variant</b><span>必须与实际上传的媒体类型一致。</span></div>
                        <div class="vs-guide-item"><b>2. 调用估算</b><span>视频会明确显示抽样帧数、调用次数和时长警告。</span></div>
                        <div class="vs-guide-item"><b>3. 运行</b><span>执行的是当前 Effective 配置，不是隐藏预置。</span></div>
                        <div class="vs-guide-item"><b>4. 验证结果</b><span>按“最终结果 → 业务输出 → 分支与证据”阅读。</span></div>
                      </div>
                    </section>
                    """,
            padding=False,
        )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### ① 检查并运行\n任务媒体已在“01 创建技能”中选择。预置演示加载后可直接检查和运行。"
            )
            run_media_summary = gr.Markdown(
                "**本次运行媒体：尚未选择。** 请返回“01 创建技能”的“当前任务媒体”上传或加载素材。",
                elem_classes="vs-source-card",
            )
            with gr.Row():
                inspect_button = gr.Button("检查媒体与调用估算", variant="secondary")
                run_button = gr.Button("运行当前 Effective 技能", variant="primary")
            policy_text = gr.Textbox(label="调用估算", interactive=False)
            with gr.Accordion("媒体策略与调用明细（高级）", open=False):
                policy_json = gr.JSON(label="媒体策略（30 秒推荐 / warn-only）")
            run_status = gr.Textbox(label="运行状态", lines=3)
            run_dir = gr.Textbox(label="运行产物目录", interactive=False)
        with gr.Group(elem_classes="vs-section"):
            business_results_html = gr.HTML(
                '<section class="vs-business-results">'
                '<div class="vs-final-result"><h3>最终结果</h3>'
                "<p>运行后显示“发生了没有、成功了没有、最终值是否满足”。</p></div>"
                "<section><h3>业务输出</h3><p>显示 03 配置的数量、事件、框、轨迹、持续时间和时间线。</p></section>"
                "<section><h3>分支与证据</h3><p>按需解释成立、未成立或无法判断的原因。</p></section>"
                "</section>"
            )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### 可视化证据\n这里显示与媒体类型匹配的标注结果（图片任务出图，视频任务出视频）。"
            )
            gr.Markdown("点击结果媒体可查看原尺寸；按 Esc 或关闭按钮返回。")
            with gr.Row():
                annotated_image = gr.Image(
                    label="标注图片", visible=False, elem_classes="vs-result-media"
                )
                annotated_video = gr.Video(
                    label="标注视频", visible=False, elem_classes="vs-result-media"
                )
        with gr.Accordion("运行详情（按需查看结构化结果与开发诊断）", open=False):  # noqa: SIM117 — preserved V2 behavior
            with gr.Tabs():
                with gr.Tab("检测结果"):
                    detections = gr.JSON(label="检测结果")
                with gr.Tab("轨迹结果"):
                    tracks = gr.JSON(label="轨迹结果")
                with gr.Tab("事件结果"):
                    events = gr.JSON(label="事件结果")
                with gr.Tab("数值结果"):
                    measurements = gr.JSON(label="数值结果")
                with gr.Tab("区域结果"):
                    regions = gr.JSON(label="区域结果")
                with gr.Tab("方向结果"):
                    directions = gr.JSON(label="方向结果")
                with gr.Tab("语义原子解释"):
                    constraints = gr.JSON(label="语义原子解释")
                with gr.Tab("逐节点 Trace"):
                    trace = gr.JSON(label="逐节点 Trace")

    return RunPage(
        configuration_state=configuration_state,
        annotated_image=annotated_image,
        annotated_video=annotated_video,
        business_results_html=business_results_html,
        constraints=constraints,
        detections=detections,
        directions=directions,
        events=events,
        inspect_button=inspect_button,
        measurements=measurements,
        policy_json=policy_json,
        policy_text=policy_text,
        regions=regions,
        run_button=run_button,
        run_dir=run_dir,
        run_media_summary=run_media_summary,
        run_status=run_status,
        trace=trace,
        tracks=tracks,
    )
