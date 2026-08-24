# Vision Skill Builder：通用事件规则编辑 V3 详细实施方案

> 文档状态：实施基线  
> 目标界面：`http://127.0.0.1:6131/` 当前五步式前端  
> 适用范围：自然语言生成、P01–P13 预置、历史技能迁移、图片/视频运行、复杂事件编排与统一结果展示  
> 核心决策：删除用户侧“高级原子编排”；以业务规则文档作为唯一编辑源，内部 RuleGraph 仅作为编译产物。

## 1. 目标与结论

当前页面外壳继续保留：

```text
01 创建 → 02 标注 → 03 审核 → 04 运行 → 05 资产
```

重点重做 `03 审核` 中的事件规则编辑，并同步重做 `04 运行` 的结果层级。新方案必须做到：

1. 简单检测、属性识别、计数、空间关系、运动、状态、持续、顺序、多分支复杂事件均使用同一套编辑模型。
2. 自然语言、预置演示和历史技能进入同一份 `SkillEditorDocument`（产品界面称“业务规则文档”），不再维护三套编辑逻辑。
3. 用户编辑业务条件、分支、时间关系、触发和输出，不接触原子节点、端口和连线。
4. 所有业务语义原子均可通过 Schema 驱动的卡片配置；技术执行原子由编译器自动插入。
5. 每个分支保存状态、业务值和证据；每次运行始终产生用户可读的最终结果。
6. 图片、视频或两者都支持，由“LLM语义建议 + 后端确定性能力校验”共同决定。
7. `XX/XXX`、区域数量、时间含义等不确定项进入待确认列表，不报 JSON 错误，不擅自补值。
8. P01–P13 和现有历史案例必须通过新模型重新编译并回归，旧前端编辑器不再作为兼容目标。

## 2. 非目标与边界

本阶段不做：

- 用户侧高级原子节点编辑器。
- 用户手工填写节点 ID、端口或连接。
- 两套配置之间双向同步。
- 让 LLM 直接输出可执行 RuleGraph。
- 因为旧页面存在某张固定卡片，就继续保留旧数据结构。
- 为某个案例新增“多区域事故逆行烟火告警”专用算子。
- 多摄像头、多视频流之间的时间同步、跨镜身份关联和联合事件编排。
- 在一次运行中同时消费多个独立媒体文件。

V3 首期运行边界固定为：

```text
一次运行 = 一个图片或一个视频媒体源
一个媒体源内 = 允许任意动态数量的区域、方向和业务分支
一个技能 = 可以同时声明 image/video variant，但每次只选择一个 variant 运行
```

同一媒体内的多区域、多车道、多目标、多阶段和复杂事件全部属于本期通用能力。`camera/scene/field` 等关联范围暂时只作为 Schema 保留值和未来兼容位，不在普通用户界面开放；本期统一绑定到当前运行媒体。后续多摄像头能力必须新增独立的 `MultiStreamRun`、时钟同步、跨镜身份和资源模型，不得复用本期单媒体语义假装支持。

内部仍然保留现有注册原子、`RuleGraph`、类型校验、执行算子和 Trace。它们作为编译器与开发诊断能力存在，不是业务配置入口。

### 2.1 开发前必须闭合的六道门槛

以下内容不是后期优化项，而是 V3 其它页面和案例实施的前置条件。任一门槛未闭合时，不得用新增固定卡片或案例分支绕过。

1. **唯一事实源**：可编辑业务语义只保存在 `SkillEditorDocument`。03 所有操作只修改该文档；`RuleGraph`、`AtomicPlan` 和 `Effective SkillPackage` 均为带哈希的确定性编译产物。禁止 03 同时改业务树和 Effective JSON，禁止静默双写。
2. **业务类型与确定性编译**：业务条件必须声明输入/输出语义类型；来源选择、AND/OR/NOT/N-of-M、分支和最终判定在保存前做类型校验。LLM 只生成业务草稿，不能生成可执行节点；执行图由版本化 Recipe 编译，并能从节点反查业务来源。
3. **时间语义与身份隔离**：持续、累计、窗口占比、同时有效、全部完成、顺序、未发生和重复发生必须有统一状态机语义；每个分支独立配置时间，按 global/object/track/pair/region 关联，禁止跨目标拼接。窗口未关闭、媒体提前结束和证据中断均有确定状态。
4. **运行事实与证据链**：运行时公开值统一使用 `RuntimeValueEnvelope`，通过稳定 `business_source_ref`、节点、身份和时间范围写入 `EvidenceIndex`。分支结果与最终结果必须保存；04 只能消费类型化 `RunResult`，不得从显示名称、数组位置或旧平铺 JSON 猜语义。
5. **ResultSpec 语义先于渲染器**：先实现并校验 `semantic_type + value_shape + source_ref + projection + unit + grouping + save/evidence/empty policy`，再由独立 `PresentationSpec` 和渲染器注册表决定卡片、表格、时间线或媒体层。没有语义类型的结果禁止进入专用渲染器；未知展示组合统一降级为 `generic.summary`，但不得丢失事实和证据入口。
6. **V3 首期边界**：一次运行只消费一个图片或一个视频媒体源；允许该媒体内部任意数量区域、方向、目标、分支和阶段。技能可以声明 image/video 两个 variant，但每次只运行其中一个。多摄像头、多文件同步、跨镜身份和跨流事件不属于 V3 首期，Schema 中的未来枚举值不得在普通界面伪装为已支持。

六道门槛的代码验收分别对应：文档迁移/哈希测试、业务编译器类型测试、时序状态机测试、运行信封与证据追踪测试、ResultSpec/PresentationSpec 分层测试、媒体边界冲突测试。只有这些测试先通过，才进入自然语言、预置和历史案例批量迁移。

### 2.2 六个前置问题的可执行解决方案

| 前置问题 | 设计决策 | 后端落点 | 验收门禁 |
|---|---|---|---|
| 1. 多份配置可能互相覆盖 | `SkillEditorDocument@3.2` 是唯一可编辑事实源；Effective Package 只读且可重建 | 所有 03 服务只返回新文档；编译产物使用四类哈希；旧格式只允许单向迁移 | 同一修改保存、重载、再次编译结果一致；禁止直接回写 Effective JSON |
| 2. “通用组合”缺少确定类型 | 每个业务能力声明输入、输出、媒体要求、参数 Schema 和版本化 Recipe | `BusinessCapabilityRegistry → BusinessRuleCompiler → RuleGraphCompiler`；LLM 只输出严格业务草稿 | 非法来源、跨媒体引用、数值未比较即参与逻辑等在编译前被业务化错误阻止 |
| 3. 时间和目标可能被错误拼接 | 时间约束属于具体分支；状态按 `global/object/track/pair/region` 隔离；复杂事件使用明确窗口和状态机 | `TemporalQualifierSpec`、`EventPattern`、`temporal.qualify/join/sequence/absence/repeat` | 连续/累计/占比、短暂中断、不同目标、窗口未关闭、媒体提前结束均有受控事件流测试 |
| 4. 结果与框证据来源不稳定 | 每个公开运行值使用稳定业务引用和 `RuntimeValueEnvelope`；证据独立写入 `EvidenceIndex` | 编译节点发布 `condition:/branch:`；复杂事件发布 `event:`；最终判定发布 `final:`；精确投影发布 `result:` | 最终结果可沿 `ResultSpec → RuntimeValueEnvelope → node → EvidenceRecord` 反查，不按中文名或数组位置猜测 |
| 5. ResultSpec 语义被渲染器倒推 | 先校验结果是什么，再选择怎么显示；业务语义和展示配置分别持久化、分别哈希 | `ResultSpec` 校验 `semantic_type/value_shape/projection`；运行时再次校验实际来源类型；`PresentationSpec` 只做展示 | 类型或投影不兼容时结果为可解释的 `not_evaluable`；未知渲染器只降级展示，不改变事实 |
| 6. “通用”被误解成跨媒体联合运行 | V3 通用范围是单次运行、单媒体源、媒体内动态多区域；双 variant 是两个可独立执行的方案，不是一次联合执行 | 运行入口只接受单个 `str/Path`；根据文件类型只选择一个 variant；列表、多文件和跨流请求在执行前拒绝 | 单图、单视频均可运行；一个技能可保存 image/video variant；任何一次运行只生成一个 `media_asset_id` 和一条媒体时间轴 |

稳定引用必须保持以下职责，不能为了方便投影而复用成另一种含义：

```text
condition:<id>  条件自身的真假/状态
branch:<id>     分支经过独立时间约束与有效期后的状态
event:<id>      复杂事件实例或时间线
final:<id>      最终判定编译值
result:<id>     ResultSpec 根据 projection 选定的精确来源节点
output:<name>   Effective Package 的兼容输出别名
node:<id>       开发诊断用确定节点引用
```

例如“区域2人数 > 2”中，`condition:people_count` 必须仍指向比较后的布尔条件，而 `result:actual_people_count` 指向比较前的数量测量。这样 04 既能显示“条件是否成立”，也能显示“实际人数是多少”，不会把布尔值错误渲染为数量。

`ResultSpec` 的固定执行顺序为：

```text
校验 semantic_type/value_shape/projection
→ 解析稳定 source_ref
→ 校验运行时来源 ValueType
→ 执行 projection、单位和分组语义
→ 应用 empty/evidence/save policy
→ 形成 BusinessOutputValue
→ 最终判定组合 AND/OR/N-of-M
→ PresentationSpec 选择兼容渲染器
```

渲染器不得参与来源选择、真假判断、数量计算或证据绑定。展示配置错误时只能回退 `generic.summary`；来源缺失、类型不兼容、仍在等待和明确未满足必须分别保留为 `not_evaluable/pending/not_satisfied`，不能统一写成“不适用”。

单媒体边界的产品和接口语义统一为：

```text
技能能力：image、video 或 image+video 两个独立 variant
运行请求：恰好一个 media 文件
运行选择：按该文件实际类型选择恰好一个 variant
运行上下文：一个 media_asset_id、一条图片瞬时时间点或视频时间轴
媒体内资源：区域、方向、目标、分支、阶段数量均动态，不设固定上限
明确拒绝：媒体数组、多文件批次作为一次事件、跨摄像头 join、跨媒体 source_ref
```

批量处理多个文件可以由上层逐个创建多次独立运行，再做运行级汇总；不得把批处理包装成一个 V3 业务事件实例。未来跨摄像头能力必须引入新的运行模型和同步语义。

## 3. 现有项目可复用基础

当前项目已经具备以下可复用资产：

- `core/registry.py`：完整的原子注册表和参数定义。
- `core/editor_schema.py`：已有 `ResolvableValue`、`EventPattern`、资源需求、结果规格等 V3 雏形。
- `core/recipes.py`：同主体属性、装备缺失、状态转变、逆行、多分支汇合、有时限顺序、缺失/重复等组合 Recipe。
- `temporal.join@1.0`：支持同时有效、窗口内完成、任意/N选M汇合。
- `temporal.sequence@2.0`：支持多阶段和每段独立时间窗。
- `temporal.absence@1.0`、`temporal.repeat@1.0`：支持未发生和重复事件。
- `state.detect@1.0`、`state.transition@1.0`：支持状态和状态转变分离。
- `evidence.collect@1.0`、`event.attach_evidence@1.0`、`result.project@1.0`：支持统一证据和结果投影。
- `core/preset_definitions.py`：P01–P13 预置定义。
- `data/preset_media_defaults.json`：预置默认媒体。
- `tests/historical_*.json`、`data/historical_runs_v2`：历史回归资产。

实施方向不是推翻现有算子执行引擎，但必须升级运行时输出协议：为每个结果保留业务来源、类型、身份、时间范围和证据引用，并更新运行持久化。现有算子和执行调度尽量复用，当前按类型平铺汇总的结果写法仅作为兼容输出，不能继续承担 V3 业务结果真相源。

## 4. 五步页面最终结构

### 4.1 01 创建

```text
01 创建
├─ 开始方式
│  ├─ 自然语言生成
│  ├─ 预置演示技能
│  └─ 历史技能
├─ 技能标识与显示名称
├─ 自然语言描述
│  ├─ 直接描述任务
│  ├─ 插入业务配置描述模板
│  └─ 写法示例与待确认提示
├─ 预置/历史说明
├─ 媒体能力结论
├─ 待确认项摘要
└─ 当前任务媒体
```

三种开始方式最终都生成同一个 `SkillEditorDocument`（产品界面称“业务规则文档”）。

### 4.2 02 标注

```text
02 标注
├─ 当前规则需要的场景资源
├─ 区域绘制
├─ 方向箭头绘制
├─ 动态增加区域/方向
├─ 显示名称
├─ 资源与规则关联
└─ 完成状态
```

自然语言阶段只生成逻辑资源要求，例如“区域1”“拥堵统计区”“参考方向”，不要求提前知道实际区域数量和内部 ID。02 根据真实媒体创建稳定 `resource_id`。

### 4.3 03 审核

```text
03 审核
├─ 系统理解摘要
├─ 待配置问题
├─ 执行参数
├─ 事件规则编辑（唯一业务配置入口）
│  ├─ 业务事件（按需）
│  ├─ 条件分支（至少一个）
│  ├─ 复杂事件编排（按需）
│  ├─ 最终判定（系统生成，可调整）
│  ├─ 业务输出（至少一个，系统生成）
│  └─ 触发策略（事件/告警任务按需）
├─ 切片增强与去重
├─ 候选框二次确认
├─ 结果媒体
└─ 校验与编译状态
```

删除“高级原子编排”入口。开发诊断仅保留为后端日志或开发模式只读数据。

#### 4.3.1 六个区域的显示规则

| 区域 | 是否必需 | 何时显示 | 省略时行为 |
|---|---|---|---|
| 业务事件 | 可选 | 规则需要把检测、状态、阈值或分支结果命名为可复用事件时 | 条件直接参与分支，不额外生成事件定义 |
| 条件分支 | 必需 | 所有技能 | 系统至少生成一个默认分支，不能全部删除 |
| 复杂事件编排 | 可选 | 分支不少于两个，或出现同时、先后、窗口、期间、未发生、重复等语义 | 单分支结果直接进入最终判定 |
| 最终判定 | 必需但默认折叠 | 所有技能 | 系统按任务意图生成唯一主判定 |
| 业务输出 | 必需但默认给出 | 所有技能 | 至少保存主判定；检测/测量任务自动增加目标或数值输出 |
| 触发策略 | 可选 | 需要产生事件、告警、通知或事件片段时 | 只返回检测/测量/状态结果，不发送告警 |

简单任务默认只展开“条件分支”和“业务输出”；复杂任务才逐步展开其他区域。LLM 没有提到的可选区域不应凭空生成配置。

### 4.4 04 运行

```text
04 运行
├─ 运行操作区
│  ├─ 检查媒体与调用估算
│  └─ 运行/重新运行
├─ 第一层：最终结果
├─ 第二层：业务输出
└─ 第三层：分支与证据
   ├─ 分支过程与复杂事件时间线
   ├─ 标注媒体与证据联动
   └─ 运行详情/开发诊断（默认折叠）
```

### 4.5 05 资产

```text
05 资产
├─ 当前加载版本
│  ├─ 业务摘要与来源
│  ├─ 编译/运行状态
│  ├─ Effective SkillPackage 摘要
│  └─ Effective SkillPackage JSON（只读）
├─ 保存新版本
├─ 已保存版本
│  ├─ 加载、删除、重命名
│  ├─ 版本差异
│  └─ 回归验证状态
├─ 能力资产库
│  ├─ 业务能力与 Recipe
│  └─ 全部执行原子（按类别）
├─ 场景资源与模型依赖
└─ 导入/导出
```

删除当前单一的 `Operator Registry（高级参考）` 折叠块。它既难读，也不能回答“当前技能用了什么”。用结构化的“能力资产库”和“当前加载版本”替代；普通用户看到业务名称，开发定位时仍能看到原子 ID、版本、输入输出和完整参数。

#### 4.5.1 当前加载版本

页面顶部始终展示当前实际运行对象，而不是只在 03 的高级区放一段 JSON：

```text
当前加载：多区域人员告警 / v3
来源：自然语言生成
状态：已审核 · 编译通过 · 可运行 · 有未保存修改
媒体：图片 + 视频
语义哈希：a81f…
原子：18 个   连接：21 条   分支：2 个   输出：4 个

[查看业务摘要] [查看结构拓扑] [查看 Effective JSON] [下载 JSON]
```

`Effective SkillPackage` 可以展示，但默认只读。修改必须回到 03 的业务条件和参数，然后重新编译生成 Effective 包，避免“业务文档”和“手改 JSON”成为两个真相源。开发排障需要手工导入 JSON 时，放在独立的“导入 SkillPackage”动作中，导入后必须严格校验并反向投影为可审核文档，不能在文本框中直接改完即运行。

当前版本视图至少包含：

- `skill_id`、显示名称、版本、来源、创建/更新时间、语义哈希。
- 当前媒体策略、模型来源、场景资源需求和未解决项。
- 分支、最终判定、业务输出的摘要。
- 实际 variant、原子数量、连接数量、入口和输出节点。
- `review_complete`、`compile_valid`、`runtime_ready`、`publish_ready`。
- 与上次保存版本的业务参数差异和编译拓扑差异。
- 完整 Effective JSON、复制和下载；默认折叠，不可直接编辑。

#### 4.5.2 能力资产库

能力资产库不是“高级参考”，而是可检索、可说明、可追踪的正式资产。顶部提供：

```text
[搜索名称或 ID] [业务能力/执行原子] [类别] [图片/视频] [当前技能已使用]
```

每张业务能力卡显示：名称、用途、适用媒体、所需输入/场景资源、可编辑参数、输出类型、使用的 Recipe、被哪些预置/技能使用，以及“在 03 新增到分支”“定位当前使用处”。点击新增只负责跳转到 03 并打开对应条件卡，不在 05 形成第二套编辑器。

每张执行原子卡显示：原子 ID 和版本、显示名称、类别、输入端口、可选端口、输出类型、默认值、参数 Schema、执行范围、固定语义说明、实现状态、测试状态、当前版本是否使用、被哪些 Recipe 引用。相同原子的不同版本全部展示，并标记“当前推荐”或“兼容旧版本”。

