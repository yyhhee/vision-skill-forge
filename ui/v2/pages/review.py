"""Review page layout; callbacks live in ui.v2.bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

from dataclasses import dataclass

import gradio as gr

from core.recipes import build_recipe_catalog
from ui.event_rule_editor import (
    render_branch_overview,
    render_branch_pattern,
    render_condition_tree,
)
from ui.v2.controllers.output_editor import EVIDENCE_CHOICES, SAVE_CHOICES


@dataclass(frozen=True)
class ReviewPage:
    """Explicit page handles consumed by event registration."""

    configuration_state: gr.HTML
    configuration_apply_button: gr.Button

    apply_variant_button: gr.Button
    atomic_apply_button: gr.Button
    atomic_node: gr.Dropdown
    atomic_parameter: gr.Dropdown
    atomic_read_button: gr.Button
    atomic_reset_button: gr.Button
    atomic_rows: gr.JSON
    atomic_status: gr.Textbox
    atomic_value: gr.Code
    business_add_branch_button: gr.Button
    business_add_condition_button: gr.Button
    business_apply_condition_button: gr.Button
    business_branch: gr.Dropdown
    business_branch_action: gr.Dropdown
    business_branch_action_button: gr.Button
    business_branch_duration: gr.Number
    business_branch_emission: gr.Dropdown
    business_branch_gap: gr.Number
    business_branch_hold: gr.Number
    business_branch_identity: gr.Dropdown
    business_branch_name: gr.Textbox
    business_branch_overview: gr.HTML
    business_branch_ratio: gr.Number
    business_branch_time_apply: gr.Button
    business_branch_time_mode: gr.Dropdown
    business_branch_time_status: gr.Markdown
    business_time_target: gr.Dropdown
    business_time_inventory: gr.Markdown
    business_time_confirm: gr.Checkbox
    business_branch_validity: gr.Dropdown
    business_branch_window: gr.Number
    business_capability: gr.Dropdown
    business_compile_apply: gr.Button
    business_condition: gr.Dropdown
    business_condition_action: gr.Dropdown
    business_condition_action_button: gr.Button
    business_condition_action_status: gr.Markdown
    business_condition_name: gr.Textbox
    business_condition_tree: gr.HTML
    business_expression_logic_apply: gr.Button
    business_expression_logic_group: gr.Group
    business_expression_logic_negated: gr.Checkbox
    business_expression_logic_operator: gr.Radio
    business_expression_logic_required: gr.Number
    business_expression_logic_selector: gr.Dropdown
    business_expression_logic_summary: gr.Markdown
    business_final_apply: gr.Button
    business_final_combination: gr.Radio
    business_final_failed: gr.Checkbox
    business_final_name: gr.Textbox
    business_final_reason: gr.Checkbox
    business_final_required: gr.Number
    business_final_source: gr.Dropdown
    business_final_type: gr.Dropdown
    business_group_button: gr.Button
    business_group_members: gr.Dropdown
    business_group_operator: gr.Radio
    business_group_required: gr.Number
    business_imported_logic_apply: gr.Button
    business_imported_logic_group: gr.Group
    business_imported_logic_negated: gr.Checkbox
    business_imported_logic_operator: gr.Radio
    business_imported_logic_required: gr.Number
    business_imported_logic_selector: gr.Dropdown
    business_imported_logic_summary: gr.Markdown
    business_include_tuning: gr.Checkbox
    business_new_logic_group: gr.Group
    business_output_add: gr.Button
    business_output_delete: gr.Button
    business_output_delete_select: gr.Dropdown
    business_outputs_apply: gr.Button
    business_outputs_table: gr.Dataframe
    output_editor_selector: gr.Dropdown
    output_editor_name: gr.Textbox
    output_editor_source: gr.Dropdown
    output_editor_kind: gr.Dropdown
    output_editor_unit: gr.Textbox
    output_editor_evidence: gr.Dropdown
    output_editor_save: gr.Dropdown
    output_editor_show: gr.Checkbox
    output_editor_status: gr.Markdown
    business_parameter_boolean: gr.Radio
    business_parameter_control_help: gr.Markdown
    business_parameter_help: gr.Markdown
    business_parameter_multi: gr.Dropdown
    business_parameter_number: gr.Number
    business_parameter_open_multi: gr.Textbox
    business_parameter_readonly: gr.Textbox
    business_parameter_select: gr.Dropdown
    business_parameter_selector: gr.Dropdown
    business_parameter_table: gr.Dataframe
    business_parameter_text: gr.Textbox
    business_pattern_apply: gr.Button
    business_pattern_branches: gr.Dropdown
    business_pattern_correlation: gr.Dropdown
    business_pattern_mode: gr.Dropdown
    business_pattern_panel: gr.Group
    business_pattern_required: gr.Number
    business_pattern_status: gr.Markdown
    business_pattern_window: gr.Number
    pattern_editor_selector: gr.Dropdown
    pattern_editor_name: gr.Textbox
    pattern_editor_step: gr.Dropdown
    pattern_editor_up: gr.Button
    pattern_editor_down: gr.Button
    pattern_editor_dependencies: gr.Markdown
    business_region_comparison: gr.Dropdown
    business_region_event: gr.Dropdown
    business_region_name: gr.Dropdown
    business_region_operator: gr.Dropdown
    business_region_override_apply: gr.Button
    business_region_override_group: gr.Group
    business_region_overrides: gr.Dataframe
    business_region_value: gr.Number
    business_restore_button: gr.Button
    business_rule_status: gr.Textbox
    business_trigger_apply: gr.Button
    business_trigger_cooldown: gr.Number
    business_trigger_mode: gr.Dropdown
    business_trigger_outputs: gr.CheckboxGroup
    business_trigger_severity: gr.Dropdown
    config_status: gr.Textbox
    context_apply_button: gr.Button
    context_enabled: gr.Checkbox
    context_long_side: gr.Number
    context_padding: gr.Slider
    context_phrases: gr.Textbox
    context_read_button: gr.Button
    context_status: gr.Textbox
    context_targets: gr.Dropdown
    dedup_metric: gr.Radio
    dedup_threshold: gr.Slider
    diff_button: gr.Button
    diff_output: gr.Code
    editor_document: gr.Code
    editor_history: gr.JSON
    editor_overview: gr.Markdown
    effective: gr.Code
    end_seconds: gr.Number
    event_rule_add_condition: gr.Button
    event_rule_alert: gr.Textbox
    event_rule_apply_button: gr.Button
    event_rule_association: gr.Dropdown
    event_rule_association_group: gr.Group
    event_rule_association_object: gr.Dropdown
    event_rule_association_subject: gr.Dropdown
    event_rule_association_threshold: gr.Slider
    event_rule_card_state: gr.Textbox
    event_rule_cards: list[dict[str, gr.Component]]
    event_rule_categories: gr.Dropdown
    event_rule_category_node: gr.Textbox
    event_rule_condition_1: gr.Dropdown
    event_rule_condition_2: gr.Dropdown
    event_rule_condition_2_row: gr.Group
    event_rule_event: gr.Dropdown
    event_rule_gap: gr.Number
    event_rule_legacy_apply_probe: gr.Button
    event_rule_logic: gr.Radio
    event_rule_operator_1: gr.Dropdown
    event_rule_operator_2: gr.Dropdown
    event_rule_read_button: gr.Button
    event_rule_region_overrides: gr.Dataframe
    event_rule_scope: gr.Dropdown
    event_rule_seconds: gr.Number
    event_rule_status: gr.Textbox
    event_rule_summary: gr.Markdown
    event_rule_trigger: gr.Radio
    event_rule_value_1: gr.Number
    event_rule_value_2: gr.Number
    frame_step: gr.Number
    grounding_prompt_apply_button: gr.Button
    grounding_prompt_node: gr.Dropdown
    grounding_prompt_read_button: gr.Button
    grounding_prompt_reset_button: gr.Button
    grounding_prompt_status: gr.Textbox
    grounding_prompt_text: gr.Textbox
    include_full: gr.Checkbox
    interval_seconds: gr.Number
    load_variant_button: gr.Button
    long_side: gr.Number
    max_frames: gr.Number
    output_config_button: gr.Button
    output_fps: gr.Number
    output_fps_mode: gr.Radio
    output_height: gr.Number
    output_size_mode: gr.Radio
    output_width: gr.Number
    overlap_x: gr.Slider
    overlap_y: gr.Slider
    preprocess_button: gr.Button
    read_execution_button: gr.Button
    resize_apply_button: gr.Button
    resize_height: gr.Number
    resize_interpolation: gr.Radio
    resize_mode: gr.Radio
    resize_width: gr.Number
    sample_button: gr.Button
    sample_fps: gr.Number
    sample_mode: gr.Radio
    save_button: gr.Button
    save_display: gr.Textbox
    save_id: gr.Textbox
    saved_path: gr.Textbox
    semantic: gr.Code
    start_seconds: gr.Number
    tile_enabled: gr.Checkbox
    tile_height: gr.Number
    tile_options: gr.Column
    tile_width: gr.Number
    unified_action: gr.Dropdown
    unified_apply_button: gr.Button
    unified_branch: gr.Dropdown
    unified_branch_action: gr.Dropdown
    unified_branch_button: gr.Button
    unified_branch_name: gr.Textbox
    unified_mutate_button: gr.Button
    unified_new_branch_id: gr.Textbox
    unified_new_node_id: gr.Textbox
    unified_operator: gr.Dropdown
    unified_patterns: gr.Code
    unified_patterns_button: gr.Button
    unified_pending: gr.JSON
    unified_pending_button: gr.Button
    unified_pending_choice: gr.Dropdown
    unified_pending_value: gr.Code
    unified_port: gr.Textbox
    unified_recipe: gr.Dropdown
    unified_recipe_button: gr.Button
    unified_redo_button: gr.Button
    unified_restore_button: gr.Button
    unified_results: gr.Code
    unified_results_button: gr.Button
    unified_source_node: gr.Dropdown
    unified_status: gr.Textbox
    unified_target_node: gr.Dropdown
    unified_undo_button: gr.Button
    unresolved: gr.JSON
    validate_button: gr.Button
    validation: gr.Textbox
    variant_choice: gr.Radio
    variant_editor: gr.Code
    variant_status: gr.Textbox


def build_review_page(controller: V2AppController) -> ReviewPage:
    with gr.Tab("03 审核"):
        configuration_state = gr.HTML(
            "<div class='status-card'><b>尚未加载运行版本</b></div>",
            elem_id="configuration-lifecycle-review",
        )
        configuration_apply_button = gr.Button(
            "应用修改，更新运行版本",
            variant="primary",
            elem_id="configuration-lifecycle-apply",
        )
        gr.Markdown(
            "修改条件、分支、时间或输出后，先在对应卡片保存到草稿，再点击上方“应用修改”。"
            "只有显示“当前运行版本已更新”后，04 才会使用新配置。",
            elem_id="configuration-lifecycle-help",
        )
        gr.HTML(
            """
                    <section class="vs-section">
                      <h2>审核系统理解，按业务含义调整规则</h2>
                      <p class="vs-section-copy"><strong>大多数用户只需使用“业务规则配置”。</strong>按目标、区域、条件、持续时间和告警方式修改即可；原子节点与端口连接仅放在页面下方的专业模式中。</p>
                      <div class="vs-guide">
                        <div class="vs-guide-item"><b>检测慢 / 原图太大</b><span>用「图像缩放」降低输入分辨率。</span></div>
                        <div class="vs-guide-item"><b>视频长 / 运行久</b><span>用「视频抽帧」减少实际处理帧数。</span></div>
                        <div class="vs-guide-item"><b>小目标漏检</b><span>用「切片增强」，如远处车辆、小碎片。</span></div>
                        <div class="vs-guide-item"><b>输出有要求</b><span>用「结果媒体」指定清晰度或 FPS。</span></div>
                      </div>
                    </section>
                    """,
            padding=False,
        )
        with gr.Group(elem_classes="vs-section"):
            gr.Markdown(
                "### 执行参数\n先选择图片或视频流程，点击“读取当前参数”查看真实生效值；修改任何配置卡片后，状态会显示在下方。"
            )
            variant_choice = gr.Radio(
                ["image variant", "video variant"],
                value="image variant",
                label="当前编辑的执行流程（variant）",
            )
            event_rule_summary = gr.Markdown(
                "### 事件判定\n生成或加载技能后，这里会说明是否需要配置持续时间。"
            )
            read_execution_button = gr.Button("读取当前参数", variant="secondary")
            config_status = gr.Textbox(
                label="配置状态",
                interactive=False,
                elem_classes="vs-status-output",
                value="尚未修改配置。默认参数可直接运行。",
            )

        with gr.Accordion("图像缩放 resize ｜ 原图过大、检测慢时使用", open=False):
            gr.Markdown(
                "**什么时候用**：原图分辨率很高导致检测慢，或需要统一输入尺寸。"
                "**怎么配**：选“按长边缩放”并把长边设为 960~1280，通常就能明显提速且不影响精度；不确定就保持原尺寸。"
            )
            resize_mode = gr.Radio(
                [
                    ("保持原尺寸（默认，推荐）", "identity"),
                    ("按长边缩放（提速常用）", "long_side"),
                    ("等比缩放到指定尺寸内", "contain"),
                    ("拉伸到指定尺寸（会变形）", "stretch"),
                ],
                value="identity",
                label="缩放模式",
            )
            with gr.Row():
                long_side = gr.Number(
                    1280, precision=0, label="长边像素", visible=False
                )
                resize_width = gr.Number(
                    1280, precision=0, label="目标宽度", visible=False
                )
                resize_height = gr.Number(
                    720, precision=0, label="目标高度", visible=False
                )
                resize_interpolation = gr.Radio(
                    ["nearest", "bilinear", "bicubic"],
                    value="bilinear",
                    label="插值方式（默认 bilinear 即可）",
                )
            resize_apply_button = gr.Button("应用缩放配置", variant="primary")
        with gr.Accordion("视频抽帧 ｜ 视频长、运行慢时使用（仅视频流程）", open=False):
            gr.Markdown(
                "**什么时候用**：视频几十秒以上、运行一次要等很久。"
                "**怎么配**：默认每秒 1 帧；需要更细的时间粒度时再提高目标 FPS。"
                "也可用起止时间只分析片段。注意抽帧会改变检测结果的时间粒度。"
            )
            sample_mode = gr.Radio(
                [
                    ("保持原始 FPS（默认，逐帧处理）", "original_fps"),
                    ("目标 FPS（默认 1 帧/秒）", "fps"),
                    ("固定时间间隔（每 N 秒 1 帧）", "interval"),
                    ("固定帧步长（每 N 帧取 1 帧）", "frame_step"),
                ],
                value="fps",
                label="抽帧模式",
            )
            with gr.Row():
                sample_fps = gr.Number(1.0, label="目标 FPS", visible=False)
                interval_seconds = gr.Number(1.0, label="间隔秒数", visible=False)
                frame_step = gr.Number(1, precision=0, label="帧步长", visible=False)
            with gr.Row():
                start_seconds = gr.Number(0.0, label="起始秒（从第几秒开始）")
                end_seconds = gr.Number(None, label="结束秒（留空=到结尾）")
                max_frames = gr.Number(
                    None, precision=0, label="最多处理帧数（留空=不限）"
                )
            sample_button = gr.Button("应用抽帧配置", variant="primary")
        with gr.Accordion(
            "事件规则编辑｜条件分支、时间编排、最终判定与业务输出",
            open=True,
        ):
            gr.Markdown(
                "LLM 已生成业务规则初稿。这里是唯一业务配置入口：用户按业务语言审核条件、参数和组合；"
                "节点 ID、端口和技术参数由系统编译，不需要手工维护。区域与方向引用来自 02 的实际标注，"
                "数量不需要提前固定。"
            )
            business_rule_status = gr.Textbox(
                label="审核与编译状态",
                interactive=False,
                value="生成或加载技能后，系统会读取当前图片/视频流程的业务分支。",
                elem_classes="vs-status-output",
            )
            business_restore_button = gr.Button(
                "还原本次生成/加载的默认规则", variant="secondary"
            )
            business_branch_overview = gr.HTML(
                render_branch_overview([], None), padding=False
            )
            with gr.Row():
                business_branch = gr.Dropdown(
                    choices=[],
                    label="当前条件分支",
                    interactive=True,
                    allow_custom_value=True,
                    elem_id="vs-business-branch",
                )
                business_branch_name = gr.Textbox(
                    label="分支名称",
                    placeholder="例如：区域2人员数量",
                )
                business_branch_action = gr.Dropdown(
                    ["重命名", "复制", "删除"],
                    value="重命名",
                    label="分支操作",
                )
            with gr.Row():
                business_add_branch_button = gr.Button("新增分支", variant="secondary")
                business_branch_action_button = gr.Button(
                    "执行分支操作", variant="secondary"
                )

            with gr.Tabs():
                with gr.Tab("条件分支"):
                    gr.Markdown(
                        "每个分支使用递归条件树。基础逻辑保留 **AND / OR / NOT**；"
                        "条件能力和参数会根据当前媒体、已有来源及 02 场景资源动态收敛。"
                    )
                    business_condition_tree = gr.HTML(
                        render_condition_tree([]), padding=False
                    )
                    with gr.Row():
                        business_condition = gr.Dropdown(
                            choices=[],
                            label="当前编辑条件",
                            interactive=True,
                            allow_custom_value=True,
                        )
                        business_condition_action = gr.Dropdown(
                            ["复制", "删除", "删除（含依赖）", "NOT 取反"],
                            value="复制",
                            label="条件操作",
                        )
                        business_condition_action_button = gr.Button(
                            "执行条件操作", variant="secondary"
                        )
                    business_condition_action_status = gr.Markdown(
                        "选择条件和操作后执行；结果会立即显示在这里。"
                    )
                    gr.Markdown("#### 新增业务条件")
                    with gr.Row():
                        initial_business_capabilities = [
                            item
                            for item in controller.business_capabilities.definitions()
                            if "image" in item.media_requirements
                            and item.category
                            not in {
                                "逻辑组合",
                                "输出与证据",
                                "时间与复杂编排",
                            }
                        ]
                        business_capability = gr.Dropdown(
                            choices=[
                                (
                                    f"{item.category} / {item.display_name}",
                                    item.capability_id,
                                )
                                for item in initial_business_capabilities
                            ],
                            value=(
                                initial_business_capabilities[0].capability_id
                                if initial_business_capabilities
                                else None
                            ),
                            label="新增哪类条件",
                        )
                        business_add_condition_button = gr.Button(
                            "添加到当前分支", variant="primary"
                        )
                    gr.Markdown(
                        "#### 当前条件配置\n"
                        "下表用于确认 LLM 生成了什么。固定内容只读；需要修改的枚举、数值和场景资源在下方使用受控选项修改。\n\n"
                        "来源说明：LLM 建议是自然语言生成的业务配置；用户修改是人工调整；系统确定性编译是系统依据已注册业务能力配方自动补齐执行原子。条件成员按 A、B、C、D…编号，普通用户可修改业务参数和 AND/OR/NOT 组合，不直接编辑执行原子。"
                    )
                    with gr.Row():
                        business_condition_name = gr.Textbox(
                            label="条件名称",
                            placeholder="系统自动生成，可修改为业务名称",
                            interactive=False,
                        )
                        business_include_tuning = gr.Checkbox(
                            True,
                            label="显示效果调优参数（推荐保持显示）",
                        )
                    business_parameter_table = gr.Dataframe(
                        headers=["配置项", "当前值", "单位", "配置来源", "作用说明"],
                        datatype=["str", "str", "str", "str", "str"],
                        type="array",
                        value=[],
                        interactive=False,
                        wrap=True,
                        label="当前配置（只读概览）",
                    )
                    business_parameter_help = gr.Markdown(
                        "选择一条业务条件后，这里会显示参数作用说明。"
                    )
                    gr.Markdown("#### 修改一个关键参数")
                    business_parameter_selector = gr.Dropdown(
                        choices=[], label="要修改的配置项"
                    )
                    business_parameter_readonly = gr.Textbox(
                        label="当前值（只读）", interactive=False
                    )
                    business_parameter_select = gr.Dropdown(
                        choices=[], label="请选择", visible=False
                    )
                    business_parameter_multi = gr.Dropdown(
                        choices=[], multiselect=True, label="请选择", visible=False
                    )
                    business_parameter_number = gr.Number(
                        label="请输入数值", visible=False
                    )
                    business_parameter_boolean = gr.Radio(
                        [("是", True), ("否", False)], label="请选择", visible=False
                    )
                    business_parameter_text = gr.Textbox(
                        label="请输入业务文本", visible=False
                    )
                    business_parameter_open_multi = gr.Textbox(
                        label="请输入一个或多个值（逗号分隔）", visible=False
                    )
                    business_parameter_control_help = gr.Markdown(
                        "枚举使用下拉，数值使用数字输入；固定内容只读。"
                    )
                    business_apply_condition_button = gr.Button(
                        "保存当前参数到草稿", variant="primary"
                    )
                    with gr.Group(visible=False) as business_region_override_group:
                        gr.Markdown(
                            "#### 每个标注区域分别配置\n"
                            "区域来自 02 标注，数量无需预先确定。可分别修改数量/速度阈值、方向关系、方向判定阈值、持续时间和允许中断；只显示当前原子真正支持的区域参数。"
                        )
                        business_region_event = gr.Dropdown(
                            choices=[], label="要配置的事件规则"
                        )
                        business_region_overrides = gr.Dataframe(
                            headers=["已标注区域"],
                            datatype=["str"],
                            type="array",
                            value=[],
                            interactive=False,
                            wrap=True,
                            label="各区域当前生效配置（只读总览）",
                        )
                        with gr.Row():
                            business_region_name = gr.Dropdown(
                                choices=[], label="标注区域"
                            )
                            business_region_comparison = gr.Dropdown(
                                choices=[], label="要修改的区域参数"
                            )
                        with gr.Row():
                            business_region_operator = gr.Dropdown(
                                choices=[],
                                label="固定选项",
                                visible=False,
                            )
                            business_region_value = gr.Number(
                                label="数值", visible=False
                            )
                        business_region_override_apply = gr.Button(
                            "应用到这个区域", variant="primary"
                        )
                    with gr.Accordion("逻辑组合（全部 / 任一 / 至少 N 项）", open=True):
                        gr.Markdown(
                            "每个逻辑组就是一组带括号的条件：选择“全部满足”表示 AND，选择“任一满足”表示 OR，"
                            "选择“至少 N 项满足”表示 N-of-M；需要排除时勾选“反转结果（NOT）”。"
                            "一般只需修改当前组的关系；只有要新增 `(A AND B) OR C` 这种嵌套层级时，才使用“新增嵌套逻辑”。"
                        )
                        with gr.Group(visible=False) as business_imported_logic_group:
                            gr.Markdown("#### 修改当前逻辑组")
                            business_imported_logic_selector = gr.Dropdown(
                                choices=[], label="选择要修改的逻辑组"
                            )
                            with gr.Row():
                                business_imported_logic_operator = gr.Radio(
                                    [
                                        ("全部满足（AND）", "AND"),
                                        ("任一满足（OR）", "OR"),
                                        ("至少 N 项满足（N-of-M）", "N_OF_M"),
                                    ],
                                    value="AND",
                                    label="这组条件如何成立？",
                                )
                                business_imported_logic_required = gr.Number(
                                    1,
                                    minimum=1,
                                    precision=0,
                                    label="N（仅N-of-M使用）",
                                    visible=False,
                                )
                            business_imported_logic_negated = gr.Checkbox(
                                False, label="反转这组的最终结果（NOT）"
                            )
                            business_imported_logic_summary = gr.Markdown()
                            business_imported_logic_apply = gr.Button(
                                "保存逻辑到草稿", variant="primary"
                            )
                        with gr.Group(visible=False) as business_expression_logic_group:
                            gr.Markdown("#### 修改当前逻辑组")
                            business_expression_logic_selector = gr.Dropdown(
                                choices=[], label="选择要修改的逻辑组"
                            )
                            with gr.Row():
                                business_expression_logic_operator = gr.Radio(
                                    [
                                        ("全部满足（AND）", "AND"),
                                        ("任一满足（OR）", "OR"),
                                        ("至少 N 项满足（N-of-M）", "N_OF_M"),
                                    ],
                                    value="AND",
                                    label="这组条件如何成立？",
                                )
                                business_expression_logic_required = gr.Number(
                                    1,
                                    minimum=1,
                                    precision=0,
                                    label="N（仅N-of-M使用）",
                                    visible=False,
                                )
                            business_expression_logic_negated = gr.Checkbox(
                                False,
                                label="反转这组的最终结果（NOT）",
                            )
                            business_expression_logic_summary = gr.Markdown()
                            business_expression_logic_apply = gr.Button(
                                "保存逻辑到草稿", variant="primary"
                            )
                        with gr.Group(visible=False) as business_new_logic_group:
                            gr.Markdown(
                                "#### 新增嵌套逻辑（可选）\n"
                                "仅当需要新增括号层级时使用；先选择同一父组中的条件，再选择全部、任一或至少 N 项。"
                            )
                            business_group_members = gr.Dropdown(
                                choices=[],
                                value=[],
                                multiselect=True,
                                label="选择要放入新逻辑组的条件或已有逻辑组",
                                allow_custom_value=False,
                            )
                            with gr.Row():
                                business_group_operator = gr.Radio(
                                    [
                                        ("全部满足（AND）", "AND"),
                                        ("任一满足（OR）", "OR"),
                                        ("至少满足 N 项", "N_OF_M"),
                                        ("对所选一项取反（NOT）", "NOT"),
                                    ],
                                    value="AND",
                                    label="这组条件如何成立？",
                                )
                                business_group_required = gr.Number(
                                    1,
                                    minimum=1,
                                    precision=0,
                                    label="至少满足几项",
                                    visible=False,
                                )
                            business_group_button = gr.Button(
                                "新增这组逻辑", variant="primary"
                            )
                    with gr.Accordion(
                        "时间设置｜选择条件或整个分支",
                        open=False,
                    ):
                        gr.Markdown(
                            "先选择作用对象，再设置等待多久。修改已有计时条件不会新增步骤；"
                            "整个分支的计时在分支内条件完成后开始。"
                            "为单项条件新增计时，可添加“持续、累计或窗口占比”条件并选择输入来源。"
                        )
                        business_time_target = gr.Dropdown(
                            [],
                            label="本次修改哪个对象",
                            elem_id="time-configuration-target",
                        )
                        business_time_inventory = gr.Markdown(
                            "请先选择分支。", elem_id="time-configuration-inventory"
                        )
                        with gr.Row():
                            business_branch_time_mode = gr.Dropdown(
                                [
                                    ("不额外等待", "immediate"),
                                    ("连续满足一段时间", "continuous"),
                                    ("观察窗口内累计满足", "cumulative"),
                                    ("观察窗口内满足时间占比", "ratio"),
                                ],
                                value="immediate",
                                label="什么时候算满足",
                            )
                            business_branch_duration = gr.Number(
                                None,
                                minimum=0,
                                label="持续/累计时间（秒）",
                                visible=False,
                            )
                            business_branch_window = gr.Number(
                                None, minimum=0, label="观察窗口（秒）", visible=False
                            )
                            business_branch_ratio = gr.Number(
                                100,
                                minimum=0,
                                maximum=100,
                                label="窗口满足比例（%）",
                                visible=False,
                            )
                        with gr.Row():
                            business_branch_gap = gr.Number(
                                0,
                                minimum=0,
                                label="允许短暂中断（秒）",
                                info="用于容忍短时遮挡或漏检。",
                                visible=False,
                            )
                            business_branch_identity = gr.Dropdown(
                                [
                                    ("所选对象整体（不区分实例）", "global"),
                                    ("同一目标", "object"),
                                    ("同一轨迹", "track"),
                                    ("同一目标对", "pair"),
                                    ("同一区域", "region"),
                                ],
                                value="global",
                                label="按谁分别计时",
                                info="目标、轨迹或区域 ID 来自所选条件的输入结果；不会把不同对象的时间相加。",
                                visible=False,
                            )
                            business_branch_emission = gr.Dropdown(
                                [
                                    ("每段连续成立只产生一次", "first"),
                                    ("满足后每个采样时刻均可产生", "repeat"),
                                ],
                                value="first",
                                label="分支结果产生方式",
                                visible=False,
                            )
                        with gr.Row():
                            business_branch_validity = gr.Dropdown(
                                [
                                    ("仅当前帧有效", "current_frame"),
                                    ("按事件起止区间有效", "event_interval"),
                                    ("成立后保持一段时间", "hold_for"),
                                ],
                                value="current_frame",
                                label="分支成立后多久仍算有效",
                            )
                            business_branch_hold = gr.Number(
                                None,
                                minimum=0,
                                label="成立后保持（秒）",
                                visible=False,
                            )
                        business_branch_time_status = gr.Markdown(
                            "请先选择要修改的条件或整个分支。"
                        )
                        business_time_confirm = gr.Checkbox(
                            False,
                            label="我确认：已有条件完成计时后，整个分支还需要再计时一次",
                            visible=False,
                            elem_id="time-configuration-confirm",
                        )
                        business_branch_time_apply = gr.Button(
                            "保存所选对象的时间设置到草稿", variant="primary"
                        )

                with gr.Tab("分支编排"):
                    gr.Markdown(
                        "选中已有组即可修改；也可以选择“新建编排组”。添加成员后，选择步骤并上移／下移。"
                        "这里只编辑所选组，其他组和最终判定的引用不会被替换。顺序关系仅适用于视频。"
                    )
                    pattern_editor_selector = gr.Dropdown(
                        choices=[("新建编排组", "__new_group__")],
                        label="选择要编辑的编排组",
                        filterable=False,
                        elem_id="pattern-editor-selector",
                    )
                    with gr.Group(visible=False) as business_pattern_panel:
                        pattern_editor_name = gr.Textbox(
                            label="编排组名称", elem_id="pattern-editor-name"
                        )
                        business_pattern_status = gr.Markdown(
                            render_branch_pattern("none", [])
                        )
                        business_pattern_mode = gr.Dropdown(
                            [
                                ("不组合，直接由最终判定处理", "none"),
                                ("顺序：逐个完成", "sequence"),
                                ("并行：全部完成", "all_completed"),
                                ("互斥选择：最先完成一个即结束", "exclusive"),
                                ("任意完成（或）：任一完成即结束", "any"),
                                ("部分汇聚：达到指定完成数量", "n_of_m"),
                            ],
                            value="none",
                            label="基础关系",
                            filterable=False,
                        )
                        business_pattern_branches = gr.Dropdown(
                            choices=[],
                            multiselect=True,
                            label="参与本组的分支或已编排组（顺序关系按选择先后）",
                        )
                        with gr.Row(elem_id="pattern-editor-move-row"):
                            pattern_editor_step = gr.Dropdown(
                                choices=[],
                                label="要移动的步骤",
                                filterable=False,
                                elem_id="pattern-editor-step",
                            )
                            pattern_editor_up = gr.Button(
                                "上移一步", elem_id="pattern-editor-up"
                            )
                            pattern_editor_down = gr.Button(
                                "下移一步", elem_id="pattern-editor-down"
                            )
                        business_pattern_help = gr.Markdown(  # noqa: F841 — preserved V2 behavior
                            "顺序：A 完成后才接受 B；并行：所有所选分支完成；"
                            "互斥：只采用最先完成的分支；任意完成：任一分支完成；"
                            "部分汇聚：至少 N 个分支完成。保存后的组会出现在同一选择框中，可再次组合。"
                        )
                        with gr.Row():
                            business_pattern_window = gr.Number(
                                None,
                                minimum=0,
                                label="相邻步骤最长间隔（秒，0 为不限制）",
                                visible=False,
                            )
                            business_pattern_required = gr.Number(
                                1,
                                minimum=1,
                                precision=0,
                                label="需要完成几个分支 N",
                                visible=False,
                            )
                            business_pattern_correlation = gr.Dropdown(
                                [
                                    ("整个媒体共同判断", "global"),
                                    ("同一目标", "object"),
                                    ("同一轨迹", "track"),
                                    ("同一目标对", "pair"),
                                    ("同一区域", "region"),
                                ],
                                value="global",
                                label="这些分支属于同一个什么对象",
                            )
                        pattern_editor_dependencies = gr.Markdown(
                            "暂无依赖关系。", elem_id="pattern-editor-dependencies"
                        )
                        business_pattern_apply = gr.Button(
                            "保存编排组到草稿", variant="primary"
                        )

                with gr.Tab("最终判定"):
                    gr.Markdown(
                        "最终判定只回答“是否告警”。选择需要参与的业务分支及 AND / OR 关系即可；"
                        "结果类型由系统根据来源确定，不需要用户配置。"
                    )
                    with gr.Row():
                        business_final_name = gr.Textbox(
                            label="最终结果名称", placeholder="例如：多区域人员告警"
                        )
                        business_final_type = gr.Dropdown(
                            [
                                "event_decision",
                                "detection_summary",
                                "measurement_decision",
                                "state_summary",
                                "timeline_summary",
                            ],
                            value="event_decision",
                            visible=False,
                            label="系统判定类型",
                        )
                        business_final_source = gr.Dropdown(
                            choices=[],
                            value=[],
                            multiselect=True,
                            label="哪些分支参与最终告警（可多选）",
                            allow_custom_value=True,
                        )
                    with gr.Row():
                        business_final_combination = gr.Radio(
                            [
                                ("全部满足（AND）", "AND"),
                                ("任一满足（OR）", "OR"),
                                ("至少 N 项满足（N-of-M）", "N_OF_M"),
                            ],
                            value="AND",
                            label="所选分支如何形成最终告警",
                        )
                        business_final_required = gr.Number(
                            1,
                            minimum=1,
                            precision=0,
                            label="至少满足 N 项",
                            info="仅选择“至少 N 项满足”时生效。",
                        )
                    with gr.Row():
                        business_final_reason = gr.Checkbox(
                            True, label="显示成立或未成立原因"
                        )
                        business_final_failed = gr.Checkbox(
                            True, label="显示失败或等待中的分支"
                        )
                    business_final_apply = gr.Button(
                        "保存最终判定到草稿", variant="primary"
                    )

                with gr.Tab("业务输出"):
                    gr.Markdown(
                        "业务输出决定 04 第二层具体显示和保存什么。数量、状态、目标框、轨迹、"
                        "事件、持续时间和时间线均使用同一输出规格，不使用案例专用卡片。"
                    )
                    business_outputs_table = gr.Dataframe(
                        headers=[
                            "输出名称",
                            "结果来源",
                            "希望看到",
                            "单位",
                            "证据",
                            "保存策略",
                            "概览显示",
                        ],
                        datatype=["str"] * 7,
                        type="array",
                        value=[],
                        interactive=False,
                        wrap=True,
                        label="业务输出规格",
                    )
                    gr.Markdown(
                        "下表用于查看已保存到草稿的输出；在下面选择一项进行修改。"
                        "结果来源按业务名称选择，结果类型只显示兼容选项。"
                    )
                    output_editor_selector = gr.Dropdown(
                        choices=[("新增业务输出", "__new_output__")],
                        value="__new_output__",
                        label="编辑哪项输出",
                        filterable=False,
                        allow_custom_value=False,
                        elem_id="output-editor-selector",
                    )
                    with gr.Row(elem_id="output-editor-main-row"):
                        output_editor_name = gr.Textbox(
                            label="输出名称", elem_id="output-editor-name"
                        )
                        output_editor_source = gr.Dropdown(
                            choices=[],
                            label="结果来源",
                            allow_custom_value=False,
                            filterable=False,
                            elem_id="output-editor-source",
                        )
                        output_editor_kind = gr.Dropdown(
                            choices=[],
                            label="希望看到的结果",
                            allow_custom_value=False,
                            filterable=False,
                            elem_id="output-editor-kind",
                        )
                    with gr.Row(elem_id="output-editor-policy-row"):
                        output_editor_unit = gr.Textbox(
                            label="单位（可不填）", elem_id="output-editor-unit"
                        )
                        output_editor_evidence = gr.Dropdown(
                            EVIDENCE_CHOICES,
                            value="optional",
                            label="证据保存",
                            filterable=False,
                            elem_id="output-editor-evidence",
                        )
                        output_editor_save = gr.Dropdown(
                            SAVE_CHOICES,
                            value="always",
                            label="结果保存",
                            filterable=False,
                            elem_id="output-editor-save",
                        )
                        output_editor_show = gr.Checkbox(
                            True, label="在结果概览中显示", elem_id="output-editor-show"
                        )
                    output_editor_status = gr.Markdown(
                        "先选择要编辑的输出，或点击新增。",
                        elem_id="output-editor-status",
                    )
                    with gr.Row():
                        business_output_add = gr.Button(
                            "新增业务输出", variant="secondary"
                        )
                        business_output_delete_select = gr.Dropdown(
                            choices=[], label="选择要删除的输出", visible=False
                        )
                        business_output_delete = gr.Button(
                            "删除所选输出", variant="stop", interactive=False
                        )
                        business_outputs_apply = gr.Button(
                            "保存业务输出到草稿", variant="primary", interactive=False
                        )

                with gr.Tab("触发策略"):
                    gr.Markdown(
                        "仅事件、告警或通知任务需要。触发策略只决定何时发出和如何保存，"
                        "不改变条件含义或持续时间。"
                    )
                    with gr.Row():
                        business_trigger_mode = gr.Dropdown(
                            [
                                ("不触发告警", "none"),
                                ("首次成立时只触发一次", "once"),
                                ("每次由不成立变为成立时触发", "on_change"),
                                ("持续成立期间按冷却时间重复触发", "repeat"),
                            ],
                            value="none",
                            label="触发方式",
                            info="“状态变化触发”必须先恢复为不成立；“持续重复”无需恢复。",
                        )
                        business_trigger_cooldown = gr.Number(
                            0, minimum=0, label="冷却时间（秒）"
                        )
                        business_trigger_severity = gr.Dropdown(
                            [
                                ("提示", "info"),
                                ("低", "low"),
                                ("中", "medium"),
                                ("高", "high"),
                                ("严重", "critical"),
                            ],
                            value="medium",
                            label="告警级别",
                        )
                    business_trigger_outputs = gr.CheckboxGroup(
                        [
                            ("事件记录", "event_record"),
                            ("标注媒体", "annotated_media"),
                            ("通知", "notification"),
                        ],
                        value=["event_record"],
                        label="触发时输出",
                    )
                    business_trigger_apply = gr.Button(
                        "保存触发策略到草稿", variant="primary"
                    )

            gr.Markdown(
                "修改参数或逻辑后，页面先保存为 **03 草稿**，不会立即影响运行。"
                "必须点击 **【应用修改，更新运行版本】**（本页顶部与下方是同一个操作）；"
                "看到“当前运行版本已更新”后，04 才会使用新配置。"
            )
            business_compile_apply = gr.Button(
                "应用修改，更新运行版本", variant="primary"
            )

        # Kept temporarily for shadow regression only. It is not a
        # second user-facing editor and will be removed after V3 cutover.
        with gr.Accordion(
            "旧事件规则兼容区",
            open=False,
            visible=False,
        ):
            gr.Markdown(
                "**业务事件快捷配置，按 3 步完成：** ① 选择要调整的业务事件；② 修改条件卡；③ 设置持续与告警并应用。"
                "目标类别决定识别什么，统计范围决定在哪里判断，条件关系决定全部满足还是任一满足。"
                "区域形状和数量仍在“02 标注”修改。"
            )
            event_rule_event = gr.Dropdown(
                choices=[],
                label="要编辑的事件规则",
                interactive=True,
                allow_custom_value=True,
            )
            event_rule_scope = gr.Dropdown(
                choices=[],
                label="统计范围（由一句话决定）",
                interactive=False,
                allow_custom_value=True,
            )
            gr.Markdown(
                "#### ② 判断条件（条件设置）\n每张卡是一条用户可读的业务条件。全画面、所有标注区域和指定区域会真实写入执行流程。"
                "“全部手工标注区域”是范围选择，不是单独区域；要删除具体区域请回到“02 标注”。"
            )
            event_rule_card_state = gr.Textbox(
                value="[]", container=False, elem_classes=["vs-card-state"]
            )
            event_rule_cards = []
            for card_index in range(1, 7):
                with gr.Group(
                    visible=False, elem_classes=["vs-condition-card"]
                ) as card_group:
                    with gr.Row():
                        gr.Markdown(f"**条件 {card_index}**")
                        card_enabled = gr.Checkbox(True, label="启用", min_width=74)
                        card_delete = gr.Button(
                            "删除", size="sm", elem_classes=["vs-condition-delete"]
                        )
                    with gr.Row():
                        card_source = gr.Dropdown(
                            choices=[],
                            label=f"条件 {card_index}：区域与统计量",
                            interactive=True,
                            allow_custom_value=True,
                        )
                        card_categories = gr.Dropdown(
                            choices=[],
                            multiselect=True,
                            label=f"条件 {card_index}：目标类别",
                            interactive=True,
                            allow_custom_value=True,
                        )
                        card_operator = gr.Dropdown(
                            [">", ">=", "=", "<=", "<", "==", "!="],
                            value=">=",
                            label=f"条件 {card_index}：比较符",
                        )
                        card_value = gr.Number(0, label=f"条件 {card_index}：阈值")
                    event_rule_cards.append(
                        {
                            "group": card_group,
                            "enabled": card_enabled,
                            "delete": card_delete,
                            "source": card_source,
                            "categories": card_categories,
                            "operator": card_operator,
                            "value": card_value,
                        }
                    )
            event_rule_add_condition = gr.Button("添加条件", variant="secondary")
            with gr.Group(
                visible=False,
                elem_classes=["vs-condition-card"],
            ) as event_rule_association_group:
                gr.Markdown(
                    "#### 目标框关联\n"
                    "选择同一帧中需要关联的主体和证据类别；阈值表示两框重叠比例。"
                )
                event_rule_association = gr.Dropdown(
                    choices=[],
                    label="要编辑的目标关联",
                    interactive=True,
                    allow_custom_value=True,
                )
                with gr.Row():
                    event_rule_association_subject = gr.Dropdown(
                        choices=[],
                        label="主体候选框",
                        interactive=True,
                        allow_custom_value=True,
                    )
                    event_rule_association_object = gr.Dropdown(
                        choices=[],
                        label="关联候选框",
                        interactive=True,
                        allow_custom_value=True,
                    )
                    event_rule_association_threshold = gr.Slider(
                        0.0,
                        1.0,
                        0.3,
                        step=0.05,
                        label="框重叠阈值",
                    )
            # Keep the legacy two-condition reader on isolated hidden
            # fields.  Sharing the visible card components made its
            # asynchronous refresh overwrite card-specific choices.
            event_rule_category_node = gr.Textbox(value="", visible=False)
            event_rule_categories = gr.Dropdown(
                choices=[],
                multiselect=True,
                value=[],
                visible=False,
                allow_custom_value=True,
            )
            event_rule_condition_1 = gr.Dropdown(
                choices=[], visible=False, allow_custom_value=True
            )
            event_rule_operator_1 = gr.Dropdown(
                [">", ">=", "=", "<=", "<", "==", "!="],
                visible=False,
            )
            event_rule_value_1 = gr.Number(visible=False)
            event_rule_condition_2_row = gr.Group(visible=False)
            event_rule_condition_2 = gr.Dropdown(
                choices=[], visible=False, allow_custom_value=True
            )
            event_rule_operator_2 = gr.Dropdown(
                [">", ">=", "=", "<=", "<", "==", "!="],
                visible=False,
            )
            event_rule_value_2 = gr.Number(visible=False)
            event_rule_region_overrides = gr.Dataframe(
                headers=["已标注区域"],
                datatype=["str"],
                type="array",
                value=[],
                visible=False,
            )
            event_rule_legacy_apply_probe = gr.Button(visible=False)
            with gr.Group(elem_classes=["vs-event-policy"]):
                gr.Markdown(
                    "**事件触发策略**\n下列配置作用于整组启用条件，避免多个条件各自持续导致含义不清。"
                )
                with gr.Row():
                    event_rule_logic = gr.Radio(
                        [
                            ("全部条件同时满足（AND）", "all"),
                            ("任一条件满足（OR）", "any"),
                        ],
                        value="all",
                        label="条件关系",
                    )
                    event_rule_seconds = gr.Number(
                        1.0, minimum=0, label="持续时间（秒）"
                    )
                    event_rule_gap = gr.Number(0.5, minimum=0, label="允许中断（秒）")
                    event_rule_trigger = gr.Radio(
                        [("只触发一次", "once"), ("达到阈值后重复触发", "repeat")],
                        value="once",
                        label="触发方式",
                    )
                event_rule_alert = gr.Textbox(label="告警名称")
            with gr.Row():
                event_rule_read_button = gr.Button(
                    "读取当前事件规则", variant="secondary"
                )
                event_rule_apply_button = gr.Button("应用事件规则", variant="primary")
            event_rule_status = gr.Textbox(
                label="当前规则说明（只读）",
                interactive=False,
                value="生成或加载技能后，在这里读取可编辑事件原子。",
            )
        with gr.Accordion("小目标增强：切片覆盖与重复框合并", open=False):
            gr.Markdown(
                "**先解决覆盖，再解决重复。**  切片把大图分块，横向/纵向覆盖只影响目标是否会落在相邻两块中，"
                "不决定是否合并框；同一目标被多块识别后，才由下方的合并方式和阈值处理。\n\n"
                "**推荐默认值**：切片 640×640、横纵覆盖 20%、实例级融合、阈值 0.45。"
                "小目标在切片边缘漏检时先提高覆盖比例；不同目标被合并时再提高合并阈值。"
            )
            tile_enabled = gr.Checkbox(False, label="启用切片增强（小目标场景打开）")
            with gr.Column(visible=False) as tile_options:
                include_full = gr.Checkbox(
                    True, label="同时保留整图检测（建议保持勾选，大小目标兼顾）"
                )
                with gr.Row():
                    tile_width = gr.Number(640, precision=0, label="切片宽度")
                    tile_height = gr.Number(640, precision=0, label="切片高度")
                    overlap_x = gr.Slider(
                        0,
                        0.9,
                        0.2,
                        step=0.05,
                        label="切片间横向覆盖（让相邻图片重复覆盖）",
                    )
                    overlap_y = gr.Slider(
                        0,
                        0.9,
                        0.2,
                        step=0.05,
                        label="切片间纵向覆盖（让相邻图片重复覆盖）",
                    )
                with gr.Row():
                    dedup_metric = gr.Radio(
                        [
                            (
                                "实例级融合（默认：框接近，或包含且中心一致）",
                                "instance",
                            ),
                            ("IoS（小框被大框包含时也容易合并）", "ios"),
                            ("IoU（仅整体框接近时合并）", "iou"),
                        ],
                        value="instance",
                        label="重复框合并方式（只处理同一目标的多次检测）",
                    )
                    dedup_threshold = gr.Slider(
                        0, 1, 0.5, step=0.05, label="合并阈值（越低越容易把框合并）"
                    )
                with gr.Accordion("查看：实例级融合、IoS、IoU 有什么区别", open=False):
                    gr.Markdown(
                        "1. **IoU**：交集 / 并集。两个框大小、位置都很接近才会高，较严格。\n\n"
                        "2. **IoS**：交集 / 较小框面积。小框被大框包含时会很高，较宽松。\n\n"
                        "3. **实例级融合**：同帧 + 同类别 + 同来源实体，且满足其一："
                        "（1）IoU ≥ 去重阈值；（2）IoS ≥ max(0.8, 去重阈值)，"
                        "且两个框中心距离 ≤ 较小框对角线的 25%。满足后视为同一实例，保留定位更好的框。\n\n"
                        "**合并后保留哪个框？** IoU、IoS、实例级融合只决定两个框是否属于同一实例，"
                        "不决定保留哪一个。启用切片时，优先保留未被切片边缘截断、来自更小切片"
                        "（画面细节更多）的框；若定位质量相同，保留模型先返回的框。未启用切片时，"
                        "保持原有的第一个框。"
                    )
            preprocess_button = gr.Button("应用覆盖与重复框合并配置", variant="primary")
        with gr.Accordion("候选框二次可见性确认（可选）", open=False):
            gr.Markdown(
                "**何时使用**：切片已找回候选框，但某个类别容易被相似物体误报时。"
                "它先保留全图/切片的召回结果，再对选中类别裁出带上下文的局部图复核；"
                "未选中的类别不受影响。\n\n"
                "**怎么配**：先点击“读取当前确认配置”，选择待复核的检测类别，"
                "再填写能确认目标真实存在的英文可见证据短语。保存后这条复核链会写入 Effective SkillPackage。"
            )
            context_enabled = gr.Checkbox(False, label="启用候选框二次可见性确认")
            context_targets = gr.Dropdown(
                choices=[],
                multiselect=True,
                label="待复核检测类别",
                allow_custom_value=True,
            )
            context_phrases = gr.Textbox(
                lines=3,
                label="确认可见证据提示词",
                placeholder="每行一个英文短语，例如：complete trash bin with visible container body",
            )
            with gr.Row():
                context_padding = gr.Slider(
                    0, 1, 1.0, step=0.05, label="上下文边距比例"
                )
                context_long_side = gr.Number(
                    640, precision=0, minimum=64, label="复核裁剪长边"
                )
            with gr.Row():
                context_read_button = gr.Button("读取当前确认配置", variant="secondary")
                context_apply_button = gr.Button("应用二次确认配置", variant="primary")
            context_status = gr.Textbox(
                label="二次确认配置状态",
                interactive=False,
                value="默认关闭。它是切片召回后的可选复核，不会替代切片或全图检测。",
            )
        with gr.Accordion(
            "结果媒体尺寸与 FPS ｜ 对输出清晰度/流畅度有要求时使用", open=False
        ):
            gr.Markdown(
                "**什么时候用**：需要把标注结果导出为固定分辨率，或让结果视频按指定帧率播放。"
                "**怎么配**：保持“原始媒体尺寸 + 按采样时间线”即可，结果和原素材一致；"
                "只有对外交付有明确规格时才选固定值。"
            )
            with gr.Row():
                output_size_mode = gr.Radio(
                    [
                        ("原始媒体尺寸（默认，推荐）", "source"),
                        ("处理后尺寸（跟随 resize）", "processed"),
                        ("固定尺寸", "fixed"),
                    ],
                    value="source",
                    label="结果媒体尺寸",
                )
                output_width = gr.Number(
                    1280, precision=0, label="结果宽度", visible=False
                )
                output_height = gr.Number(
                    720, precision=0, label="结果高度", visible=False
                )
            with gr.Row():
                output_fps_mode = gr.Radio(
                    [
                        ("按采样时间线（默认，时长一致）", "sample_timeline"),
                        ("原始视频 FPS（更流畅，文件更大）", "source"),
                        ("固定 FPS", "fixed"),
                    ],
                    value="sample_timeline",
                    label="结果视频 FPS",
                )
                output_fps = gr.Number(25.0, label="固定结果 FPS", visible=False)
            output_config_button = gr.Button("应用结果媒体配置", variant="primary")
        with gr.Accordion(
            "高级原子编排（专业模式）｜节点、连接、复杂时序与结果契约",
            open=False,
            visible=False,
        ):
            editor_overview = gr.Markdown(
                "### 统一规则编排中心（专业模式）\n仅在业务规则配置无法表达需求时使用。"
            )
            gr.Markdown(
                "这里展示执行层原子、节点 ID、输入端口、Recipe 和 EventPattern。"
                "它与上方业务规则配置共享同一份 SkillEditorDocument；专业修改不会被普通表单静默覆盖。"
            )
            unified_status = gr.Textbox(
                label="统一配置状态",
                interactive=False,
                value="生成或加载技能后，读取 LLM 生成的完整配置。",
            )
            editor_history = gr.JSON(value={"undo": [], "redo": []}, visible=False)
            with gr.Row():
                unified_undo_button = gr.Button("撤销", variant="secondary")
                unified_redo_button = gr.Button("重做", variant="secondary")
                unified_restore_button = gr.Button(
                    "恢复 LLM 生成结果", variant="secondary"
                )
            with gr.Row():
                unified_branch = gr.Dropdown(
                    choices=[],
                    label="业务分支（名称 + 内部 ID）",
                    allow_custom_value=True,
                )
                unified_action = gr.Dropdown(
                    [
                        "新增原子",
                        "复制原子",
                        "删除原子",
                        "替换能力",
                        "连接原子",
                        "断开连接",
                    ],
                    value="新增原子",
                    label="组合编辑动作",
                )
            with gr.Row():
                unified_branch_action = gr.Dropdown(
                    [
                        "新增分支",
                        "复制分支",
                        "重命名分支",
                        "启用/停用",
                        "上移",
                        "下移",
                        "删除分支",
                    ],
                    value="新增分支",
                    label="业务分支动作",
                )
                unified_new_branch_id = gr.Textbox(
                    label="新分支 ID", placeholder="例如 branch_accident"
                )
                unified_branch_name = gr.Textbox(
                    label="分支显示名称", placeholder="例如 区域3交通事故"
                )
                unified_branch_button = gr.Button("执行分支编辑", variant="secondary")
            with gr.Row():
                atomic_node = gr.Dropdown(
                    choices=[],
                    label="原子节点（名称 + 来源 ID）",
                    allow_custom_value=True,
                )
                unified_operator = gr.Dropdown(
                    choices=[],
                    label="原子能力（完整注册表）",
                    allow_custom_value=True,
                )
                unified_new_node_id = gr.Textbox(
                    label="新节点 ID", placeholder="例如 region_people_count"
                )
            with gr.Row():
                unified_source_node = gr.Dropdown(
                    choices=[],
                    label="连接：来源原子",
                    allow_custom_value=True,
                )
                unified_target_node = gr.Dropdown(
                    choices=[],
                    label="连接：目标原子",
                    allow_custom_value=True,
                )
                unified_port = gr.Textbox(
                    label="目标输入端口",
                    placeholder="例如 objects / conditions / events",
                )
                unified_mutate_button = gr.Button("执行组合编辑", variant="secondary")
            recipes = build_recipe_catalog()
            with gr.Row():
                unified_recipe = gr.Dropdown(
                    choices=[
                        (f"{item.display_name}（{item.recipe_id}）", item.recipe_id)
                        for item in recipes.values()
                    ],
                    value=next(iter(recipes)) if recipes else None,
                    label="插入可复用组合 Recipe",
                )
                unified_recipe_button = gr.Button(
                    "插入到当前业务分支", variant="secondary"
                )
            gr.Markdown("#### 当前原子关键参数（用户覆盖层）")
            with gr.Row():
                atomic_parameter = gr.Dropdown(
                    choices=[],
                    label="关键参数",
                    allow_custom_value=True,
                )
            atomic_value = gr.Code(
                label="参数值（JSON；普通文本可直接填写）", language="json", lines=5
            )
            with gr.Row():
                atomic_read_button = gr.Button("读取完整配置", variant="secondary")
                atomic_apply_button = gr.Button("保存参数到草稿", variant="primary")
                atomic_reset_button = gr.Button("恢复生成值", variant="secondary")
            atomic_status = gr.Textbox(label="原子配置状态", interactive=False)
            with gr.Accordion("复杂事件编排 EventPattern", open=False):
                gr.Markdown(
                    "支持同时有效、时间窗内全部完成、先后顺序、重叠、N 选 M、缺失和重复等组合；"
                    "每个阶段可独立配置持续时间、身份范围和允许中断。"
                )
                unified_patterns = gr.Code(
                    label="EventPattern 列表（JSON）", language="json", lines=14
                )
                unified_patterns_button = gr.Button(
                    "保存复杂事件编排到草稿", variant="secondary"
                )
            with gr.Accordion("待确认条件与结果契约", open=False):
                with gr.Row():
                    unified_pending_choice = gr.Dropdown(
                        choices=[],
                        label="需用户确认的不确定条件",
                        allow_custom_value=True,
                    )
                    unified_pending_value = gr.Code(
                        label="确认值（JSON 或文本）", language="json", lines=3
                    )
                    unified_pending_button = gr.Button(
                        "确认并写入草稿", variant="secondary"
                    )
                unified_pending = gr.JSON(
                    label="待确认条件（02 实际标注或 03 用户确认）"
                )
                unified_results = gr.Code(
                    label="用户结果契约（数值、方向、目标、轨迹、事件、时间线、标注媒体等）",
                    language="json",
                    lines=10,
                )
                unified_results_button = gr.Button(
                    "保存结果与证据契约到草稿", variant="secondary"
                )
            unified_apply_button = gr.Button(
                "应用修改，更新运行版本", variant="primary"
            )
            with gr.Accordion("完整 V3 编辑文档（审计）", open=False):
                atomic_rows = gr.JSON(label="原子参数清单")
                editor_document = gr.Code(
                    label="SkillEditorDocument@3.0（当前唯一配置源）",
                    language="json",
                    lines=16,
                )
        with gr.Accordion("模型输入提示词（调试）", open=False):
            gr.Markdown(
                "**什么时候用**：模型漏检、误检或需要比较不同英文表述时。"
                "选择一个 Rex 检测节点，修改它发送给模型的视觉查询。"
                "**不会改动规则语义或其它节点**；系统始终自动追加固定的框坐标输出协议。"
            )
            grounding_prompt_node = gr.Dropdown(
                choices=[],
                label="要编辑的模型检测节点",
                interactive=True,
                allow_custom_value=True,
            )
            grounding_prompt_text = gr.Textbox(
                lines=3,
                label="模型检测提示词",
                placeholder="例如：Someone fell down",
            )
            with gr.Row():
                grounding_prompt_read_button = gr.Button(
                    "读取当前提示词", variant="secondary"
                )
                grounding_prompt_apply_button = gr.Button(
                    "应用到当前节点", variant="primary"
                )
                grounding_prompt_reset_button = gr.Button(
                    "还原默认短语提示词", variant="secondary"
                )
            grounding_prompt_status = gr.Textbox(
                label="模型提示词说明",
                interactive=False,
                value="生成或加载技能后，读取当前 Rex 检测节点的视觉查询。",
            )
        with gr.Accordion(
            "高级审计与手动编辑 ｜ 检查 LLM 语义、直接改 JSON、保存版本", open=False
        ):
            gr.Markdown(
                "**什么时候用**：怀疑 LLM 理解错了你的描述（看 Semantic IR 和未解析条件）；"
                "需要直接编辑完整 SkillPackage JSON；或把调好的配置保存为新版本。普通使用不需要展开。"
            )
            with gr.Row():
                semantic = gr.Code(
                    label="Semantic IR（LLM 理解的语义）", language="json", lines=18
                )
                unresolved = gr.JSON(label="未解析条件（LLM 没听懂的部分）")
            effective = gr.Code(
                label="Effective SkillPackage（唯一执行配置，可手动修改）",
                language="json",
                lines=22,
            )
            with gr.Row():
                load_variant_button = gr.Button(
                    "读取当前 variant JSON", variant="secondary"
                )
                apply_variant_button = gr.Button(
                    "写回 variant 并校验", variant="secondary"
                )
            variant_status = gr.Textbox(label="variant 状态", interactive=False)
            variant_editor = gr.Code(
                label="当前 WorkflowVariant JSON",
                language="json",
                lines=12,
                visible=False,
            )
            with gr.Row():
                validate_button = gr.Button("校验完整配置", variant="secondary")
                diff_button = gr.Button(
                    "查看 Generated / Effective Diff", variant="secondary"
                )
                save_button = gr.Button("保存为新版本", variant="primary")
            with gr.Row():
                save_id = gr.Textbox(label="保存技能标识（可自定义）")
                save_display = gr.Textbox(label="保存显示名称（可自定义）")
            validation = gr.Textbox(label="校验结果", lines=4)
            diff_output = gr.Code(label="配置 Diff", lines=10)
            saved_path = gr.Textbox(label="保存路径")

    return ReviewPage(
        configuration_state=configuration_state,
        configuration_apply_button=configuration_apply_button,
        apply_variant_button=apply_variant_button,
        atomic_apply_button=atomic_apply_button,
        atomic_node=atomic_node,
        atomic_parameter=atomic_parameter,
        atomic_read_button=atomic_read_button,
        atomic_reset_button=atomic_reset_button,
        atomic_rows=atomic_rows,
        atomic_status=atomic_status,
        atomic_value=atomic_value,
        business_add_branch_button=business_add_branch_button,
        business_add_condition_button=business_add_condition_button,
        business_apply_condition_button=business_apply_condition_button,
        business_branch=business_branch,
        business_branch_action=business_branch_action,
        business_branch_action_button=business_branch_action_button,
        business_branch_duration=business_branch_duration,
        business_branch_emission=business_branch_emission,
        business_branch_gap=business_branch_gap,
        business_branch_hold=business_branch_hold,
        business_branch_identity=business_branch_identity,
        business_branch_name=business_branch_name,
        business_branch_overview=business_branch_overview,
        business_branch_ratio=business_branch_ratio,
        business_branch_time_apply=business_branch_time_apply,
        business_branch_time_mode=business_branch_time_mode,
        business_branch_time_status=business_branch_time_status,
        business_time_target=business_time_target,
        business_time_inventory=business_time_inventory,
        business_time_confirm=business_time_confirm,
        business_branch_validity=business_branch_validity,
        business_branch_window=business_branch_window,
        business_capability=business_capability,
        business_compile_apply=business_compile_apply,
        business_condition=business_condition,
        business_condition_action=business_condition_action,
        business_condition_action_button=business_condition_action_button,
        business_condition_action_status=business_condition_action_status,
        business_condition_name=business_condition_name,
        business_condition_tree=business_condition_tree,
        business_expression_logic_apply=business_expression_logic_apply,
        business_expression_logic_group=business_expression_logic_group,
        business_expression_logic_negated=business_expression_logic_negated,
        business_expression_logic_operator=business_expression_logic_operator,
        business_expression_logic_required=business_expression_logic_required,
        business_expression_logic_selector=business_expression_logic_selector,
        business_expression_logic_summary=business_expression_logic_summary,
        business_final_apply=business_final_apply,
        business_final_combination=business_final_combination,
        business_final_failed=business_final_failed,
        business_final_name=business_final_name,
        business_final_reason=business_final_reason,
        business_final_required=business_final_required,
        business_final_source=business_final_source,
        business_final_type=business_final_type,
        business_group_button=business_group_button,
        business_group_members=business_group_members,
        business_group_operator=business_group_operator,
        business_group_required=business_group_required,
        business_imported_logic_apply=business_imported_logic_apply,
        business_imported_logic_group=business_imported_logic_group,
        business_imported_logic_negated=business_imported_logic_negated,
        business_imported_logic_operator=business_imported_logic_operator,
        business_imported_logic_required=business_imported_logic_required,
        business_imported_logic_selector=business_imported_logic_selector,
        business_imported_logic_summary=business_imported_logic_summary,
        business_include_tuning=business_include_tuning,
        business_new_logic_group=business_new_logic_group,
        business_output_add=business_output_add,
        business_output_delete=business_output_delete,
        business_output_delete_select=business_output_delete_select,
        business_outputs_apply=business_outputs_apply,
        business_outputs_table=business_outputs_table,
        output_editor_selector=output_editor_selector,
        output_editor_name=output_editor_name,
        output_editor_source=output_editor_source,
        output_editor_kind=output_editor_kind,
        output_editor_unit=output_editor_unit,
        output_editor_evidence=output_editor_evidence,
        output_editor_save=output_editor_save,
        output_editor_show=output_editor_show,
        output_editor_status=output_editor_status,
        business_parameter_boolean=business_parameter_boolean,
        business_parameter_control_help=business_parameter_control_help,
        business_parameter_help=business_parameter_help,
        business_parameter_multi=business_parameter_multi,
        business_parameter_number=business_parameter_number,
        business_parameter_open_multi=business_parameter_open_multi,
        business_parameter_readonly=business_parameter_readonly,
        business_parameter_select=business_parameter_select,
        business_parameter_selector=business_parameter_selector,
        business_parameter_table=business_parameter_table,
        business_parameter_text=business_parameter_text,
        business_pattern_apply=business_pattern_apply,
        business_pattern_branches=business_pattern_branches,
        business_pattern_correlation=business_pattern_correlation,
        business_pattern_mode=business_pattern_mode,
        business_pattern_panel=business_pattern_panel,
        business_pattern_required=business_pattern_required,
        business_pattern_status=business_pattern_status,
        business_pattern_window=business_pattern_window,
        pattern_editor_selector=pattern_editor_selector,
        pattern_editor_name=pattern_editor_name,
        pattern_editor_step=pattern_editor_step,
        pattern_editor_up=pattern_editor_up,
        pattern_editor_down=pattern_editor_down,
        pattern_editor_dependencies=pattern_editor_dependencies,
        business_region_comparison=business_region_comparison,
        business_region_event=business_region_event,
        business_region_name=business_region_name,
        business_region_operator=business_region_operator,
        business_region_override_apply=business_region_override_apply,
        business_region_override_group=business_region_override_group,
        business_region_overrides=business_region_overrides,
        business_region_value=business_region_value,
        business_restore_button=business_restore_button,
        business_rule_status=business_rule_status,
        business_trigger_apply=business_trigger_apply,
        business_trigger_cooldown=business_trigger_cooldown,
        business_trigger_mode=business_trigger_mode,
        business_trigger_outputs=business_trigger_outputs,
        business_trigger_severity=business_trigger_severity,
        config_status=config_status,
        context_apply_button=context_apply_button,
        context_enabled=context_enabled,
        context_long_side=context_long_side,
        context_padding=context_padding,
        context_phrases=context_phrases,
        context_read_button=context_read_button,
        context_status=context_status,
        context_targets=context_targets,
        dedup_metric=dedup_metric,
        dedup_threshold=dedup_threshold,
        diff_button=diff_button,
        diff_output=diff_output,
        editor_document=editor_document,
        editor_history=editor_history,
        editor_overview=editor_overview,
        effective=effective,
        end_seconds=end_seconds,
        event_rule_add_condition=event_rule_add_condition,
        event_rule_alert=event_rule_alert,
        event_rule_apply_button=event_rule_apply_button,
        event_rule_association=event_rule_association,
        event_rule_association_group=event_rule_association_group,
        event_rule_association_object=event_rule_association_object,
        event_rule_association_subject=event_rule_association_subject,
        event_rule_association_threshold=event_rule_association_threshold,
        event_rule_card_state=event_rule_card_state,
        event_rule_cards=event_rule_cards,
        event_rule_categories=event_rule_categories,
        event_rule_category_node=event_rule_category_node,
        event_rule_condition_1=event_rule_condition_1,
        event_rule_condition_2=event_rule_condition_2,
        event_rule_condition_2_row=event_rule_condition_2_row,
        event_rule_event=event_rule_event,
        event_rule_gap=event_rule_gap,
        event_rule_legacy_apply_probe=event_rule_legacy_apply_probe,
        event_rule_logic=event_rule_logic,
        event_rule_operator_1=event_rule_operator_1,
        event_rule_operator_2=event_rule_operator_2,
        event_rule_read_button=event_rule_read_button,
        event_rule_region_overrides=event_rule_region_overrides,
        event_rule_scope=event_rule_scope,
        event_rule_seconds=event_rule_seconds,
        event_rule_status=event_rule_status,
        event_rule_summary=event_rule_summary,
        event_rule_trigger=event_rule_trigger,
        event_rule_value_1=event_rule_value_1,
        event_rule_value_2=event_rule_value_2,
        frame_step=frame_step,
        grounding_prompt_apply_button=grounding_prompt_apply_button,
        grounding_prompt_node=grounding_prompt_node,
        grounding_prompt_read_button=grounding_prompt_read_button,
        grounding_prompt_reset_button=grounding_prompt_reset_button,
        grounding_prompt_status=grounding_prompt_status,
        grounding_prompt_text=grounding_prompt_text,
        include_full=include_full,
        interval_seconds=interval_seconds,
        load_variant_button=load_variant_button,
        long_side=long_side,
        max_frames=max_frames,
        output_config_button=output_config_button,
        output_fps=output_fps,
        output_fps_mode=output_fps_mode,
        output_height=output_height,
        output_size_mode=output_size_mode,
        output_width=output_width,
        overlap_x=overlap_x,
        overlap_y=overlap_y,
        preprocess_button=preprocess_button,
        read_execution_button=read_execution_button,
        resize_apply_button=resize_apply_button,
        resize_height=resize_height,
        resize_interpolation=resize_interpolation,
        resize_mode=resize_mode,
        resize_width=resize_width,
        sample_button=sample_button,
        sample_fps=sample_fps,
        sample_mode=sample_mode,
        save_button=save_button,
        save_display=save_display,
        save_id=save_id,
        saved_path=saved_path,
        semantic=semantic,
        start_seconds=start_seconds,
        tile_enabled=tile_enabled,
        tile_height=tile_height,
        tile_options=tile_options,
        tile_width=tile_width,
        unified_action=unified_action,
        unified_apply_button=unified_apply_button,
        unified_branch=unified_branch,
        unified_branch_action=unified_branch_action,
        unified_branch_button=unified_branch_button,
        unified_branch_name=unified_branch_name,
        unified_mutate_button=unified_mutate_button,
        unified_new_branch_id=unified_new_branch_id,
        unified_new_node_id=unified_new_node_id,
        unified_operator=unified_operator,
        unified_patterns=unified_patterns,
        unified_patterns_button=unified_patterns_button,
        unified_pending=unified_pending,
        unified_pending_button=unified_pending_button,
        unified_pending_choice=unified_pending_choice,
        unified_pending_value=unified_pending_value,
        unified_port=unified_port,
        unified_recipe=unified_recipe,
        unified_recipe_button=unified_recipe_button,
        unified_redo_button=unified_redo_button,
        unified_restore_button=unified_restore_button,
        unified_results=unified_results,
        unified_results_button=unified_results_button,
        unified_source_node=unified_source_node,
        unified_status=unified_status,
        unified_target_node=unified_target_node,
        unified_undo_button=unified_undo_button,
        unresolved=unresolved,
        validate_button=validate_button,
        validation=validation,
        variant_choice=variant_choice,
        variant_editor=variant_editor,
        variant_status=variant_status,
    )
