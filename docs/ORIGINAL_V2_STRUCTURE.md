# 原版 V2 结构整理

2026-10-16，以提交 `bf71b22` 为功能基线，在原版 `vision_skill` 目录实施。

## 入口与职责

启动方式和端口环境变量保持原样：

```powershell
$env:VISION_SKILL_PORT = '6131'
python app_v2.py
```

`app_v2.py` 保留 `V2AppController`、`build_v2_app`、`default_v2_controller` 和既有公开展示辅助函数。测试、启动脚本和调用方可以继续使用原导入路径。它只承担默认依赖装配、兼容导出和启动，不再定义整套页面及业务控制器。

```text
app_v2.py
  ├─ application/v2/              技能用例与共享基础设施
  │    ├─ base.py                 Registry、存储、客户端、序列化和既有上下文
  │    ├─ skills.py               生成、预置/保存版本加载、保存、删除、校验
  │    ├─ execution.py            运行前准备、执行及运行产物汇总
  │    └─ support.py              项目根路径、媒体选项、值转换和应用异常
  └─ ui/v2/
       ├─ app.py                  五个页面的组装顺序和事件注册
       ├─ controller.py           保持旧 API 的控制器门面，转换应用异常
       ├─ controllers/            业务编辑、专业编辑、事件、执行配置、标注、结果、资产
       ├─ pages/                  创建、标注、审核、运行、资产的组件构建
       ├─ bindings/               对应事件回调及跨页面同步
       ├─ workspace.py            显式、有类型的跨页面组件引用
       ├─ presentation.py         展示常量与只读配置投影
       └─ theme.py                原有 CSS 与标注 JavaScript
```

## 依赖与状态约束

- 页面构建器只创建组件并返回明确的页面句柄；页面之间通过 `Workspace` 访问组件，不使用 `locals()`、动态执行或全局组件字典。
- `bindings` 保留既有回调的输入、输出、执行顺序、成功后续步骤和队列设置。跨页面共用的回调通过明确的句柄传递，仍由原组件承载技能和历史状态。
- `V2AppController` 通过按职责拆分的类共享一份上下文。各类不单独初始化存储或生成第二份技能状态，也没有覆盖顺序决定业务规则的重复方法。这是保留原控制器 API 的迁移边界。
- 应用服务不导入 Gradio 或 UI 模块。服务通过 `ApplicationError` 表达原有用户错误，门面统一转换为既有 `gr.Error`；已有表单更新留在 UI 控制器。
- `core/`、`clients/`、`operators/` 以及预置技能文件保持原样，不引入第二套编译器、执行器、插件系统或模型规则。
- 本轮保留已有的广义异常处理、校验异常类型等行为；对应 Ruff 标注只解释代码迁移，后续修改这些策略应另行评审和测试。

## 修改时如何定位

| 要修改的内容 | 位置 |
|---|---|
| 某页面的控件、布局和默认展示 | `ui/v2/pages/<页面>.py` |
| 控件点击、输入同步、多个页面联动 | `ui/v2/bindings/<职责>.py` |
| 条件/分支编辑与展示适配 | `ui/v2/controllers/business.py`、`editor.py` |
| 事件卡、时间与关联参数适配 | `ui/v2/controllers/events.py` |
| ROI、方向和标注操作 | `ui/v2/controllers/annotation.py` |
| 技能生成、加载、保存流程 | `application/v2/skills.py` |
| 执行和运行产物汇总 | `application/v2/execution.py` |
| 编译语义、算子算法或模型请求 | 原有 `core/`、`operators/`、`clients/` |

## 验证

- 原版基线：597 项现有测试通过，记录 `data/validation/original-refactor-baseline.xml`。
- 新增组件/事件图特征回归：650 个组件、239 条事件绑定、组件属性、布局、回调名称、输入输出、后续触发关系、CSS 和标注 JavaScript 与 `bf71b22` 对比；同时实际调用六个删除按钮回调，验证其各自保留对应条件卡索引。
- 迁移审查核对全部 138 个控制器方法的 AST，在仅统一应用异常名称后，没有发现方法逻辑差异。各回调注册分段保留原顺序。
- 完整回归：598 passed，324 条既有 Gradio 弃用警告；产物 `data/validation/original-refactor-final.xml`。现有测试包含受控模型、编辑、持久化、预置结构与运行回归；结构整理不产生新的真实模型准确率验收记录。
- 改动文件 Ruff 检查与格式检查通过。原版 6131 已重新启动，HTTP 200，在线配置仍为 650 个组件和 239 条事件绑定。

以后有意调整页面布局或绑定关系时，先确认行为变更，再更新组件图特征；不要只为消除失败覆盖基线。