每张卡必须可以点击“查看详情”，不能只显示原子名称和 JSON。折叠态保持简洁：

```text
IoU 跟踪                         [视频] [当前推荐] [当前技能已使用]
把不同时间出现的同一目标连接成连续轨迹。
可配置 3 项 · 被 6 个 Recipe 使用
[查看详情] [定位当前使用处]
```

详情使用侧边抽屉或弹窗，分为五个用户可选择的页签：

| 页签 | 展示内容 |
|---|---|
| 能力说明 | 解决什么问题、何时使用、不适合什么情况、图片/视频要求、是否需要区域或方向 |
| 配置参数 | 每个参数的用户名称、当前值、默认/推荐值、单位、范围、用途、调大/调小影响和示例 |
| 组合关系 | 输入业务对象、输出结果、所属 Recipe、前后依赖、可组合能力 |
| 当前使用 | 当前技能哪些分支/条件使用、实际参数、参数来源、是否共享；可跳转 03 |
| 开发信息 | 原子 ID/版本、技术字段、端口类型、默认 JSON、实现与测试状态；默认折叠 |

“配置参数”页即使当前技能没有使用该原子，也必须展示完整配置说明；使用中则额外并排展示“当前值”和“系统推荐值”。无参数原子明确显示“该能力没有需要用户配置的参数”，不能显示空白。

能力详情中的说明来源于注册 Schema，不允许在 Gradio 页面手写另一份文案。业务能力、Recipe 和执行原子使用同一个说明服务，保证 03 帮助和 05 资产解释一致。

#### 4.5.3 当前注册的全部执行原子分类

05 必须由 `OperatorRegistry` 动态读取，不能在前端硬编码。当前基线共 77 个注册项，分类如下；后续新增原子注册后自动出现：

| 类别 | 当前执行原子 |
|---|---|
| 媒体输入与采样 | `media.image@1.0`、`media.video@1.0`、`video.sample@1.0`、`video.sample@1.1` |
| 图像预处理 | `image.resize@1.0`、`image.resize@1.1`、`image.tile@1.0`、`image.tile@1.1`、`object.crop@1.0` |
| 感知与目标集合 | `rex.ground@1.0`、`rex.ground@1.1`、`objects.deduplicate@1.0`、`objects.filter_by_label@1.0`、`objects.filter_by_phrase@1.0`、`objects.merge@1.0`、`objects.relabel@1.0`、`objects.from_tracks@1.0`、`filter.apply@1.0` |
| 外观与状态 | `visual.color_fraction@1.0`、`visual.geometry@1.0`、`state.detect@1.0`、`state.transition@1.0` |
| 区域与参考方向 | `region.full_frame@1.0`、`region.manual@1.0`、`region.manual_set@1.0`、`region.from_objects@1.0`、`regions.merge@1.0`、`direction.manual@1.0`、`direction.manual_set@1.0`、`direction.image_axis@1.0` |
| 跟踪与运动测量 | `track.iou@1.0`、`track.confirm@1.0`、`tracks.filter@1.0`、`tracks.filter_by_events@1.0`、`measure.heading@1.0`、`measure.majority_heading@1.0`、`measure.lane_majority_heading@1.0`、`measure.speed@1.0`、`measure.region_speed@1.0`、`logic.heading_by_lane@1.0` |
| 空间、目标对与集合关系 | `spatial.inside@1.0`、`spatial.associate@1.0`、`pairs.build@1.0`、`pairs.measure@1.0`、`pairs.filter@1.0`、`set.partition@1.0`、`set.difference@1.0`、`set.semi_join@1.0`、`set.anti_join@1.0` |
| 数量、统计与逻辑 | `measure.count@1.0`、`measure.region_count@1.0`、`reduce.count@1.0`、`reduce.exists@1.0`、`reduce.all@1.0`、`reduce.statistic@1.0`、`reduce.quantify@1.0`、`logic.compare@1.0`、`logic.all@1.0`、`logic.any@1.0`、`logic.not@1.0` |
| 时间与事件编排 | `temporal.hold@1.0`、`temporal.persist@1.0`、`temporal.qualify@1.0`、`temporal.event_duration@1.0`、`temporal.join@1.0`、`temporal.sequence@1.0`、`temporal.sequence@2.0`、`temporal.absence@1.0`、`temporal.repeat@1.0` |
| 事件、证据与结果 | `event.from_condition@1.0`、`event.relabel@1.0`、`event.trigger@2.0`、`evidence.collect@1.0`、`event.attach_evidence@1.0`、`result.project@1.0`、`output.draw@1.0`、`output.alert@1.0` |

#### 4.5.4 参数可见性与资产追踪

每个原子参数在注册表中增加 `ui_policy`：

```text
business_editable  业务含义参数，在03条件卡直接编辑
tuning_editable    效果调优参数，在03“更多设置”编辑
resource_bound     来自02标注或模型/媒体选择，只能选择引用
derived_readonly   编译器根据上下文生成，03只读说明
internal_hidden    端口、临时ID、类型转换等内部实现参数
```

05 展示全部参数及其策略；03 只编辑前两类并选择第三类。当前技能使用某原子时，资产卡显示对应分支、条件、实际参数值和参数来源，但修改动作仍跳转 03。

每个可展示参数必须同时注册 `ParameterPresentation`，不能只注册技术类型和取值范围：

```text
parameter_key             内部稳定字段名
display_name              用户看到的名称
short_help                字段下方的一句话说明
long_help                 点击“?”后的完整说明
business_effect           该参数会改变哪个业务结果
unit                      秒、个、%、度、像素或无单位
ui_control                数字框、滑块、选择器、开关、时间/比例控件
display_format            百分比、小数位和单位格式
value_transform           技术值与用户值双向转换
default_value
recommended_value/range
valid_range
increase_effect           调大后的影响
decrease_effect           调小后的影响
examples
warnings
visible_when
ui_policy
```

同一个技术字段在不同业务上下文含义不同时，使用 `presentation_overrides` 覆盖。例如跟踪中的 IoU 表示“是否是同一目标”，区域判断中的 overlap 表示“进入区域多少”，去重中的 IoU 表示“是否是重复框”，三者不能共用“重叠阈值”这一条模糊文案。

任何标记为 `business_editable` 或 `tuning_editable` 的参数，如果缺少 `display_name`、`short_help`、`long_help`、单位/格式、有效范围和影响说明，则能力目录校验失败，不允许发布到 03。

#### 4.5.5 05 验收

- 77 个当前注册原子无遗漏，数量与 `OperatorRegistry.definitions()` 一致。
- 原子新增、版本升级、停用后，05 无需改页面代码即可更新。
- 能按类别、媒体、使用状态和关键词筛选。
- 每个业务条件能追踪到 Recipe 和实际原子；每个原子能反查使用它的条件和技能。
- 当前 Effective 包与 04 实际运行包的语义哈希完全一致。
- 03 修改参数并编译后，05 当前版本摘要和 JSON 立即刷新。
- 删除旧“高级参考”后，保存、加载、删除、导入、导出等现有资产功能不缺失。
- 每个能力可点开查看说明；所有可编辑参数均有用途、范围、默认/推荐值、影响方向和示例。
- 详情抽屉支持键盘打开/关闭、焦点返回和移动端查看，帮助信息不只依赖鼠标悬停。

## 5. 唯一业务数据模型

`BusinessRuleDocument` 是产品层名称；实现上不新增第二套平行持久化模型，而是直接演进现有 `core/editor_schema.py::SkillEditorDocument`。本方案后续所称 `BusinessRuleDocument` 均指“承担业务规则文档职责的 `SkillEditorDocument@3.x`”。自然语言生成、用户修改、预置和历史迁移只能读写这一份对象。

明确决策：

```text
唯一可编辑真相源： SkillEditorDocument@3.x（产品名 BusinessRuleDocument）
只读编译产物：     RuleGraph / Effective SkillPackage
单次运行事实：     RunResult + RuntimeValueEnvelope + EvidenceIndex
结果展示投影：     RunResultViewModel（可重建、可缓存，不是事实源）
旧格式：           仅通过单向导入器转换，不与新文档双向同步
```

因此不新增独立 `BusinessRuleDocument` Python 根类，不新增第二份保存文件，也不允许 03 直接编辑 RuleGraph/Effective JSON。现有 `SkillTemplate`、`SceneProfile`、`ResolvableValue`、`ResultSpec` 和 `EventPattern` 在原 Schema 内按兼容迁移扩展。

```text
BusinessRuleDocument
├─ metadata
├─ source
├─ media_policy
├─ model_sources
├─ scene_requirements
├─ scene_profiles
├─ branches
├─ event_patterns
├─ final_decision
├─ result_specs
├─ trigger_policy
├─ pending_decisions
├─ validation_report
└─ compiled_artifact_ref
```

### 5.1 顶层状态

文档必须分别记录：

```text
draft_valid       LLM草稿结构有效
review_complete   必填业务参数已完成
compile_valid     已成功编译内部RuleGraph
runtime_ready     媒体、资源和配置均可执行
publish_ready     可保存为正式技能版本
```

“生成成功”不再等同于“可以运行”。

### 5.2 参数来源与不确定项

沿用并扩展 `ResolvableValue`：

```json
{
  "state": "unresolved",
  "value": null,
  "source": "natural_language",
  "source_span": "持续XX秒",
  "recommended_value": null,
  "alternatives": [],
  "reason": "用户未提供持续时间",
  "required_before": "run"
}
```

状态：

```text
explicit         用户或原文明确给出
defaulted        使用已声明系统默认
inferred         LLM推断，需显示来源
unresolved       待用户确认
runtime_derived  运行时产生
not_applicable   对当前能力不适用
```

前端统一显示参数来源：`原文明确`、`LLM建议`、`系统默认`、`用户修改`、`待填写`、`由02标注提供`。

### 5.3 文档、编译产物和运行结果的所有权

| 对象 | 谁创建 | 是否可编辑 | 何时变化 | 是否参与哈希 |
|---|---|---|---|---|
| `SkillEditorDocument@3.x` | LLM/预置/历史导入，用户在 03 修改 | 是，唯一入口 | 用户修改业务语义时 | `semantic_hash` |
| `RuleGraph` | 确定性编译器 | 否 | 业务语义或执行参数变化后重编译 | `compile_hash` |
| `Effective SkillPackage` | 编译器 + 场景资源绑定器 | 否 | 编译或 02 资源绑定变化后更新 | `package_hash` |
| `RunResult` | 运行时 | 否 | 每次运行产生新实例 | 记录上述三个哈希 |
| `RunResultViewModel` | 结果投影器 | 否，可重新生成 | 展示规格或渲染器版本变化 | `presentation_hash` |

业务规则修改与纯展示修改分开：改变条件、阈值、来源、时序或业务输出语义时更新 `semantic_hash` 并重新编译；只改变卡片布局、颜色、排序或显示精度时只更新 `presentation_hash`，不重新执行视觉模型。

### 5.4 现有 SkillEditorDocument 的兼容演进

实施时先为当前 `SkillEditorDocument@3.0` 增加版本迁移链，而不是原地改变旧 JSON 含义：

```text
3.0 当前结构
→ migrate_3_0_to_3_1：条件树、最终判定、语义 ResultSpec
→ migrate_3_1_to_3_2：运行结果契约、证据和展示规格
```

读取时允许旧版本进入迁移器；保存时统一写当前版本。每次迁移必须幂等、保留未知扩展字段到兼容区并生成迁移报告。无法安全恢复业务语义的旧原子图进入 `read_only_legacy`，不能伪装成可完整编辑文档。

## 6. 通用条件树

每个分支使用递归条件树，不再使用固定数量的条件卡。

```text
ConditionExpression
├─ ConditionLeaf
├─ ConditionGroup(AND/OR)
├─ NotExpression
└─ NOfMExpression
```

示例：

```json
{
  "type": "group",
  "operator": "all",
  "children": [
    {
      "type": "condition",
      "condition_id": "c_region2_count",
      "capability_id": "count.compare",
      "input_ref": "source_vehicle",
      "params": {
        "scope": "resource:region2",
        "operator": ">",
        "value": 2
      }
    }
  ]
}
```

条件树支持：

- 任意增加、删除、复制、重命名、排序。
- AND、OR、NOT、至少满足 N 项。
- 条件组嵌套。
- 引用同分支前序结果。
- 引用其他分支的公开结果。
- 类型安全的输入来源选择。
- 每个叶子条件独立参数、说明和证据要求。

### 6.1 基础逻辑符号

03 条件组直接保留业界通用的 `AND / OR / NOT` 符号，并同时显示中文含义，不改成难以对应规则表达式的自造名称：

| 符号 | 前端显示 | 含义 | 规则 |
|---|---|---|---|
| `AND` | 全部满足（AND） | 子条件全部为真时成立 | 至少两个子条件 |
| `OR` | 任一满足（OR） | 任一子条件为真时成立 | 至少两个子条件 |
| `NOT` | 条件取反（NOT） | 被取反的一个条件不成立时成立 | 只能作用于一个条件或条件组 |

`N-of-M` 作为补充逻辑保留为“至少满足 N 项”，但不替代基础三种逻辑。

交互方式：

```text
条件组关系：[全部满足（AND）▼]
  条件1 ……
  条件2 ……
  子条件组：[任一满足（OR）▼]
    条件3 ……
    NOT 条件4 ……
```

- AND、OR 支持任意嵌套；NOT 可以取反一个叶子或整个条件组。
- 条件树决定计算顺序，不依赖文本表达式的隐式优先级。
- 卡片摘要同时生成可读表达式，例如 `条件1 AND 条件2 AND (条件3 OR NOT 条件4)`。
- 删除条件后若组内不足两个子项，前端提示合并/删除该组，不留下非法空组。
- `NOT 目标存在` 表示当前判断点目标不存在；“事件 A 后 30 秒内未发生 B”必须使用时间窗缺失，不得错误编译成逐帧 NOT。
- LLM 原文中的“并且/同时/且”映射 AND，“或者/任一”映射 OR，“不是/没有/未”结合上下文映射 NOT 或时间窗缺失；最终由确定性语义校验确认。

## 7. 通用业务能力目录

前端不直接平铺所有技术原子，而是把注册原子投影成用户可理解的 `BusinessCapability`。每项能力由后端 Schema 驱动生成编辑器。

### 7.1 目标与属性

- 目标类别、检测短语、模型类别筛选。
- 颜色、尺寸、位置、宽高比。
- 上衣、裤子、安全帽、安全绳等穿戴/装备属性。
- 姿态、目标状态、检测类别状态。
- 同一目标多属性绑定。
- 正向属性、属性缺失、类别排除。

主要复用：`rex.ground`、`visual.color_fraction`、`visual.geometry`、`pairs.*`、`set.semi_join`、`set.anti_join`、`state.detect`。

### 7.2 空间与区域

- 全画面、一个命名区域、区域集合、动态区域集合。
- 位于区域内/外、中心点、重叠比例。
- 目标之间重叠、包含、被包含、接近、双向匹配。
- 进入、离开、穿越边界。
- 每区域分别判断、全部区域、任一区域、N选M区域。

主要复用：`region.*`、`spatial.inside`、`spatial.associate`、`set.partition`、`reduce.quantify`。

### 7.3 数量与测量

- 全画面计数、区域计数、按类别计数、按区域分组。
- 单阈值、多个比较、区间内/外。
- 速度、方向、持续时间等数值。
- 最大、最小、平均、中位、累计、存在、全部。

主要复用：`measure.*`、`reduce.*`、`logic.compare`。

### 7.4 轨迹与运动

- 创建/确认轨迹。
- 方向、逆行、速度、位移。
- 停留、静止、徘徊。
- 目标轨迹与区域、方向资源关联。

主要复用：`track.*`、`measure.heading`、`measure.speed`、`logic.heading_by_lane`。

### 7.5 状态与事件

- 当前状态。
- 同一目标状态转变。
- 条件转事件。
- 引用预置或模型检测事件。
- 事件有效期、事件重命名、告警。

主要复用：`state.*`、`event.from_condition`、`event.relabel`。

### 7.6 时间与复杂编排

- 持续、累计、比例、允许中断。
- 同一对象/轨迹/目标对/区域/全局连续。
- 同时有效、全部完成、窗口内完成、任一、N选M。
- 先后顺序、每段独立延迟、during/contains/overlaps/until。
- 规定窗口内未发生。
- 重复发生 N 次。
- 冷却、并行事件实例、事件消费策略。

主要复用：`temporal.*`、`event.trigger@2.0`。

### 7.7 输出与证据

- 布尔结果、数量、测量值、方向、轨迹、事件、时间线。
- 目标框、标注媒体、通知。
- 事件证据收集、目标框投影、分支证据。

主要复用：`evidence.collect`、`event.attach_evidence`、`result.project`、`output.draw`、`output.alert`。

### 7.8 不直接暴露的技术原子

以下能力仍保留在执行参数或由编译器自动插入，不进入事件条件选择器：

- 媒体读取与视频抽帧。
- resize、tile、crop。
- 去重、集合合并、绘制。
- 内部过滤、类型归约和证据连接。

“支持全部原子能力组合”在产品层的含义是：全部业务语义能力均可配置，编译器可自动补足必要技术原子；不是让普通用户逐节点连线。

## 8. Schema 驱动的条件编辑器

新增 `BusinessCapabilityDefinition`：

```text
capability_id
version
display_name
category
description
input_contract
output_contract
parameter_schema
editor_schema
parameter_presentations
presentation_overrides
media_requirements
resource_requirements
validation_rules
compiler_recipe
evidence_contract
```

示例：

