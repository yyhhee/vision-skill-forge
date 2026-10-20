# 当前增量：16 运行记录

2026-10-20：[完整验收记录](qa/history/design-qa.md)。源图16与[最终实拍](qa/history/iteration-05/16/implementation.png)同为1513×1040、DPR1、五行与首条详情展开；已实际审阅[左右对照](qa/history/compare-16-05/side-by-side.png)、[叠加](qa/history/compare-16-05/overlay-50.png)、列表/详情局部，以及摘要、日期、空、错、1366与760窄屏状态。五项还原表面与迭代失败保留，合理语义差异登记D-31/32，无剩余P0/P1/P2，不宣称生成图逐像素相同。

105项单测、150项全量浏览器回归通过；补缺失ID安全守卫后36项定向回归、最终样式后21项历史检查通过，类型/构建及4项包装检查通过。01/04/12/13与上轮截图SHA一致；02仅32像素通道差≤2，14仅14像素图标/字形边缘差异（阈值12以上2像素），已定位为P3，无布局回归。仍为6174纯前端，不改6131、不接后端、不提交部署。历史列表只读当次快照，正常空归档不塞示例，缺失记录不借其它运行；下文全部历史保留。

final result: passed

# 历史增量：14 能力管理

2026-10-20：[完整验收记录](qa/capabilities/design-qa.md)。原图`C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/14-capability-management.png`，实现[iteration-07/14](qa/capabilities/iteration-07/14/implementation.png)，源图/实现1512×1040像素与CSS视口、DPR1、全部/空搜索/颜色复核选中/说明折叠。[同输入左右](qa/capabilities/compare-14-07/side-by-side.png)、[叠加](qa/capabilities/compare-14-07/overlay-50.png)、[列表](qa/capabilities/compare-14-07/focused-list.png)、[详情](qa/capabilities/compare-14-07/focused-detail.png)已实际复核。七轮保留早期失败与修复证据；五项表面、紧凑/窄屏及展开/空/错误/导入/停用状态均有记录。合理变化登记D-29/30，P3字形光栅化和库图标笔画差异保留，不宣称与生成图逐像素相同；无剩余P0/P1/P2。

97项单测、130项全量浏览器回归、末次页面21项检查、类型/构建和4项包装检查通过。01/02/04/12/13最终实拍与上一版相应图片SHA完全一致。能力启停与结构校验分离，停用阻止依赖应用/运行/继续但不破坏R/V或历史结果；内置不可删，自定义删除检查引用。清单导入仅元数据，启用也不冒充执行器已接入。仍为6174纯前端，未改6131、未部署或提交；下文历史完整保留。

final result: passed

# 历史增量：13 统一模型接入

2026-10-20：[完整验收记录](qa/models/design-qa.md)。源图 `C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/13-model-connections.png`；实拍[iteration-04/13](qa/models/iteration-04/13/implementation.png)，1513×1039 CSS/像素、DPR1、相同视觉页签/编辑项/折叠状态。[左右同输入](qa/models/compare-13-04/side-by-side.png)、[叠加](qa/models/compare-13-04/overlay-50.png)、[列表局部](qa/models/compare-13-04/focused-list.png)、[配置局部](qa/models/compare-13-04/focused-form.png)均已审阅。原图语义修正登记D-27/28；窄屏添加按钮和面板溢出问题已修复。01/02/04/12最终实拍与上一轮完全相同。

89项单测、109项全量浏览器测试、类型/构建与4项包装检查通过；模型管理无真实连接、密钥、自动路由或技能执行绑定。仍为6174纯前端，未改原6131、未提交或部署。详细报告保留失败记录、五项表面、操作异常与验收边界，下文旧证据完整保留。

final result: passed

最终记录为qa/models/final-verification-05，0失败/跳过/重试波动；缓存异常反馈另有专项验证。无剩余P0/P1/P2。

# 历史增量：02 一句话创建

