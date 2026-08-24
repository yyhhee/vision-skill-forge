# ADR 0005: 运行值信封与证据索引

- 状态：Accepted
- 日期：2026-08-21

## 决策

V3 的每个公开运行值使用 RuntimeValueEnvelope，记录运行、节点、稳定业务来源、语义类型、形状、状态、身份、时间和证据引用。媒体证据统一保存为 EvidenceRecord，并由 EvidenceIndex 查询。

旧 EventSet、ObjectSet、TrackSet 和 ScalarSet 分类文件继续作为兼容诊断产物，但不再是 04 业务结果真相源。LegacyOutputEnvelopeAdapter 只按编译绑定和节点 ID 包装旧值，禁止按显示名称猜语义。

## 验收

- 最终结果可稳定追踪至 ResultSpec、分支/条件、节点和证据。
- 局部证据失败不抹掉业务值，信封记录缺失诊断。
- 保存重载后引用和查询结果不变。