```json
{
  "capability_id": "motion.wrong_way",
  "display_name": "车辆逆行",
  "category": "轨迹与运动",
  "input_contract": "ObjectSet<vehicle>",
  "output_contract": "ConditionSet<track>",
  "media_requirements": ["video"],
  "resource_requirements": ["region", "direction"],
  "editor_schema": [
    {"name": "scope", "editor": "scene_resource_select", "label": "判断范围"},
    {"name": "reference", "editor": "direction_resource_select", "label": "正常行驶方向"},
    {
      "name": "cosine_threshold",
      "editor": "angle_degrees",
      "label": "判定逆行所需的最小夹角",
      "help": "车辆运动方向与正常方向的夹角达到该值时，才判断为逆行。",
      "display_unit": "度",
      "display_value": 120,
      "maps_to": "logic.compare.threshold",
      "value_transform": "degrees_to_cosine"
    },
    {
      "name": "minimum_displacement",
      "editor": "screen_diagonal_percent",
      "label": "判定车辆已移动的最小距离",
      "help": "位移不足时不判断方向，减少静止车辆框抖动造成的误报。",
      "display_unit": "%画面对角线"
    }
  ],
  "compiler_recipe": "reverse_motion"
}
```

新增能力时只注册能力定义、编译 Recipe 和测试，不修改整套页面。

`name` 和 `maps_to` 只用于内部编译，03 渲染时只能使用 `label` 和帮助文案。`value_transform` 必须可逆：用户看到的角度、百分比或画面比例修改后能稳定转换为 Effective SkillPackage 的余弦、0–1 比例或像素值；帧数保持帧数，不做隐式时间换算。重新加载时必须还原为相同用户值。

## 9. 条件分支模型与界面

### 9.1 分支模型

```text
BusinessBranch
├─ branch_id
├─ display_name
├─ description
├─ input_sources
├─ condition_tree
├─ temporal_qualifiers
├─ validity_policy
├─ branch_outputs
├─ evidence_policy
├─ persistence_policy
├─ participates_in_final_decision
└─ enabled
```

### 9.2 分支界面

```text
分支A：业务名称                           [复制] [停用] [删除]

满足条件：
  条件组：全部满足 AND
    条件1 [目标与属性]
    条件2 [空间与区域]
    条件3 [数量与数值]
  [新增条件] [新增条件组]

时间约束：
  [无 / 持续 / 累计 / 窗口 / 重复]

成立后有效：
  [当前帧 / 事件区间 / 保持XX秒 / 直到重置]

分支输出：
  ☑ 是否成立  ☑ 数值  ☑ 目标框  ☑ 持续时间

保存策略：
  ☑ 保存分支结果  ☑ 保存触发证据
```

简单检测同样使用一个分支，不需要事件编排阶段。

### 9.3 分支中可以新增的具体条件

用户点击“新增条件”后，先按业务类别选择，不显示原子 ID。搜索可以输入“红衣”“数量”“逆行”“持续”“事故”等业务词；选择后由 Schema 生成参数表单。

| 条件类别 | 用户可选条件 | 03 中主要可编辑参数 | 典型编译能力 |
|---|---|---|---|
| 目标与类别 | 检测目标、按模型类别筛选、按自然语言短语筛选、多类别合并、类别排除 | 模型来源、目标类别/短语、单类或多类、输出框标签、包含/排除、去重规则 | `rex.ground`、`objects.filter_*`、`objects.merge`、`set.difference` |
| 外观与属性 | 颜色、上衣颜色、裤子颜色、尺寸、位置、宽高比、业务属性 | 主体目标、属性部位、颜色、最小颜色占比、主色模式、尺寸/位置/宽高比及阈值 | `visual.color_fraction`、`visual.geometry`、`filter.apply` |
| 同一主体 | 同一人员同时满足多个属性、主体与装备绑定、主体缺少装备 | 主体来源、属性/装备来源、绑定关系、关系度量、阈值、是否同帧、存在/缺失 | `pairs.*`、`set.semi_join`、`set.anti_join` |
| 区域归属 | 在全画面/指定区域/动态区域内或外、每个区域分别判断 | 目标来源、范围、区域引用、判断方式、重叠阈值、区域量词 | `region.*`、`spatial.inside`、`set.partition`、`reduce.quantify` |
| 目标关联 | 重叠、包含、被包含、接近、双方匹配 | 主体、对象、关系、IoU/IoS/覆盖率/中心距离、比较符、阈值、同帧要求 | `spatial.associate` 或 `pairs.*` |
| 数量 | 目标数量、区域数量、多类别总数、每类分别计数、数量区间 | 计数对象、统计范围、分组方式、比较符、阈值；可添加多条比较并设 AND/OR | `measure.count`、`measure.region_count`、`reduce.count`、`logic.compare` |
| 数值与统计 | 速度、方向值、持续时间、均值/中位/最大/最小/总和 | 测量来源、单位、统计函数、窗口、比较符、阈值或上下限 | `measure.*`、`reduce.statistic`、`logic.compare` |
| 轨迹与运动 | 移动方向、逆行、速度、停留、静止、轨迹有效性 | 目标、区域、参考方向、同向/逆向、余弦阈值、观测窗口、最小位移、速度阈值、轨迹确认条件 | `track.*`、`measure.heading`、`measure.speed`、`logic.heading_by_lane` |
| 状态 | 当前状态、检测标签状态、属性状态、状态转变 | 主体、证据模式、状态映射、正向状态、起始/结束状态、最大转变时间 | `state.detect`、`state.transition` |
| 业务事件 | 事故、摔倒、火、烟、拥堵等可检测/可组合事件 | 事件证据来源、事件标签、过滤范围、最短事件时长、有效期 | 检测/状态/数量 Recipe、`event.from_condition`、`event.relabel` |
| 分支引用 | 另一分支当前成立、已完成、未成立或输出数值满足条件 | 来源分支、引用字段、状态/比较关系、关联范围 | 类型安全的分支输出引用、`logic.*`、`temporal.join` |

“事故”“摔倒”“拥堵”等不是独立写死的 UI 卡片类型，而是业务能力或 Recipe：事故可以来自模型事件检测；摔倒可以来自倒地状态或状态转变；拥堵可由区域车辆数量、密度或速度组合。条件卡必须显示其实际判定方法，用户可以替换方法和调整参数。

### 9.4 时间约束不是普通条件，但可附着到任意条件或分支

每张条件卡和条件组均提供“添加时间约束”：

| 时间约束 | 可编辑参数 |
|---|---|
| 立即 | 无 |
| 连续持续 | 持续秒数、允许中断秒数、同一目标/目标对/区域/全局、首次/连续输出 |
| 累计持续 | 统计窗口、累计秒数、身份范围 |
| 窗口占比 | 统计窗口、满足比例、允许中断 |
| 事件有效期 | 成立后保持秒数、结束/重置条件 |
| 重复发生 | 窗口秒数、最少次数、是否同一身份 |
| 未发生 | 锚点事件、之前/之后窗口、禁止事件、关联范围 |

分支级“成立后有效”和跨分支 EventPattern 分开配置，避免把条件持续、分支有效期和最终事件冷却混为一个时间字段。

### 9.5 具体原子参数是否可以修改

可以，但按“业务参数—调优参数—资源参数—派生参数”分层，不允许用自由 JSON 破坏类型关系。

03 不直接显示 `iou_threshold`、`gap_tolerance_seconds`、`correlation_scope`、`min_displacement_pixels` 等技术字段名。每个控件采用统一结构：

```text
允许短暂中断  [?]
[0.5] 秒
条件短暂消失不超过该时间时，仍视为连续满足。  推荐：0.3–1.0 秒
```

- 字段标题使用业务语言，技术名称不放在标题、占位符或错误消息中。
- 字段下方始终有一句简短说明，不依赖用户主动查看帮助。
- `?` 点击后打开参数详情抽屉，显示用途、当前/默认/推荐值、合法范围、调大/调小影响、示例、影响的分支和恢复默认。
- 技术字段名、实际编译值和原子映射只放在详情抽屉的“开发信息”折叠区。
- 数值使用最直观且稳定的单位：0–1 比例显示百分比，帧数保留“帧”，像素可显示画面比例，方向余弦显示夹角度数。帧数不强制换算为秒。
- 校验和警告使用业务语言，并说明如何修复；不得返回 Pydantic 字段路径或原始 JSON 解析错误。

典型参数显示规范：

| 内部参数 | 03 用户名称 | 用户控件/单位 | 必须说明的影响 |
|---|---|---|---|
| 跟踪 `iou_threshold` | 同一目标匹配要求 | 0–100% 滑块 | 调低更容易保持连续轨迹但可能串错目标；调高更严格但轨迹可能中断 |
| 去重 IoU/IoS 阈值 | 认定为重复框的最低重叠比例 | 0–100% 滑块 | 调低会合并更多框；调高会保留更多相近框 |
| 区域 `overlap_threshold` | 目标进入区域的最低比例 | 0–100% 滑块 | 调高要求目标更深入区域；调低会在边缘更早命中 |
| `gap_tolerance_seconds` | 允许短暂中断 | 秒 | 调大可容忍漏检，但可能把两段事件连在一起 |
| `min_displacement_pixels` | 判定已移动的最小距离 | %画面对角线 | 调大可减少框抖动误判，但可能漏掉慢速移动 |
| 方向余弦 `threshold` | 同向最大偏差/逆行最小夹角 | 度 | 用角度描述方向严格度，内部自动转换余弦 |
| `max_missing_frames` | 目标暂时消失可保留多少帧 | 帧 | 调大可跨越更多漏检帧，但增加串轨风险 |
| `window_frames` | 运动观察帧数 | 帧 | 帧数少响应快但易抖动；帧数多更稳定但告警更慢 |
| `required_ratio` | 时间窗口内至少满足 | 百分比 | 比例越高越接近持续满足 |
| `correlation_scope` | 多个事件按什么对象关联 | 全局/同一人员或车辆/同一区域/同一目标对 | 选择错误会把不同对象发生的事件错误组合 |
| `maximum_matches` | 最多保留的事件组合 | 个 | 限制复杂组合数量，避免大量重复结果 |

参数名称和说明可按业务能力覆盖。例如车辆逆行使用“正常行驶方向”和“逆行最小夹角”，人员移动则使用“参考移动方向”和“方向偏差”，不向用户显示同一个笼统的 `threshold`。

### 9.5.1 参数详情抽屉

```text
允许短暂中断
用途：避免偶发漏检把一次连续事件切成多段。
当前值：0.5秒（来自系统默认）
推荐范围：0.3–1.0秒
可用范围：0秒以上

调大：更能容忍遮挡和漏检，但可能连接原本分开的两次事件。
调小：事件分段更严格，但容易因单帧漏检而中断。

示例：持续要求为5秒、允许中断0.5秒时，中间漏检0.3秒仍算连续。
影响：分支“区域4车辆逆行” → 持续条件

[恢复推荐值] [查看开发信息]
```

帮助抽屉是 03 和 05 共用组件。03 从当前条件上下文进入，优先展示当前值及业务影响；05 从能力资产进入，展示该参数在各 Recipe 中的含义和默认值。关闭后焦点回到原 `?` 按钮。

### 9.5.2 条件卡默认直接显示

- 输入目标/事件/分支来源。
- 模型类别或检测短语。
- 统计范围及区域引用。
- 比较符、阈值、上下限和单位。
- 关系类型及 IoU、IoS、覆盖率、中心距离等阈值。
- 颜色、部位、颜色占比，或状态映射。
- 方向关系、参考方向、最小位移和速度阈值。
- 持续时间、允许中断、窗口、次数和身份范围。
- 业务框标签、分支结果名称和证据输出。

### 9.5.3 “更多设置”显示效果调优参数

- 检测去重度量/阈值、目标集合筛选方式。
- 视频抽样 FPS/间隔/帧步长和最大帧数。
- resize、tile、裁剪上下文等预处理参数。
- 跟踪 IoU、最大丢失帧、最少命中数、最小轨迹跨度。
- 方向观测窗口、速度统计方式、区域归属采样方式。
- 事件消费、最大匹配数、触发模式和证据保存级别。

这些参数只在当前条件或其共享输入源上修改。若一个原子被多个条件共享，修改前显示影响范围，并允许“仅本条件复制一份”或“修改共享配置”。

### 9.5.4 不可直接修改

- 节点 ID、端口名、内部 key、类型转换节点和拓扑连接。
- 编译器自动插入的存在/数量归约。
- 由媒体元数据计算的宽高、FPS、时长和时间戳。
- 由 02 标注产生的归一化几何坐标；03 可选择、重命名、替换引用，但绘制坐标回 02 修改。

每次修改后即时执行局部校验，并显示“这项参数会影响什么结果”。保存前执行全量校验、重新编译和估算。

### 9.6 分支卡完整交互

```text
分支A：区域1指定着装人员                  [启用] [复制] [删除]
说明：区域1至少存在1名红色上衣、灰色裤子的人员

条件组：全部满足 AND                      [改为OR] [添加子组]
  1. 检测人员
     目标来源：[Rex]  类别/短语：[人员]  框标签：[红色上衣、灰色裤子人员]
  2. 红色上衣
     作用对象：[条件1人员]  部位：[上半身]  颜色：[红色]  最小占比：[0.20]
  3. 灰色裤子
     作用对象：[同一条件1人员]  部位：[下半身]  颜色：[灰色]  最小占比：[0.20]
  4. 区域归属
     作用对象：[满足条件1-3的同一人员]  区域：[区域1]  方式：[框中心在区域内]
  5. 集合存在
     数量：[>=] [1]

[新增条件] [新增条件组] [添加时间约束]

分支成立后有效：[当前满足期间]
分支输出：☑ 是否成立  ☑ 人数  ☑ 目标框
证据：☑ 命中帧  ☑ 条件值  ☑ 原始模型标签
```

卡片标题使用业务语言；底部提供只读“实现说明：使用 8 个原子”，点击后跳转 05 对应资产并高亮当前实际参数，不在 03 展开节点连线。

### 9.7 业务事件（按需）

“业务事件”不是事件类型枚举，也不是必须先建事件再建分支。它用于把一种判定方法命名成可复用事件，供多个分支、复杂编排和输出引用。

可选生成方式：

| 生成方式 | 示例 | 可编辑参数 |
|---|---|---|
| 模型直接检测 | 交通事故、火、烟、倒地人员 | 模型来源、目标类别/短语、范围、模型阈值（来源支持时）、事件名称、框标签 |
| 条件转事件 | 区域车辆数大于 10 形成“拥堵事件” | 来源条件/条件组、立即或持续资格、身份范围、事件名称 |
| 状态转事件 | 人员处于倒地状态 | 主体、状态证据、正向状态、持续资格、事件名称 |
| 状态变化事件 | 站立/行走变为倒地 | 主体、起始状态、结束状态、最大转变时间、事件名称 |
| 关系事件 | 人员进入危险区、人员未佩戴安全帽 | 主体/对象、关系、阈值、存在或缺失、事件名称 |
| 分支完成事件 | 区域4逆行分支持续达标 | 来源分支、取“当前成立”或“完成时刻”、有效期、事件名称 |

每个事件还可配置：

- 事件主体：全局、目标、轨迹、目标对、区域。
- 生效方式：当前满足期间、完成瞬间、完成后保持 N 秒、直到指定重置事件。
- 去重键：按全局、主体、区域或事件实例。
- 证据：目标框、轨迹、数值、方向、命中帧和片段。
- 对外名称：事件名称；与业务框标签、告警名称分别保存。

若事件只在一个分支内部使用，前端将其折叠在条件卡中，不要求用户管理独立事件资产。只有被跨分支引用、参与复杂编排或单独输出时，才在“业务事件”区域列出。

## 10. 复杂事件编排

### 10.1 模型

```text
EventPattern
├─ stages
├─ gateways
├─ transitions
├─ correlation_policy
├─ instance_policy
└─ trigger_policy
```

### 10.2 用户可选模式

| 模式 | 适用语义 | 必要参数 |
|---|---|---|
| 所有分支当前同时有效 | A、B、C 此刻都成立 | 参与分支；可选最小重叠时长 |
| 所有分支分别完成 | 各分支都完成过，不要求同时 | 参与分支、完成记录何时重置 |
| 所有分支在窗口内完成 | A、B、C 在 60 秒内分别完成 | 参与分支、窗口秒数、窗口起点 |
| 任一分支成立 | A 或 B 或 C | 参与分支 |
| 至少 N 个分支成立 | 4 个条件中至少 3 个 | 参与分支、N、按当前成立或已完成 |
| 触发分支发生时检查其他分支 | 事故发生时，人数和逆行条件均有效 | 触发分支、被检查分支、允许前后容差 |
| 按指定顺序完成 | A 后 B，再后 C | 阶段顺序、每条边最小/最大间隔 |
| 任意顺序完成 | A、B、C 顺序不限但须在窗口内完成 | 参与分支、总窗口 |
| A 在 B 之后/之前 | 烟火在事故 20 秒后发生 | A、B、最小/最大间隔 |
| A 在 B 期间 | 有人在车辆拥堵期间逆行 | A、B、时间关系 `during` |
| A 包含/重叠 B | 长事件包含短事件，或两个区间重叠 | A、B、关系、可选最小重叠时长/比例 |
| A 后 B 未发生 | 事故后 30 秒内没有人员撤离 | 锚点 A、禁止事件 B、前/后窗口 |
| 事件重复 N 次 | 同一车辆 60 秒内逆行出现 3 次 | 来源事件、次数、窗口、是否同一身份 |
| 保持直到事件 B | A 成立后一直有效，直到 B 重置 | 来源 A、重置事件 B、最大保持时长 |

选择一个模式后只显示该模式需要的字段。若 LLM 没有明确“同时”“窗口”“先后”等语义，多分支默认使用“所有分支当前同时有效”，并在审核摘要中明确写出默认解释；不能静默使用“都曾经发生过”。

### 10.2.1 所有编排模式共有参数

- 参与分支或业务事件，可排序、增删、停用。
- 关联范围：全局、同一目标、同一轨迹、同一目标对、同一区域、同一摄像头、指定业务字段。
- 实例策略：允许并行实例/仅保留一个，事件是否消费，最大匹配数。
- 完成记录：保留到技能运行结束、窗口结束或指定重置事件。
- 输出名称、保存编排过程、失败/等待原因和证据摘要。
- 瞬时事件有效期：仅完成时刻、前后容差、完成后保持 N 秒。

单分支且无顺序、窗口、缺失或重复语义时，不显示复杂事件编排，编译器直接把分支结果交给最终判定。

### 10.3 关键语义

