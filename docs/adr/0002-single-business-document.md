# ADR 0002: 唯一业务规则文档

- 状态：Accepted
- 日期：2026-08-21

## 决策

产品所称 BusinessRuleDocument 直接由现有 SkillEditorDocument@3.x 演进，不新增第二个可编辑根模型。

- SkillEditorDocument@3.x：唯一可编辑真相源。
- RuleGraph 与 Effective SkillPackage：确定性只读编译产物。
- RunResult、RuntimeValueEnvelope 与 EvidenceIndex：单次运行事实。
- RunResultViewModel：可从运行事实和展示规格重建的投影。
- 旧格式：只允许单向迁移，不双写、不反向同步。

## 验收

- 3.0 文档可通过显式 3.0→3.1→3.2 链幂等迁移。
- 自然语言、预置和历史导入最终写同一文档类型。
- 03 不直接修改 RuleGraph、端口或 Effective JSON。