2026-10-19：[完整验收记录](qa/create/design-qa.md)。原图 `C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/02-natural-language-create.png`；实拍[iteration-04/02](qa/create/iteration-04/02/implementation.png)，源图/实现均1513×1039像素、相同CSS视口、DPR1、fixture02预览展开。已审阅[左右同输入对比](qa/create/compare-02-04/side-by-side.png)、[叠加](qa/create/compare-02-04/overlay-50.png)、[表单局部](qa/create/compare-02-04/focused-form.png)、[理解图局部](qa/create/compare-02-04/focused-understanding.png)。四轮修复与五项还原表面均有证据，无剩余P0/P1/P2；合理文案/功能差异登记D-08/25/26，不宣称逐像素同一或用户已接受02。

80项单测、94项浏览器测试、4项包装检查及类型/构建通过；实际创建→手工标注两个区域→明确校验应用R1的完整链通过。01/04/12与上一轮截图完全相同。仍为6174纯前端，只支持列明的准确演示原句，不冒充LLM；未知描述不伪造配置，新建区域没有自动坐标。未改6131、未接后端、未部署。详细记录包含交互/异常/控制台/网络与残余边界，下文全部历史保留。

final result: passed

# 历史增量：01 技能库

2026-10-19：[完整验收记录](qa/library/design-qa.md)。原图 `C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/01-skill-library.png`；实现[iteration-04/01](qa/library/iteration-04/01/implementation.png)，1513×1040 CSS/像素、DPR1、fixture01列表5项、区域技能详情展开。[左右同输入对比](qa/library/compare-01-04/side-by-side.png)、[叠加](qa/library/compare-01-04/overlay-50.png)、[目录](qa/library/compare-01-04/focused-catalog.png)、[详情](qa/library/compare-01-04/focused-detail.png)已实际复核。字体、间距、颜色、素材、文案五项与原图比较，合理产品差异登记D-01/06/12/22–24；早期排版、菜单、缓存提示、未保存导航与窄屏遮挡问题已修正，证据保留，无待修P0/P1/P2。

75项单测、83项浏览器测试、4项包装检查及类型/构建通过。04与12保持上一轮零像素差异。新建是完整模板复制，不冒充LLM规划；四项缩略图参考条目明确仅有说明。仍为6174纯前端，未改6131、未部署；没有全部页面/模型/视频接入或用户视觉批准的隐含承诺。详细报告包含主要交互、异常、实际控制台/网络状态与残余测试边界。保留下文全部历史。

final result: passed

# 历史增量：12 完整技能保存与加载

2026-10-19：[完整验收记录](qa/versions/design-qa.md)。来源原图为 `C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/12-save-and-versions.png`；浏览器实拍为 [iteration-02/12](qa/versions/iteration-02/12/implementation.png)，1513×1040 CSS/像素、DPR1、fixture12选V3提议V4。已审阅[同输入左右对比](qa/versions/compare-12-02/side-by-side.png)、[叠加](qa/versions/compare-12-02/overlay-50.png)、[表单局部](qa/versions/compare-12-02/focused-save-form.png)及[历史局部](qa/versions/compare-12-02/focused-history.png)。早期样式刷新、保存按钮出屏和窄屏采集时机问题已修复，历史轮次未删除。D-06/10/12/20/21登记的产品差异为明确修正，无待修复P0/P1/P2；五项还原表面、操作路径、异常与截图均在详细记录。

66项单测、68项浏览器测试、4项包装检查与类型/构建通过。04与上一轮基准截图零像素差异。6174纯前端；6131原版未动；未接模型/后端/真实视频。保留下文全部历史证据，不以本轮覆盖旧报告。

final result: passed

# 04 联动工作台 · 历史还原与操作复核

## 当前运行闭环增量