- “同时有效”比较事件区间是否重叠。
- “窗口内完成”比较完成时间，不要求同一时刻有效。
- 瞬时事件参与联合判断时必须有明确有效期或完成语义。
- 持续约束附着于条件或分支，不得把一个统一持续时间错误施加给所有分支。
- 同一目标连续、同一目标对连续和全局连续必须分开。
- 每条顺序边可以有独立最小/最大延迟。
- 不允许循环依赖和悬空分支引用。

### 10.4 可执行时序语义规范

时序不能只定义前端模式名称。编译器、运行时、结果页和测试统一采用以下规范。

#### 10.4.1 时间域与区间

- 视频使用媒体时间戳，不使用机器处理时间；暂停、推理变慢不会改变业务时间。
- 图片只有一个 `t=0` 瞬时点，不允许持续、顺序、延迟、缺失窗口和重复等视频时序能力。
- 持续事件使用半开区间 `[start_at, end_at)`；瞬时事件使用 `qualified_at`，参与区间关系时必须由模式显式配置容差或有效保持时间。
- 每个阶段统一记录 `first_seen_at`、`qualified_at`、`last_seen_at`、`ended_at`。关系边使用 `source_anchor/target_anchor` 明确引用其中哪个时间点。
- 抽帧误差使用实际采样时间戳计算并记录 `sampling_tolerance`；用户配置的秒数和帧数保持原单位，不做隐藏换算。比较结果必须同时保存要求值、实际值和容差。
- 视频未观察到完整结束边界时，结果标记 `open_interval=true`；不能伪造结束时间。

#### 10.4.2 阶段状态机

```text
idle
→ observing        首次命中，尚未达到持续/比例/次数要求
→ qualified        已满足阶段条件并产生完成时间
→ active/ended     继续有效或已结束
→ reset            按窗口、消费或重置事件清除

任意阶段还可进入：timed_out / not_evaluable / error
```

对用户统一投影为 `satisfied / not_satisfied / pending / not_evaluable / error`。`pending` 只表示观察窗口尚未结束且仍可能满足；媒体已结束且条件未满足时转为 `not_satisfied`，资源或媒体能力不足时为 `not_evaluable`。

#### 10.4.3 组合模式判定公式

| 模式 | 确定性成立规则 | 等待/失败规则 |
|---|---|---|
| `all_active` | 所有参与阶段有效区间的交集时长达到 `minimum_overlap` | 尚有可能形成交集时等待；媒体结束仍无交集则失败 |
| `all_completed` | 每个阶段至少有一个未被消费的 `qualified_at` | 缺少阶段且媒体未结束时等待 |
| `all_completed_within_window` | `max(qualified_at)-min(qualified_at) <= window` | 最早完成实例超窗后按实例策略重置或失败 |
| 触发时检查其他分支 | 在触发阶段 `qualified_at`，其他分支处于 active，或落入显式前后容差 | 触发发生但被检查分支无效则该实例失败 |
| 顺序 | 每条边的目标锚点减来源锚点位于 `[min_delay,max_delay]` | 最大延迟未到前等待；超过后按 timeout 行为处理 |
| `during` | A 的有效区间完全落在 B 的有效区间内 | 任一必要区间结束且关系不成立则失败 |
| `contains` | A 的有效区间包含 B | 同上 |
| `overlaps` | 区间交集达到最小时长或比例 | 媒体结束仍不足则失败 |
| `absence` | 锚点后的完整禁止窗口已经关闭，期间不存在符合关联键的 B | 窗口关闭前始终是等待；B 出现立即失败 |
| `repeat` | 同一关联键下出现至少 N 个不同事件实例，且首尾完成时间在窗口内 | 次数仍可能达到时等待；窗口关闭不足 N 次则失败/滑窗 |
| `until` | A 从资格成立后保持有效，直到 B 或最大保持时间 | B 未发生且媒体仍在观察时保持 active |

#### 10.4.4 关联、实例和消费

- 每个时序事件实例必须有稳定 `event_instance_id` 和 `correlation_key`。
- 本期关联范围只开放 `global/object/track/pair/region`；`camera/scene/field` 不进入普通用户配置。
- `consume_events=true` 时，同一个事件实例只可被一个成功模式实例消费；重放运行结果不会再次消费或发送通知。
- 并行实例按 `correlation_key` 隔离；达到 `maximum_active_per_key` 时必须按配置拒绝新实例或淘汰最旧实例，并产生可观察诊断。
- OR/N-of-M 只把实际参与成功路径的阶段写入 `participating_branches`，不能把未参与分支的框混入最终证据。

#### 10.4.5 编译与测试门槛

每个前端时序模式必须注册：业务 Schema、状态机实现、可编译 Recipe、支持的输入类型、媒体要求、边界测试和结果投影。任何模式若底层原子不能完整表达，03 可以展示“当前版本尚不支持”，但不得生成一个可保存却不可执行的近似规则。

必须使用受控事件流测试区间边界、刚好等于阈值、抽帧误差、视频提前结束、短暂中断、多身份并行、事件消费、超时、重置和保存重载；视觉模型测试只验证上游能否产生正确事件，不代替时序状态机测试。

## 11. 最终判定、业务输出与触发

### 11.1 最终判定

每个技能必须且只能有一个主最终判定。LLM 根据用户想看到的结果自动选择，用户可调整：

| 判定类型 | 用户看到的主结论 | 必要配置 | 适用任务 |
|---|---|---|---|
| `event_decision` | 已触发/未触发/等待/无法判断 | 来源分支或 EventPattern、事件名称 | 告警、事故、逆行、摔倒等事件任务 |
| `detection_summary` | 检测完成，发现 N 个目标 | 目标来源、统计方式、结果名称 | 只需要识别框和数量的任务 |
| `measurement_decision` | 实际值 X，要求 Y，满足/不满足 | 数值来源、比较符、阈值、单位 | 人数、车数、速度、持续时长等测量任务 |
| `state_summary` | 当前状态/状态已变化 | 主体、状态来源、期望状态或转变 | 站立、倒地、佩戴状态等 |
| `timeline_summary` | 已完成 K/M 个阶段，成功/失败/等待 | EventPattern、阶段完成要求 | 顺序、多阶段和窗口流程 |

可编辑字段：最终结果名称、判定类型、来源、成功条件、是否显示原因、是否显示失败/等待分支、总览排序。最终状态固定为 `triggered/satisfied`、`not_triggered/not_satisfied`、`pending`、`not_evaluable`、`error` 的兼容集合，用户不能把这些状态改成含义不清的“不适用”。

默认选择规则：

- 用户说“告警、事件、是否发生”时选择 `event_decision`。
- 用户说“识别、框出、统计有多少”且没有阈值时选择 `detection_summary`。
- 用户要求输出数值并判断阈值时选择 `measurement_decision`。
- 用户只关注当前/变化状态时选择 `state_summary`。
- 存在两个及以上阶段、顺序或窗口完成时选择 `timeline_summary`。

### 11.2 业务输出

`ResultSpec` 先定义“结果是什么”，`PresentationSpec` 再定义“结果怎么显示”。两者分开持久化、校验和哈希：

```text
ResultSpec                         业务语义，参与 semantic_hash
├─ result_id
├─ display_name
├─ semantic_type                  decision/boolean/scalar/entity_set/track_set/event_set/timeline/resource/media
├─ value_shape                    single/list/grouped/interval/series
├─ source_ref                     稳定引用最终判定、分支、条件、事件、测量或资源
├─ projection                     count/value/status/duration/entities/events/stages 等
├─ unit
├─ grouping                       语义分组键，不是页面布局
├─ condition_snapshot_policy
├─ label_policy
├─ save_policy
├─ evidence_policy
└─ empty_policy

PresentationSpec                   展示偏好，只参与 presentation_hash
├─ result_id
├─ preferred_renderer
├─ show_in_overview / display_order / overview_span
├─ value_format / precision
├─ sort_by
├─ visualization_options
└─ interaction_policy
   ├─ drilldown
   ├─ highlight_evidence
   └─ default_focus
```

规则行为、数值、来源、单位、分组语义和保存内容属于 `ResultSpec`；卡片/表格选择、位置、显示精度、颜色和展开方式属于 `PresentationSpec`。修改 PresentationSpec 不触发重新编译和视觉推理，只重建 `RunResultViewModel`；修改 ResultSpec 语义必须重新校验，并在来源或投影变化时重新编译/运行。

用户可添加以下输出；系统至少生成“最终判定”，并按原文自动补充用户明确要求的结果：

| 输出类型 | 可选来源 | 主要配置 |
|---|---|---|
| 最终判定 | 主最终判定 | 显示名称、是否置顶、空结果文案 |
| 分支状态 | 任一条件分支 | 当前状态/完成状态、成立时间、持续时间、原因 |
| 布尔判断 | 条件、条件组、事件或分支 | 名称、真/假显示文案 |
| 数量 | 目标集合、轨迹集合、区域分组 | 名称、单位、总数/每类/每区域、是否同时显示阈值结论 |
| 数值/统计 | 速度、方向余弦、距离、时长、统计归约 | 名称、单位、精度、统计函数、阈值条件 |
| 目标框/目标列表 | 原始目标或经过业务条件筛选的目标 | 业务框标签、保留原模型标签、排序、最大显示数 |
| 轨迹 | 目标轨迹或事件关联轨迹 | 轨迹标签、是否绘制轨迹线/ID、时间范围 |
| 事件列表 | 业务事件、分支事件、最终事件 | 事件名称、起止时间、主体、区域、严重级别 |
| 持续结果 | 条件、事件或分支 | 实际持续时间、要求时间、是否达标 |
| 时间线/阶段 | EventPattern | 阶段顺序、完成时间、等待/失败阶段 |
| 场景资源 | 区域或参考方向 | 是否叠加显示名称、边界、箭头 |
| 标注媒体 | 目标框、轨迹、事件、区域、方向、数值组合 | 图片/视频、显示层、标签策略、输出尺寸/FPS |
| 证据包 | 任一结果 | 关键帧、片段、目标、轨迹、数值、方向、Trace 级别 |

每个输出可配置：显示名称、来源、是否出现在概览、顺序、保存策略（始终/触发时/非空时/仅摘要）、证据策略、空结果策略。适用但没有命中时应显示 0、未发现或未触发；只有输入能力确实不适用时才显示“不适用”。

#### 11.2.1 ResultSpec 语义类型和兼容迁移

每个 `semantic_type + value_shape + projection` 组合必须在后端注册输入类型、输出值 Schema、允许单位、允许分组、证据要求和兼容渲染器。`source_ref` 必须指向带类型的公开业务输出，不能再仅用底层输出名称列表表达来源。

现有 `core/editor_schema.py::ResultSpec` 的 `result_type/required_outputs/evidence_policy` 通过迁移器转换：

```text
旧 result_type       → semantic_type + value_shape + projection
旧 required_outputs  → 类型化 source_ref[]
旧 evidence_policy   → 新 evidence_policy
缺失展示字段         → 由 PresentationSpec 默认注册表补充
```

无法唯一判断投影含义时生成 `PendingDecision`，不得根据输出名称猜测。例如底层 `events` 既可能表示“是否发生”，也可能表示“事件列表”；迁移器必须让用户确认或保持只读兼容结果。

#### 11.2.2 03 的通用业务输出编辑器

03 不让用户选择“逆行卡”“拥堵卡”“摔倒卡”等案例组件，而是配置一份与业务含义一致的输出规格：

```text
输出名称：      [区域2车辆数量]
结果来源：      [分支2 / 区域内车辆集合]
希望看到：      [数量]
统计方式：      [总数]
分组方式：      [不分组 / 按区域 / 按类别 / 按分支]
显示方式：      [指标卡 / 阈值卡 / 表格]   仅列出兼容选项
概览位置：      [关键输出，排第2]
数值格式：      [整数] [单位：辆]
证据联动：      [点击时高亮参与统计的车辆]
保存策略：      [每次保存摘要和证据引用]
无结果显示：    [0辆]
```

用户可编辑字段统一使用业务名称、单位和短说明；`renderer_id`、字段路径、证据索引等实现值由表单生成，不直接暴露。LLM 负责生成初稿，03 允许新增、复制、删除、排序和修改所有输出。

可选“希望看到”按来源动态收敛：

| 来源语义 | 用户可选投影 |
|---|---|
| 最终判定 | 结论、原因、触发时间、完成阶段数 |
| 条件/条件组/分支 | 是否满足、实际值、要求值、持续时间、成立区间 |
| 目标集合 | 数量、目标列表、目标框、类别分组、区域分组 |
| 轨迹集合 | 轨迹数、轨迹列表、运动方向、速度、轨迹线 |
| 事件集合 | 是否发生、事件数、事件列表、起止时间、主体 |
| 数值/统计 | 原值、聚合值、阈值结论、分组表格 |
| EventPattern | 最终状态、阶段进度、顺序时间线、共同有效区间 |
| 场景资源 | 区域、边界、参考方向、资源名称 |

展示方式不能改变结果语义：数量可以显示为指标卡或表格，但不能因为换了卡片就被转换为“事件发生”。若用户选择不兼容的展示方式，前端禁止保存并给出可理解原因。

### 11.3 标签隔离

必须分别维护：

```text
model_label     输入模型原始标签
business_label  条件分支目标框标签
event_label     事件名称
alert_label     告警名称
result_name     业务输出名称
```

事件名称不得覆盖目标框标签。未进入任何业务分支的目标保留输入模型标签。

### 11.4 触发策略

触发策略只决定“何时发出和如何处理告警”，不再承载条件含义。可选项如下：

| 配置项 | 可选值 |
|---|---|
| 触发时机 | 首次达到最终条件、每次新事件实例、条件由假变真、持续满足时按间隔重复 |
| 重复策略 | 仅首次、允许重复、重新成立后允许、每个主体仅首次 |
| 冷却时间 | 0 或大于 0 的秒数 |
| 冷却范围 | 全局、主体/轨迹、目标对、区域、事件实例 |
| 告警级别 | 低、中、高、严重；允许项目扩展枚举 |
| 通知 | 不通知、页面内、Webhook/项目已接入通知通道 |
| 事件记录 | 保存/不保存，事件名称和业务字段 |
| 证据保存 | 关键帧、前后事件片段、完整命中区间、仅结构化证据 |
| 去重 | 按事件实例、主体、区域或自定义业务键 |
| 恢复事件 | 不产生、条件恢复时产生一条恢复记录 |

事件片段额外配置触发前秒数、触发后秒数和最长片段；若输入是图片则该项自动隐藏。没有“告警/通知/事件输出”意图的检测与测量任务不显示触发策略，也不自动创建告警。

## 12. 分支结果与最终结果保存

### 12.1 分支结果必须保存

```text
BranchResult
├─ branch_id/name
├─ status
├─ boolean_value
├─ first_satisfied_at
├─ qualified_at
├─ last_satisfied_at
├─ active_duration
├─ expires_at
├─ outputs
├─ reason
└─ evidence_refs
```

状态必须区分：

```text
satisfied
not_satisfied
pending
not_evaluable
disabled
error
```

### 12.2 最终结果始终存在

```text
FinalResult
├─ name
├─ result_type
├─ status
├─ triggered/decision
├─ trigger_time
├─ reason
├─ participating_branches
├─ failed_branches
├─ pending_branches
├─ business_output_refs
└─ evidence_summary
```

最终状态：`triggered`、`not_triggered`、`pending`、`not_evaluable`、`error`。

“没有触发”“尚在等待”“输入不足无法判断”不能合并为“不适用”。

### 12.3 运行目录

每次运行至少保存：

```text
run_summary.json
final_result.json
business_outputs.json
branch_results.json
result_spec_snapshot.json
presentation_spec_snapshot.json
scene_resource_snapshot.json
renderer_manifest.json
events.json
measurements.json
detections.json
tracks.json
regions.json
directions.json
evidence.json
annotated_media
```

默认策略：最终结果、业务输出、分支状态、触发证据和标注媒体始终保存；完整逐帧证据和开发 Trace 按策略保存。

### 12.4 通用导出

导出不按案例单独开发，统一从 `FinalResult + BusinessOutputValue + BranchResult + EvidenceIndex` 生成：

| 导出形式 | 内容 | 适用范围 |
|---|---|---|
| 业务摘要 JSON | 最终结论、业务输出、分支状态、稳定引用 | 系统集成、历史重放 |
| CSV/表格 | 用户在 03 选择的标量、数量、事件和分组列 | 统计与批量分析 |
| 证据包 | 摘要 JSON、关键帧/片段、框/轨迹/区域/时间引用 | 审核与追溯 |
| 标注图片/视频 | 按 ResultSpec 选择的证据层合成 | 汇报和人工复核 |
| 可读报告 | 最终结果、业务输出、主要原因、关键证据缩略图 | 普通用户查看 |

导出字段名、单位、顺序、分组和标签与 04 保持一致；原始技术字段只在“包含开发明细”选项中附加。CSV 不适合的嵌套目标/时间线输出使用独立明细表或 JSON，不把复杂结构压成不可解析文本。

### 12.5 类型化运行结果与证据链

当前运行时按 `EventSet/ObjectSet/TrackSet/ScalarSet` 平铺写入分类文件，会丢失业务分支和 ResultSpec 来源。V3 保留这些分类文件用于兼容诊断，但新增以下事实协议作为唯一业务结果来源：

```text
RuntimeValueEnvelope
├─ value_id
├─ run_id
├─ source_node_id
├─ business_source_ref          条件/分支/事件/最终判定/ResultSpec
├─ value_type / value_shape
├─ value
├─ unit
├─ status / applicability
├─ identity_key                object/track/pair/region/global
├─ time_scope                  timepoint/interval/series
├─ entity_refs[]
├─ resource_refs[]
├─ evidence_refs[]
└─ diagnostics_ref

EvidenceRecord
├─ evidence_id
├─ media_asset_id
├─ timestamp/frame_index/time_range
├─ evidence_type               box/track/region/vector/measurement/event/frame/clip
├─ entity_refs[]
├─ geometry/value
├─ coordinate_space
└─ produced_by
```

执行要求：

