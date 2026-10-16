"""Application assembly: theme, shared state, five pages and event registration."""
from __future__ import annotations

import gradio as gr
from ui.v2.controller import V2AppController
from ui.v2.theme import CSS, ANNOTATION_DRAG_JS
from ui.v2.workspace import Workspace
from ui.v2.bindings import bind_workspace
from ui.v2.pages.create import build_create_page
from ui.v2.pages.annotation import build_annotation_page
from ui.v2.pages.review import build_review_page
from ui.v2.pages.run import build_run_page
from ui.v2.pages.assets import build_assets_page


def build_v2_app(controller: V2AppController) -> gr.Blocks:
    with gr.Blocks(title="Vision Skill Forge", css=CSS, js=ANNOTATION_DRAG_JS) as demo:
        gr.HTML(
            """
            <section class="vs-hero">
              <p class="vs-kicker">VISION SKILL FORGE</p>
              <h1>AI 一句话生成视觉技能</h1>
                      <p>一句话先生成可编辑技能；需要时补充区域或方向参考；最后在图片或视频上运行并查看可解释结果。</p>
              <div class="vs-badges"><span class="vs-badge">自然语言生成</span><span class="vs-badge">可编辑规则</span><span class="vs-badge">图片与视频</span><span class="vs-badge">结果与证据</span></div>
            </section>
            """,
            padding=False,
        )
        gr.HTML(
            """
            <div id="vs-result-media-modal" aria-modal="true" role="dialog" aria-label="原尺寸结果媒体">
              <div class="vs-media-modal-shell">
                <button type="button" class="vs-media-modal-close" data-vs-close-media-modal>关闭</button>
                <img id="vs-result-media-original-image" alt="原尺寸标注结果">
                <video id="vs-result-media-original-video" controls></video>
              </div>
            </div>
            """,
            visible=True,
        )
        gr.HTML(
            """
            <section aria-label="按五步完成一次视觉任务">
              <div class="vs-workflow">
                <div class="vs-step"><span class="vs-step-index">01 创建技能</span><strong>选技能和媒体</strong><span>一句话、预置示例或历史版本，再选任务媒体</span></div>
                <div class="vs-step"><span class="vs-step-index">02 标注场景</span><strong>手工区域 / 方向</strong><span>规则需要空间或方向参考时，先在任务媒体上绘制</span></div>
                <div class="vs-step"><span class="vs-step-index">03 审核配置</span><strong>确认并调优</strong><span>关联已标注区域，再调整阈值、持续和告警</span></div>
                <div class="vs-step"><span class="vs-step-index">04 运行与结果</span><strong>上传并执行</strong><span>先看标注媒体，再看事件和证据</span></div>
                <div class="vs-step"><span class="vs-step-index">05 技能资产</span><strong>保存并复用</strong><span>把确认过的配置保存为独立版本</span></div>
              </div>
            </section>
            """,
            padding=False,
        )
        generated_state = gr.Textbox(visible=False, label="Generated SkillPackage state")
        annotation_state = gr.JSON({}, visible=False, label="Annotation workspace state")
        current_preset_state = gr.Textbox(
            "", visible=False, label="Current preset state"
        )
        current_source = gr.Markdown(
            "### 当前实际执行来源\n尚未生成或加载技能。",
            elem_classes="status-card",
        )

        with gr.Tabs(elem_classes="tab-nav"):
            create = build_create_page(controller)
            annotation = build_annotation_page(controller)
            review = build_review_page(controller)
            run = build_run_page(controller)
            assets = build_assets_page(controller)
        workspace = Workspace(
            create=create,
            annotation=annotation,
            review=review,
            run=run,
            assets=assets,
            generated_state=generated_state,
            annotation_state=annotation_state,
            current_preset_state=current_preset_state,
            current_source=current_source,
        )
        bind_workspace(controller, workspace)
    return demo
