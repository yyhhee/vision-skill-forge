"""Assets page layout; callbacks live in ui.v2.bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

from dataclasses import dataclass

import gradio as gr

from core.operator_asset_catalog import build_operator_asset_catalog


@dataclass(frozen=True)
class AssetsPage:
    """Explicit page handles consumed by event registration."""

    asset_delete_button: gr.Button
    asset_load_button: gr.Button
    asset_refresh_button: gr.Button
    asset_save_button: gr.Button
    asset_save_display: gr.Textbox
    asset_save_id: gr.Textbox
    asset_save_path: gr.Textbox
    asset_save_root: gr.Textbox
    asset_saved: gr.Dropdown
    asset_status: gr.Textbox
    capability_asset_detail: gr.JSON
    capability_asset_select: gr.Dropdown
    effective_asset_refresh: gr.Button
    effective_asset_view: gr.JSON
    operator_asset_detail: gr.JSON
    operator_asset_layer: gr.Radio
    operator_asset_layers: dict[str, list[dict[str, Any]]]
    operator_asset_select: gr.Dropdown


def build_assets_page(controller: V2AppController) -> AssetsPage:
    with gr.Tab("05 资产"):
        gr.HTML(
            """
                    <section class="vs-section">
                      <h2>技能资产与固定能力</h2>
                      <p class="vs-section-copy">在这里把当前 Effective SkillPackage 保存为可复用版本，或加载、删除此前确认过的自定义版本。保存的是当前可执行配置，预置技能不会被删除或覆盖。</p>
                    </section>
                    """,
            padding=False,
        )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### 保存当前配置\n保存后生成独立版本；同一个技能标识会自动递增版本号。"
            )
            with gr.Row():
                asset_save_id = gr.Textbox(label="资产保存技能标识")
                asset_save_display = gr.Textbox(label="资产保存显示名称")
            asset_save_root = gr.Textbox(
                label="资产保存目录（可修改）",
                value=controller.asset_save_root(),
                interactive=True,
                info="将在此目录下分别创建 generated_packages 和 skill_documents。相对路径按项目目录解析。",
            )
            asset_save_button = gr.Button("保存为独立版本", variant="primary")
            asset_save_path = gr.Textbox(
                label="本次保存结果", interactive=False, lines=2
            )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### 已保存版本\n加载会写回当前 Effective SkillPackage；删除只影响选中的自定义版本。"
            )
            asset_saved = gr.Dropdown(
                controller.saved_skill_choices(), label="已保存版本"
            )
            with gr.Row():
                asset_load_button = gr.Button("加载选中版本", variant="primary")
                asset_refresh_button = gr.Button("刷新列表", variant="secondary")
                asset_delete_button = gr.Button("删除选中版本", variant="stop")
            asset_status = gr.Textbox(label="资产操作状态", interactive=False)
        capability_assets = controller.business_capabilities.definitions()
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### 业务能力资产库\n"
                "按业务类别查看 03 可组合的能力。选择一项后可查看输入输出、媒体要求、资源要求、可编辑参数、编译 Recipe 和证据契约。"
            )
            with gr.Accordion("业务能力资产库是做什么的？", open=False):
                gr.Markdown(
                    "业务能力是面向业务需求的可组合语义，例如检测目标、判断可见属性、限定区域、统计数量、判断关系或持续时间、发出事件。\n\n"
                    "一句话生成技能时，大模型只在这一层理解并生成业务规则；随后系统会将每项业务能力自动编译为所需的执行原子。"
                    "这里用于查看能力说明和可编辑业务参数，不需要手动选择抽帧、去重等底层执行步骤。\n\n"
                    "通用编排约束：每个可独立判定的主体、命名区域或事件链建立独立分支；"
                    "分支内用递归 AND / OR / NOT / N-of-M 组合属性、数量、关系和状态条件；"
                    "最后再按用户原句把多个分支汇合并触发事件。P01–P13 仅用于回归验证，不会被当作模板复制。"
                )
            capability_asset_rows = gr.Dataframe(  # noqa: F841 — preserved V2 behavior
                headers=["类别", "业务能力", "媒体", "所需标注", "编译组合"],
                datatype=["str", "str", "str", "str", "str"],
                value=[
                    [
                        item.category,
                        item.display_name,
                        "、".join(item.media_requirements),
                        "、".join(item.resource_requirements) or "无",
                        item.compiler_recipe,
                    ]
                    for item in capability_assets
                ],
                interactive=False,
                wrap=True,
            )
            capability_asset_select = gr.Dropdown(
                choices=[
                    (
                        f"{item.category}｜{item.display_name}",
                        item.capability_id,
                    )
                    for item in capability_assets
                ],
                value=capability_assets[0].capability_id,
                label="查看业务能力说明",
            )
            capability_asset_detail = gr.JSON(
                controller.business_capability_detail(
                    capability_assets[0].capability_id
                ),
                label="业务能力完整说明",
            )
        operator_assets_initial = build_operator_asset_catalog(controller.registry)
        operator_asset_layers = {
            "业务组合": [
                item for item in operator_assets_initial if item["default_visible"]
            ],
            "系统基础": [
                item for item in operator_assets_initial if item["layer"] == "系统基础"
            ],
            "全部技术原子": operator_assets_initial,
        }
        operator_assets_default = operator_asset_layers["业务组合"]
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                f"### 执行原子资产（当前注册 {len(operator_assets_initial)} 项）\n"
                f"默认展示与业务能力直接关联的 {len(operator_assets_default)} 项。系统基础步骤由运行时自动补全。原子不是 03 的节点编辑入口。"
            )
            with gr.Accordion("“业务组合 / 系统基础”有什么区别？", open=False):
                gr.Markdown(
                    "两者都是实际执行的原子，区别只在展示分层：\n\n"
                    "- **业务组合**：至少被一个业务能力直接使用，例如检测、区域、计数、关系、轨迹、时序、事件；默认展示，便于查看业务能力的实现。\n"
                    "- **系统基础**：为运行提供支撑，例如抽帧、缩放、切片、去重、坐标处理、输出绘制；通常由系统自动补全，仅在排查运行细节时查看。\n\n"
                    "一句话生成技能只面向业务能力；系统会自动编排所需执行原子。切换这里的目录不会改变技能配置或运行效果。"
                )
            operator_asset_layer = gr.Radio(
                choices=list(operator_asset_layers),
                value="业务组合",
                label="原子目录范围",
                info="需要排查运行细节时再查看系统基础或全部技术原子。旧技能会在加载时自动迁移。",
            )
            operator_asset_select = gr.Dropdown(
                choices=[
                    (
                        f"{item['category']}｜{item['display_name']}（{item['operator']}）",
                        item["operator"],
                    )
                    for item in operator_assets_default
                ],
                value=operator_assets_default[0]["operator"],
                label="查看执行原子说明",
            )
            operator_asset_detail = gr.JSON(
                operator_assets_default[0],
                label="原子能力配置说明（技术字段仅在 developer_info）",
            )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### 当前加载版本与 Effective SkillPackage\n"
                "这是 03 编译后的只读运行包，可审计媒体 variant、输出、配置槽和四类哈希。"
            )
            effective_asset_refresh = gr.Button("刷新当前加载版本", variant="secondary")
            effective_asset_view = gr.JSON(label="Effective SkillPackage（只读审计）")

    return AssetsPage(
        asset_delete_button=asset_delete_button,
        asset_load_button=asset_load_button,
        asset_refresh_button=asset_refresh_button,
        asset_save_button=asset_save_button,
        asset_save_display=asset_save_display,
        asset_save_id=asset_save_id,
        asset_save_path=asset_save_path,
        asset_save_root=asset_save_root,
        asset_saved=asset_saved,
        asset_status=asset_status,
        capability_asset_detail=capability_asset_detail,
        capability_asset_select=capability_asset_select,
        effective_asset_refresh=effective_asset_refresh,
        effective_asset_view=effective_asset_view,
        operator_asset_detail=operator_asset_detail,
        operator_asset_layer=operator_asset_layer,
        operator_asset_layers=operator_asset_layers,
        operator_asset_select=operator_asset_select,
    )
