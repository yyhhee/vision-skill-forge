# 三项配置一致性修复与复验

日期：2026-10-19。范围：独立前端 6174；不修改原项目或 6131 服务。

## 交付结论

本轮三个问题已实现并通过前端交互复验。保持现有视觉方向与模拟边界；尚未实施 12 完整技能保存与加载，也没有接入 LLM、真实模型或后端。本目录目前不是 Git 仓库，本轮未提交或推送。

### 1. 技能说明不再冒充重新编排

- 顶部说明条标注“说明”，工具提示明确不会重新编排。
- 编辑器标题为“修改技能说明”，保存后提示“检测规则未改变”。
- 显示从实际条件、分支、编排组和输出配置生成的只读摘要，不使用自由文本倒推业务逻辑。
- “按描述重新编排”明确未接入、不可点击，不返回固定结果冒充 LLM 生成。

![说明编辑与实际配置摘要](<C:/Users/83915/Vision Skill Forge Frontend/qa/consistency-fixes/final-verification/test-artifacts/consistency-description-ed-49d7c-t-unconnected-replan-action-isolated-chromium/01-description-boundary.png>)

### 2. 自定义语义证据的关联变更需要核对

- 去掉颜色修改时对自定义短语进行正则替换的行为。
- 新增显式短语来源：自定义保留原文 / 按目标、颜色、部位生成模板。模板不调用模型，也不代表识别准确率已验证。
- 使用规范化的来源身份、类别、颜色、部位记录核对上下文，不依赖图片、施工场景或特定装备。
- 关联变化后保留自定义短语，显示待核对；可以保存草稿，启用语义证据时未经核对不能应用。
- 待核对状态持久保存在文档中，关闭、刷新或重新打开表单不会清除；确认只针对当前关联上下文，后续再变更需再次核对。
- 仅调整数值占比不要求重新核对语义；仅 A 模式暂不阻断应用，但待核对信息仍保留，重新启用 B 时恢复阻断。
- 保留已有默认名称更新策略并补齐部位变化；用户自定义名称保留，核对提示同时要求检查名称。

![自定义证据待核对](<C:/Users/83915/Vision Skill Forge Frontend/qa/consistency-fixes/final-verification/test-artifacts/consistency-linked-input-c-3dbe4-ck-apply-until-acknowledged-isolated-chromium/02-linked-review.png>)

### 3. 新版本与活动旧任务明确选择

- 活动任务与准备验证的技能身份、修订号或快照不同时，先显示双方技能名和版本。
- 取消：不创建或停止任何任务。
- 继续旧任务：明确使用旧版本，保留原身份与快照。
- 停止旧任务并新建：先构造新任务，再将旧任务取消状态与新任务一起更新，旧快照和设置不改写。
- 同一技能、相同修订、完全相同快照仍复用已有任务，避免重复新建。
- 不同技能即使都是 R3，也必须选择，不仅比较版本数字。

![新旧任务版本选择](<C:/Users/83915/Vision Skill Forge Frontend/qa/consistency-fixes/final-verification/test-artifacts/consistency-cancelling-a-r-a9d3e-tinuing-explicitly-keeps-R3-isolated-chromium/03-version-choice.png>)

![明确新建后的R4任务](<C:/Users/83915/Vision Skill Forge Frontend/qa/consistency-fixes/final-verification/test-artifacts/consistency-starting-R4-ex-eecdd-hout-rewriting-its-snapshot-isolated-chromium/04-new-r4-task.png>)

## 测试与复验

| 检查 | 结果 |
| --- | --- |
| TypeScript 类型检查 | 通过 |
| 单元 / 组件测试 | 56 项通过；新增关联核对、非人物类别模板与实际摘要测试 |
| 独立无登录 Chromium 浏览器回归 | 55 项通过，包含本轮新增 6 个跨页一致性用例 |
| 构建及 Sites 包装测试 | 构建通过，4 项包装测试通过 |
| 固定桌面截图 | 03 / 04 / 05 / 06 / 07 / 08 / 15，DPR1，页面错误记录均为空 |
| 较窄视口回归 | 现有 760×900、1366×768 等操作测试通过；不代表已重设计窄屏布局 |
| Graphify | 已执行 AST 更新；大图 HTML 可视化被工具的节点数量上限跳过，不影响 graph.json 更新 |

浏览器最终记录：`final-verification/functional-results.json`、`final-verification/playwright-report/index.html`。各测试独立上下文，仅放行 6174；未使用用户登录浏览器或用户实际草稿。

早期尝试保留以便追溯：先复现缺失核对的失败单元用例；浏览器启动时发现默认 Playwright 可执行文件不存在，随后明确指定已有独立 Chromium；修正新测试的精确标签定位、示例技能名和演示存储构造。不是依靠重试消除失败；最终完整回归无重试通过。

## 视觉比较

- 保留原主图和批准基准，不覆盖旧截图。
- 与修改前的同视口 04 对比：场景面板与规则画布区域的像素差异均为 0；差异集中在顶部新增“说明”标记及文字位置，已登记 D-17。
- 与批准的 iteration-06 比较也生成并排、叠加、差异图；其中画布头部“编辑”入口是此前迭代已存在的差异，本轮没有新增该入口。
- 原生成图的比较同样保留，不能据此宣称整套页面达到逐像素一致。
- 本轮人工查看了说明编辑、待核对提示、版本选择、新 R4 任务以及 04 并排和叠加结果；05 的固定保存按钮仍可达。
- 修正登记：规格包 DECISIONS.md 的 D-17 / D-18 / D-19。

![04修改前后叠加，仅说明文字区域出现重影](<C:/Users/83915/Vision Skill Forge Frontend/qa/consistency-fixes/compare-pre-fix-04/overlay-50.png>)

## 实现位置

- `src/data/evidenceBinding.ts`：规范化关联上下文、模板生成与待核对判断。
- `src/data/ruleSummary.ts`：从配置生成只读条件与组合摘要。
- `src/data/editor.ts`、`document.ts`、`validation.ts`：表单保存、可选文档元数据及应用门禁。
- `src/components/InspectorDrawer.tsx`、`src/App.tsx`：说明编辑、短语来源、核对提示与草稿反馈。
- `src/components/runs/RunExperience.tsx`、`src/data/useDemoRuns.ts`：版本冲突选择及成组任务记录更新。
- `tests/unit/consistency.test.ts`、`tests/e2e/consistency.spec.ts`：本轮针对性覆盖；既有正向编辑测试加入显式核对步骤。

下一步：在上述一致性基础上实现 12 完整技能保存与加载，并保证条件树、嵌套编排、时间、输出、标注、运行设置及本轮核对元数据完整往返；加载归档不能自动覆盖已应用快照或历史运行。
