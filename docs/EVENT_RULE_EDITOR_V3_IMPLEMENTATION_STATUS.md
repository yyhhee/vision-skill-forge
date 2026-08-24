# Event Rule Editor V3 实施状态与证据

本文件只记录可复现事实。设计目标以 EVENT_RULE_EDITOR_V3_IMPLEMENTATION_PLAN.md 为准。

## 实施前冻结基线

| 项目 | 基线 |
|---|---|
| Git 基线 | 2633f91 |
| Python | 3.11.15，vision-skill Conda 环境 |
| 测试 | 451 passed，116 warnings，23.94s |
| 注册执行原子 | 77 |
| 预置 | P01–P13，共 13 个 |
| V3 发布开关 | VISION_SKILL_RULE_EDITOR_V3=shadow |

复现命令：

    C:\Users\83915\Miniconda3\envs\vision-skill\python.exe -m pytest -q

注意：系统根环境中的 pytest.exe 不属于项目运行环境，直接调用会产生错误的导入失败；验收统一使用上述 Python 模块入口。

## 需求—实现—证据矩阵

| 阶段 | 核心交付 | 当前状态 | 验证证据 |
|---|---|---|---|
| Phase 0 | 五项 ADR、基线、feature flag | 已完成 | `docs/adr/0001`–`0005`；基线提交 `2633f91`；`tests/test_feature_flags.py` |
| Phase 1 | 唯一文档迁移、ResultSpec/PresentationSpec、运行信封、EvidenceIndex、四类哈希 | 真实图片运行闭环已通过 | `tests/test_editor_migrations.py`、`test_result_spec_projection.py`、`test_runtime_value_envelope.py`、`test_evidence_index.py`、`test_run_result_view.py`、`test_business_runtime_closure.py`；已覆盖 `condition/branch/event/final/result` 稳定来源、实际来源类型校验、AND/OR/N-of-M、结果框/数量/证据和标注媒体持久化 |
| Phase 2 | 图片多区域/同主体属性/计数纵向切片 | 编译纵切和通用图片运行链通过，指定着装真实媒体待验 | `tests/test_business_rule_compiler.py::test_image_business_tree_compiles_to_atomic_graph_and_semantic_outputs`；`tests/test_business_runtime_closure.py` |
| Phase 3 | 视频逆行持续纵向切片 | 编译与资源门禁通过，受控视频待验 | `tests/test_business_rule_compiler.py::test_video_branch_qualifier_keeps_frames_and_requires_direction_resource` |
| Phase 4 | 复杂时序纵向切片 | 顺序/汇合编译通过，状态机边界待补 | `tests/test_business_rule_compiler.py::test_complex_pattern_can_be_the_final_semantic_source`；现有 event atom tests |
| Phase 5 | 通用 03/04/05 Schema 驱动页面 | 进行中 | 03 已改为只读参数概览 + Schema 受控单项编辑器；固定枚举使用下拉，开放类别/短语使用文本或标签输入，数字使用受限数值框，区域/方向/来源使用动态下拉，布尔使用是/否，系统派生内容只读；当前条件树和 AND/OR/NOT 组合直接可见；复杂编排改名为“分支之间如何判定”；最终结果类型不再暴露。04 三层 ViewModel、05 能力与原子资产单测已存在 |
| Phase 6 | 自然语言四层测试 | 离线协议、复杂草稿与首个在线图片切片已通过 | `tests/test_v2_planner.py` 覆盖围栏 JSON、空/坏 JSON 的业务错误；`tests/test_business_rule_draft.py` 覆盖递归 AND/OR/NOT/N-of-M 与双 variant 隔离；`tests/test_v2_ui.py::test_natural_complex_event_draft_compiles_time_sequence_outputs_and_media` 覆盖复杂事件、输出和标注媒体编译；6131 在线输入“区域1红衣灰裤人员 + 区域2人数 >2”明确选择仅图片，LLM 2 次后接受 image，02 使用 `WeDetect/imgs/03.png` 手工完成两个区域，03 正确投影两个独立分支与 AND 条件树 |
| Phase 7 | P01–P13、历史迁移、影子对比 | 结构迁移与重新编译已通过，浏览器/真实媒体对比待验 | `tests/fixtures/v3/preset_reproduction_manifest.json`；`tests/test_v3_preset_reproduction.py` 覆盖 13 个预置两类自然语言表达、统一业务编辑器、媒体范围、最终判定和重新编译；冻结的 10 个成功历史案例全部迁移且语义哈希/原节点不丢失 |
| Phase 8 | 默认入口、资产审计与回滚 | 未开始 | 待发布门禁全部通过 |

当前全量自动回归：`518 passed, 232 warnings`。媒体边界测试确认：01 只允许用户明确选择“仅图片/仅视频/图片和视频”；同一技能可独立编译 image/video 两个 variant；视频持续与复杂顺序节点不会进入图片 variant；每次运行入口只接受一个媒体文件。受控参数测试确认：所有已注册业务参数编辑类型均由通用前端覆盖；比较方式等固定枚举使用下拉，开放类别与短语可编辑，区域/方向/来源动态选择，修改后能重新编译到底层原子。预置/历史测试确认：导入技能按媒体形成一个主业务分支，原流程组成能力可读、关键参数可改，结果来源按媒体隔离，检测类最终结果显式编译为“目标集合数量 > 0”，不会由渲染器猜真假。

该数字只证明离线代码和冻结 fixture 通过，不替代后续自然语言在线冒烟、P01–P13 浏览器复现和真实媒体证据验收。

完成状态只能由自动测试、持久化产物或浏览器复现证据更新，不能以页面已出现或代码已提交代替。
