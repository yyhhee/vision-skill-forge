# Vision Skill Builder Demo

一句自然语言生成可查看、可编辑、可校验、可保存、可执行的视觉技能。

项目目录：`C:\yhe_user\detection_project\vision_skill`

## 当前状态

V2 Demo 已打通：自然语言经 DeepSeek Thinking 抽取为 Canonical Semantic IR，再由固定编译器生成可编辑的图片/视频 DAG；原始媒体、ROI/方向配置、前处理、真实执行结果与逐节点 Trace 均可在 Gradio 查看。

当前版本包含 P01～P13 预置演示技能及其默认图片/视频素材；启动后可直接在页面选择并运行。

## 运行

```powershell
conda activate vision-skill
cd C:\yhe_user\detection_project\vision_skill
python app_v2.py
```

浏览器打开 `http://127.0.0.1:6131`。Rex vLLM 服务需在 `http://127.0.0.1:8000/v1` 可用。

五个页签分别用于：技能来源、Semantic IR 与 Effective SkillPackage、媒体与场景标注、运行与结果、技能与能力目录。

技能来源是互斥的：`自然语言生成`、`预置演示技能`、`已保存技能`。页面顶部始终显示当前实际执行来源，切换来源会清空旧配置。

## 测试与复验

```powershell
conda run -n vision-skill python -m pytest -q
conda run -n vision-skill python scripts\run_preset_v2_acceptance.py
conda run -n vision-skill python scripts\run_historical_v2_acceptance.py
```

- V2 预置技能：`presets_v2/P*.json`
- 默认素材目录：`data/demo_media/`（13 个预置演示技能均有可直接使用的默认素材）
- 真实运行产物：`data/runs/<run_id>/` 与 `data/runs_v2/<run_id>/`
- V2 预置验收：`tests/preset_v2_acceptance_results.json`
- 历史语句验收：`tests/historical_v2_acceptance_consolidated_20260814.json`

## 配置

- Planner：DeepSeek OpenAI-compatible API
- Planner 模型：`deepseek-v4-flash`
- Rex：现有 Rex-Omni vLLM OpenAI-compatible API
- UI：Gradio

真实密钥仅保存在本地 `.env` 中，`.env.example` 不包含密钥。

## 核心约束

- LLM 只编译固定操作符，不生成运行代码。
- 所有操作符规则、参数、版本和输入输出类型固定清晰。
- 生成技能必须在 UI 中完整展示并允许手动修改。
- 自定义技能默认使用显式 `image.resize(mode=identity)`；视频默认 `video.sample(mode=frame_step, frame_step=1)`，即保持原尺寸和原始 FPS。预置技能保留其已经验收的显式参数。
- 自然语言语义层默认不读取 resize、抽帧、切片和去重参数；需要时只能读取只读媒体可行性上下文，且不能把它写入 Semantic IR。
- 视频抽帧、resize、tile、Grounding、跟踪、逻辑和时序均为显式节点，可从 Effective 配置回读到界面。
- `measure.count` 可统计图片当前帧对象或视频唯一轨迹，例如白色车辆数量；统计作用域写入节点参数。
- 方向管线对人、车、动物等任意目标复用 `detect → track → heading → reference → compare`；参考可选图像轴、整段视频多数方向、逐命名车道多数方向或人工箭头。
- ROI 不是必需项；自动区域、手工区域和全图都以显式技能节点表达。
- 测试结果必须来自真实执行，禁止用预期结果冒充已通过结果。
- 技能可显式选择仅图片、仅视频或同时支持图片和视频；同时支持时使用共享语义、分媒体工作流。
- 视频 30 秒是 Demo 推荐上限而非硬限制；超过时只警告，不隐藏截断。
