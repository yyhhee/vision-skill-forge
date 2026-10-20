# 12 完整技能保存与加载 · 实施与验收

日期：2026-10-19。范围：独立6174纯前端；不修改6131原成品，不接后端、不调用模型、不部署。

## Findings

最终没有待修复的P0/P1/P2问题。已修复过程中的以下问题，保留失败证据，不以编译成功替代验收：

- [已修复P1] 首次模块刷新时版本样式/fixture隔离代码未被开发服务器重新加载。attempt-01/02中记录异常；刷新实际模块后，浏览器断言grid布局、fixture不写普通存储，全量回归通过。
- [已修复P2] attempt-03保存按钮落在视口下方。调整versions-grid高度与表单独立滚动、底部操作区；attempt-04及iteration-02均可见。原生桌面面板x202/y137、高851，底988；右栏x940.3，宽558.7。
- [已修复采集问题] iteration-01窄屏采到React懒加载占位而非成品，不作为窄屏验收。采集脚本显式等待页面主标题，重新采集iteration-02；窄屏页面与浏览器操作均复核。
- [产品修正] 原图的第五步骤、未配置3秒、V/R混用、警告色“已应用”改为真实数据与清晰边界。登记D-06/D-10/D-12/D-20/D-21。原图与数据本身不一致，不能声称逐字逐像素还原。

## 来源、状态与证据

- source visual truth：`C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/12-save-and-versions.png`
- 原图SHA256：`ab40b523942df9cb5cd74abc5fe6fa1b81a9ed7ff44626376cb70a0b53c3d3eb`
- 实现URL：`http://127.0.0.1:6174/skills/regional-alert/versions?fixture=12`
- 实现截图：[iteration-02/12/implementation.png](iteration-02/12/implementation.png)，SHA256 `a7023db28a4649d934a25c97291aadd5e53f327c76a473b8b3e7648c5ab43051`。
- 原图1513×1040px；实现1513×1040 CSS px，DPR1，1513×1040px。独立无登录Chromium151.0.7922.34，zh-CN/Asia-Shanghai/light。没有缩放、裁去差异、蒙版或修改原图。
- 状态：fixture12、左侧选V3、右侧提议V4、当前草稿10%、运行R3为20%、高级标识折叠、保存范围展开。原图捏造的3秒不复制；真实时序摘要来自文档。V1–V3仅是演示fixture，不伪装用户历史。
- 已将原图和实现放在同一比较输入中审阅：[完整左右对比](compare-12-02/side-by-side.png)、[50%叠加](compare-12-02/overlay-50.png)、[历史与摘要](compare-12-02/focused-history.png)、[保存表单](compare-12-02/focused-save-form.png)、[页脚](compare-12-02/focused-save-footer.png)。首轮compare-12-01亦保留，最终同状态原生截图一致。
- 04非回归：[regression-04-01/metrics.json](regression-04-01/metrics.json)，与上一轮consistency-fixes/desktop-01/04逐像素一致（差异0），未触动已确认的布局与主图。
- 窄窗口：[1366×768](iteration-02/12-compact/implementation.png)、[760×900](iteration-02/12-narrow/implementation.png)。主操作可达，无页面横向溢出；面板内滚动/窄屏竖向滚动；窄屏先保存后历史。
- [加载确认态](iteration-02/12/load-confirmation.png)。四份environment.json均记录字体loaded、DPR1、页面错误0、外部请求0、fixture普通存储键为空。

## 五项还原表面复核

