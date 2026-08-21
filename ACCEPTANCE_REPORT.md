# Vision Skill Builder V2 Demo 验收报告

日期：2026-08-14  
项目：`C:\yhe_user\detection_project\vision_skill`

## 结论

当前 Demo 的完整闭环已打通：一句自然语言可生成可查看、可修改、可保存、可删除、可执行的图片/视频视觉技能；语义、前处理、ROI/方向配置和运行结果彼此可解释。自动化测试 `271/271` 通过，P01～P13 的 V2 真实案例矩阵 `63/63 semantic_passed`，历史用户失败语句 `10/10 automatic_passed`。

这里的通过只针对已声明的受控验收案例；它不代表 Rex 在所有现场画面上达到生产级准确率。界面继续明确区分 `runtime_executed` 与 `semantic_passed`。

## 核心要求与证据

| 要求 | 状态 | 证据 |
|---|---|---|
| 一句话生成通用技能 | 通过 | `DeepSeekSemanticPlanner → Canonical Semantic IR → WorkflowCompiler`；LLM 不生成代码或自由 DAG |
| 图片/视频媒体选择 | 通过 | 一个 SkillPackage 共享语义、独立 image/video variants；可仅图片、仅视频或二者 |
| 保持原尺寸 | 通过 | 自定义技能默认显式 `image.resize@1.1 {"mode":"identity"}`；真实运行 preprocessing summary 可审计 |
| 保持原始 FPS | 通过 | 自定义视频默认显式 `video.sample@1.1 {"mode":"frame_step","frame_step":1}` |
| 语义与前处理解耦 | 通过 | 前处理修改前后 Semantic IR 相同；Planner Prompt 禁止写入 resize/抽帧/tile/ROI 坐标 |
| 通用计数 | 通过 | `measure.count@1.0`：图片 frame、视频 unique track、事件 unique；白色车辆真实结果 4 |
| 通用运动方向 | 通过 | 任意实体 `detect→track→heading→reference→compare`；图像轴、全局多数、逐车道多数、人工方向 |
| ROI/车道/方向人工配置 | 通过 | 原媒体画布支持矩形、多边形、方向箭头；类型化配置槽写回 Effective SkillPackage |
| 默认媒体 | 通过 | 13 个预置、21 个声明 variant 均有内容寻址默认素材；临时上传与“设为默认”分离 |
| 可解释结果 | 通过 | 任务目标、来源、variant、框、轨迹、事件、数值、区域、方向、语义原子、Trace 分页显示 |
| 预置来源不混淆 | 通过 | 页面顶部明确显示自然语言/预置/已保存，切换来源清空旧执行状态 |
| P01～P13 | 通过 | `tests/preset_v2_acceptance_results.json`：63/63，runtime failed 0 |
| 历史失败语句 | 通过 | `tests/historical_v2_acceptance_consolidated_20260814.json`：10/10 |

## 真实 Gradio 真点击验收

### 自然语言计数

- 输入：`识别白色车数量。`
- 来源显示：自然语言生成，明确“未使用预置演示技能”。
- 媒体：`shared_normal_highway.png`，原始尺寸 1536×1024。
- 执行：identity resize；数值结果 `4`；标注图可见。
- 产物：`data/runs/20260814_012317_4be052ce`。

### P05 车道逆行

- 来源显示：预置 `P05_highway_wrong_way`，自然语言未参与当前技能。
- 默认素材自动加载：`P05_positive_short.mp4`，960×720、2 FPS、7 帧、3.5 秒。
- 执行结果：1 track、1 event；标注 MP4 可由 OpenCV 读取（7 帧、2 FPS、960×720）。
- 区域结果：`lane_left`、`lane_right` 两个多边形。
- 方向结果：`lane_left` 的整段视频多数方向向量。
- 产物：`data/runs/20260814_012936_bd4b6243`。

截图证据位于 `output/playwright/v2_acceptance/.playwright-cli/`。浏览器控制台存在 Gradio `upload_progress?upload_id=undefined` 的非阻断 404；不影响媒体加载、执行或产物生成。

## 回归摘要

```text
pytest:                 271 passed / 0 failed
P01-P13 V2 matrix:      63 semantic passed / 0 failed / 0 pending
historical utterances:  10 automatic passed / 0 failed
default media:          13 presets / 21 declared variants / 21 defaults
```

历史语句涵盖：红上衣灰裤、反光背心、黄色反光衣、蹲姿无支撑、橙色反光衣与安全帽两层否定、白衣负例、轿车/客车/人排除货车/面包车、白色车辆计数。

## 边界与后续

