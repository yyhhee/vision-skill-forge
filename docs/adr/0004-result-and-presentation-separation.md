# ADR 0004: 结果语义与展示规格分离

- 状态：Accepted
- 日期：2026-08-21

## 决策

ResultSpec 定义结果是什么、从哪里来、如何投影、单位、分组、保存、空值和证据策略，参与 semantic_hash。PresentationSpec 定义渲染器、排序、布局、精度和交互方式，只参与 presentation_hash。

渲染器不得根据预置 ID、技能名称或中文事件名推断业务含义。未知组合必须降级到 generic.summary，同时保留状态、值和证据入口。

## 验收

- 只修改 PresentationSpec 不重新编译或运行视觉模型。
- 修改 ResultSpec 来源或投影会使语义/编译结果失效。
- 每个 ResultSpec 有兼容渲染器和可访问文本。
