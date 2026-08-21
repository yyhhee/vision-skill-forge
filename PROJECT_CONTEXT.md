# Durable Project Context

> 本文件用于上下文压缩或新任务接手时快速恢复。完整细节见 `IMPLEMENTATION_PLAN.md`。
> **最新基线**：2026-08-14 V2 Demo 已实施并验收；下文第 15 节及 `project_state.json` 优先于此前历史实现记录。运行完成与语义通过仍须分开解读。

## 1. 项目目标

在 `C:\yhe_user\detection_project\vision_skill` 建立独立 Gradio Demo：

```text
上传图片/视频
→ 输入一句自然语言
→ DeepSeek Planner 编译 VisualSkillSpec
→ 展示并允许人工修改完整技能配置
→ 校验
→ 调用 Rex-Omni 和固定规则操作符执行
→ 输出标注媒体、事件和逐节点 Trace
```

## 2. 已有基础

- Rex-Omni 项目：`C:\yhe_user\detection_project\Rex-Omni`
- Rex API 示例：`C:\yhe_user\detection_project\Rex-Omni\api_use.py`
- Rex Gradio 示例：`C:\yhe_user\detection_project\Rex-Omni\app01.py`
- Rex Automatic Grounding Data Engine：`applications/_2_automatic_grounding_data_engine`
- Rex vLLM 服务默认：`http://127.0.0.1:8000/v1`
- 当前 Rex 服务只接收图片；视频必须在本项目中抽帧后逐帧调用。

## 3. Planner

- Provider：DeepSeek
- Base URL：`https://api.deepseek.com`
- Model：`deepseek-v4-flash`
- 密钥：只在 `.env`，不得回显或写入文档/源码。
- 使用 OpenAI-compatible Chat Completions。

## 3.1 Python 环境

- Conda 环境名：`vision-skill`
- Python：3.11
- 环境定义：`environment.yml`
- 后续测试和运行统一使用 `conda run -n vision-skill ...`。

## 4. 已确认架构决策

1. 项目与 Rex-Omni 源码目录独立，通过 API 调用 Rex。
2. 使用 Gradio，不建设 React/FastAPI 分层。
3. LLM 只从固定 Operator Registry 选择节点并填参数。
4. Registry 是 Planner、Validator、UI、Executor、Explain 的唯一事实来源。
5. 用户看到并编辑的是 Effective VisualSkillSpec；Executor 不得隐式改写。
6. 不使用独立 SceneConfig。
7. 区域来源必须是显式节点：自动 Grounding、手工 ROI 或全图。
8. 所有空间数据回到原媒体归一化坐标 `[0,1]`。
9. Planner 失败时允许显式降级为原句 Direct Grounding，但 UI 必须标注降级。
10. 未执行真实端到端测试前，不得把任何预置技能标记为 passed。

## 5. MVP 操作符

```text
media.image@1.0
media.video@1.0
video.sample@1.0
image.resize@1.0
image.tile@1.0
rex.ground@1.0
region.full_frame@1.0
region.manual@1.0
region.from_objects@1.0
direction.manual@1.0
track.iou@1.0
spatial.inside@1.0
spatial.associate@1.0
measure.count@1.0
measure.speed@1.0
measure.heading@1.0
measure.majority_heading@1.0
logic.compare@1.0
logic.all@1.0
logic.any@1.0
logic.not@1.0
filter.apply@1.0
temporal.persist@1.0
output.draw@1.0
output.alert@1.0
```

## 6. 预置技能

1. 烟火检测
2. 交通事故检测
3. 特种车辆检测（12 类）
4. 高速车辆拥堵
5. 高速车辆逆行
6. 车道人员逗留
7. 车辆违停
8. 道路抛洒物
9. 施工未戴安全帽
10. 高处作业未系安全绳
11. 服务区垃圾
12. 人员摔倒
13. 桥梁病害

## 7. 每次真实测试必须保存

```text
data/runs/<run_id>/effective_skill.json
data/runs/<run_id>/events.json
data/runs/<run_id>/trace.json
data/runs/<run_id>/annotated.jpg 或 annotated.mp4
data/runs/<run_id>/evidence/
```

测试状态更新到 `tests/preset_test_results.json`。

## 8. 当前真实状态