- 方向、速度和距离当前是原媒体二维像素坐标，不经标定不换算真实世界单位。
- `track.iou@1.0` 适合 Demo 的短视频可解释跟踪；复杂遮挡场景可按同一 TrackSet 契约替换跟踪器。
- SAHI 式切片可与全图检测同时开启，主要改善小目标召回；IoS/IoU 和阈值都在节点中显式配置，不解决类别语义冲突。
- 下一阶段应使用现场摄像头数据做人审、阈值标定与性能压测，而不是针对单句话追加隐藏规则。

## 复验命令

```powershell
conda activate vision-skill
cd C:\yhe_user\detection_project\vision_skill
python -m pytest -q
python app_v2.py
```

## 2026-08-14 Candidate Context Confirmation

The optional context-confirmation strategy is now a generic, per-variant
Effective SkillPackage transformation. It is not a P11-specific branch:

```text
tile/full-frame recall -> selected candidate phrases -> padded object crop
-> local Rex confirmation -> source-entity association -> keep confirmed
-> merge unselected candidates -> deterministic same-label deduplication
```

The Gradio "candidate context confirmation" panel exposes the selected
detection labels, confirmation phrases, crop padding and crop long side. It
can be read, updated or disabled. All generated nodes remain editable in the
Effective SkillPackage. `tests/test_context_confirmation.py` also guarantees
that a downstream count stays attached to the confirmed objects after a
reconfiguration. Full regression: `295 passed`.

## 2026-08-14 P11 / P13 / Lane Wizard Follow-up

- `measure.count@1.0` has the explicit reusable `group_by: none | label`
  parameter. P11 now emits `垃圾容器`, `溢出垃圾`, and `散落垃圾` as independent
  visible labels and publishes their per-label counts.
- P11 uses the existing generic tiling atom with an explicit `384 x 384`,
  `25%` overlap recall configuration. Its existing padded crop confirmation
  remains selectable and visible in the Effective SkillPackage; it is not a
  hidden garbage-specific rule.
- P13 keeps its regular-joint exclusion but disables `include_full_frame` on
  its generic tiling atom and sets same-label IoS deduplication to `0.35`.
  Grounding is therefore local-tile based, avoiding coarse whole-image
  candidates and reducing same-class tile overlaps without cross-category
  suppression.
- The generic annotation wizard now selects the next dependency-aware slot,
  creates collision-free names for repeatable regions, and exposes "添加另一个区域".
  A direction set only asks for arrows for already saved region IDs.
- Result media remains bounded in the workspace and opens an original-size
  modal on click. Escape and the close button dismiss it.

Regression: `300 passed, 6 warnings`. The warnings are Gradio deprecations.
The live Rex endpoint was unavailable on port 8000 during this change, so the
post-change P11/P13 field-media re-run remains pending rather than claimed.

## 2026-08-14 Atomic Category Evidence and Skill Assets

- Added `objects.filter_by_label@1.0`, a planner-visible atomic operator that
  partitions explicit upstream output labels without reinterpreting a detector
  phrase or applying hidden confidence competition.
- P11 now composes a reusable visible-evidence disambiguation subgraph:
  `select loose-litter -> ground container evidence -> mutual_match -> not ->
  filter -> merge -> same-label deduplicate`. A container that overlaps a
  loose-litter candidate is retained as `垃圾容器`; only the conflicting
  loose-litter candidate is removed. `溢出垃圾` remains independent.
- P04/P05 use generic named `region_set` / keyed `direction_set` slots. The
  two supplied lanes are editable example values, not a maximum; a regression
  adds a third area and its matching arrow successfully.
- The `05 资产` page now performs actual save, load and delete operations on
  independent `SkillPackage` versions. Loading replaces the current Effective
  SkillPackage used by review, annotation and execution.

Regression: `304 passed, 9 warnings`. These are structural and UI contract
checks. Although Rex port 8000 is reachable now, this report does not claim a
post-change P11 field-media accuracy result until that media has been rerun
and manually reviewed.

## 2026-08-17 Manual Lane Annotation Correction

- P04 and P05 no longer ship synthetic `lane_left` / `lane_right` polygons.
  Their `region.manual_set@1.0` nodes start with `regions: []`.
- P05 also starts with an empty `direction.manual_set@1.0` direction list.
  After the user saves regions, the dependency-aware wizard presents one
  direction item per saved region key. P04 never presents direction work.
- Empty named sets are valid pending parameters. `configuration_status` and
  executable validation still reject a run until the required region set (and
  P05 direction set) is complete.
- The annotation panel now states the exact workflow and that the number of
  regions is determined by the uploaded video, not by a fixed two-lane preset.

Regression: `304 passed, 9 warnings`; `http://127.0.0.1:6125/` returned HTTP
200 after restarting the updated application.

## 2026-08-17 Named Region/Direction Upsert Keeps Position

