from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .registry import OperatorRegistry
from .schema import StrictModel


BusinessCategory = Literal[
    "目标与属性",
    "空间与区域",
    "数量与测量",
    "轨迹与运动",
    "状态与事件",
    "时间与复杂编排",
    "逻辑组合",
    "输出与证据",
]

BusinessValueType = Literal[
    "frame_set",
    "entity_set",
    "pair_set",
    "scoped_set",
    "track_set",
    "vector_set",
    "scalar_set",
    "condition_set",
    "state_set",
    "event_set",
    "result",
    "any",
]


_CONTRACT_TYPES: tuple[tuple[str, BusinessValueType], ...] = (
    ("ObjectSet", "entity_set"),
    ("EntitySet", "entity_set"),
    ("PairSet", "pair_set"),
    ("ScopedSet", "scoped_set"),
    ("TrackSet", "track_set"),
    ("VectorSet", "vector_set"),
    ("ScalarSet", "scalar_set"),
    ("ConditionSet", "condition_set"),
    ("StateSet", "state_set"),
    ("EventSet", "event_set"),
    ("FrameSet", "frame_set"),
    ("ResultSpec", "result"),
)


def _contract_types(contract: str) -> list[BusinessValueType]:
    if "Any" in contract:
        return ["any"]
    return list(dict.fromkeys(value for token, value in _CONTRACT_TYPES if token in contract))


class BusinessParameterDefinition(StrictModel):
    parameter_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    editor: Literal[
        "text",
        "number",
        "select",
        "multi_select",
        "percentage",
        "duration",
        "frames",
        "angle_degrees",
        "scene_resource_select",
        "direction_resource_select",
        "source_select",
        "boolean",
        "condition_tree",
        "readonly",
    ]
    help: str = Field(min_length=1)
    default: Any = None
    unit: str | None = None
    choices: list[Any] = Field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    required: bool = False
    level: Literal["business", "tuning", "resource", "derived"] = "business"
    maps_to: list[str] = Field(default_factory=list)
    value_transform: str | None = None


class BusinessCapabilityDefinition(StrictModel):
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str = Field(default="1.0", pattern=r"^[0-9]+.[0-9]+$")
    display_name: str = Field(min_length=1)
    category: BusinessCategory
    description: str = Field(min_length=1)
    input_contract: str = Field(min_length=1)
    output_contract: str = Field(min_length=1)
    parameters: list[BusinessParameterDefinition] = Field(default_factory=list)
    media_requirements: list[Literal["image", "video"]] = Field(default_factory=lambda: ["image", "video"])
    resource_requirements: list[Literal["region", "direction"]] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    compiler_recipe: str = Field(min_length=1)
    atoms: list[str] = Field(default_factory=list)
    evidence_contract: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    accepted_source_types: list[BusinessValueType] = Field(default_factory=list)
    output_value_type: BusinessValueType | None = None

    @model_validator(mode="after")
    def fill_machine_readable_contract(self):
        if not self.accepted_source_types:
            self.accepted_source_types = _contract_types(self.input_contract)
        if self.output_value_type is None:
            inferred = _contract_types(self.output_contract)
            self.output_value_type = inferred[0] if inferred else "any"
        return self


class BusinessCapabilityRegistry:
    def __init__(
        self,
        definitions: list[BusinessCapabilityDefinition],
        operator_registry: OperatorRegistry,
    ):
        self._definitions: dict[str, BusinessCapabilityDefinition] = {}
        for definition in definitions:
            if definition.capability_id in self._definitions:
                raise ValueError(
                    f"duplicate business capability: {definition.capability_id}"
                )
            for atom in definition.atoms:
                operator_registry.require(atom)
            self._definitions[definition.capability_id] = definition

    def require(self, capability_id: str) -> BusinessCapabilityDefinition:
        definition = self._definitions.get(capability_id)
        if definition is None:
            raise KeyError(f"unknown business capability: {capability_id}")
        return definition

    def definitions(self) -> list[BusinessCapabilityDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]

    def search(self, text: str) -> list[BusinessCapabilityDefinition]:
        query = text.strip().lower()
        if not query:
            return self.definitions()
        return [
            item
            for item in self.definitions()
            if query
            in " ".join(
                [
                    item.capability_id,
                    item.display_name,
                    item.category,
                    item.description,
                    *item.search_terms,
                ]
            ).lower()
        ]