1. 编译器为每个公开业务来源生成稳定 `business_source_ref`，并写入节点绑定表。
2. 算子输出或执行引擎适配层在产生值时创建 Envelope，来源引用沿集合筛选、关联、归约、时间和事件算子继续传播。
3. `result.project` 只消费 Envelope 和 ResultSpec，不通过显示名称、数组位置或平铺 JSON 猜来源。
4. `BranchResult`、`FinalResult` 和 `BusinessOutputValue` 只保存稳定引用与必要快照，证据内容统一存入 EvidenceIndex。
5. 运行目录同时保存文档哈希、Effective Package 哈希、ResultSpec/PresentationSpec 快照、SceneProfile 快照和渲染器清单。
6. 局部证据失败不能抹掉已经计算出的业务值；Envelope 标记证据缺失并保留诊断原因。

兼容阶段为现有算子增加 `LegacyOutputEnvelopeAdapter`：根据执行节点 ID 和编译绑定表包装旧类型输出。该适配器只解决来源封装，不能通过结果名称推断业务语义；无法恢复的来源标记 `not_evaluable` 或进入只读历史结果。

运行时升级范围明确为：不重写 Rex、跟踪、计数、时序等算子算法，但修改 `ExecutionResult`、输出传播、`core/runtime.py` 聚合、`RunStore` 持久化和证据索引。这是 04 通用结果页的前置条件，不可延后到 UI 完成后补做。

## 13. 04 运行与结果：三层结果架构

04 不再以“检测/轨迹/事件/数值/区域/方向 JSON”作为主导航。用户结果严格分为三层：

```text
第一层：最终结果
回答“发生了没有、成功了没有、最终值是否满足”。

第二层：业务输出
展示用户在03要求的数量、事件、框、轨迹、持续时间、方向和时间线。

第三层：分支与证据
解释为什么成立/未成立/无法判断，并在媒体中定位证据。
```

检查媒体、调用估算和运行按钮属于“运行操作区”，不是结果层。开发 Trace、原始模型响应和节点 JSON 属于第三层下的开发诊断，不单独占据用户结果层级。

### 13.1 当前页面问题与保留项

本轮基于 6131 当前 P05 运行结果进行了截图审查：

- [当前运行与媒体区](audits/2026-08-21-04-results/01-current-run-and-media.png)
- [当前技术结果标签与检测 JSON](audits/2026-08-21-04-results/02-current-technical-details.png)
- [当前事件结果 JSON](audits/2026-08-21-04-results/03-current-event-result.png)

当前页面已经具备运行、调用估算、媒体预览、检测/轨迹/事件等结构化结果和 Trace，这些能力保留。主要问题是：

- 运行完成后最醒目的是 `runtime_executed` 状态，不是业务最终结论。
- 当前事件已产出“逆行车辆”1条，但用户必须打开“事件结果”并阅读 JSON 才能知道发生了什么。
- 固定技术标签按数据类型组织，不对应用户在 03 配置的业务输出。
- 原始 ID、`applicable`、`source_node`、`raw_output` 等实现字段占据主要阅读空间。
- 标注媒体先于最终结论，用户无法先确认“事件是否发生”。
- 运行产物目录和技术说明优先级过高，应收进运行详情。
- 多个横向技术标签在窄窗口产生拥挤和溢出，不适合复杂输出扩展。

### 13.2 页面总体结构

```text
04 运行与结果
├─ 运行操作区
│  ├─ 当前媒体与任务摘要
│  ├─ 检查媒体与调用估算
│  ├─ 运行/重新运行
│  └─ 运行状态与耗时
├─ 第一层：最终结果
├─ 第二层：业务输出
├─ 第三层：分支与证据
│  ├─ 分支过程
│  ├─ 复杂事件时间线（按需）
│  ├─ 可视化证据
│  └─ 证据明细
└─ 运行详情（第三层内默认折叠）
   ├─ 媒体与模型调用
   ├─ 结构化原始结果
   └─ 开发诊断
```

页面不是五个地位相同的技术 Tab。运行完成后，三层结果按纵向阅读顺序出现；页面顶部提供锚点导航：`最终结果｜业务输出｜分支与证据`。复杂内容内部再使用局部 Tab 或抽屉。

#### 13.2.1 由创建、标注和审核共同驱动结果页

04 不能根据预置编号、事件中文名或案例类型硬编码页面。完整数据链固定为：

```text
01 自然语言中的“希望看到什么”
→ LLM 生成 ResultSpec 初稿和可选 PresentationSpec 建议
→ 02 创建真实区域/方向等 SceneResource
→ 03 审核来源、投影、名称、布局、证据与保存策略
→ 编译器生成 source_ref、类型和证据契约
→ 运行时产生类型化 BusinessOutputValue
→ ResultProjector 构造三层结果
→ ResultRendererRegistry 选择兼容渲染器
→ 04 渲染卡片、表格、时间线和媒体证据层
```

四个步骤的职责边界：

- 01 决定用户意图和输出初稿，例如“输出区域2车数、事故判断、烟火框和烟火持续时间是否达标”。
- 02 提供运行时真实场景资源。区域或方向数量未知时动态增加；结果页按实际资源引用显示，不预设“必须有区域1到区域5”。
- 03 是结果配置唯一入口。用户决定看哪些结果、如何命名、排序、分组、保存和联动证据。
- 04 只执行确定性投影和展示，不重新猜测自然语言，也不根据标签名称补业务含义。
- 05 保存 ResultSpec、渲染器版本和 Effective SkillPackage，使历史运行可以原样重放。

#### 13.2.2 禁止案例专用页面

前端实现不得出现以下判断：

```text
if preset_id == "P05"
if event_name contains "逆行"
if skill_name == "多区域复合安全事件"
```

案例只能作为 fixture 验证通用组合。页面分支只允许基于 `semantic_type`、`value_shape`、`media_type`、PresentationSpec 和数据规模。新增业务案例若只使用已注册的结果类型与证据层，不应修改 04 页面代码。

### 13.3 运行操作区

运行前展开：显示当前技能、媒体、variant、缺失资源、调用估算和主要操作。运行完成后自动收起为一行，不挤占结果首屏：

```text
✓ 运行完成 · 视频 00:11 · 处理6帧 · 事件1条 · 耗时8.4秒
[重新运行] [展开调用详情]
```

约束：

- `runtime_executed`、Effective、variant 等术语不作为普通用户主文案；需要时在详情显示。
- “运行成功”只表示流程执行完成，不能替代“事件已发生/未发生”。
- 运行产物目录、模型调用和降级信息移入“运行详情”。
- 运行中显示当前阶段和进度；无法估算时说明原因，不能显示空文本框。

### 13.4 第一层：最终结果

最终结果是运行后的第一个完整卡片，始终存在且占满主内容宽度：

```text
┌──────────────────────────────────────────────────────────┐
│ 多区域复合安全事件                         [已触发]       │
│ 事件已发生                                               │
│ 触发时间 00:52.5                                        │
│ 前置分支均已完成，烟火持续12.4秒，达到10秒要求。          │
│                                                          │
│ 6/6 必要分支满足  ·  0 等待  ·  0 无法判断               │
│ [查看触发证据] [定位到00:52.5] [导出结果]                │
└──────────────────────────────────────────────────────────┘
```

#### 13.4.1 状态表达

状态必须同时使用文字、图标和颜色，不能只靠颜色：

| 状态 | 用户文案 | 视觉语义 | 首要动作 |
|---|---|---|---|
| `triggered/satisfied` | 已触发/已满足 | 成功色 + 对勾 | 查看触发证据 |
| `not_triggered/not_satisfied` | 未触发/未满足 | 中性或警示色 + 未满足图标 | 查看未满足条件 |
| `pending` | 等待中 | 信息色 + 进度图标 | 查看正在等待什么 |
| `not_evaluable` | 无法判断 | 警示色 + 问题图标 | 前往补充资源/查看原因 |
| `error` | 运行错误 | 错误色 + 错误图标 | 查看错误与重试 |
| 检测完成 | 检测完成 | 中性色/成功色 | 查看目标输出 |

“未触发”不默认使用错误红色，因为未发生事件可能是正常结果；只有运行错误使用错误色。安全任务若把“未满足”定义为风险，可由结果规格配置严重级别。

#### 13.4.2 不同任务的最终卡

- 事件任务：是否发生、触发时间、事件名称、关键原因。
- 检测任务：检测完成、发现目标数、满足业务条件数。
- 测量任务：实际值、要求、满足/不满足。
- 状态任务：当前状态或状态变化、主体和时间。
- 多阶段任务：完成阶段数、最终成功/失败/等待、当前阶段。

未触发时先展示最关键的未满足项，再展示已满足摘要：

```text
最终结果：未触发
主要原因：区域1逆行仅持续2.1秒，要求5秒。

未满足 2项：区域1逆行持续、区域5交通事故
已满足 3项：区域2拥堵、区域3未戴安全帽、全画面车辆数
[查看未满足分支]
```

无法判断时列出可行动原因：`区域1缺少参考方向`、`视频长度不足`、`模型来源不可用`，并提供“去02补充标注”或“检查媒体”的入口。

### 13.5 第二层：业务输出

业务输出严格按 03 的 `PresentationSpec.display_order` 动态生成，不再固定为技术类型标签。概览输出先以卡片网格展示，详情按需展开。

每项运行结果先归一化为统一类型，不把某个算子的原始 JSON 直接交给页面：

```text
BusinessOutputValue
├─ output_id / display_name
├─ semantic_type / value_shape
├─ value / unit
├─ status / reason
├─ source_ref / condition_snapshot
├─ grouping_key / time_scope
├─ entity_refs[] / evidence_refs[]
└─ data_quality / applicability
```

`BusinessOutputValue` 只保存机器可计算事实，不保存格式化字符串和卡片配置。`RunResultViewModel` 根据 PresentationSpec 产生 `formatted_value`。`status` 与 `applicability` 分离：适用但未命中仍是有效结果；输入能力不支持、资源缺失或媒体不足才是不可判断/不适用。

#### 13.5.1 输出卡类型

| 输出类型 | 默认可视化 | 必须显示 |
|---|---|---|
| 布尔/事件 | 状态卡 | 已发生/未发生/等待/无法判断、时间、主体 |
| 数量 | 大数字卡或分组条目 | 实际数量、单位、范围/类别、阈值结论 |
| 数值/统计 | 指标卡 + 阈值标尺 | 实际值、单位、比较条件、是否满足 |
| 持续时间 | 进度条/区间条 | 实际时长、要求时长、达标状态、有效区间 |
| 目标框/目标列表 | 数量摘要 + 缩略图/类别列表 | 业务标签、数量、来源；可在媒体中高亮 |
| 轨迹 | 轨迹摘要 + 时间范围 | 轨迹数、目标 ID、起止时间；可高亮轨迹 |
| 方向 | 参考箭头与实际箭头对比 | 同向/逆向、夹角或方向结论；技术余弦放详情 |
| 事件列表 | 事件卡列表/表格 | 名称、主体、开始/结束、持续和严重级别 |
| 时间点/时间段 | 时间轴标记 | 时间、区间、来源事件 |
| 阶段流程 | 紧凑时间线 | 已完成阶段、当前阶段、失败/等待阶段 |
| 统计表 | 可排序表格 | 行列含义、单位、空值说明 |
| 标注媒体 | 图片/视频预览卡 | 当前叠加层、证据标记、全屏查看 |

#### 13.5.2 卡片示例

```text
区域2车辆数量
8 辆
要求：> 6辆                    [满足]
统计时间：00:35.2
[查看车辆] [定位证据]

烟火持续时间
12.4 秒 / 要求 ≥10秒          [达标]
████████████████░░
有效区间：00:42.5–00:54.9
[查看时间段]

烟火目标
火焰2 · 烟雾1 · 爆炸1
[在视频中高亮] [查看目标列表]
```

#### 13.5.3 布局与密度

- 关键输出由用户在 03 标记“显示在概览”，排在业务输出区前部。
- 桌面端使用响应式 12 栅格：普通指标卡占 3–4 列，表格/媒体/时间线占 6–12 列。
- 移动或窄窗口单列排列，不使用可横向溢出的固定标签栏。
- 输出超过 8 项时，先显示关键输出，其余按“事件/数值/目标/时间”分组折叠，并提供搜索与筛选。
- 同一来源的“实际值 + 是否满足”可以在一张卡中呈现，但若用户在 03 明确要求两个独立结果，则分别保存并允许分别展示。
- 卡片空状态区分：`本次0条`、`未触发`、`等待中`、`无法判断`、`未配置此输出`。

#### 13.5.4 通用渲染器注册表

04 使用 `ResultRendererRegistry`，按结果语义选择展示，而不是为业务名写组件：

| 渲染器 | 兼容结果 | 默认用途 |
|---|---|---|
| `decision.card` | 最终判定、布尔、状态 | 主结论、是否发生、是否满足 |
| `metric.value` | 单个数量/数值 | 大数字、单位、上下文 |
| `metric.threshold` | 数值 + 比较条件 | 实际值、要求值、满足状态、区间 |
| `duration.progress` | 持续条件/事件时长 | 实际时长、要求时长、有效区间 |
| `entity.summary` | 目标/轨迹集合 | 数量、类别摘要、证据入口 |
| `entity.table` | 目标/轨迹集合明细 | 分页列表、属性、区域、时间 |
| `event.list` | 事件集合 | 事件名称、主体、区域、起止时间 |
| `timeline.pattern` | EventPattern/阶段集合 | 顺序、窗口、汇合、等待和失败 |
| `table.grouped` | 分组数量/统计 | 按区域、类别、分支或时间分组 |
| `media.annotated` | 带证据引用的任意结果 | 图片/视频叠加与定位 |
| `text.enum` | 枚举、方向、状态文本 | 业务化文本和图标 |
| `generic.summary` | 任意已知结构 | 安全降级摘要，不丢值和证据入口 |

每个渲染器注册以下契约：

```text
renderer_id
compatible_result_types
compatible_value_shapes
supported_media
required_fields
presentation_schema
overview/detail support
fallback_renderer
accessible_text_builder
renderer_version
```

选择顺序为：用户在 03 选择的兼容渲染器 → 该结果类型默认渲染器 → `generic.summary`。渲染失败不能导致结果消失；必须显示降级摘要并保留“查看原始值/证据”的入口。开发 JSON 只作为最后诊断，不是普通用户的降级页面。

#### 13.5.5 动态数量、分组与大结果集

- 未知区域、类别、分支和目标数量使用 `grouping_key` 动态重复卡片或生成表格，不为“区域1/区域2”预留固定槽位。
- 同一 ResultSpec 可以按区域、类别、分支或时间桶分组；分组项沿用同一渲染器和展示规格。
- 结果数量少时显示卡片，超过用户阈值时自动转为摘要 + 可搜索表格；语义不变。
- 目标、轨迹、事件和逐帧测量使用分页或虚拟化；首屏只加载概览和关键证据。
- 组合输出允许一张卡显示“实际值 + 要求 + 判断”，但持久层仍分别保存原值和判定，便于导出、追溯和重新展示。

#### 13.5.6 类型到可视化的通用映射

```text
标量 + 阈值       → 指标/阈值卡
目标集合          → 数量摘要 + 列表 + 目标框证据层
轨迹集合          → 轨迹摘要 + 轨迹线/方向证据层
事件集合          → 事件列表 + 时间点/时间段
持续条件          → 时长卡 + 有效区间
复杂编排          → 最终判定 + 阶段/汇合时间线
区域/方向资源     → 媒体区域/箭头叠加层
目标对/关联关系   → 关联表 + 框间连线或双框高亮
状态转变          → 前后状态摘要 + 转变时刻
```

例如红衣灰裤人员、逆行车辆、摔倒和交通事故不需要四套页面：它们分别复用目标集合、轨迹/方向、状态转变和事件集合的渲染器。复杂多区域任务只是把这些输出按 `display_order` 组合到同一结果页。

### 13.6 第三层：分支过程

分支区回答“为什么”。顶部先给出汇总：

```text
分支与证据                     4个满足 · 1个未满足 · 1个等待
[全部] [未满足优先] [等待] [无法判断]
```

默认排序：`无法判断 → 未满足 → 等待 → 已满足 → 已停用`，让用户先看到需要处理的问题；触发成功时可切换为按编排顺序。

每个分支卡默认只展示业务信息：

```text
✓ 区域2交通拥堵                                      已满足
  区域2车辆8辆，要求 >6辆；持续10.8秒，要求10秒。
  首次满足 00:24.4 · 证据目标8个
  [定位证据] [查看判定过程]
```

展开“判定过程”后显示条件树，不显示底层节点：

```text
✓ 区域2内车辆数量 = 8
✓ 8 > 6
✓ 条件连续满足10.8秒 ≥ 10秒
```

NOT/OR/AND 结构保留分组和缩进；失败条件直接标明实际值、要求值和原因。节点 ID、端口和原始模型输出不进入该视图。

### 13.7 复杂事件可视化

只有存在 `EventPattern` 时显示时间线；简单单分支任务不显示空时间线。

#### 13.7.1 顺序流程

```text
阶段1 前置条件         已完成 00:22.2
      │ 等待至少20秒，实际20.3秒
      ▼
阶段2 烟火爆炸         已发生 00:42.5
      │ 需持续10秒，实际12.4秒
      ▼
最终事件               已触发 00:52.5
```

#### 13.7.2 同时有效/多分支汇合

使用汇合视图，不伪装成顺序：各分支独立显示有效区间，在共同交集处标出触发时刻。窗口内完成模式显示统一时间窗和每个分支完成点。

#### 13.7.3 失败和等待

- 超时边使用警示样式并显示“超过最大间隔5秒”。
- 等待中的下一阶段显示剩余条件，不显示虚假预计完成时间。
- 缺失事件显示完整观察窗口，窗口尚未结束时状态为等待，而不是提前成功。
- 时间线必须有等价文本列表，不能只靠图形表达。

### 13.8 可视化证据浏览器

标注图片/视频属于第三层的核心证据；如果用户在 03 明确把标注媒体或目标框设为业务输出，则第二层同时展示一张摘要卡，点击进入这里。

```text
可视化证据
┌───────────────────────────────┬─────────────────────┐
│ 图片/视频                     │ 当前选中结果         │
│ 框、轨迹、区域、方向、事件标记 │ 分支、条件值、时间   │
│ 时间轴上的事件/阶段标记        │ 关联目标与证据       │
└───────────────────────────────┴─────────────────────┘

显示层：☑目标框 ☑业务标签 ☑轨迹 ☑区域 ☑方向 ☑事件
筛选：分支｜业务输出｜区域｜目标类别｜仅关键证据
```