- 方案：完成。
- `.env`：已保存 DeepSeek 配置。
- 实现代码：完成；Schema、Registry、Validator、Planner、Rex Gateway、图像/视频执行器、持久化和 Gradio UI 均已落地。
- DeepSeek：真实 `deepseek-v4-flash` 非思考 JSON 编译一次通过，并只生成 Registry 操作符。
- Rex：真实 `rex-omni-awq` API 已完成全部 13 个预置技能端到端执行。
- 测试：49 项自动化测试全部通过；9 项旧专项策略合同已退出活跃测试集合；13 个预置均有真实运行记录。
- UI 技能来源：自然语言、预置演示、已保存技能三种模式互斥，顶部显示当前实际执行来源。
- 安全帽规则：安全帽中心位于人员框顶部 35% 头部子区域，再取反得到未戴帽人员；不再使用安全帽面积占整个人体框面积的规则。
- 通用自然语言编译：所有可框定位实体查询统一走 `自然语言 → 原子约束账本 → 固定编译器`。LLM 只输出基础实体、required/absent、可见属性类型和肯定式英文证据，不允许输出任务专用策略名；固定编译器生成候选、证据、关联、取反、过滤节点。
- 自定义技能管理：保存时可分别指定稳定技能标识（英文开头，可含数字、下划线、连字符）和中文显示名称；已保存技能可按明确选中的版本删除，预置目录不受影响。
- SAHI 式切片增强：技能配置页提供显式可选项；执行全图检测和重叠切片检测、坐标回映及同标签 IoS/IoU 去重。它用于提高高分辨率图像的小目标召回，不解决类别语义混淆；Rex 无置信度分数，因此不是 SAHI 分数型 NMS/NMM 的逐行复刻。
- 通用多尺度证据：基础实体用全图召回；required 非颜色证据统一使用 `image.tile@1.0`（640×640、20% overlap、保留全图）提高小目标召回；absent/排除证据只用全图，避免切片弱匹配放大后过度删除。该规则按逻辑极性工作，不按姿态、服装或类别任务词工作。
- 通用颜色原子能力：`visual.color_fraction@1.0` 在候选框指定子区域按固定语义 HSV 色族和显式阈值判断白/黑/灰/红/橙/黄/绿/蓝，不让 Rex 猜颜色。黄色语义族覆盖黄至荧光黄绿但排除橙色；有彩色默认占比 0.1，白/黑/灰默认 0.2，均直接写入可编辑 SkillSpec。
- 复合分句可拆为多个原子约束：同一个原文 clause 可分别成为不同 kind 的 predicate source，例如“黄色反光衣”固定要求 `wearable=reflective vest` 与 `color=yellow` 两个节点，禁止压缩为单个 Rex phrase；同 kind 重复仍会被校验拒绝。
- 通用布尔极性：每个原子保存 `source_span`，固定编译器按 `最终否定 = 原子否定 XOR 外层集合否定` 重新归位 required/absent；原子否定包括无/未/没有/没/不/缺失，外层否定包括排除/去除/剔除/负样本。LLM 无权决定最终极性；遗漏紧邻否定词时编译器自动补回；归一化后的同语义原子自动去重，双重否定还会同步修正显示标签。
- 已删除旧专项入口：安全帽固定分支、车辆固定排除分支、反光衣蹲姿扩词分支、旧 entity_contrast 编译器均不再存在；降级也不再回到安全帽专项工作流。
- 真实通用回归（同一张施工图）：反光衣 6 人 `data/runs/20260812_122759_65efb394`；白衣 0 人 `data/runs/20260812_122806_b05c7164`；蹲姿＋双膝弯曲＋臀部无支撑 1 人 `data/runs/20260812_122938_3ec40b8f`。
- 复合颜色＋穿戴回归：“识别穿着黄色反光衣的人”检出左侧两名荧光黄色反光衣人员，排除所有橙色反光衣，记录 `data/runs/20260812_124621_45f63795`；白衣保持 0 人，记录 `data/runs/20260812_124629_cdd08a20`。
- 布尔语义真实回归：“橙色反光衣且未带帽”得到 1 人 `data/runs/20260812_140841_3e69d4e8`；“排除未带帽”“去除未带帽”“负样本是未带帽”均归一化为橙色反光衣且戴帽，三种表达均得到相同 3 人，记录分别为 `20260812_140850_8882159b`、`20260812_140903_55749015`、`20260812_141325_0de82d1e`。
- `person_bus_car/v1 + smoke.png` 实测：原图模式 25 框，320×320/20% overlap/全图+切片/IoS 0.5 为 27 框，并新增客车内部轿车误框；该图不建议开启。
- UI：Gradio 在 `http://127.0.0.1:6122` 完成 HTTP 200 启动烟雾测试。
- 详细证据：`ACCEPTANCE_REPORT.md`、`tests/preset_test_results.json`、`data/runs/`。
- 历史 V1 预置技能均已有真实端到端运行产物；这些记录证明 runtime 闭环，不自动证明 V2 的正/负语义验收。最新口径见第 13 节。

