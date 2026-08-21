# Vision Skill Builder V2 — 测试与验收计划

> 本文件与 `IMPLEMENTATION_PLAN.md` 配套。V2 尚待实施；现有运行产物是历史 runtime 证据，不自动等于 V2 semantic pass。

## 1. 验收原则

分开回答三个问题：

1. **结构正确吗？** Schema、Registry、类型、DAG、Semantic IR 覆盖完整。
2. **真实跑完了吗？** 真实 DeepSeek（编译案例）、真实 Rex、真实 Executor，产物完整。
3. **结果语义正确吗？** 与明确 ground truth 对照，目标/事件满足精度容差。

状态词：

```text
not_run
blocked
compile_failed
needs_review
unsupported
validation_failed
execution_failed
runtime_executed
runtime_no_detection
semantic_passed
semantic_failed
```

禁止把“产生任意框/任意事件”直接记为 `semantic_passed`。

## 2. 自动化测试层级

### L1 Schema / Registry

- SkillPackage 支持 `accept=[image]`、`[video]`、`[image,video]`。
- image/video variants 与 accept 一致；每个 variant 单独类型校验。
- 操作符名称和版本唯一，默认参数合法，定义/实现/UI/解释一致。
- 未知字段、未知操作符、坏引用、循环、不可达节点被拒绝。
- 旧 v1 SkillSpec 只能通过显式迁移器变为 V2。

### L2 Semantic IR / Compiler

- 原句每个实体、属性、载体、关系、数量、否定和时序条件都有连续 source span。
- 无法解析的条件进入 `unresolved` 并阻止无审阅编译。
- 颜色修饰载体时不能静默落到整个人/车辆。
- 同一目标的多属性从同一原始候选集分支并按稳定 ID 合取。
- 原子否定 XOR 集合否定统一计算；双重否定和排除表述结果正确。
- 图片 + 时序语义得到 `unsupported`；只有显式确认才允许 `degraded_semantics`。
- LLM 输出不能包含未注册操作符、任务专项策略名或 Python。

### L3 同义改写 / Metamorphic

以下话术必须得到相同 semantic hash、等价 DAG、相同 Rex phrases/参数，并在同一媒体上产生等价结果：

```text
检测穿红色上衣、灰色裤子的人。
识别穿红色上衣、灰色长裤的人。
找出上身红衣且下身灰裤的人员。
把红上衣并且穿灰裤的人框出来。
```

同类回归覆盖：

- 检测/识别/找出/框出。
- 且/并且/同时/逗号并列。
- 裤子/长裤、上衣/外套等 Ontology 同义词。
- 排除/去除/剔除/负样本。
- 未/无/没有/不、双重否定。
- 主动/被动语序和属性前置/后置。

### L4 Operator

- resize：long-side、stretch、contain padding 坐标恢复。
- crop/tile：局部框恢复为原始媒体 `[0,1]`。
- video.sample：fps、interval_seconds、frame_step、start/end、max_frames。
- 视频 >30 秒：产生 warn-only，不拒绝、不隐藏截断。
- tile + full frame 可同时运行；调用数估算与 Trace 实际数一致。
- IoU/IoS 公式、阈值边界、同标签限制与确定性 keep 顺序。
- color、relative size、position、inside/outside、near、overlap、contains。
- best_owner、not_associated、count scope、track、speed、heading、persist、sequence。

### L5 UI

- 三个技能来源互斥，顶部实际来源与当前配置一致。
- image/video/both 选择及双 variant 编辑正确。
- Generated / Effective Diff、Semantic IR、未解析项和实际 Rex phrases 可见。
- resize、抽帧、切片、全图、去重、时间段、预计调用数均可配置。
- ROI 可不配置；需要时可手工绘制并写入技能节点。
- 运行按钮明确运行当前 Effective 技能。
- 结果页显示目标、规范目标、variant、标注媒体、detections/events、constraint funnel、证据和 Trace。
- 自定义 skill_id/display_name 可保存；按明确选中版本删除，不影响其他版本和 presets。

## 3. 通用视觉回归矩阵

使用生成控制场景 + 真实复杂场景：

- 颜色：黑、白、灰、红、橙、黄、绿、青、蓝、紫、粉、棕。
- 载体：整体对象、上衣、裤子、头盔、反光衣、车辆主体、开放载体。
- 形状、大小、材质、位置、数量、状态、姿态、空间关系。
- 每类至少正样本、负样本、混淆样本。
- 多主体反串联：A 仅红上衣、B 仅灰裤时，结果必须为 0；同一人兼具两属性时为 1。
- 类别排除：轿车/客车/人作为正类，货车/面包车作为负类；框冲突按显式 negative-wins，不按跨类置信度猜测。
- SAHI A/B：大图小目标场景验证召回；普通大目标和类别混淆场景验证不会虚报“必然提升”。

开放词汇能力的验收记录必须注明“工作流结构是否正确”与“Rex 视觉结果是否正确”，便于区分编译缺陷和模型能力边界。

## 4. 图片 / 视频 / Both 验收