- Redrawing an existing named lane (or a per-lane direction arrow) previously
  removed it and appended it at the end, so the wizard list reordered
  (`lane_a, lane_c, lane_b`). `bind_named_region`,
  `bind_named_direction` (in `core/configuration.py`) and the direct node
  editors `apply_manual_roi_points` / `apply_manual_direction` (in
  `app_v2.py`) now upsert in place, preserving the original drawing order.
- Executor lookups are key-based (`lane.id` / direction `key`), so order
  preservation has no semantic effect; it only keeps the annotation wizard
  stable while the user draws, redraws, adds or deletes an arbitrary number
  of lanes.
- Added `scripts/verify_lane_wizard_flow.py`, which drives the real preset
  JSONs through `ConfigurationBinder` and the wizard state machine: P04 with
  3 manual lanes (draw / redraw / delete-to-empty / re-add), P05 with 4
  manual lanes plus 4 keyed arrows (draw / redraw / delete cleans the
  matching arrow), including the dependency-aware `current_slot` transitions.
- Full regression: `304 passed, 9 warnings` (Gradio deprecations only).

## 2026-08-17 Wrong-Way Arrow Direction Diagnosis & UX Fix

- Verified the direction contract is correct end to end:
  `logic.heading_by_lane@1.0` uses the drawn arrow as the **normal driving
  direction** (`vector = end - start`), and flags a track as wrong-way when
  its heading points opposite (`cosine < threshold`, threshold `-0.5`).
  This is exactly "与箭头相反的判为逆行", and it is covered by
  `test_compare_heading_uses_each_tracks_lane_reference`.
- Replayed a real P05 run (`data/runs/20260817_100958_73f91fd1`, media
  `data/demo_media/P05.mp4`): both drawn arrows pointed opposite to the actual
  two-way traffic, so every track was legitimately flagged opposite. The
  judgement logic was not inverted; the arrows had been drawn backwards
  (left lane traffic moves down-right while its arrow pointed up-left, and
  vice versa).
- Added a one-click **反转方向（方向箭头）** button that swaps the two draft
  direction points before saving, so a backwards arrow is corrected without
  redrawing.
- The direction drag now shows a live **arrowhead** during the drag (an SVG
  line plus arrowhead instead of a bare rectangle), so the drawn direction is
  visible before the pointer is released.
- Clarified the direction-tool and P04/P05 wizard copy: the arrow must be
  dragged along the lane's normal driving direction (tail → nose); a track
  moving opposite to it is wrong-way.

Regression: `304 passed, 9 warnings`; `http://127.0.0.1:6125/` returned HTTP
200 after restarting the updated application.

## 2026-08-17 Annotation Wizard / Delete / Upload Fixes

- The named-region wizard no longer auto-jumps to the direction slot after
  saving the first lane. A `region_set` slot always offers `new_item`, so
  "保存并继续下一项" stays on regions and hands out the next lane id
  (`lane_regions_2`, …). The user draws all lanes first, then selects the
  direction slot from the dropdown to draw one arrow per lane. Fixes the
  previous "draw region 1, then clicking polygon to draw region 2 errors"
  behaviour (the wizard had already switched the slot to the direction set).
- Deleting a saved annotation no longer errors. A dedicated
  `annotation_delete_target` dropdown lists the saved lanes (or arrows) of the
  current slot; `delete_named_annotation` dispatches to
  `delete_named_region` or the new `delete_named_direction` in
  `core/configuration.py`. Deleting a lane still cleans its matching arrow.
- Added a `clear_task_media` button next to the task-media file picker so the
  preset media can be reset explicitly before uploading a new file.
- Fixed a drag-preview regression in `annotation_drag_js`: the direction
  arrow preview is an SVG object, and `clearPreview()` must remove
  `preview.svg` (or the DOM node), not call `.remove()` on a plain object.
- Wizard markdown now derives a slot's 已完成/待完成 from its configured
  status and shows `可添加新区域` for the optional add-more action.
- The undo button is now "撤销上一步" and treats drag shapes (rectangle /
  direction arrow) atomically: undo clears the whole two-point draft, while
  polygon undo still pops one vertex. This removes the confusing leftover
  point after undoing a drag shape.
- Saving an arrow (or the next lane) no longer depends on the item_id
  textbox being fresh: `bind_annotation` now auto-derives the named target
  from the package when the provided id is empty or stale (direction set →
  the first lane missing an arrow; region set → the next free region id).
  Explicit redraws of an existing key are still honoured.

Regression: `304 passed, 9 warnings` (Gradio deprecations only);
`http://127.0.0.1:6125/` returned HTTP 200 after restarting.

完整设计、操作符含义与执行顺序见 `UNIVERSAL_VISUAL_SKILL_IMPLEMENTATION_PLAN.md` 第 20 节；上下文压缩后从 `PROJECT_CONTEXT.md` 第 15 节和 `project_state.json` 继续。