def _p(
    parameter_id: str,
    label: str,
    editor: str,
    help_text: str,
    *,
    default: Any = None,
    unit: str | None = None,
    choices: list[Any] | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    required: bool = False,
    level: str = "business",
    maps_to: list[str] | None = None,
    value_transform: str | None = None,
) -> BusinessParameterDefinition:
    return BusinessParameterDefinition(
        parameter_id=parameter_id,
        label=label,
        editor=editor,  # type: ignore[arg-type]
        help=help_text,
        default=default,
        unit=unit,
        choices=choices or [],
        minimum=minimum,
        maximum=maximum,
        required=required,
        level=level,  # type: ignore[arg-type]
        maps_to=maps_to or [],
        value_transform=value_transform,
    )


def build_business_capability_registry(
    operator_registry: OperatorRegistry,
) -> BusinessCapabilityRegistry:
    scope = _p(
        "scope",
        "判断范围",
        "scene_resource_select",
        "选择全画面或 02 实际标注的区域；区域数量不需要提前确定。",
        default="full_frame",
        level="resource",
    )
    source = _p(
        "source",
        "输入目标或事件",
        "source_select",
        "选择当前分支前序结果或其它分支公开结果，系统只显示类型兼容来源。",
        required=True,
    )
    comparison = _p(
        "operator",
        "比较方式",
        "select",
        "选择大于、至少、等于、不超过、小于或不等于。",
        default=">=",
        choices=[">", ">=", "==", "<=", "<", "!="],
        maps_to=["logic.compare@1.0.operator"],
    )
    threshold = _p(
        "threshold",
        "比较值",
        "number",
        "实际数量或测量值将与此值比较。",
        default=1,
        maps_to=["logic.compare@1.0.value"],
    )
    definitions = [
        BusinessCapabilityDefinition(
            capability_id="target.detect",
            display_name="检测目标",
            category="目标与属性",
            description="按模型类别或自然语言可见描述识别目标，并保留原模型标签。",
            input_contract="FrameSet",
            output_contract="ObjectSet",
            parameters=[
                _p("targets", "目标类别", "multi_select", "选择一个或多个需要识别的类别。", required=True, maps_to=["rex.ground@1.1.targets"]),
                _p("phrases", "检测描述", "text", "使用可从画面直接观察的短语。", maps_to=["rex.ground@1.1.targets[].phrases"]),
                _p("business_label", "业务框标签", "text", "结果中显示的业务名称；原模型标签会另行保留。"),
            ],
            compiler_recipe="direct_grounding",
            atoms=["rex.ground@1.1"],
            evidence_contract=["box"],
            search_terms=["识别", "框出", "人", "车辆", "火", "烟"],
        ),
        BusinessCapabilityDefinition(
            capability_id="target.filter_class",
            display_name="按类别筛选或排除",
            category="目标与属性",
            description="从已有目标中保留指定类别，或排除不需要的类别。",
            input_contract="ObjectSet",
            output_contract="ObjectSet",
            parameters=[
                source,
                _p("labels", "目标类别", "multi_select", "选择保留或排除的模型类别。", required=True),
                _p("mode", "筛选方式", "select", "选择保留这些类别或排除这些类别。", default="include", choices=["include", "exclude"]),
            ],
            compiler_recipe="class_filter",
            atoms=["objects.filter_by_label@1.0", "set.difference@1.0"],
            evidence_contract=["box"],
        ),
        BusinessCapabilityDefinition(
            capability_id="attribute.color",
            display_name="可见属性颜色",
            category="目标与属性",
            description="判断目标整体或其关联区域的可见颜色，例如物体表面、上半部或下半部。",
            input_contract="ObjectSet",
            output_contract="ObjectSet",
            parameters=[
                source,
                _p("part", "判断区域", "select", "选择整体、上半区域或下半区域；可用于服装、物体部件等场景。", default="whole", choices=["whole", "upper_clothing", "lower_clothing"]),
                _p("color", "颜色", "select", "选择用户要判断的颜色。", required=True),
                # A tiny default fraction treats bright background pixels as
                # clothing (for example, a white chair inside a person's
                # detector box).  Keep the tuning exposed, but use the same
                # conservative 20% baseline as the deterministic semantic
                # compiler; users can still lower it explicitly when a
                # partial-colour task really needs that behaviour.
                _p("minimum_fraction", "颜色至少占该部位", "percentage", "占比越高判定越严格。", default=20, unit="%", minimum=0, maximum=100, level="tuning", maps_to=["visual.color_fraction@1.0.min_fraction"], value_transform="percent_to_ratio"),
            ],
            compiler_recipe="visible_color",
            atoms=["visual.color_fraction@1.0", "filter.apply@1.0"],
            evidence_contract=["box", "measurement"],
            search_terms=["颜色", "外观", "红色", "灰色", "上衣", "裤子"],
        ),
        BusinessCapabilityDefinition(
            capability_id="attribute.geometry",
            display_name="尺寸、位置或宽高比",
            category="目标与属性",
            description="按目标在画面中的大小、位置和形状比例筛选。",
            input_contract="ObjectSet",
            output_contract="ObjectSet",
            parameters=[source, _p("dimension", "判断维度", "select", "选择尺寸、位置或宽高比。", choices=["size", "position", "aspect_ratio"], required=True), comparison, threshold],
            compiler_recipe="geometry_filter",
            atoms=["visual.geometry@1.0", "filter.apply@1.0"],
            evidence_contract=["box", "measurement"],
        ),
        BusinessCapabilityDefinition(
            capability_id="subject.same_attributes",
            display_name="同一主体的多证据归属",
            category="目标与属性",
            description="确保多项属性、部件或关联物证据属于同一主体，禁止跨目标拼接。",
            input_contract="ObjectSet[]",
            output_contract="ObjectSet",
            parameters=[
                _p("subject", "主体目标", "source_select", "选择需要同时满足属性的主体。", required=True),
                _p("attributes", "属性证据", "multi_select", "选择必须属于同一主体的多项属性。", required=True),
                _p("minimum_overlap", "属性与主体最低重叠", "percentage", "调高更严格，调低可容忍属性框偏移。", default=30, unit="%", level="tuning", value_transform="percent_to_ratio"),
            ],
            compiler_recipe="same_subject_attributes",
            atoms=["pairs.build@1.0", "pairs.measure@1.0", "pairs.filter@1.0", "set.semi_join@1.0"],
            evidence_contract=["box", "relation"],
        ),
        BusinessCapabilityDefinition(
            capability_id="subject.missing_equipment",
            display_name="主体缺少关联物",
            category="目标与属性",
            description="按同一主体判断其应关联的对象、部件或可见证据是否缺失。",
            input_contract="ObjectSet subject + ObjectSet associated_object",
            output_contract="ObjectSet",
            parameters=[
                _p("subject", "主体目标", "source_select", "选择需要检查关联关系的主体。", required=True),
                _p("equipment", "应有关联物", "source_select", "选择主体应关联的对象、部件或可见证据。", required=True),
                _p("association", "关联成立要求", "percentage", "关联物框与主体框达到该比例才算属于该主体。", default=30, unit="%", level="tuning", value_transform="percent_to_ratio"),
            ],
            compiler_recipe="equipment_absence",
            atoms=["pairs.build@1.0", "pairs.measure@1.0", "pairs.filter@1.0", "set.anti_join@1.0"],
            evidence_contract=["box", "relation"],
            search_terms=["缺少关联物", "缺少部件", "未佩戴", "未戴安全帽", "未系安全绳"],
        ),
        BusinessCapabilityDefinition(
            capability_id="spatial.membership",
            display_name="目标在区域内或外",
            category="空间与区域",
            description="按框中心或重叠比例判断目标是否属于一个或多个动态区域。",
            input_contract="ObjectSet + RegionSet",
            output_contract="ObjectSet/ScopedSet",
            parameters=[
                source,
                scope,
                _p("membership", "区域判断方式", "select", "选择框中心、任意重叠或最低重叠比例。", default="center", choices=["center", "overlap", "overlap_ratio"]),
                _p("minimum_overlap", "目标进入区域的最低比例", "percentage", "调高要求目标更深入区域。", default=30, unit="%", level="tuning", maps_to=["spatial.inside@1.0.overlap_threshold"], value_transform="percent_to_ratio"),
                _p("inside", "判断区域内或区域外", "select", "选择区域内或区域外。", default=True, choices=[True, False]),
            ],
            resource_requirements=["region"],
            compiler_recipe="region_membership",
            atoms=["region.manual_set@1.0", "spatial.inside@1.0", "set.partition@1.0"],
            evidence_contract=["box", "region"],
        ),
        BusinessCapabilityDefinition(
            capability_id="spatial.association",
            display_name="两个目标的空间关系",
            category="空间与区域",
            description="判断重叠、包含、被包含、接近或双向匹配。",
            input_contract="ObjectSet + ObjectSet",
            output_contract="PairSet/ObjectSet",
            parameters=[
                _p("subject", "主体目标", "source_select", "选择关系主体。", required=True),
                _p("object", "关联目标", "source_select", "选择与主体关联的对象。", required=True),
                _p("relation", "关系", "select", "选择重叠、包含、被包含、接近或双方匹配。", choices=["overlap", "contains", "inside", "near", "bidirectional"], required=True),
                _p("threshold", "关系成立要求", "percentage", "按所选关系解释为重叠、覆盖或匹配比例。", default=30, unit="%", level="tuning", value_transform="percent_to_ratio"),
            ],
            compiler_recipe="spatial_association",
            atoms=["spatial.associate@1.0", "pairs.build@1.0", "pairs.measure@1.0", "pairs.filter@1.0"],
            evidence_contract=["box", "relation"],
        ),
        BusinessCapabilityDefinition(
            capability_id="measure.count",
            display_name="目标数量",
            category="数量与测量",
            description="统计全画面、指定区域、每类或每区域的目标数量。",
            input_contract="CountableSet",
            output_contract="ScalarSet",
            parameters=[
                source,
                scope,
                _p("group_by", "统计分组", "select", "选择总数、每类别或每区域分别统计。", default="total", choices=["total", "category", "region"]),
                comparison,
                threshold,
            ],
            compiler_recipe="count_compare",
            atoms=["measure.count@1.0", "measure.region_count@1.0", "reduce.count@1.0", "logic.compare@1.0"],
            evidence_contract=["measurement", "box", "region"],
            search_terms=["人数", "车辆数", "数量", "拥堵"],
        ),
        BusinessCapabilityDefinition(
            capability_id="measure.statistic",
            display_name="数值统计与比较",
            category="数量与测量",
            description="对速度、方向、距离、持续时间等数值做最大、最小、平均、中位或累计判断。",
            input_contract="ScalarSet",
            output_contract="ConditionSet",
            parameters=[
                source,
                _p("statistic", "统计方式", "select", "选择当前值、最大、最小、平均、中位或总和。", default="latest", choices=["latest", "max", "min", "mean", "median", "sum"]),
                comparison,
                threshold,
                _p("unit", "单位", "text", "填写用户希望看到的业务单位。"),
            ],
            compiler_recipe="statistic_compare",
            atoms=["reduce.statistic@1.0", "logic.compare@1.0"],
            evidence_contract=["measurement"],
        ),
        BusinessCapabilityDefinition(
            capability_id="motion.track",
            display_name="创建并确认目标轨迹",
            category="轨迹与运动",
            description="将同一目标跨帧关联，并按命中次数与缺失帧数确认有效轨迹。",
            input_contract="ObjectSet",
            output_contract="TrackSet",
            parameters=[
                source,
                _p("match_requirement", "同一目标匹配要求", "percentage", "调低更容易接续，调高更严格。", default=40, unit="%", level="tuning", maps_to=["track.iou@1.0.iou_threshold"], value_transform="percent_to_ratio"),
                _p("minimum_hits", "至少命中多少帧", "frames", "达到该帧数后才确认轨迹。", default=2, unit="帧", level="tuning"),
                _p("missing_frames", "暂时消失可保留多少帧", "frames", "帧数越大越能跨越遮挡，但串轨风险增加。", default=5, unit="帧", level="tuning"),
                _p("motion_prediction", "使用运动预测接续轨迹", "boolean", "同时比较当前位置和预测位置，适合透视变化大或移动较快的目标。", default=False, level="tuning", maps_to=["track.iou@1.0.motion_prediction"]),
            ],
            media_requirements=["video"],
            compiler_recipe="track_confirm",
            atoms=["track.iou@1.0", "track.confirm@1.0"],
            evidence_contract=["track", "box"],
        ),
        BusinessCapabilityDefinition(
            capability_id="motion.direction",
            display_name="运动方向",
            category="轨迹与运动",
            description="计算轨迹方向并与画面轴或 02 参考箭头比较。",
            input_contract="TrackSet + VectorSet",
            output_contract="ConditionSet",
            parameters=[
                source,
                scope,
                _p("reference", "参考方向", "direction_resource_select", "选择画面方向或 02 标注箭头。", required=True, level="resource"),
                _p("relation", "方向关系", "select", "选择同向、逆向或允许偏差。", default="same", choices=["same", "opposite", "within_angle"]),
                _p("angle", "方向角度要求", "angle_degrees", "用角度设置方向严格度，内部自动转换余弦。", default=60, unit="度", minimum=0, maximum=180, value_transform="degrees_to_cosine"),
                _p("minimum_displacement", "判定已移动的最小距离", "percentage", "减少静止框抖动误判。", default=2, unit="%画面对角线", level="tuning", value_transform="screen_diagonal_percent"),
                _p("small_target_displacement_ratio", "远处小目标位移灵敏度", "percentage", "按目标框尺寸降低远处小目标的位移门槛；数值越小越灵敏。", default=20, unit="%目标框对角线", minimum=0, maximum=100, level="tuning", maps_to=["measure.heading@1.0.min_displacement_box_ratio"], value_transform="percent_to_ratio"),
            ],
            media_requirements=["video"],
            resource_requirements=["direction"],
            compiler_recipe="direction_compare",
            atoms=["measure.heading@1.0", "logic.compare@1.0"],
            evidence_contract=["track", "vector"],
        ),
        BusinessCapabilityDefinition(
            capability_id="motion.wrong_way",
            display_name="相对参考方向反向运动",
            category="轨迹与运动",
            description="按同一轨迹、场景区域和参考方向判断反向运动；逆行只是交通场景中的一种用法。",
            input_contract="ObjectSet + RegionSet + VectorSet",
            output_contract="ConditionSet<track>",
            parameters=[
                source,
                scope,
                _p("reference", "参考方向", "direction_resource_select", "选择 02 为该区域绘制的参考方向。", required=True, level="resource"),
                _p("minimum_reverse_angle", "反向最小夹角", "angle_degrees", "运动方向与参考方向夹角达到该值才判为反向。", default=120, unit="度", minimum=90, maximum=180, value_transform="degrees_to_cosine"),
                _p("minimum_displacement", "判定目标已移动的最小距离", "percentage", "减少静止框抖动误报。", default=2, unit="%画面对角线", level="tuning", value_transform="screen_diagonal_percent"),
                _p("motion_prediction", "使用运动预测接续轨迹", "boolean", "同时比较当前位置和预测位置，减少高速或远处目标轨迹断裂。", default=True, level="tuning", maps_to=["track.iou@1.0.motion_prediction"]),
                _p("small_target_displacement_ratio", "远处小目标位移灵敏度", "percentage", "按目标框尺寸降低远处目标的方向门槛；数值越小越灵敏。", default=20, unit="%目标框对角线", minimum=0, maximum=100, level="tuning", maps_to=["measure.heading@1.0.min_displacement_box_ratio"], value_transform="percent_to_ratio"),
            ],
            media_requirements=["video"],
            resource_requirements=["region", "direction"],
            compiler_recipe="reverse_motion",
            atoms=["track.iou@1.0", "measure.heading@1.0", "logic.compare@1.0", "temporal.qualify@1.0"],
            evidence_contract=["box", "track", "region", "vector"],
            search_terms=["逆行", "反向"],
        ),
        BusinessCapabilityDefinition(
            capability_id="motion.speed",
            display_name="速度、停留或静止",
            category="轨迹与运动",
            description="测量目标速度，并据此判断快速、慢速、停留或静止。",
            input_contract="TrackSet",
            output_contract="ScalarSet/ConditionSet",
            parameters=[source, scope, _p("motion_state", "运动状态", "select", "选择速度判断、停留或静止。", choices=["speed", "dwell", "stationary"], required=True), comparison, threshold],
            media_requirements=["video"],
            compiler_recipe="speed_or_dwell",
            atoms=["measure.speed@1.0", "logic.compare@1.0"],
            evidence_contract=["track", "measurement"],
        ),
        BusinessCapabilityDefinition(
            capability_id="state.current",
            display_name="目标当前状态",
            category="状态与事件",
            description="根据检测类别或属性证据判断同一目标当前处于何种状态。",
            input_contract="EntitySet + evidence",
            output_contract="StateSet",
            parameters=[source, _p("positive_state", "目标状态", "text", "填写希望判断的可观察状态，例如开启、损坏、倒地或占用。", required=True), _p("evidence", "状态证据", "source_select", "选择检测类别或属性证据。", required=True)],
            compiler_recipe="state_detect",
            atoms=["state.detect@1.0"],
            evidence_contract=["box", "condition"],
        ),
        BusinessCapabilityDefinition(
            capability_id="state.transition",
            display_name="同一目标状态转变",
            category="状态与事件",
            description="判断同一目标从起始状态转为目标状态，例如关闭转为开启或站立转为倒地。",
            input_contract="StateSet",
            output_contract="EventSet",
            parameters=[source, _p("from_state", "起始状态", "text", "转变前的状态。", required=True), _p("to_state", "目标状态", "text", "转变后的状态。", required=True), _p("maximum_seconds", "最长转变时间", "duration", "两个状态必须在该时间内完成转变。", unit="秒")],
            media_requirements=["video"],
            compiler_recipe="state_change_event",
            atoms=["state.detect@1.0", "state.transition@1.0", "temporal.qualify@1.0"],
            evidence_contract=["box", "event"],
            search_terms=["摔倒", "状态变化"],
        ),
        BusinessCapabilityDefinition(
            capability_id="event.detect_or_compose",
            display_name="业务事件",
            category="状态与事件",
            description="将可见检测、状态变化或多项条件组合为用户命名的业务事件。",
            input_contract="ConditionSet/ObjectSet/EventSet",
            output_contract="EventSet",
            parameters=[source, scope, _p("method", "判定方法", "select", "显示并选择实际判定方法，不把事件名写死为卡片类型。", choices=["visible_detection", "state_transition", "condition_composition"], required=True), _p("event_label", "事件名称", "text", "事件记录中显示的业务名称。", required=True)],
            compiler_recipe="event_from_evidence",
            atoms=["event.from_condition@1.0", "event.relabel@1.0"],
            evidence_contract=["event", "box", "measurement"],
            search_terms=["事故", "摔倒", "烟火", "拥堵"],
        ),
        BusinessCapabilityDefinition(
            capability_id="temporal.persist",
            display_name="持续、累计或窗口占比",
            category="时间与复杂编排",
            description="可附着到任意条件或分支，独立设置持续方式和身份范围。",
            input_contract="ConditionSet",
            output_contract="EventSet",
            parameters=[
                source,
                _p("mode", "时间约束", "select", "选择连续持续、累计持续或窗口占比。", default="continuous", choices=["continuous", "cumulative", "ratio"]),
                _p("duration", "持续时间", "duration", "达到该媒体时间后条件才成立。", default=1, unit="秒", maps_to=["temporal.persist@1.0.seconds"]),
                _p("allowed_gap", "允许短暂中断", "duration", "用于容忍短暂遮挡或漏检。", default=0.5, unit="秒", level="tuning", maps_to=["temporal.persist@1.0.gap_tolerance_seconds"]),
                _p("identity_scope", "按什么对象连续", "select", "选择全局、同一目标、同一轨迹、同一目标对或同一区域。", default="global", choices=["global", "object", "track", "pair", "region"]),
            ],
            media_requirements=["video"],
            compiler_recipe="temporal_persist",
            atoms=["temporal.persist@1.0"],
            evidence_contract=["event", "measurement"],
        ),
        BusinessCapabilityDefinition(
            capability_id="temporal.join",
            display_name="多个分支汇合",
            category="时间与复杂编排",
            description="判断分支同时有效、全部完成、窗口内完成、任一或至少 N 项完成。",
            input_contract="EventSet[]",
            output_contract="EventSet",
            parameters=[
                _p("branches", "参与分支", "multi_select", "选择参与本次汇合的业务分支。", required=True),
                _p("mode", "汇合方式", "select", "选择并行完成、互斥选择、任意完成或至少N项完成。", default="all_completed", choices=["all_completed", "exclusive", "any", "n_of_m"]),
                _p("window", "完成时间窗口", "duration", "窗口内完成模式使用该媒体时间。", unit="秒"),
                _p("required_count", "至少完成分支数", "number", "N选M模式需要填写。", minimum=1),
                _p("correlation_scope", "多个事件按什么对象关联", "select", "本期支持全局、同一目标、轨迹、目标对或区域。", default="global", choices=["global", "object", "track", "pair", "region"]),
            ],
            media_requirements=["video"],
            compiler_recipe="multi_branch_join",
            atoms=["temporal.join@1.0", "event.attach_evidence@1.0"],
            evidence_contract=["event"],
        ),
        BusinessCapabilityDefinition(
            capability_id="temporal.sequence",
            display_name="有时限的先后顺序",
            category="时间与复杂编排",
            description="先完成一个阶段，再在每段独立时间窗口内完成后续阶段。",
            input_contract="EventSet[]",
            output_contract="EventSet",
            parameters=[
                _p("stages", "阶段顺序", "multi_select", "按顺序选择业务分支或事件阶段。", required=True),
                _p("step_windows", "每段允许时间", "text", "为每个相邻阶段单独设置最短与最长延迟。", required=True),
                _p("correlation_scope", "阶段按什么对象关联", "select", "防止把不同目标的阶段拼接。", default="global", choices=["global", "object", "track", "pair", "region"]),
            ],
            media_requirements=["video"],
            compiler_recipe="ordered_process",
            atoms=["temporal.sequence@2.0", "event.attach_evidence@1.0"],
            evidence_contract=["event"],
        ),
        BusinessCapabilityDefinition(
            capability_id="temporal.absence",
            display_name="规定窗口内未发生",
            category="时间与复杂编排",
            description="从锚点事件开始观察完整窗口，窗口关闭前保持等待，禁止事件出现则立即失败。",
            input_contract="EventSet anchor + EventSet forbidden",
            output_contract="EventSet",
            parameters=[_p("anchor", "开始观察的事件", "source_select", "选择时间窗口锚点。", required=True), _p("forbidden", "窗口内不应发生的事件", "source_select", "选择禁止事件。", required=True), _p("window", "观察窗口", "duration", "必须完整观察该媒体时间后才能判定未发生。", required=True, unit="秒"), _p("correlation_scope", "按什么对象关联", "select", "选择全局、同一目标、轨迹、目标对或区域。", choices=["global", "object", "track", "pair", "region"])],
            media_requirements=["video"],
            compiler_recipe="negative_or_repeated_event",
            atoms=["temporal.absence@1.0"],
            evidence_contract=["event"],
        ),
        BusinessCapabilityDefinition(
            capability_id="temporal.repeat",
            display_name="事件重复发生",
            category="时间与复杂编排",
            description="同一关联对象在时间窗口内发生至少 N 个不同事件实例。",
            input_contract="EventSet",
            output_contract="EventSet",
            parameters=[source, _p("count", "至少发生次数", "number", "必须是不同事件实例。", default=2, minimum=1), _p("window", "统计窗口", "duration", "首尾事件完成时间必须落在该窗口内。", unit="秒"), _p("correlation_scope", "按什么对象关联", "select", "选择全局、同一目标、轨迹、目标对或区域。", choices=["global", "object", "track", "pair", "region"])],
            media_requirements=["video"],
            compiler_recipe="negative_or_repeated_event",
            atoms=["temporal.repeat@1.0"],
            evidence_contract=["event"],
        ),
        BusinessCapabilityDefinition(
            capability_id="logic.group",
            display_name="AND / OR / NOT / N-of-M 条件组",
            category="逻辑组合",
            description="嵌套组合条件；NOT 只能作用于一个条件或条件组。",
            input_contract="ConditionSet[]",
            output_contract="ConditionSet",
            parameters=[_p("operator", "条件关系", "select", "选择全部满足（AND）、任一满足（OR）、条件取反（NOT）或至少N项。", choices=["AND", "OR", "NOT", "N_OF_M"], required=True), _p("required_count", "至少满足条件数", "number", "N-of-M 模式填写。", minimum=1)],
            compiler_recipe="logic_group",
            atoms=["logic.all@1.0", "logic.any@1.0", "logic.not@1.0", "reduce.quantify@1.0"],
            evidence_contract=["condition"],
        ),
        BusinessCapabilityDefinition(
            capability_id="output.business_result",
            display_name="业务结果与证据",
            category="输出与证据",
            description="把最终判定、分支状态、数量、框、轨迹、事件、持续时间或时间线保存为用户结果。",
            input_contract="Any business source",
            output_contract="ResultSpec",
            parameters=[source, _p("result_type", "希望看到的结果", "select", "选择判定、数量、数值、目标框、轨迹、事件、持续时间或时间线。", choices=["decision", "count", "value", "entities", "tracks", "events", "duration", "timeline"], required=True), _p("display_name", "结果名称", "text", "用户在 04 看到的名称。", required=True), _p("evidence", "保存证据", "select", "选择必须保存、尽量保存或不需要证据。", default="optional", choices=["required", "optional", "none"])],
            compiler_recipe="result_projection",
            atoms=["result.project@1.0", "evidence.collect@1.0"],
            evidence_contract=["box", "track", "event", "measurement", "region", "vector"],
        ),
    ]
    return BusinessCapabilityRegistry(definitions, operator_registry)


__all__ = [
    "BusinessCapabilityDefinition",
    "BusinessCapabilityRegistry",
    "BusinessParameterDefinition",
    "BusinessValueType",
    "build_business_capability_registry",
]