- `image` 技能：至少一张正图、一张负图、一张混淆图。
- `video` 技能：至少一个正视频、一个负视频、一个边界视频；演示视频推荐 ≤30 秒，但执行器不强制。
- `both` 技能：image 与 video variant 分别满足各自案例，不能只跑其中一个就标完全通过。
- 视频帧级目标技能共享图片语义，并验证抽帧、跟踪/聚合和视频渲染。
- 时间事件必须使用真实变化或合成运动序列；静态图片重复帧仅可标 pipeline smoke，不可标时序 semantic pass。

## 5. 预置技能矩阵

| ID | 技能 | 声明媒体能力 | 必验语义 |
|---|---|---|---|
| P01 | 烟火 | image + video | 图片可见烟火；视频可见/持续烟火 |
| P02 | 交通事故 | image + video | 可见碰撞/侧翻/事故外观；视频持续事件 |
| P03 | 12 类特种车辆 | image + video | 中文类别标签、独立 phrases、类别不互相去重 |
| P04 | 拥堵 | video | 数量高 + 速度低 + 持续 |
| P05 | 逆行 | video | 相对多数或手工参考方向相反 + 持续 |
| P06 | 车道人员逗留 | video | track + 车道 ROI + dwell |
| P07 | 违停 | video | track + 静止 + 禁停 ROI + persist |
| P08 | 道路抛洒物 | image + video | 道路区域障碍物；视频可持续 |
| P09 | 未戴安全帽 | image + video | person + head region + helmet association + not |
| P10 | 未系安全绳 | image + video | person + harness/rope association + not |
| P11 | 服务区垃圾 | image + video | 垃圾/散落废弃物 |
| P12 | 人员摔倒 | video | 姿态变化/摔倒状态 + persist |
| P13 | 桥梁病害 | image + video | 裂纹/锈蚀/渗水/剥落/露筋，切片 A/B |

注意：P06 没有车道区域只能证明“人员逗留”；P07 没有禁停区域只能证明“持续静止车辆”；不能用更弱语义冒充完整预置目标。

## 6. 每个真实案例的必存内容

```text
data/runs/<run_id>/generated_skill.json
data/runs/<run_id>/effective_skill.json
data/runs/<run_id>/semantic_ir.json
data/runs/<run_id>/result.json
data/runs/<run_id>/events.json
data/runs/<run_id>/trace.json
data/runs/<run_id>/annotated.jpg 或 annotated.mp4
data/runs/<run_id>/evidence/
```

案例清单另存：

```text
case_id、媒体路径/hash、来源/许可、媒体类型、时长、skill/version/variant、
instruction、semantic_hash、ground truth、容差、实际匹配、误检、漏检、
structure_status、runtime_status、semantic_status、run_id、审核日期、备注
```

## 7. 素材原则

- 优先使用用户已有真实素材；补充素材可来自授权清楚的网络来源或生成图像/视频。
- 生成素材用于控制变量和边界条件，真实素材用于展示复杂背景下的可信度。
- 任何素材来源写入 manifest。
- 预置视频暂推荐最多 30 秒，便于 Demo 成本和耗时可控；这是测试素材建议，不是运行能力硬限制。

## 8. V2 实施后的最小放行门槛

1. 全部确定性单测通过。
2. 媒体三选、30 秒 warn-only、双 variant UI 流程通过。
3. “红上衣、灰裤/长裤”同义改写与多人防串联通过。
4. 用户已报告的安全帽、反光衣、颜色、蹲姿、类别排除案例做通用回归；不允许新增案例专项分支。
5. 13 个预置至少完成结构验证和真实 runtime；对外称“语义通过”的项必须具备正/负/混淆证据。
6. `project_state.json`、`tests/preset_test_results.json`、验收报告与真实产物一致。

## 9. 2026-08-14 执行结果

- 确定性与 UI 自动化：`271 passed, 0 failed`。
- P01～P13 当前 V2 配置：`tests/preset_v2_acceptance_results.json`，63/63 semantic passed、0 pending。
- 历史自然语言失败案例：`tests/historical_v2_acceptance_consolidated_20260814.json`，10/10 automatic passed。
- Gradio 真点击：`tests/gradio_v2_acceptance_20260814.json`，自然语言图片计数与 P05 默认视频/车道/方向/事件流程通过。
- 13 个预置共 21 个声明媒体 variant，均配置内容寻址默认素材。

后续新增业务案例必须继续保存 structure、runtime、semantic 三层状态；现场素材若没有人工 ground truth，不得仅凭运行成功写为 semantic passed。
## Preset-loading regression

The UI contract test asserts that the temporal-event dropdown does not output to itself and that variant changes do not consume the stale selected event ID. Browser acceptance must load `P04_highway_congestion` followed by `P13_bridge_damage`, verify the correct target/default media/variant, and require an empty server error log.

## Result applicability regression

Result applicability must resolve registry union types through the actual workflow dataflow. In particular, `filter.apply@1.0` returns `EntitySet` in the registry but must remain a detection result when its entity input resolves to `ObjectSet`. Applicable-empty and structurally-not-applicable remain distinct UI states.
