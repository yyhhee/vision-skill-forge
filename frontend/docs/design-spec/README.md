# Vision Skill Forge 前端还原规格包

日期：2026-10-19。基准：2026-10-17 统一浅色效果图，16 张原图。
状态：**规格 v1 已锁定；独立素材尚待补齐；前端实现尚未开始；视觉与功能验收均未执行。**

## 本轮交付

| 文件 | 用途 |
|---|---|
| RESTORATION_SPEC.md | 视觉、组件、路由、交互和纯前端实现边界 |
| SCREEN_CONTRACTS.md | 16 张图的逐页固定状态、动作与期望结果 |
| ASSET_INVENTORY.md / assets.json | 素材来源、尺寸、缺口、获取方式与验收门槛 |
| DECISIONS.md | 允许优化的逐项修正账本；不得以优化名义随意改图 |
| ACCEPTANCE.md | 相同视口／数据／展开状态下的对比及独立功能验收 |
| baseline.lock.json | 原图尺寸、SHA-256 和基准环境约束 |
| design.tokens.json | 以 04 为主的统一视觉变量 |
| screen-states.json | 16 个可复现截图用例，不是 16 套独立业务状态 |
| mock-fixtures.json | 演示文档、版本、素材元信息、结果与时间种子 |
| QA_REPORT_TEMPLATE.md | 后续每页验收必须填写的证据模板 |
| validate_spec.py | 规格关联、原图完整性和固定数据自检；不是 UI 测试 |
| SPEC_CHECK_REPORT.json | 本轮实际自检记录；不含浏览器验收结论 |
| IMPLEMENTATION_HANDOFF.md | 后续实施顺序、阶段门槛与禁止事项 |
| references/ | 原图副本，禁止覆盖、拉伸或以截图代替软件界面 |

## 阅读顺序

先读 RESTORATION_SPEC → DECISIONS → SCREEN_CONTRACTS → ASSET_INVENTORY → ACCEPTANCE。
机器可读文件以相同 ID 互相引用，后续实现不得各页写一份不关联的演示规则。

## 已锁定与未锁定

- 已锁定：设计方向、04 公共样式基准、逐页原图、固定截图状态、交互行为、允许修正项与验收门槛。
- 未完成：独立照片／证据／真实视频素材、字体和图标二进制归档、修正区域的可视化目标、浏览器渲染结果。
- 可开始的下一阶段：独立前端工程的壳层与通用组件；素材缺口在对应页面验收前必须关闭。
- 不可声称：16 页已经实现、所有素材已经就绪、1:1 已通过、旧项目检测效果已经重新验收。

## 工作边界

本目录是规格与参考包，不是前端软件。没有改动原 vision_skill、Vision Skill Forge 成品目录、6131 服务、原图册或其图片。
不接 LLM、视觉模型、Python 服务、远程模型地址或生产数据库；不部署公网；不引入自动模型路由。
不得把任意自然语言的固定演示结果冒充真实编排，不得把重复静态帧冒充真实视频时序识别。

## 自检

在本目录运行：`python validate_spec.py --self-test`。Python 3.10+，仅使用标准库，无网络请求、不写文件。
结果报告为规格包自检，不能代替 ACCEPTANCE.md 的浏览器截图、叠加对比、操作与控制台检查。