## 9. 下一步唯一建议动作

打开 `http://127.0.0.1:6122`，自然语言生成后在 Effective SkillSpec 中检查并修改通用原子节点；运行页查看逐节点输入输出和耗时，再保存人工确认版本。

## 10. 2026-08-12 通用视觉属性与关系编译升级

- 唯一能力目录：`core/visual_catalog.py`。颜色、属性维度、空间关系和计数比较符由目录统一提供给 Planner、Validator、Registry 和 Executor。
- 颜色支持：黑、白、灰、红、橙、黄、绿、青、蓝、紫、粉、棕；执行使用固定 HSV 色域和可编辑像素占比阈值。
- 属性维度：颜色、形状、大小、材质、画面位置、状态、穿戴、姿态、外观；颜色和几何使用固定算子，开放词汇属性使用 Rex 原子证据。
- 空间语义：画面绝对位置由检测框中心和 `position_margin` 判断；实体相对位置、near、overlap、inside、contains 由同帧检测框执行固定计算；ROI 可手工修改。
- 多实体关系工作流保留每个实体自己的原子属性，不允许将“青色球体/紫色瓶子”等属性丢失或压回复合关系短语。
- 大小默认是同类候选框面积的相对分组，支持在 SkillSpec 中切换为固定归一化面积阈值。
- DeepSeek `deepseek-v4-flash` 默认启用 Thinking Mode：`PLANNER_THINKING=enabled`、`PLANNER_REASONING_EFFORT=high`；可在 `.env` 中关闭。思考模式下不发送 `temperature`。
- 当前自动化回归：85 passed。综合记录：`tests/generic_visual_attribute_regression.json`；生成验证图：`tests/assets/generated_visual_attribute_scene.png`。
- 真实生成图回归已通过：小型红色金属方块=1、紫瓶左侧青球=1、打开的紫色玻璃瓶=1、棕色木盒=1、物体总数=6。
- 能力边界：编译结构与算子语义可确定性验证，但开放词汇形状/材质/状态的最终召回仍受 Rex 模型视觉能力限制。

## 11. 2026-08-12 属性载体与主色语义回归

- `black_cloth/v1 + ultralytics/03.png` 原结果 7 人，根因是黑色像素占比直接作用于整个人框，阴影、安全带、栏杆、鞋和背景造成假阳性。
- 通用执行结构升级为：`基础实体 -> 属性载体 -> 载体主色 -> 载体/实体关联`。颜色可选 `carrier`，例如 clothing、helmet、vehicle body；不新增任何黑衣专项分支。
- `visual.color_fraction@1.0` 新增可编辑参数 `selection_mode=fraction|dominant` 与 `dominance_margin`。载体颜色默认使用 dominant；实体整体颜色继续使用 fraction。
- 已保存修复技能 `black_cloth/v2`，保留 v1。独立加载 v2 对 `03.png` 实测：8 个人候选、8 个衣物载体、2 个黑色主色衣物、最终 2 人。
- 验证记录：`tests/black_cloth_regression.json`；真实运行：`data/runs/20260812_173354_ec403068`；自动化测试：88 passed。

## 12. 2026-08-12 多服装载体组合属性回归

- “识别穿红色上衣、灰色长裤的人”初始运行 0 人，记录 `data/runs/20260812_180020_53675f50`。
- 根因包括：上衣被过窄翻译成 shirt；载体存在条件与载体颜色条件重复；普通 overlap 会把载体串给相邻人员；灰色主色领先阈值不适合高光、褶皱面料。
- 新增固定载体类别目录：shirt/jacket/coat/top 归一为 `upper body clothing`；pants/trousers/shorts/skirt 归一为 `lower body clothing`；另支持 clothing/headwear/footwear/vehicle body。
- 新增 `spatial.associate relation=best_owner`：按“载体框被哪一个主体框覆盖比例最大”唯一归属载体，并使用可编辑最小覆盖阈值；解决邻近/遮挡人员串属性。
- 多个载体属性在同一基础实体集合上逐级过滤，语义为 AND。灰色服装使用显式像素占比，黑色服装保留主色判断。
- 最终真实运行 `data/runs/20260812_182408_e269c040`：正确命中中央红色上衣、灰色长裤人员 1 名；回归记录 `tests/multi_carrier_color_regression.json`；自动化测试 90 passed。

