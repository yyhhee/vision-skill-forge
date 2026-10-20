# Vision Skill Forge · 前端还原原型

本目录是从现有6174前端复制保存的原型，位于独立 `next` 分支的 `frontend/`。已实现01技能库、02一句话演示创建、03–08/15编辑、09–11模拟运行、12完整技能版本、13模型配置、14能力管理和16运行记录。原vision_skill/6131与原6174目录未改动；同仓库的根目录后端也尚未与本前端连接。

版本边界、复验与已知未修复问题见[前端回退点](../docs/NEXT_FRONTEND_CHECKPOINT.md)。本回退点保存当前成果，不代表所有已审计缺陷已修复或可替代原成品。

## 本地预览

新副本测试入口：http://127.0.0.1:6175/skills 。原6174服务仍属于原前端目录，不是这个新副本。

固定截图入口：http://127.0.0.1:6175/skills/regional-alert/editor?view=linked&fixture=04

普通入口保存本地非敏感演示草稿；fixture入口独立恢复基准，不写入用户演示存储。运行与结果是明确标注的固定脚本演示，不是真实模型执行或视频推理。浏览器存储按来源（含端口）隔离；不会自动迁移原6174已有的技能或历史数据。

## 当前可以操作

- 03 场景标注：选择资源、命名、多边形/矩形/方向绘制、调整顶点、保存、撤销/重做和引用保护。
- 05 条件：分别查看颜色占比与模型语义证据，选择AND/OR/仅一种，编辑来源、部位、颜色、占比、短语。
- 06 时间：按条件/整个分支设定即时、持续、累计、比例、次数；明确来源和有效期，提示重复计时。
- 07 编排：新增/重命名可复用组、顺序/并行/OR/NOT、上移/下移/移除/添加成员、顺序锚点/间隔，循环引用阻断。
- 08 输出：受控选择来源和兼容类型、证据保存、触发周期/冷却；真实空结果，不发送外部通知。
- 15 校验：问题定位到真实字段，逐项修复、重新校验，全部有效才应用为新快照。
- 09 运行设置：抽帧、范围、缩放、切片、覆盖与去重；保存/应用分开，开始只读取已应用版本。切片覆盖与去重说明可展开。
- 10 模拟进度：开始、暂停/继续、单步、取消、故障示例、刷新恢复同一任务；未结束任务不重复新建。
- 11 结果证据：事件定位时间、同主体证据、只读运行快照、结果筛选、JSON导出；改草稿不改旧结果，新规则无脚本时不伪造结果。

运行入口：`/skills/regional-alert/validate`。完整固定结果示例：`/runs/run-regional-r3?state=completed&fixture=11`。原目录中的全量逐轮对照查看器没有全部入库；本副本保留精选证据，见 `qa/README.md`。

从 `/skills` 或 `/skills/regional-alert/editor?view=scene` 开始；画布的“编辑…”或顶部“更多操作”可进入其它编辑。独立顺序配置示例为 `/skills/sequence-demo/editor?view=orchestration&drawer=group`，不覆盖区域告警文档。

- 场景与分支双向选择；联动/仅画面/仅画布；画布拖动、缩放、适配。
- 选择并重绘区域，归一化坐标考虑contain黑边，调整顶点，保存/撤销/重做。
- 编辑颜色、阈值、证据AND/OR/单证据、数量、分支组合与连续时间、最终AND/OR和事件名称；受控输出选择。
- 表单或区域尚未保存时保护切换；草稿保存不改变运行快照；显式校验应用才从R3生成R4。
- 查看已应用配置、完整导出、刷新恢复演示草稿；损坏旧存储不会被静默覆盖。
- 海报模拟时间轴，不是视频播放器、测色器或识别模型。规则修改不产生伪造检测结果。

## 文件组织

src/App.tsx负责工作台装配，components/分离壳层/场景/画布/参数面板，data/统一文档、草稿与运行修订，fixtures/只放演示数据。绘制与图形库按模块懒加载，不把整张参考图铺作界面。

public/assets/为真实本地PNG和WOFF2；asset-manifest.json包含尺寸、来源、许可与SHA。主图为生成重建，不是无损原照；实际1448×1086，未达到建议1600长边，但满足585×440原生显示的2倍像素。logo有少量字形差异，字体原始来源未知。所有差异进入IMPLEMENTATION_DEVIATIONS与design-qa，不宣称逐像素一致。

## 检查与对比

已执行的数据/表单测试、浏览器测试和视觉证据见qa/04与design-qa.md。浏览器操作通过与视觉通过是独立结论。

```powershell
npm ci
npm run dev -- --host 127.0.0.1 --port 6175 --strictPort
npm run typecheck
npm test
npm run build
$env:VSF_TEST_BASE_URL = "http://127.0.0.1:6175"
$env:VSF_REQUIRE_OWN_SERVER = "1"
npm run test:e2e
npm run capture:04 -- qa/04/new-iteration
```

需要安装Playwright匹配的Chromium，或通过 `VSF_CHROMIUM_EXECUTABLE` 指定已安装的独立Chromium可执行文件。本次用户明确允许独立无登录Chromium访问6175、DPR1，不访问用户登录档案。E2E在 `VSF_REQUIRE_OWN_SERVER=1` 时自行启动并结束测试服务器；不要先手动占用6175。`capture:04` 也读取 `VSF_TEST_BASE_URL`，但截图前需有对应预览服务；其余历史批量截图脚本仍使用6174，不能将其误当新副本验收命令。捕获脚本拒绝覆盖旧轮次，不把脚本成功当视觉验收。

scripts/compare_reference.py使用现有Python环境的Pillow/numpy，输出同尺寸并排/50%叠加/差异/局部图和统计，不重采样、不mask、不修改原图。差异比例仅用于定位，不能解释为相似度评分。

原规格已归档到 `docs/design-spec/`，16张参考图保留在其中；旧规格的“尚未实施”等状态是当时记录，不覆盖本次实际状态。另保留04只读原图副本。用户于2026-10-19明确确认04主图与整体效果；qa/04/approved-baseline.json记录人工批准、既有iteration-06截图散列与适用范围，未覆盖原图或删除差异。该确认不是逐像素原图一致、全套页面完成或一次新自动回归通过。

## 官方依赖说明

[React Flow](https://reactflow.dev/api-reference/react-flow)、[react-konva](https://konvajs.org/docs/react/index.html)、[Phosphor](https://github.com/phosphor-icons/react)、[Noto Sans SC](https://fontsource.org/fonts/noto-sans-sc)、[Playwright截图比较](https://playwright.dev/docs/test-snapshots)。锁文件固定实际安装版本，字体图标在本地打包。保留[React Flow署名](https://reactflow.dev/remove-attribution)，未提供Pro订阅不会隐藏。

## 下一阶段

先修复审计确认的统一校验、图片时间有效期、运行摘要一致性问题，再明确前后端契约并接通图片／视频真实执行闭环。相机、外部部署与真实模型执行不属于本次存档；不因现有自动化测试通过而省略后续真实业务验收。
