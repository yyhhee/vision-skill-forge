# ADR 0003: 可执行时序语义

- 状态：Accepted
- 日期：2026-08-21

## 决策

视频时序统一使用媒体时间戳。持续区间采用半开区间 [start_at, end_at)，图片只有 t=0 瞬时点，不能配置持续、顺序、延迟、缺失窗口或重复。

每个阶段记录 first_seen_at、qualified_at、last_seen_at、ended_at，并投影为 satisfied、not_satisfied、pending、not_evaluable 或 error。组合模式必须同时提供状态机、时间锚点、关联键、消费、超时、重置和边界测试。

## 验收

- 阈值相等、抽帧容差、媒体提前结束、短暂中断、多身份并行和保存重放结果确定。
- 尚可能完成才是 pending；媒体结束后转为 not_satisfied。
- 无完整结束边界时记录 open_interval，不伪造结束时间。
