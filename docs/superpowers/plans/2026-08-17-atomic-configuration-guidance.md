# 原子能力配置引导 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 从现有 Effective SkillPackage 推导简洁的原子能力配置卡片，并让方向规则在审核页可读。

**Architecture:** 在 `V2AppController` 增加只读 guidance 推导方法，复用现有 DAG/配置槽读取逻辑；Gradio 创建页增加一个 Markdown 输出，四条加载链统一刷新；方向事件控制模型增加描述字段，保留现有编辑器和运行时。

**Tech Stack:** Python, Pydantic SkillPackage, Gradio, pytest。

## Global Constraints

- 不新增专用拥堵或逆行算子。
- 不引入新的复杂配置页面、跳转逻辑或运行时架构。
- 生产代码必须先有会失败的回归测试。

### Task 1: 控制器 guidance 与方向规则模型

**Files:** `app_v2.py`; `tests/test_v2_ui.py`

- [ ] 写 P04/P05 guidance 和方向 controls 失败测试。
- [ ] 在 `read_event_rule_controls` 增加 `condition_kind`、`condition_summary`、`atom_summary` 等只读字段，并从事件条件链反推类别。
- [ ] 增加 `configuration_guidance_markdown`，只读取 DAG 和 configuration slots，输出原子摘要、配置状态和下一步。
- [ ] 运行新增测试并重构重复文本格式化。

### Task 2: 创建页卡片与加载链

**Files:** `app_v2.py`; `tests/test_v2_ui.py`

- [ ] 写 UI contract 失败测试，要求出现“识别出的原子能力/下一步配置”等文案且四条加载链输出 guidance 组件。
- [ ] 在创建页 source status 后添加 Markdown 卡片。
- [ ] 在 compile、preset、saved、asset load 和 variant refresh 链刷新卡片。
- [ ] 运行 UI contract 测试。

### Task 3: 全量验证与项目状态

**Files:** `project_state.json`; `tests/preset_test_results.json`; `graphify-out/`

- [ ] 运行新增测试和全量 pytest。
- [ ] 检查服务日志无新请求异常。
- [ ] 更新项目状态和 graphify。