联动规则：

- 点击最终结果的“查看触发证据”，跳到触发时刻并高亮参与分支。
- 点击数量卡的“查看车辆”，只高亮该输出实际统计的目标集合。
- 点击分支卡，媒体定位到首次满足或失败最明显的时间点。
- 点击事件时间线节点，媒体跳到对应时间，右侧显示事件证据。
- 视频时间轴显示事件、阶段完成、持续达标和中断标记；可使用“上一个/下一个证据”。
- 业务标签优先于用户标签，用户标签优先于模型原标签；不属于任何业务输出的目标保留模型标签。
- 框、轨迹和箭头使用稳定颜色，但同时显示文字/形状差异，避免只靠颜色区分。
- 目标太多时按当前输出/分支过滤，不能一次绘制全部造成不可读。

图片任务提供缩放、平移、框列表联动；视频任务提供播放、逐证据跳转、时间轴和全屏。证据为空时说明“本次没有命中证据”，不能留下空白播放器。

#### 13.8.1 通用证据层注册表

媒体叠加同样不按案例实现，使用 `EvidenceLayerRegistry`：

| 证据层 | 数据来源 | 可视化 |
|---|---|---|
| `boxes` | 目标/事件实体引用 | 框、业务标签、置信度（按需） |
| `tracks` | 轨迹引用 | 轨迹线、起止点、轨迹 ID |
| `regions` | SceneResource 区域 | 边界、名称、包含/排除样式 |
| `directions` | 参考方向与实际运动向量 | 箭头、同向/逆向结论 |
| `event_markers` | 事件/阶段时间 | 视频时间轴标记、关键帧 |
| `measurements` | 数值及阈值快照 | 框旁数值、区域统计、时长区间 |
| `relationships` | 主体与对象引用对 | 双框高亮、关联线、关系文本 |
| `state_transitions` | 状态前后证据 | 前后关键帧、转变时刻、主体 |

每层声明所需字段、支持媒体、默认样式、图例、点击命中规则、可访问文本和降级方式。证据层只消费稳定 `entity_refs/evidence_refs/resource_refs`，不能通过框标签或事件名称猜关联。

02 标注的区域和方向只在被当前输出/分支引用时默认显示；用户可在证据浏览器临时开关其他资源，但这不修改 03 的 ResultSpec。若 02 删除了已引用资源，03 必须先显示受影响输出并阻止发布，04 历史运行仍用该次运行快照正常回放。

### 13.9 证据明细与运行详情

普通用户看到的是业务化明细抽屉：

```text
分支证据
事件证据
目标与轨迹明细
数值与时间判定明细
区域与方向资源
媒体与模型调用
```

每项从业务输出或分支进入，并保留上下文。例如“烟火持续判定”展示首次满足、允许中断、实际中断、累计/连续时长和达标结论。

开发诊断只在开发模式显示：

```text
结构化原始结果
逐节点 Trace
原始模型响应
编译诊断
性能明细
运行产物目录
```

原有检测/轨迹/事件/数值/区域/方向 JSON 仍可在这里查看和复制，用于排障和兼容，但不再是主导航。

### 13.10 状态、加载与错误设计

- 未运行：显示任务摘要和“检查媒体与调用估算”，不展示空结果卡。
- 估算完成：显示预计帧数、调用数和风险，再允许运行。
- 运行中：保留上次结果但标记“正在生成新结果”，或明确清空；不能混淆新旧运行。
- 运行完成：先落盘 `FinalResult`，再渲染三层结果；局部证据加载失败不应抹掉最终结论。
- 运行错误：最终结果显示错误，保留已经成功生成的分支结果和可用证据。
- 刷新/加载历史运行：三层结构完整恢复，不依赖内存中的临时对象。

### 13.11 响应式与可访问性

- 结果结论使用文本、图标和颜色三重表达；色彩对比符合 WCAG AA。
- 键盘可依次访问结果卡、输出卡、分支卡、媒体控件和详情抽屉；焦点样式清晰。
- 所有图表、时间线、进度条和方向箭头提供可读文本等价内容。
- 视频控件有可访问名称；证据时间点可通过按钮跳转，不要求精确拖动进度条。
- 目标框颜色不作为唯一类别标识，始终带业务标签或图例。
- 大数字附带单位和上下文，不能只显示“8”。
- 窄屏时操作按钮换行，主要结论不被横向滚动隐藏。

### 13.12 前后端展示模型

后端在持久化 `RunResult` 基础上提供确定性展示投影，前端不自行猜测状态和证据关系：

```text
RunResultViewModel
├─ run_header
├─ final_result_card
├─ overview_output_cards[]
├─ remaining_output_groups[]
├─ branch_cards[]
├─ pattern_timeline
├─ evidence_player
│  ├─ media_ref
│  ├─ overlay_layers[]
│  ├─ timeline_markers[]
│  └─ evidence_index[]
├─ evidence_details[]
└─ runtime_details
```

每张卡必须携带稳定 `source_ref` 和 `evidence_refs`。前端通过引用完成“输出卡 → 分支 → 时间点 → 框/轨迹/数值”的联动，不能按显示名称或数组位置猜关联。

持久层与展示层分开：

```text
RunResult（事实，可重算展示）
├─ final_result
├─ branch_results[]
├─ business_output_values[]
├─ evidence_index
├─ scene_resource_snapshot
├─ result_spec_snapshot
├─ presentation_spec_snapshot
└─ package/version refs

RunResultViewModel（确定性展示投影，可缓存）
├─ renderer_id + renderer_version
├─ card props / table columns / timeline items
├─ interaction targets
└─ accessible text
```

历史结果必须携带运行时的 `ResultSpec`、`PresentationSpec`、场景资源和渲染器版本快照。默认按运行时快照复现；用户可以在不改事实的前提下临时套用新 PresentationSpec，导出时记录所用 `presentation_hash`。新前端可以迁移 ViewModel，但不能用当前技能的语义 ResultSpec 覆盖旧运行事实；迁移失败时使用兼容渲染器或 `generic.summary`。

建议增加：

```text
GET /api/runs/{id}/view
GET /api/runs/{id}/evidence?source_ref=...
GET /api/runs/{id}/media-overlays?branch_id=...&output_id=...
GET /api/result-renderers
GET /api/evidence-layers
```

大目标列表、逐帧证据和长时间线分页/虚拟化；首屏只请求最终结果和概览输出，证据详情按需加载。

`GET /api/result-renderers` 返回普通用户名称、适用结果、预览、可编辑展示参数和帮助说明；技术 ID 仅作为稳定值。03 与 04 必须读取同一注册表，避免审核时可选但运行时无法渲染。

### 13.13 04 验收矩阵

必须覆盖：

- 事件已触发、未触发、等待、无法判断、运行错误。
- 检测任务 0 个/多个目标。
- 数值满足/不满足和区间判断。
- 单分支、AND/OR/NOT 嵌套、多分支同时有效、窗口完成和顺序事件。
- 图片与视频；有框、无框、有轨迹、无轨迹。
- 1个输出、10个以上输出和大量目标/分支。
- 点击最终结果、输出卡、分支和时间线后，媒体定位及高亮正确。
- 刷新、历史运行重载和版本对比后，三层结果不丢失。
- 普通模式看不到原始 JSON/Trace 主导航；开发模式仍可查看完整技术数据。
- `本次0条`、`未触发`、`等待中`、`无法判断`、`未配置输出`语义严格区分。
- 桌面、窄窗口和键盘操作可完成主要结果阅读与证据定位。
- 自然语言明确要求的每项输出都生成独立 `ResultSpec`，03 可审核，04 可见，保存重载后不丢失。
- 动态增加或减少区域、类别、分支后，04 自动生成对应分组，不修改前端案例代码。
- 每个 ResultSpec 都能选择兼容渲染器；未知组合使用 `generic.summary`，不能白屏或只显示 JSON。
- 红衣灰裤人员、数量阈值、逆行、摔倒、事故、烟火持续和多阶段组合全部由公共渲染器与证据层完成，无案例名称/预置 ID 分支。
- 输出卡、表格、媒体叠加和导出使用同一业务值、单位、标签和证据引用，不出现相互矛盾的结果。

### 13.14 讨论案例的通用结果验收

以下只是通用结果系统的组合测试，不形成专用组件：

| 输入任务 | 01/03 生成或审核的输出 | 04 使用的公共展示 |
|---|---|---|
| 区域1红色上衣、灰色裤子人员；区域2人数 >2 | 最终告警、匹配人员、区域2实际人数、人数判断 | `decision.card` + `entity.summary` + `metric.threshold` + boxes/regions |
| 事故发生时其他分支均有效 | 最终告警、每分支状态、事故事件、持续结果、逆行轨迹 | `decision.card` + 分支卡 + `event.list` + `duration.progress` + tracks/directions |
| 逆行、拥堵、全画面车数区间、未戴安全帽、摔倒、事故，之后烟火持续 | 最终事件、各业务判断、区域2车数、车辆/烟火框、烟火实际时长及达标判断、阶段时间线 | 公共指标卡/事件列表/目标摘要/时长卡/时间线/证据层的组合 |
| 只识别并框出车辆 | 检测完成、车辆数量、车辆框 | `decision.card`（检测摘要）+ `entity.summary` + boxes；不生成空事件时间线 |
| 未知数量区域分别统计 | 按实际 SceneResource 分组的数量 | 一个分组 ResultSpec + 动态 `table.grouped` 或重复指标卡 |

每条验收至少覆盖：自然语言生成 ResultSpec → 02 资源绑定 → 03 修改输出和展示参数 → 编译运行 → 04 首屏结论 → 点击定位证据 → 保存重载 → 导出。还要验证删除/增加区域、把概览卡改为表格、修改业务标签、改变输出顺序后，无需修改结果页代码即可正确更新。

P01–P13 与历史案例采用同一流程建立结果 Golden：比较语义值、状态、来源、单位、证据引用和渲染器兼容性，不对像素位置做脆弱断言；关键截图仅用于浏览器视觉回归。

## 14. 媒体能力判定

### 14.1 流程

```text
LLM提取语义需求
→ 能力目录汇总媒体要求
→ 依赖闭包计算
→ 用户显式媒体要求校验
→ 编译器试编译各variant
→ 最终媒体能力结论
```

### 14.2 确定性规则

图片和视频均可：目标检测、颜色/装备/属性、单帧姿态、静态区域归属、单帧关联、单帧计数、可由单帧识别的火烟/事故/损伤等。

仅视频：跟踪、速度、运动方向、逆行、进入/离开/越线、停留、持续、状态转变、先后顺序、延迟、时间窗口、重复次数、同一目标连续判断。

有静态和动态两种语义时可生成双 variant，例如：

```text
image：当前存在倒地人员
video：同一人员从正常状态转为倒地
```

双 variant 表示同一技能可接受两种媒体入口，不表示一次运行同时处理图片和视频。运行前根据当前唯一媒体选择一个 variant；两个 variant 各自编译、校验和保存输出契约，不能在同一最终判定中跨媒体引用。

### 14.3 冲突处理

用户要求图片但规则包含逆行时，不得静默降级：

```text
当前规则需要视频，因为包含轨迹和方向。
可选：改用视频；或明确接受单帧朝向异常的降级语义。
```

## 15. 自然语言生成新流程

```text
原文
→ 结构化语义草稿
→ 分支切分
→ 条件树生成
→ 时间模式生成
→ 输出要求生成
→ 场景资源要求生成
→ 媒体能力建议
→ 确定性归一化与校验
→ BusinessRuleDocument
→ 03用户审核
→ 编译RuleGraph
```

LLM负责理解业务，不负责生成节点 ID 和端口。

LLM结构化输出必须包含：

- 原文片段来源。
- 业务事件定义（存在时）。
- 分支和条件。
- 条件参数及是否明确。
- 分支持续和身份范围。
- 事件顺序与不确定时间语义。
- 最终判定类型和来源。
- 用户要求的输出。
- 触发策略（存在告警/通知意图时）。
- 场景资源需求。
- 媒体能力建议和原因。

确定性层负责：

- Schema 校验和容错归一化。
- `区域N` 等逻辑资源规范化。
- 数量比较修复和缺值登记。
- 同主体属性绑定。
- 类型检查。
- 媒体能力最终裁决。
- 技术原子补全。
- 输出和证据契约编译。

LLM 返回空文本、Markdown 或字段错层时应进入结构化修复/重试；最终错误必须是业务可读错误，不暴露 `Expecting value` 等 JSON 解析异常。

### 15.1 两种通用输入方式

01 创建页保留一个“描述任务”输入框，同时支持两种写法，不要求用户选择不同模式：

#### 方式一：直接描述任务

用户可以像正常说话一样描述，LLM 自动拆分业务事件、条件分支、编排、最终判定和输出：

```text
区域1有穿红色衣服、灰色裤子的人，并且区域2人的数量大于2，则发出告警。
```

#### 方式二：按配置结构具体描述

输入框提供“插入描述模板”，用户可填写任意部分，顺序不限，未填写部分由系统根据任务补全或保持省略：

```text
业务事件：区域3发生交通事故；区域4车辆逆行持续3秒。

条件分支：
- 分支A：区域1存在穿红色上衣、灰色裤子的同一人员。
- 分支B：区域2人员数量大于2，持续10秒。
- 分支C：区域3交通事故发生。
- 分支D：区域4车辆逆行持续3秒。

复杂事件编排：分支C发生时，A、B、D都处于有效状态。

最终判定：四个条件满足时判定“多区域联合事件”发生。

业务输出：区域2实际人数、逆行车辆框和持续时间、事故框、各分支状态、最终结论。

触发策略：首次满足时告警，冷却30秒，保存事件片段。
```

支持的引导标题包括但不限于：

```text
任务/目标
业务事件
条件分支/判断条件
复杂事件编排/时间关系
最终判定/成功条件
业务输出/希望看到的结果
触发策略/告警方式
媒体要求
场景资源
```

这不是固定表单语法，也不要求完整填写。用户可以只写：

```text
条件分支：区域1车辆数大于5并持续10秒。
业务输出：实际车辆数、是否满足、车辆框。
```

系统会生成单分支规则和默认最终判定，不会因为缺少“业务事件”“复杂事件编排”“触发策略”而报错。

用户也可以在同一行用分号描述，例如：`业务事件：车辆拥堵；条件分支：区域1车辆数大于5；最终判定：持续10秒则拥堵；业务输出：车辆数、拥堵结论和车辆框。`

### 15.1.1 统一解析和优先级

```text
原始文本
→ 轻量标题分段（只保留段落边界和原文，不解释业务）
→ LLM结合完整原文与分段提示生成业务草稿
→ 确定性归一化、引用解析和冲突校验
→ 同一个BusinessRuleDocument
```

- 两种写法共用同一能力目录、Schema、编译器、03 编辑器和运行时，不维护两套专用逻辑。
- 标题只是帮助 LLM 定位用户意图，不限制事件名称、条件类型、分支数量和组合方式。
- 用户明确写出的“最终判定、输出、编排、触发策略”优先于系统推断；系统不得用默认值覆盖原文明确信息。
- 明确段落之间冲突时生成待确认项并展示冲突原文，例如“最终判定要求 AND，但复杂编排写 OR”。
- 引导段落中使用 `XXX/XX` 或缺少阈值时仍生成可编辑草稿，并把缺值放入待确认项。
- 未识别标题和自由补充文字不能丢弃，继续作为完整原文交给 LLM，并记录来源片段。
- 结构化描述不能绕过通用校验，也不能直接提供原子 ID、端口或 RuleGraph JSON。
- 自由描述与等价的结构化描述应生成语义等价的规范化文档和稳定拓扑。

### 15.2 LLM 自然语言生成必须独立测试

自然语言生成不是只做人工演示，必须成为正式回归对象。测试分四层：

1. **离线协议测试**：使用 Fake LLM 固定响应，覆盖正常 JSON、空响应、Markdown 包裹、字段错层、额外字段、截断、超时和修复重试，不依赖外部服务。
2. **语义 Golden 测试**：输入真实中文自然语言，断言归一化后的业务语义，不断言 LLM 原始措辞和字段顺序。
3. **在线模型冒烟测试**：在发布前或定时任务中调用真实 LLM，记录模型、提示词版本、Schema 版本、响应哈希和归一化结果；同一关键用例至少重复三次。
4. **生成后端到端测试**：自然语言生成业务文档后，继续完成参数、编译、媒体估算和真实媒体运行，验证最终结果与业务输出，而不是只验证“生成成功”。

每条自然语言用例至少断言：

```text
目标与模型输入源
业务分支数量和名称语义
条件树结构
同主体/同轨迹/同目标对身份范围
阈值、持续和时间窗口
待确认项及原文片段
场景资源需求
图片/视频/双媒体结论及理由
复杂事件编排模式
最终判定
业务输出
编译Recipe
是否可以运行
```

自然语言测试不得依赖“某次 LLM 恰好输出指定节点 ID”。语义相同的改写应得到等价的规范化业务文档和稳定语义哈希。

### 15.3 LLM 测试覆盖集合

Golden Set 至少包含：

- P01–P13 对应的自然语言表达及同义改写。
- 当前历史自然语言案例。
- 本文三个多区域/复杂事件案例。
- 每个关键语义同时提供自由描述版、标题引导版和单行分号版，三者做语义等价比较。
- 只填写部分引导段落、段落顺序变化、同义标题、未知标题和段落冲突。
- 简单检测、属性、关系、计数、范围、排除、状态和事件。
- AND、OR、NOT、N-of-M 和嵌套条件组。
- 独立持续、同时有效、窗口完成、多阶段顺序、缺失和重复。
- 图片专用、视频专用、双媒体和媒体冲突。
- `XX/XXX`、缺数量、缺持续、未知区域数量、歧义时间关系。
- 空响应、非法 JSON、字段错层、重复条件和互相矛盾的 LLM 输出。

发布门槛：