09/10/11已实现；当前报告见[运行闭环QA](qa/run-flow/design-qa.md)，逐页对比为[运行流程原图对比](http://127.0.0.1:6174/qa/run-flow/index.html)。46项单测、49项浏览器测试及4项包装检查通过；无真实模型/视频接入，用户尚未确认这三页为新视觉基准。既有编辑流程与04证据继续保留。

当前运行增量 final result: passed

## 当前编辑流程增量

03/05/06/07/08/15已扩展；当前完整复核报告见[编辑流程QA](qa/editor-flow/design-qa.md)，逐页对比入口为[本地对比页](http://127.0.0.1:6174/qa/editor-flow/index.html)。原04历史证据保留在下文，不以新结果覆盖原始过程。

当前增量 final result: passed

日期：2026-10-19。范围：04的首个纯前端增量，不是16页完整应用交付。

## 结论

- 构建、类型检查：通过。
- 数据/表单单测：13/13通过。
- 独立无登录Chromium浏览器测试：19/19通过；失败轮次和修复记录保留。
- 包装/静态资源测试：4/4通过，未发布或部署。
- 视觉：已有6轮真实捕获和同尺寸原图对比；用户于2026-10-19确认04主图与整体效果，已锁定人工认可的修正版视觉基准。
- final result: passed

原04通过范围仅为已审阅的主图与整体视觉、当时已执行操作测试；不是全套或逐像素原图验收。

原阻塞项已由用户明确确认关闭：用户原话为“确认好了04的主图与整体效果，效果可以”。D-05干净主图仍是生成重建，与原合成图的工人、钢筋、阴影等纹理不同；此差异作为人工认可的素材替换保留，不再要求逐像素复现原照片。原字库未知，沿用当前Noto Sans SC，不宣称原字形完全一致。真正的200%浏览器缩放和真实视频播放尚未验收，不在此次确认范围内。

**基准记录：qa/04/approved-baseline.json引用既有iteration-06截图及SHA，不覆盖原图，不删除差异，也不将用户确认冒充一次新的自动回归测试。后续页面复用此视觉方向，仍需逐页截图与操作验收。**

## 原始目标与实际捕获

- 原图：reference-images/04-linked-workbench.png，1513×1040，SHA256 `26098014f082510395e27890f70959573ff5cb1757bcf9053069afa5f916c6cf`。
- 当前实现：qa/04/iteration-06/implementation.png，1513×1040，SHA256 `56e17b550753e48e896378a0a41ae7207a0eb5d66f0da67a8da7bb1636eb2fd1`。
- 完整对照：qa/04/iteration-06/comparison/side-by-side.png。
- 50%叠加：同目录overlay-50.png；定位差异：diff.png。
- 局部：focused-topbar.png、focused-canvas.png、focused-scene.png；不是只比较整张缩略图。
- 环境：Chromium151.0.7922.34，Windows10.0.26200，CSS1513×1040，DPR1，100%默认缩放，zh-CN，Asia/Shanghai，浅色，reduced-motion。
- 状态：fixture04独立种子；区域1被选中；A/B展开；抽屉关闭；画布0/0/1；12秒模拟时间；结果证据收起；运行R3、未应用草稿。
- 媒体：同一干净海报1448×1086；元信息如实记录，无真实mp4/FPS；缩略条明确模拟。
- 字体：本地WOFF2，400/500/600/700均检查loaded；环境文件记录全部散列。无外部字体/图片请求。
- 首轮内置浏览器DPR1.25，截图1513×1040但CSS取整至1514，不作为严格验收。用户明确授权后改为独立无登录Chromium，仅访问6174。
- 所有比较均未缩放、裁去问题、重绘或mask。05/06两次原始PNG散列完全相同，固定状态复现稳定。

## 五项必查表面

| 表面 | 对比发现与处理 | 当前状态 |
|---|---|---|
| 字体与排版 | 初始节点字重偏轻、检测节点内容偏右；调整700标题/500行文、左对齐检测内容。统一Noto本地字库；原生成字形仍有差别 | 主层级无明显换行冲突；字形光学差异保留，未声称原字体相同 |
| 间距与布局 | 面板初始高1px、画布与节点上下约3–5px偏移；调整面板间隔、47.86%列宽、节点坐标、分支内行高、流程圈位置 | 9个主要几何锚点全部在原规格±2px内，有独立浏览器断言；曲线细节仍非逐像素原曲线 |
| 色彩与状态 | 固定靛蓝主操作，橙/青区域身份；选中额外图标/描边，深色文字增强对比度；草稿与R版本区分 | D-02/D-06/D-07/D-12明确优化，不掩盖原图差异 |
| 素材与图标 | 缺独立照片/logo，生成干净同构素材；移除烘焙ROI和全部UI，真实Konva层叠加；Phosphor真图标本地打包 | 主图纹理差异为待确认P1；logo/图标轻微轮廓差异为P3。实际1448长边未达建议1600，不做拉伸伪装 |
| 文案与内容 | 精确fixture规则/2分支/AND/R3；修正“非运行界面”为“前端演示·模拟数据·未连接后端”；海报/模拟时间轴与无真实识别边界明确 | D-04/D-10/D-12允许修正；重复海报不冒充视频帧 |

## 发现、修正与复验历史

| 轮次 | 发现 | 实施修正 | 复验 |
|---|---|---|---|
| 01 内置浏览器 | DPR1.25不符；节点/流程圈偏移；连线直角；部分图标和正文密度不符 | 获用户授权后换独立Chromium；保留首轮，不归零冒充成功 | iteration-01完整原始截图/叠加；02开始DPR1 |
| 02 | 面板/节点偏移3–5px，节点内容居中偏右；圆弧风格不符；缺库署名 | 固定面板/节点锚点，检测内容左对齐；改用库支持的圆角依赖边；恢复React Flow署名D-17 | iteration-03及局部图 |
| 03 | A连接端点偏右、B条件间距偏紧；场景工具比原图靠右；画布点阵过淡 | 规范端点位置、条件行高/间距；工具栏280px；字重校准 | iteration-04对比 |
| 04 | 点阵/进度条细节；场景素材仍明显不同；保存边界/存储边界需额外检查 | 本地原生progress显示真实模拟比例；补点阵；修复未保存区域保护、无效旧存储不覆盖；依赖模块拆分懒加载 | iteration-05及浏览器测试 |
| 05 | 新增边界测试发现Esc打开确认框后被原生默认取消；测试匹配“颜色”范围过宽 | Esc阻止默认行为；使用明确控件标签；不放宽断言，不增加任意等待 | 最终19/19；iteration-06重新捕获 |
| 06 | 主要锚点稳定；原图照片/原字库仍不相同 | 不用更新原图或mask消除差异；保留待确认项 | 与05 PNG完全同SHA；未建立normalized |

## 操作测试证据

机器记录qa/04/functional-results.json；HTML报告qa/04/playwright-report/index.html；首次失败截图与trace在functional-attempt-01/03；functional-attempt-02保留当时15/15记录。

19项覆盖：固定视口与本地资产/零页面错误/无外部请求；双向选择；保存不应用/显式R4；未保存表单取消与放弃；保存后应用不读旧草稿；撤销重做；自定义条件名与证据OR；分支范围与连续时间字段；最终AND/OR与受控输出；三视图/模拟时间轴/证据折叠；未保存多边形保护；刷新与fixture隔离；1366×768/1920×1080/760×900控件可达；损坏存储保留；Esc保护；完整导出；9个主要几何锚点±2px。

13项单测覆盖R3不可变副本、无效几何/比例/数量/引用阻断、独立种子、条件稳定ID及颜色/证据/时间/输出受控表单。

检查与捕获记录均未冒充模型准确率、真实视频、完整16页功能或旧项目P01–P13回归。

## 未关闭项与下一步

- [已关闭/素材基准] 2026-10-19用户明确接受04主图重建与整体效果；纹理差异仍保留，不当作抗锯齿误差。
- [P3] 原图字形/图标光学差异、连线曲率细节；遵循统一字体与真实图标库，不手绘假图标替换。
- [未执行] 真正200%浏览器缩放、真实视频和其余15个原图状态的视觉验收。
- 已建立人工批准的基准清单，直接引用审阅过的iteration-06文件；未另造截图，未运行“自己截图自己通过”的新比较。历史轮次中的“待确认”描述为当时真实状态。

下一阶段按03场景 → 05条件 → 06时间 → 07编排组 → 08输出 → 15校验完善编辑链路；保留本轮原图/真实截图/差异与功能记录，继续只做独立纯前端。