1. 字体：保持已确认的本地Noto Sans SC与既有字体栈，标题/正文/说明层级一致；字体加载完成后截图。原图为生成式栅格，不能逐字验证其原始font文件；保留既有真实字体而不描画文字。
2. 间距布局：沿用双栏、12px栏距、表格与摘要堆叠、右侧表单及固定页脚。实际锚点与图面核对；新增导入按钮与真实状态行导致局部垂直位置不同，属于D-20/21；无整体风格重画。
3. 色彩：沿用白底、浅蓝背景、靛蓝主按钮、浅紫选中行、橙色风险说明及成功色。原图错误应用状态修正，不因贴图要求造成误导。
4. 图像素材：复用用户确认的04干净主图、真实logo/本地字体、现有Phosphor图标；非CSS手绘替代。海报contain保持比例与清晰度，不假装真实视频，不新生成或替换素材。与最初生成图的照片差异是既有已确认基准，非本轮未审批替换。
5. 文案内容：版本/运行分开；待保存预览与历史摘要明确；实际条件、时间、输出、区域、运行设置可检查。保存范围不包含密钥、媒体本体或结果；未接入功能不宣称已实现。

## 操作及数据验收

- 完整SkillDocument深拷贝保存，不从执行包重建。包含技能名称/描述、稳定ID、实体来源、全部条件、分支、嵌套编排组、顺序与依赖、条件/分支时间、有效期、输出触发、标注点及未完成状态、运行配置、素材引用、语义待复核状态、Schema及可序列化元数据。
- 每次保存追加新V；V与R独立。确认本地持久化成功后才提示成功，失败不更新名称/草稿或覆盖历史。
- 导入只暂存为版本；显式打开确认后替换当前草稿，可先备份。取消无改动；加载不应用、不启动任务、不重写R或旧运行结果。返回编辑时保留原场景页上下文；加载嵌套组后能继续编辑顺序与间隔。
- 导出单版本，清空隔离测试存储后导入、加载，文档逐字段相等，仍可编辑。支持当前完整技能格式和旧vsf-frontend-demo的draft；从不导入旧applied/revision作为生效状态。
- JSON/schema/引用/循环/输出类型/坐标校验；2MB文件限制与保存体积约束；拒绝敏感字段、不安全键、不可序列化元数据、data/blob媒体引用；同版本重复导入幂等，身份冲突拒绝。
- 缓存损坏保留原始内容、不自动清空；存储配额错误不假成功，可导出有效草稿备份。证据待核对可归档，但加载后仍阻止应用直到用户复核。
- 完整技能JSON只是配置，不含媒体文件。当前仅提供已有施工海报；不同mediaRef可暂存/导出，但打开会明确阻止，绝不冒用当前图片。异技能ID导入不覆盖当前技能；须在对应技能上下文操作。本轮不提供通用技能库或媒体上传。

## 最终验证

- `npm run typecheck`：通过。
- `npm test`：66/66通过，6文件。
- `npm run test:e2e`：68/68通过，无重试（原55 + 版本13），报告[final-verification/playwright-report/index.html](final-verification/playwright-report/index.html)，机器结果[functional-results.json](final-verification/functional-results.json)。前期失败尝试保留在attempt-01等目录。
- `npm run build`：通过；生成Sites所需client/server/hosting文件，但未发布。
- `npm run test:sites`：4/4通过。
- 两轮最终截图采集仅访问6174，全部0页面错误、0外部请求。04零像素回归。

## Open Questions / 边界

无阻塞项。没有真实后端/模型/视频接入；浏览器本地缓存不是云备份，建议导出JSON防浏览器数据清理。未声称已测所有设备、200%浏览器缩放、屏幕阅读器或真实媒体跨设备恢复。用户尚未确认12为新的视觉基准；此报告为实施验收，不冒充用户批准。

## Implementation Checklist

- [x] 完整文档归档与读写、导入导出、异常保护。
- [x] 与工作台入口联动、加载确认、保存/应用/运行边界。
- [x] 原生视口左右对比、叠加与局部复核，失败轮次记录。
- [x] 窄窗口与04回归、全套自动化测试。
- [x] 保留原服务、历史证据和已确认视觉基准。

Follow-up polish：可在用户确认后进一步压缩很长版本说明的表格呈现；目前说明会换行，不会丢失文本。不属于本轮阻塞项。

final result: passed