```text
离线协议用例：100%通过
Golden结构解析：100%成功
必要语义覆盖：不得静默丢失
媒体能力判定：100%符合确定性规则
缺失参数：100%进入待确认，不得编造
待确认项补齐后的编译通过率：100%
错误信息：不得暴露原始JSON解析异常
```

## 16. 三类验收示例

### 16.1 示例一：多区域属性与计数

原文：

> 区域1有穿红色衣服、灰色裤子的人，区域2中人的数量大于2，则发出事件告警。

生成：

```text
分支A 区域1指定着装人员
  人员
  AND 上衣颜色=红色
  AND 裤子颜色=灰色
  AND 属性属于同一人员
  AND 位于区域1
  AND 数量>=1

分支B 区域2人员数量
  人员
  AND 位于区域2
  AND 数量>2

最终：A AND B，同一帧同时满足
```

标签：

```text
分支A框：红色上衣、灰色裤子人员
分支B框：人员
其他目标：保留输入模型标签
事件/告警：用户填写的事件名称
```

### 16.2 示例二：事故触发时多条件有效

原文：

> 区域3发生交通事故时，区域1目标条件、区域2人数持续条件、区域3逆行持续条件都处于有效状态，则告警。

生成：

```text
A 区域1目标条件
B 区域2人数条件 + 分支独立持续
C 区域3交通事故（触发分支）
D 区域3车辆逆行 + 同一车辆持续

编排：C发生时，A、B、D均处于有效状态
```

事故为瞬时事件，需声明触发时间和可选有效期；B 和 D 各自维护持续状态。

### 16.3 示例三：多阶段复杂事件

原文包含区域1逆行、区域2拥堵、全画面车辆数区间、区域3未戴安全帽、区域4摔倒、区域5事故，之后延迟出现烟火爆炸并持续。

媒体结论：仅视频。

分支：

```text
A 区域1逆行：车辆→轨迹→方向→逆向→同一车辆持续T1
B 区域2拥堵：车辆→区域2→数量>N2→拥堵事件
C 全画面数量：Nmin<count(vehicle)<Nmax
D 区域3未戴安全帽：人员与安全帽同主体关联→缺失
E 区域4摔倒：正常状态→倒地状态；不支持时显示降级选择
F 区域5事故：事故事件+发生时间+证据框
G 烟火爆炸：火/烟/爆炸目标或事件+持续T3
```

编排：

```text
Stage1 = join(A,B,C,D,E,F, mode=待确认)
Stage2 = G after Stage1，延迟语义待确认
Final = Stage2持续T3后触发
```

待确认：所有 `XX/XXX`；Stage1 是同时有效还是窗口完成；“XX秒后”是至少、以内、约等于或区间；“烟火爆炸”是火烟爆炸还是烟花；摔倒是状态还是动作。

业务输出：区域2车辆数、拥堵判断、逆行判断、事故判断、烟火框、车辆框、烟火实际持续时间、持续是否达标、最终事件。

## 17. P01–P13 预置适配

每个预置新增版本化复现 fixture。原有已验证 RuleGraph 继续作为效果基线和执行实现，但 03 不直接把节点图当作用户编辑源：系统按媒体投影为一个主业务分支，把检测、属性、关联、计数比较、轨迹、方向和持续等已注册能力显示为“原有流程组成步骤”。用户可以用业务名称修改可逆关键参数，也可以围绕整个导入判定继续新增通用条件和 AND/OR/NOT 组合；无法安全逆向拆解的结构不得伪装成可任意删除的条件树节点。

| 预置 | 业务模板 | 关键输出 |
|---|---|---|
| P01 火烟 | 火/烟目标或事件，可选持续 | 火烟框、事件、持续 |
| P02 交通事故 | 事故事件 | 是否发生、事故框、时间 |
| P03 特殊车辆 | 多目标类别/属性 | 分类目标框、数量 |
| P04 高速拥堵 | 分区域车辆数、区域速度、持续 | 数量、速度、拥堵事件 |
| P05 高速逆行 | 轨迹、区域方向、逆向、持续 | 逆行车辆、方向、持续 |
| P06 人员停留 | 人员轨迹、区域、停留 | 停留事件、人员框、时长 |
| P07 违停 | 车辆轨迹、静止、区域、持续 | 违停事件、车辆、时长 |
| P08 道路遗撒 | 道路异物检测 | 异物框、事件 |
| P09 未戴安全帽 | 同主体装备缺失 | 人员框、缺失装备事件 |
| P10 未系安全绳 | 同主体装备缺失 | 人员框、缺失装备事件 |
| P11 服务区垃圾 | 垃圾目标、区域 | 垃圾框、事件 |
| P12 人员摔倒 | 倒地状态或状态转变、持续 | 摔倒事件、人员框、状态证据 |
| P13 桥梁损伤 | 损伤目标、部位/区域 | 损伤框、事件 |

每个预置 fixture 必须包含：

```text
SkillEditorDocument@3.x 业务投影
媒体能力与理由
默认场景资源
默认参数
ResultSpec
预期编译原子/Recipe
正例、反例、混淆例断言
```

加载预置后，03 必须显示和自然语言生成相同的业务卡片，并允许用户修改后另存版本。

### 17.1 预置效果必须可复现

现有 P01–P13 效果尚可，实施前先冻结当前有效基线，新方案不得因为编辑器重构而降低已有案例效果。每个预置建立 `PresetReproductionManifest`：

```text
preset_id
业务语义摘要
当前有效RuleGraph/SkillPackage引用
SkillEditorDocument 业务语义摘要或可验证投影
媒体能力
默认媒体与指纹
默认区域/方向资源
关键参数和单位
预期Recipe与关键原子
预期业务输出
正例/反例/混淆例
允许的数值与框位置容差
当前基线结果
```

复现要求：

1. 预置加载使用版本化 fixture，不调用 LLM，保证相同版本可重复加载。
2. 相同 fixture 必须产生稳定业务语义哈希和稳定编译拓扑；运行 ID、临时路径等非语义字段除外。
3. 使用当前默认媒体复跑，关键事件结论、目标类别、数值和证据类型不得退化。
4. 对视觉模型非确定性结果采用明确容差和语义断言，不以完整 JSON 字节相等作为标准。
5. 每个预置至少有一个正例；有现成负例和混淆例的必须全部保留。
6. 预置失败时报告“业务文档、编译、视觉结果、事件判定、输出投影”中的具体失败层级。

当前首批落地的 `tests/fixtures/v3/preset_reproduction_manifest.json` 同时保存每个预置的自由描述、按“条件分支/最终判定/业务输出”组织的引导描述、媒体能力和应在 03 可见的通用能力。加载与回归不按 `preset_id` 进入专用编译分支：统一经过 `build_editor_document → BusinessRuleEditor.prepare → EditorService.apply`。检测类图片流程的最终判定必须在编译期显式归约为“目标集合数量 > 0”，不能由 04 渲染器根据框数量临时猜测。

### 17.2 预置只作为通用方法参考

从效果较好的预置中提取：

- 通用目标 grounding 方法。
- 同主体装备缺失 Recipe。
- 分区域数量和速度 Recipe。
- 轨迹方向与逆行 Recipe。
- 停留、静止和持续 Recipe。
- 摔倒状态转变 Recipe。
- 事件证据和结果投影方法。
- 默认参数建议及其适用条件。

这些方法进入能力目录或通用 Recipe，不得在自然语言编译器中增加 `if preset_id == Pxx` 式业务分支。预置可以提供经过验证的默认值，但自然语言生成的新技能必须能通过同一能力组合复用这些方法。

### 17.3 新增案例必须可实现

新增案例不能只出设计稿。每个新案例进入 `NewCaseAcceptanceManifest`，完成定义为：

```text
自然语言可生成
03可完全编辑
不确定项可人工补齐
媒体能力判断正确
02所需资源可配置
只使用通用能力/Recipe组合
能够编译
能够估算
至少有一个真实或受控媒体正例
至少有一个负例或边界例
最终结果、业务输出和证据完整
保存后可再次加载复现
```

如果案例缺少能力，应先抽象出可复用的 `BusinessCapability + Recipe + ResultContract`，再实现案例；不得新增仅服务单个案例的隐藏专用节点或页面分支。

## 18. 历史技能迁移与回归

旧 UI 和旧编辑数据不继续双向兼容，但提供一次性导入器：

```text
旧SkillPackage/旧SkillEditorDocument
→ 识别已知原子拓扑和Recipe
→ 投影为BusinessRuleDocument
→ 编译新RuleGraph
→ 对比旧结果契约
```

迁移等级：

```text
full              可完整编辑
needs_review      已转换但有待确认项
read_only_legacy  无法安全投影，仅保留只读
failed            迁移失败并输出报告
```

历史回归集合至少覆盖：

- 颜色、反光衣、上衣裤子同主体。
- 安全帽、安全绳缺失。
- 多类别、排除和去重。
- 数量、区域、独立多区域。
- 逆行、拥堵、停留、违停。
- 摔倒状态与状态转变。
- 火烟、事故、道路异物、垃圾、桥梁损伤。
- 持续、顺序、同时有效、窗口完成、缺失、重复。
- 框标签、事件名称、数值结果和证据投影。

## 19. 后端模块与接口

建议新增：

```text
core/editor_migrations.py
core/business_capabilities.py
core/business_rule_generation.py
core/business_rule_normalizer.py
core/media_capability_resolver.py
core/business_rule_validator.py
core/business_rule_compiler.py
core/business_result_schema.py
core/business_result_projector.py
core/runtime_values.py
core/evidence_index.py
core/run_result_view.py
core/result_presentation_schema.py
core/result_renderer_registry.py
core/evidence_layer_registry.py
core/preset_business_rules.py
core/legacy_business_rule_importer.py
ui/event_rule_editor.py
ui/run_results.py
ui/result_renderers.py
ui/result_evidence_player.py
```

保留并复用：`core/registry.py`、`core/recipes.py`、operators 和媒体资产。`core/editor_schema.py` 原位演进；`core/context.py`、`core/executor.py`、`core/runtime.py` 和运行存储升级输出契约，但不重写现有视觉算子算法。

建议接口：

```text
GET  /api/business-capabilities
GET  /api/operator-assets
GET  /api/operator-assets/{operator_id}
GET  /api/parameter-presentations/{capability_id}
GET  /api/business-rules/current-package
GET  /api/business-rules/current-package/diff
POST /api/business-rules/generate
POST /api/business-rules/validate
POST /api/business-rules/compile
POST /api/business-rules/estimate
POST /api/scene-profiles
GET  /api/result-renderers
GET  /api/evidence-layers
POST /api/runs
GET  /api/runs/{id}/results
GET  /api/runs/{id}/view
GET  /api/runs/{id}/evidence
GET  /api/runs/{id}/media-overlays
POST /api/presets/{id}/load
POST /api/history/{id}/migrate
```

Gradio 当前可先通过控制器方法实现同样边界，后续再抽 HTTP API；数据模型和服务边界不能绑定 Gradio 组件。

## 20. 编译流程

```text
SkillEditorDocument@3.x（产品名 BusinessRuleDocument）
→ 校验条件树与引用
→ 解析模型输入源
→ 编译各分支RuleGraph片段
→ 自动插入轨迹、区域、归约和类型转换
→ 编译分支持续与有效期
→ 编译EventPattern
→ 编译最终判定与触发
→ 编译语义ResultSpec和证据投影
→ 独立校验PresentationSpec兼容性
→ 可达性清理
→ SkillPackage/RuleGraph严格校验
```

编译器必须保持：

- 稳定 ID，可重复编译。
- 同一业务文档得到稳定语义哈希。
- 不修改业务文档本身。
- 每个业务条件可追踪到原子节点。
- 每个结果可追踪到分支或测量来源。
- 用户修改一项参数只影响对应业务路径。

## 21. 校验规则

### 21.1 参数

- 必填参数非空。
- 阈值单位明确。
- 数量下限小于上限。
- 持续和窗口大于零。
- IoU、比例、余弦等在合法范围。
- 延迟最小值不大于最大值。

### 21.2 类型

- 方向和速度必须消费轨迹或可计算运动的输入。
- 数量必须消费对象/轨迹集合。
- 持续必须消费条件或事件。
- 同主体属性必须有主体身份。
- 分支引用必须输出兼容类型。

### 21.3 资源

- 一次运行只能绑定一个媒体资产和一个 variant；跨媒体、跨摄像头引用在 V3 首期直接报不支持。
- 运行前必须完成必需区域和方向。
- 资源数量不提前写死，按 cardinality 校验。
- 一个区域可以被多个分支复用。
- 删除资源时列出受影响条件。

### 21.4 时序

- 无循环依赖。
- 顺序边完整。
- 瞬时事件的联合语义明确。
- 同一目标/目标对/区域/全局身份范围明确。
- 时间窗口足以覆盖各段持续和延迟。

### 21.5 结果

- 最终结果必须存在。
- 输出来源存在且类型兼容。
- 数值结果来自测量源。
- 目标框来自真实对象集合。
- 事件名称、告警名称和框标签隔离。
- 适用但零结果显示“本次0条”，不可写“不适用”。
- 每个 ResultSpec 必须具有确定的 `semantic_type/value_shape/projection/source_ref`，不能依赖显示名称补语义。
- PresentationSpec 只能选择该语义结果注册的兼容渲染器；展示校验失败不改变业务结果事实。
- 每个 BusinessOutputValue 必须存在 RuntimeValueEnvelope 来源链；缺失证据时明确标记，不能静默挂接其他结果的框。

## 22. 测试与回归矩阵

### 22.1 单元测试

- 每个 `BusinessCapability` 的参数、输入、输出、媒体要求和编译 Recipe。
- `ResolvableValue`、待确认、类型和范围校验。
- 分支结果、最终结果、空结果策略。
- 标签隔离和证据投影。
- `RuntimeValueEnvelope` 在筛选、关联、归约、时序和事件转换后的来源、身份、时间与证据引用传播。
- ResultSpec 语义校验和 PresentationSpec 兼容校验分离；纯展示修改不改变 semantic/compile/package hash。
- `SkillEditorDocument@3.0 → 3.1 → 3.2` 迁移幂等，保存重载不形成第二份业务文档。
- 六个事件规则区域的显示条件、默认生成和省略行为。
- 每种最终判定类型、输出类型和触发策略的 Schema 与互斥校验。
- 所有可编辑参数均有完整 `ParameterPresentation`，业务覆盖优先级正确。
- 百分比、角度、秒数、画面比例与底层技术值的双向转换无损且边界正确。
- 帧数参数以“帧”显示、保存和重载，不被隐式换算为秒。
- 面向用户的校验错误不泄露技术字段名、Pydantic 路径或原始 JSON 错误。

### 22.2 条件树测试

- AND、OR、NOT、N-of-M。
- AND、OR 嵌套、组级 NOT、叶子 NOT，以及逐帧 NOT 与时间窗未发生的区分。
- 嵌套条件组。
- 同主体属性。
- 全画面/区域/区域集合。
- 单阈值和区间。
- 跨分支引用。

### 22.3 时序测试

- 独立持续。
- 同一轨迹持续。
- 同一目标对持续。
- 同时有效与窗口完成差异。
- 多阶段独立时间窗。
- before/after/during/contains/overlaps/until。
- absence、repeat、冷却和并行实例。
- 第 10.4 节状态机的区间边界相等、窗口未关闭、媒体提前结束、采样容差、消费、重置和多身份隔离。

### 22.4 自然语言生成测试

建立四套数据：

```text
tests/business_rule_nl_protocol_cases.json
tests/business_rule_nl_golden.json
tests/business_rule_nl_guided_equivalence.json
tests/business_rule_nl_online_smoke.json
```

协议测试固定 LLM 响应；Golden 测试固定输入与规范化语义断言；在线冒烟只在明确配置真实模型时运行。每条输入固定断言：分支数、条件树、参数来源、待确认项、媒体能力、场景资源、编排模式、结果规格、编译 Recipe 和生成后可运行状态。

同时断言可选区域不能过度生成：简单框选任务不生成复杂编排和告警策略；多分支同时任务生成 `all_active`；顺序/窗口/缺失/重复语义选择对应 EventPattern；用户明确要求的数量、框、事件、时长等均生成独立业务输出。

自然语言测试必须把同一任务分别写成自由描述、标题引导描述和单行分号描述，断言规范化后的业务事件、AND/OR/NOT 条件树、分支、最终判定、业务输出、触发策略和语义哈希等价。显式段落与推断冲突时必须产生待确认项，不能静默选择一方。

同一语义至少包含一种同义改写；关键复杂用例在线重复三次，按规范化语义等价判定稳定性。

### 22.5 P01–P13

建立 `tests/preset_reproduction_manifest.json`。每个预置验证：固定 fixture 加载、稳定语义哈希、业务卡片、媒体、默认资源、编译拓扑、估算、正例、反例、混淆例、业务输出、证据和标注媒体，并与实施前冻结基线比较。

### 22.6 新增案例验收

建立 `tests/new_case_acceptance.json`。每个新增案例必须通过“自然语言生成 → 03编辑 → 编译 → 运行 → 最终结果 → 保存重载”的完整链路；同时检查没有新增案例专用 UI 分支或按案例 ID 硬编码的编译逻辑。

### 22.7 历史案例

使用现有 `tests/historical_*.json` 与 `data/historical_runs_v2` 建立迁移清单，比较：语义、目标数量、事件数量、关键标签、关键测量、正负结论和证据引用。视觉模型有非确定性时使用容差和语义断言，不比较无意义的完整 JSON 字节相等。

### 22.8 浏览器 E2E

在 6131 页面覆盖：

```text
自然语言生成
→ 媒体能力结论
→ 上传媒体
→ 02标注
→ 03修改条件/时序/输出
→ 校验
→ 调用估算
→ 运行
→ 最终结果
→ 业务输出
→ 分支过程
→ 证据详情
→ 保存版本
```

并覆盖：