## 13. 2026-08-12 V2 完整方案决策（最新）

完整且唯一实施基线为 `IMPLEMENTATION_PLAN.md`。关键决策：

1. 一句话不是直接变成一个 Rex Prompt，而是 `原文条件账本 → Canonical Semantic IR → 语义覆盖校验 → 固定编译器 → SkillPackage → Executor`。
2. DeepSeek `deepseek-v4-flash` 只抽取带 `source_span` 的原子语义；默认启用 Thinking Mode（`reasoning_effort=high`）。LLM 不自由生成 DAG、操作符语义或 Python。
3. 技能媒体能力可选 `image`、`video` 或 `image + video`，不强制同时支持。一个 SkillPackage 共享语义，但使用独立的 image/video workflow variants；运行时按真实媒体显式选择 variant。
4. 时序语义不能由图片等价执行。逆行、逗留、持续、序列等技能通常仅支持 video；若生成图片代理语义，必须经用户确认并标 `degraded_semantics`。
5. 视频 **30 秒只是 Demo 推荐上限，不是硬限制**。超过 30 秒只警告并展示预计帧数、Rex 调用数和耗时；默认不拒绝、不截断。用户可显式选择片段或配置 `max_frames`。
6. 同义改写必须规范为同一语义。例如“裤子/长裤”等表达应产生相同 `semantic_hash`、等价 DAG、相同 Rex phrases/参数和同媒体结果。
7. 复合属性的所有分支从同一原始主体候选集并行计算，并按稳定 person ID 合取，避免顺序依赖和多人属性串联。
8. 颜色、形状、大小、材质、位置、数量、状态、姿态、空间和时序采用通用原子能力与 Ontology；禁止为安全帽、蹲姿、反光衣、白衣等测试话术新增任务专项执行分支。
9. 前处理全部为可见节点/配置：resize、视频抽帧三模式、crop、tile、是否保留全图、IoS/IoU 去重、时间范围和调用估算。ROI 不全局必填；需要时用 full-frame、自动 Grounding 或手工 `region.manual` 节点，不引入 SceneConfig。
10. SAHI 式切片可与全图检测同时启用，主要提高大图小目标召回，不解决类别语义冲突。Rex 无可靠统一置信度时使用确定性同标签去重，不做跨类别“高分胜出”。
11. UI 明确区分自然语言、预置和已保存技能来源；展示 Semantic IR、Effective 配置、实际英文 phrases、每个条件候选/通过/排除数、媒体 variant、标注结果、事件、证据与 Trace。自定义技能可自定义名称、版本化保存和按版本删除。
12. 验收状态拆成结构合法、运行完成、语义通过。现有 13 个预置的真实运行产物保留为历史 runtime 证据，但需使用正/负/混淆案例按声明媒体 variant 重新验收；静态图片重复成的视频不能证明时序语义正确。

下一实施顺序：先写失败测试和 V2 Schema，再实现 Semantic IR/固定编译器，然后做媒体 variants 与前处理 UI，最后用通用改写回归和 13 个预置真实案例重验。当前项目状态应视为 `v2_design_complete_implementation_pending`。

## 14. 2026-08-13 通用场景配置与媒体处理决策（最新）

完整方案已保存为 `UNIVERSAL_VISUAL_SKILL_IMPLEMENTATION_PLAN.md`，上下文压缩或继续实施时必须先读取。关键决策：

1. 上传媒体按 SHA-256 保存原始字节和原始宽高/FPS/帧数/时长，任何推理处理都不得覆盖原文件。
2. 自然语言只生成目标、属性、逻辑、区域需求、方向关系和时序事件，不生成 resize、抽帧、切片或 ROI 坐标。
3. 媒体上传可放在 UI 首步，但不是技能生成的强制条件；前处理参数在生成后、执行前配置。
4. resize、抽帧、切片和去重仍是 Effective SkillPackage 中可见、可编辑的显式节点。
5. ROI 在原图或视频标注帧上绘制并保存为原媒体归一化坐标，因此修改前处理不会使 ROI 失效。
6. 车道使用一个或多个命名矩形/多边形；方向可选择整段视频逐车道自动多数或逐车道手工箭头。
7. 自然语言产生需要几何值的工作流时生成配置槽；未完成必填槽不能执行，不得默认为全图或虚构方向。
8. 配置值仍直接写入技能节点，不引入独立 SceneConfig。
9. 目标框、轨迹、条件和事件使用类型化原子重复组合，禁止 P01～P13 专项执行分支。
10. 当前自动化测试为 187 passed；P05/P06/P07 的当前配置需重新做 hash 对齐的真实语义验收。

## 15. 2026-08-14 V2 Demo 终态（上下文压缩后从这里继续）

1. 当前入口是 `app_v2.py`，环境为 conda `vision-skill`，Gradio 端口 6122；DeepSeek 密钥只从 `.env:PLANNER_API_KEY` 读取，禁止写入文档或日志。
2. 自定义图片默认显式 `image.resize@1.1(mode=identity)`；自定义视频默认 `video.sample@1.1(mode=frame_step, frame_step=1)` 加 identity resize。预置技能保留已验证的显式前处理参数。
3. Planner 默认不读取执行参数。可选 `execution_context` 是只读提示，不能进入 Semantic IR；应用前处理后的 `semantic_ir` 和 `semantic_hash` 保持不变。
4. `measure.count@1.0` 已通用支持图片 frame 对象计数、视频 unique 轨迹计数和事件计数。“识别白色车数量”真实 Gradio 运行结果为 4，产物 `data/runs/20260814_012317_4be052ce`。
5. 方向能力对人、车、动物等任意实体复用；参考可选图像轴、整段视频全局多数、逐命名车道多数或人工箭头。车道归属使用轨迹历史中心点的多数区域，平局取最新有效归属。
6. P05 Gradio 真运行产物为 `data/runs/20260814_012936_bd4b6243`：2 个车道多边形、1 个车道参考向量、1 条轨迹、1 个逆行事件、可读标注 MP4。
7. 原始媒体内容寻址目录和元数据已接入 UI；13 个预置的 21 个声明 image/video variant 均有默认素材。临时上传不会覆盖默认，只有显式按钮才修改默认。
8. 通用穿戴证据融合局部物品归属与完整主体框；穿戴类否定误分为 entity exclusion 时按语法重标，不依赖具体物品名。视频属性去抖使用通用 `temporal.hold@1.0`。
9. P09/P11/P13 的修复分别基于通用时间保持、肯定式可见排除证据与几何/排除组合，没有增加运行时案例 ID 分支。
10. 真实 V2 预置矩阵：`tests/preset_v2_acceptance_results.json`，63/63 semantic passed、runtime failed 0。历史语句：`tests/historical_v2_acceptance_consolidated_20260814.json`，10/10 automatic passed。
11. 全量自动化：271 passed、0 failed；唯一 warning 是 Gradio Blocks `css` 参数未来弃用。
12. Gradio 真点击截图位于 `output/playwright/v2_acceptance/.playwright-cli/`。浏览器观察到 Gradio 上传进度接口的非阻断 404；图片与视频运行、产物和结果均正常。
13. 完整通用方案及原子规则见 `UNIVERSAL_VISUAL_SKILL_IMPLEMENTATION_PLAN.md` 第 20 节，最新验收摘要见 `ACCEPTANCE_REPORT.md`。

若继续开发，先运行 `python -m pytest -q` 并保持预置 JSON/hash 不变；下一阶段应是现场数据复核、阈值标定、性能和跟踪器替换，而不是继续为单个句式加专项规则。
## 2026-08-14 preset-loading regression fix

- Active demo URL: `http://127.0.0.1:6125/`.
- Restarted the stale Gradio process so the runtime schema accepts `semantic_ir.target.classes`.
- Removed stale temporal-event dropdown coupling during preset and variant switches.
- Verified the original failure sequence `P04_highway_congestion -> P13_bridge_damage` in the real UI; default media, media variant, task target, and preset source all update correctly.
- Final automated result: `288 passed`; the fresh 6125 server error log remained empty after the browser regression.