- 03 的每类条件均可新增、修改、复制、删除和重新组合。
- 条件组选择器明确显示“全部满足（AND）”“任一满足（OR）”“条件取反（NOT）”，摘要表达式与条件树一致。
- 03 修改业务参数或调优参数后，局部校验、编译状态和 05 当前包同步刷新。
- 05 按类别完整显示注册原子，数量与后端注册表一致，并可反查当前技能使用处。
- 05 展示的 Effective SkillPackage 与 04 实际运行包哈希一致，JSON 默认只读。
- 原 `Operator Registry（高级参考）` 不再出现，现有保存、加载、删除、导入和导出功能仍可用。
- 简单检测只展开必要区域；多分支时序任务自动展开复杂编排；纯检测任务不出现告警设置。
- 最终判定始终唯一且存在，用户原文要求的每个业务结果都能在业务输出中独立配置和查看。
- 03 页面标签中不出现 `iou_threshold`、`gap_tolerance_seconds` 等内部字段，字段下有简短说明且 `?` 可打开完整帮助。
- 05 每个有参/无参原子都可打开详情，五个详情页签内容完整；从“当前使用”可定位到 03 对应条件。
- 参数帮助抽屉支持键盘操作、关闭后焦点返回，且 03 与 05 的说明内容来自同一 Schema。
- 01 同一个输入框可处理自由任务描述、标题引导描述和单行分号描述；三种等价输入得到等价业务配置。
- 04 首屏先显示最终结果，再显示业务输出；普通用户无需打开 JSON 即可判断事件和数值结论。
- 最终结果、业务输出、分支和复杂时间线均可联动到正确媒体时间点、目标框、轨迹或数值证据。
- 04 的已触发、未触发、等待、无法判断、错误、0条检测和历史重载状态均有独立可读界面。
- 每次运行只选择一个图片或视频 variant；动态多区域可用，跨媒体引用和多摄像头配置在 V3 首期被明确拒绝。
- 修改 PresentationSpec 后历史运行只重建 ViewModel，不重新调用模型；修改 ResultSpec 来源或投影后正确要求重新编译/运行。

## 23. 实施阶段

每个阶段都必须交付一条可运行、可保存、可回归的纵向链路，不能先做完所有 Schema 和页面后才第一次真实运行。

### Phase 0：架构决策与冻结基线

- 固化本方案第 2、5、10.4、11.2 和 12.5 节为 ADR：单媒体边界、唯一业务文档、时序语义、结果语义/展示分层、运行结果信封。
- 动态收集当前测试数量和注册原子数量，不在完成标准中硬编码容易过期的数字。
- 保存 P01–P13、历史 Golden、关键浏览器流程、默认媒体指纹、当前输出和允许容差。
- 保存当前自然语言成功/失败案例和原始 LLM 异常类型。
- 建立 V3 feature flag 和回滚开关；旧路径可运行，新 UI 只写唯一新文档，不做双向同步。

验收：五份 ADR 评审通过；当前基线可一键重复执行；任一失败可定位到固定产物。

### Phase 1：唯一文档、运行信封与迁移骨架

- 在现有 `SkillEditorDocument@3.x` 上增加条件树、最终判定、语义 ResultSpec、PresentationSpec 和明确版本迁移，不创建平行根模型。
- 实现 `RuntimeValueEnvelope`、`EvidenceRecord`、EvidenceIndex 和稳定业务来源绑定。
- 修改 `ExecutionResult`、`core/runtime.py` 和 `RunStore`；为旧算子提供 `LegacyOutputEnvelopeAdapter`。
- 建立 `semantic_hash/compile_hash/package_hash/presentation_hash` 四类哈希及失效规则。
- 建立最小确定性编译骨架和类型化 `source_ref` 校验。

验收：旧 `SkillEditorDocument@3.0` 可幂等迁移；手工构造的最小文档能编译运行；每个结果都能追踪到节点、业务来源和证据；改变纯展示配置不重新运行。

### Phase 2：图片纵向切片

固定首个切片为“区域1红色上衣、灰色裤子人员 + 区域2人数大于2”：

- 02 支持在一张图片上动态绘制区域并绑定资源。
- 03 先实现目标、同主体属性、区域、数量、AND、最终判定和业务输出的 Schema 表单。
- 编译器生成现有目标/属性/区域/计数原子组合。
- 04 展示最终告警、匹配人员、区域2实际人数、阈值结论和正确框证据。
- 使用手工 fixture 驱动，不依赖 LLM。

验收：正例、人数不足、属性跨人、区域外目标、0目标、资源缺失全部正确；保存重载后结果和证据一致。

### Phase 3：视频纵向切片

固定第二个切片为“指定区域车辆逆行并持续 N 秒”：

- 增加跟踪、参考方向、最小位移、连续持续和同一轨迹身份。
- 运行时保留轨迹、方向、时间区间、持续实际值和中断证据。
- 04 支持轨迹/方向叠加、持续卡和视频证据跳转。
- 验证图片媒体冲突会被确定性拒绝，不静默降级。

验收：逆行、正常行驶、静止抖动、短轨迹、短暂中断、不同车辆拼接、持续不足和视频结束边界全部通过。

### Phase 4：复杂时序纵向切片

固定第三个切片为“事故发生时其他分支有效，之后规定窗口内发生烟火并持续 N 秒”：

- 实现第 10.4 节状态机、时间锚点、关联键、并行实例、消费、超时和重置。
- 先支持 `all_active`、触发时检查、sequence、窗口、persist；随后扩展 absence/repeat/contains/overlaps/until。
- 03 提供按模式收敛的时序表单；04 提供分支状态、汇合/顺序时间线和参与成功路径的证据。
- 使用受控事件流完成时序测试，再接视觉模型输出。

验收：边界相等、抽帧误差、窗口未结束、媒体提前结束、多身份并行、事件消费和保存重放语义确定且一致。

### Phase 5：平台化扩展 03、04 与能力目录

- 从前三个切片提炼通用 `BusinessCapabilityDefinition`、Recipe、ParameterPresentation、ResultContract 和 EvidenceContract。
- 扩展全部业务条件类别、嵌套 AND/OR/NOT/N-of-M、独立时间约束、输出和触发 UI。
- 实现 `ResultRendererRegistry`、`EvidenceLayerRegistry`、`generic.summary` 和 04 三层结果页。
- 03 只显示业务参数和兼容展示选项；05 动态展示全部当前注册原子，数量来自注册表。
- 删除用户侧高级原子编排 UI，但保留开发诊断只读能力。

验收：新增一个只使用现有能力的新案例时，无需修改 03/04 页面代码；未知展示组合能安全降级；用户无需节点知识即可配置三个切片。

### Phase 6：自然语言生成

- LLM 只生成受限业务意图草稿，经确定性层进入现有 `SkillEditorDocument@3.x`。
- 同一输入框支持自由描述、标题引导描述和单行分号描述。
- 加入结构化重试、归一化、待确认、确定性媒体裁决和能力版本锁定。
- 建立离线协议、Golden、在线冒烟和生成后真实运行四层测试。

验收：缺失 `XX` 不报 JSON 错；产生明确待确认项；三种等价写法生成等价语义；图片、视频和复杂切片均可由自然语言生成后运行。

### Phase 7：预置、历史迁移与影子对比

- 为 P01–P13 建立版本化业务 fixture，加载预置不调用 LLM。
- 把当前有效方法提炼为公共能力和 Recipe；禁止按预置 ID 编译。
- 执行旧格式单向迁移，输出 `full/needs_review/read_only_legacy/failed` 报告。
- 对同一媒体执行新旧结果影子对比，但不重复发送告警或产生外部副作用。
- 跑完正例、反例、混淆例、历史 Golden 和浏览器 E2E。

验收：P01–P13 关键效果不低于冻结基线；历史迁移无静默语义变化；所有差异可以定位到语义、编译、视觉、时序、结果或展示层。

### Phase 8：正式切换与 05 资产完善

- 只有发布门禁通过后，才把新方案设为唯一入口；旧数据保持只读和可回滚，不立即删除运行能力。
- 05 完整展示当前加载版本、业务能力、Recipe、执行原子、参数说明、版本差异和只读 Effective JSON。
- 保留保存、加载、删除、导入、导出和版本记录，并校验 05 包哈希与 04 实际运行包一致。
- 稳定观察期结束后再移除旧事件编辑代码和兼容适配器。

验收：新方案成为默认且唯一写入口；回滚开关验证有效；当前运行版本可审计；不存在第二套可编辑配置或静默双写。

## 24. 建议代码改动清单

新增：

```text
core/editor_migrations.py
core/business_capabilities.py
core/business_rule_generation.py
core/business_rule_normalizer.py
core/media_capability_resolver.py
core/business_rule_validator.py
core/business_rule_compiler.py
core/business_result_schema.py
core/business_result_projector.py
core/runtime_values.py
core/evidence_index.py
core/run_result_view.py
core/result_presentation_schema.py
core/result_renderer_registry.py
core/evidence_layer_registry.py
core/preset_business_rules.py
core/legacy_business_rule_importer.py
ui/event_rule_editor.py
ui/run_results.py
ui/result_renderers.py
ui/result_evidence_player.py
ui/skill_assets.py
core/operator_asset_catalog.py
core/parameter_presentations.py
core/effective_package_view.py
tests/test_editor_schema_v3.py
tests/test_editor_migrations.py
tests/test_business_capabilities.py
tests/test_business_rule_compiler.py
tests/test_business_rule_generation.py
tests/test_media_capability_resolver.py
tests/test_business_results.py
tests/test_runtime_value_envelope.py
tests/test_evidence_index.py
tests/test_temporal_state_machine.py
tests/test_run_result_view.py
tests/test_result_spec_projection.py
tests/test_result_renderer_registry.py
tests/test_generic_result_visualization.py
tests/test_result_evidence_navigation.py
tests/test_preset_business_rules.py
tests/test_historical_business_rule_migration.py
tests/business_rule_nl_protocol_cases.json
tests/business_rule_nl_golden.json
tests/business_rule_nl_guided_equivalence.json
tests/business_rule_nl_online_smoke.json
tests/preset_reproduction_manifest.json
tests/new_case_acceptance.json
tests/test_operator_asset_catalog.py
tests/test_parameter_presentations.py
tests/test_effective_package_view.py
```

修改：

```text
app_v2.py
core/editor_schema.py
core/editor_service.py
core/context.py
core/executor.py
core/registry.py
core/recipes.py
core/rule_graph.py
core/runtime.py
core/persistence.py
core/preset_definitions.py
core/preset_media.py
tests/test_v2_ui.py
```

删除或停用：

```text
03中的高级原子编排组件
前端节点增删改查组件
前端端口连接组件
以原子图为用户唯一编辑源的控制器回调
```

## 25. 完成定义

只有同时满足以下条件，V3 才算完成：

1. 自然语言、P01–P13、历史迁移统一进入现有 `SkillEditorDocument@3.x` 这一唯一根文档，不存在第二套平行根模型或双写。
2. 03 可编辑全部业务条件、嵌套逻辑、独立持续、复杂编排、输出和触发。
3. 02 可按真实媒体动态补充区域和方向，不要求提前知道数量或 ID。
4. 技能可以声明图片、视频或双 variant，但每次运行只消费一个媒体源；媒体结论由确定性能力校验，冲突不静默降级。
5. 分支结果、最终结果和用户要求的业务输出均持久化。
6. 04 默认展示最终结论和业务输出，证据与 Trace 按需展开。
7. 事件名称、告警名称、业务输出名称和框标签互不污染。
8. P01–P13、历史 Golden、原子/组合/时序测试和浏览器 E2E 全部通过。
9. 不再存在用户侧高级原子编排入口。
10. 新增业务能力只需注册 Schema、编译 Recipe、结果契约和测试，无需重写事件编辑页面。
11. LLM 自然语言生成通过离线协议、语义 Golden、在线冒烟和生成后运行四层测试。
12. P01–P13 可从版本化 fixture 重复复现，关键效果不低于实施前冻结基线。
13. 每个新增案例均能由通用能力组合生成、编辑、编译、运行、输出和保存重载，无案例 ID 硬编码。
14. 03 分支条件覆盖全部业务能力，所有业务参数和安全调优参数均可通过 Schema 表单修改。
15. 05 按类别完整展示当前及后续注册原子，能从业务条件追踪到 Recipe、原子和实际参数。
16. 当前加载的 Effective SkillPackage 可在 05 审计、下载和比较，且与实际运行版本一致；不再保留难读且不可操作的“高级参考”。
17. 业务事件、复杂编排和触发策略只按语义需要出现；最终判定唯一、业务输出完整，不向简单任务暴露无关配置。
18. 05 每个原子能力均可点开查看完整配置说明；03 所有可编辑参数使用用户可理解的名称、单位、影响说明和帮助入口，不直接暴露技术字段名。
19. 帧相关参数保持“帧”单位；03 条件组明确支持并展示 AND、OR、NOT 及其嵌套语义。
20. LLM 同时支持自由任务描述和按业务事件、条件分支、复杂编排、最终判定、业务输出、触发策略组织的引导描述，两种方式通用并生成同一业务模型。
21. 04 严格按“最终结果 → 业务输出 → 分支与证据”展示；普通用户无需阅读技术 JSON，所有业务结论均可定位到对应媒体与结构化证据。
22. 01 的输出意图、02 的场景资源、03 的 ResultSpec 与 04 的卡片/媒体证据使用同一稳定引用链；任一配置变更都能确定性反映到结果页。
23. 04 不含预置 ID、技能名称或事件中文名分支；所有案例均通过结果类型、值形状、展示规格和证据层组合渲染。
24. 每个 ResultSpec 都有兼容渲染器和可访问文本；未知或旧版本结果至少通过 `generic.summary` 保留值、状态和证据入口，不能白屏或退化为普通用户阅读 JSON。
25. 动态区域、方向、类别、分支和大量目标不需要前端预设数量，能够分组、分页、筛选并在图片/视频中正确联动。
26. 每个公开运行值均使用 `RuntimeValueEnvelope`，能够从最终结果稳定追踪到 ResultSpec、分支/条件、节点、身份、时间和 EvidenceRecord；04 不从平铺 JSON 猜来源。
27. 第 10.4 节每种时序模式均有明确状态机、时间锚点、区间边界、等待/失败/重置规则和受控事件流测试，不存在只可配置但不可确定执行的模式。
28. ResultSpec 与 PresentationSpec 分开持久化和哈希；纯布局、排序、显示精度或渲染器修改不触发重新编译和视觉推理，也不改变历史业务事实。
29. V3 首期明确不支持多摄像头/多媒体联合运行；Schema 中的未来关联范围不在普通用户界面制造“已支持”的假象。
30. 图片、视频、复杂时序三个纵向切片依次通过完整链路后，才允许扩展全部能力和切换旧入口；每个阶段都有可运行产物和回滚路径。

---

本方案以“用户需要的结果”为第一导向：自然语言先生成可审查的业务规则，用户在 02 补充真实场景资源，在 03 修改参数、组合、时间和输出，后端编译内部原子图，04 先展示最终结果和业务输出，再提供分支与证据解释。讨论中的多区域案例只是验收样例，不是产品结构边界。

## 26. 2026-08-24 用户可理解性收敛（实施约束）

### 26.1 媒体能力必须由用户明确选择

01 不提供“自动判断”。新建技能只允许：

- 仅图片：只生成和校验 image variant；不得因告警文案自动升级为视频。
- 仅视频：只生成和校验 video variant。
- 图片和视频：LLM 必须分别给出 image、video 两套可审核分支，后端分别编译；缺少任一流程即要求重新生成，不静默降级。

LLM 可以说明所选媒体无法表达某个动作或时间语义，但不能替用户改变媒体选择。

### 26.2 条件参数采用受控编辑器

03 的参数总表改为只读概览，不再让用户直接修改表格字符串或 JSON：

- 比较方式、筛选方式、状态、关系等枚举使用下拉或单选，显示“业务名称 + 符号”，例如“大于（>）”。
- 阈值、时间、比例、帧数等使用带单位、上下限和整数约束的数字输入。
- 区域、方向、输入来源使用来自 02 和当前分支的动态候选下拉。
- 布尔参数使用“是/否”。
- 开放词表的模型类别、检测短语和业务标签使用文本或标签输入；LLM 值作为当前建议展示，用户修改后重新经过同一 Schema 校验与编译。
- 系统派生字段、内部 ID、端口、几何坐标和明确标记为不可编辑的配置只读；不允许以自由文本破坏已校验语义。
- 技术字段名只出现在 05 资产详情或高级审计中，不进入普通编辑表单。

### 26.3 当前条件组合必须直接可见

每个分支先展示当前生效条件树和自然语言摘要，再提供组合操作。AND、OR、NOT、N-of-M 在树中直接显示；“当前条件组合”默认展开。组合操作只能选择同级条件，后端继续负责类型检查与非法空组折叠。

### 26.4 复杂编排改为业务问题

普通界面名称改为“分支之间如何判定”，问题是“这些分支什么时候算完成”，选项为：

- 不使用（普通 AND / OR 告警）
- 同时处于满足状态
- 都完成过即可
- 规定时间内全部完成
- 任一完成
- 至少 N 个完成
- 按所选顺序完成
- 规定时间内未发生
- 规定时间内重复发生

图片普通任务默认“不使用”。对象/轨迹/区域关联仅在视频时序确有需要时显示为进阶项。

### 26.5 最终判定不暴露 ResultSpec 类型

普通用户只配置：最终告警名称、参与最终告警的条件分支、AND/OR/N-of-M、是否展示未成立原因。`decision_type`、ResultSpec 语义类型及来源端口由系统推导并保留在后端。多个来源的用户语义就是“选择哪些分支参与最终告警”，不再展示“最终结果类型”或技术来源列表。

### 26.6 固定图片纵向切片验收

输入：

> 区域1有穿红色衣服、灰色裤子的人，区域2中人的数量大于2，则发出告警。

媒体选择“仅图片”，上传 `WeDetect/imgs/03.png`。验收要求：

1. 生成结果只接受 image。
2. 02 明确列出区域1、区域2，必须加载同一任务图片手工绘制；两项未完成前不得运行。
3. 03 显示两个独立分支；区域1属性必须绑定同一人员，区域2人数条件保持 `> 2`。
4. `>` 通过比较方式下拉修改，`2` 通过数字框修改；LLM 检测短语和内部资源 ID 不可自由编辑。
5. 当前条件树明确展示分支内 AND；最终判定默认选择两个分支并使用 AND。
6. 用户不配置复杂时序，也不看到“最终结果类型”。
