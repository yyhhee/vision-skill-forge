from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, model_validator

from .business_capabilities import BusinessCapabilityRegistry
from .business_source_scope import partition_source_refs, source_media_types
from .document_hashes import refresh_document_hashes
from .editor_schema import (
    BusinessBranch,
    CardinalitySpec,
    ConditionExpression,
    CorrelationPolicy,
    EventPattern,
    FinalDecisionSpec,
    InstancePolicy,
    PatternGateway,
    PatternStage,
    PatternTransition,
    PendingDecision,
    ResolvableValue,
    ResourceRequirement,
    ResultProjection,
    ResultSpec,
    RuleGraph,
    SkillEditorDocument,
    TemporalQualifierSpec,
    TriggerPolicy,
)
from .result_presentation_schema import PresentationSpec
from .schema import StrictModel


class BusinessDraftError(ValueError):
    """A natural-language draft error safe to show as a review requirement."""


class DraftCondition(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1)
    operator: Literal["ATOM", "AND", "OR", "NOT", "N_OF_M"] = "ATOM"
    capability_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.-]+$"
    )
    parameters: dict[str, Any] = Field(default_factory=dict)
    negated: bool = False
    children: list["DraftCondition"] = Field(default_factory=list)
    required_count: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_tree_node(self):
        if self.operator == "ATOM":
            if self.capability_id is None:
                raise ValueError("ATOM draft condition requires capability_id")
            if self.children:
                raise ValueError("ATOM draft condition cannot contain children")
        elif self.capability_id is not None or self.parameters:
            raise ValueError("condition group cannot declare atomic capability parameters")
        elif self.operator == "NOT" and len(self.children) != 1:
            raise ValueError("NOT draft condition requires one child")
        elif self.operator in {"AND", "OR"} and len(self.children) < 2:
            raise ValueError(f"{self.operator} draft condition requires two children")
        elif self.operator == "N_OF_M":
            if len(self.children) < 2 or self.required_count is None:
                raise ValueError("N_OF_M draft condition requires children and required_count")
            if self.required_count > len(self.children):
                raise ValueError("draft condition required_count exceeds child count")
        return self


class DraftBranchTime(StrictModel):
    mode: Literal["immediate", "continuous", "cumulative", "ratio"] = "immediate"
    duration_seconds: float | None = Field(default=None, ge=0)
    observation_window_seconds: float | None = Field(default=None, ge=0)
    required_ratio: float = Field(default=1.0, ge=0, le=1)
    allowed_gap_seconds: float = Field(default=0.0, ge=0)
    identity_scope: Literal["global", "object", "track", "pair", "region"] = "global"


class DraftBranch(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1)
    media_type: Literal["image", "video"]
    logic: Literal["AND", "OR", "N_OF_M"] = "AND"
    required_count: int | None = Field(default=None, ge=1)
    conditions: list[DraftCondition] = Field(min_length=1)
    time: DraftBranchTime = Field(default_factory=DraftBranchTime)

    @model_validator(mode="after")
    def validate_logic(self):
        if self.logic == "N_OF_M":
            if self.required_count is None:
                raise ValueError("N_OF_M branch requires required_count")
            if self.required_count > len(self.conditions):
                raise ValueError("branch required_count exceeds condition count")
        return self


class DraftResource(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1)
    resource_type: Literal["region", "direction"]
    semantic_role: str = Field(min_length=1)
    media_types: list[Literal["image", "video"]] = Field(min_length=1)
    minimum_items: int = Field(default=1, ge=1)
    paired_region_key: str | None = None


class DraftPattern(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1)
    media_type: Literal["video"] = "video"
    mode: Literal[
        "all_active",
        "all_completed",
        "all_completed_within_window",
        "any",
        "n_of_m",
        "sequence",
        "absence",
        "repeat",
    ]
    branch_keys: list[str] = Field(min_length=1)
    window_seconds: float | None = Field(default=None, ge=0)
    required_count: int | None = Field(default=None, ge=1)
    correlation_scope: Literal["global", "object", "track", "pair", "region"] = "global"


class DraftFinalDecision(StrictModel):
    name: str = Field(min_length=1)
    decision_type: Literal[
        "event_decision",
        "detection_summary",
        "measurement_decision",
        "state_summary",
        "timeline_summary",
    ] = "event_decision"
    source_refs: list[str] = Field(min_length=1)
    combination: Literal["AND", "OR", "N_OF_M"] = "AND"
    required_count: int | None = Field(default=None, ge=1)


class DraftResult(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    result_kind: Literal[
        "decision",
        "boolean",
        "count",
        "value",
        "entities",
        "tracks",
        "events",
        "duration",
        "timeline",
        "media",
    ]
    unit: str | None = None
    evidence_policy: Literal["required", "optional", "none"] = "optional"
    save_policy: Literal["always", "on_change", "on_match", "never"] = "always"
    show_in_overview: bool = True


class DraftPendingDecision(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    kind: Literal[
        "target_class",
        "comparison_operator",
        "count_threshold",
        "duration",
        "time_window",
        "direction_reference",
        "correlation",
        "generic",
    ] = "generic"
    prompt: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    recommended_value: Any = None
    affected_refs: list[str] = Field(default_factory=list)
    required_before: Literal["compile", "run", "publish", "never"] = "run"


class NaturalLanguageBusinessDraft(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    media_requirement: Literal["image", "video", "both"]
    branches: list[DraftBranch] = Field(min_length=1)
    resources: list[DraftResource] = Field(default_factory=list)
    patterns: list[DraftPattern] = Field(default_factory=list)
    final_decision: DraftFinalDecision
    results: list[DraftResult] = Field(min_length=1)
    trigger_policy: dict[str, Any] = Field(default_factory=dict)
    pending_decisions: list[DraftPendingDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_typed_sources(self):
        """Keep full-frame scope separate from typed upstream results.

        ``full_frame`` is a legal spatial scope, but it is not an EntitySet,
        TrackSet, EventSet, or other typed condition result.  Rejecting it here
        makes the planner repair a missing detect/track/event condition instead
        of leaving an attractive-looking draft that cannot compile in 03.
        """

        typed_source_parameters = {
            "source",
            "subject",
            "object",
            "attributes",
            "equipment",
        }
        for branch in self.branches:
            for condition in _walk_draft_conditions(branch.conditions):
                if condition.operator != "ATOM":
                    continue
                for parameter in typed_source_parameters:
                    value = condition.parameters.get(parameter)
                    values = value if isinstance(value, list) else [value]
                    if "full_frame" in values:
                        raise ValueError(
                            f"{branch.name}/{condition.name} 的 {parameter} 必须引用"
                            "前序条件或分支结果；full_frame 只能用于 scope。"
                        )
        return self

    @model_validator(mode="after")
    def validate_declared_media_flows(self):
        selected_media = {item.media_type for item in self.branches}
        selected_media.update(item.media_type for item in self.patterns)
        expected = {
            "image": {"image"},
            "video": {"video"},
            "both": {"image", "video"},
        }[self.media_requirement]
        if selected_media != expected:
            raise ValueError(
                f"media_requirement={self.media_requirement} 必须生成 "
                f"{sorted(expected)} 分支，实际为 {sorted(selected_media)}。"
            )
        branch_media = {item.key: item.media_type for item in self.branches}
        video_only_capabilities = {
            "motion.track",
            "motion.direction",
            "motion.wrong_way",
            "motion.speed",
            "state.transition",
        }
        for branch in self.branches:
            if branch.media_type != "image":
                continue
            if branch.time.mode != "immediate":
                raise ValueError(
                    f"图片分支“{branch.name}”只能立即判断，不能配置持续或窗口时间。"
                )
            invalid = {
                condition.capability_id
                for condition in _walk_draft_conditions(branch.conditions)
                if condition.capability_id in video_only_capabilities
            }
            if invalid:
                raise ValueError(
                    f"图片分支“{branch.name}”包含仅视频能力："
                    + "、".join(sorted(invalid))
                )
        for pattern in self.patterns:
            unknown = set(pattern.branch_keys) - set(branch_media)
            if unknown:
                raise ValueError(
                    "复杂事件引用未知分支：" + "、".join(sorted(unknown))
                )
            if any(branch_media[key] != "video" for key in pattern.branch_keys):
                raise ValueError(
                    f"复杂事件“{pattern.name}”只能引用同一视频流程的分支。"
                )
        return self


DraftCondition.model_rebuild()


_RESULT_SCHEMA = {
    "decision": ("decision", "single", "status"),
    "boolean": ("boolean", "single", "status"),
    "count": ("scalar", "single", "count"),
    "value": ("scalar", "single", "value"),
    "entities": ("entity_set", "list", "entities"),
    "tracks": ("track_set", "list", "tracks"),
    "events": ("event_set", "list", "events"),
    "duration": ("scalar", "single", "duration"),
    "timeline": ("timeline", "series", "stages"),
    "media": ("media", "single", "media"),
}


def _safe_id(prefix: str, key: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", key).strip("_")
    if not value or not value[0].isalpha():
        value = "item_" + value
    return f"{prefix}_{value}"[:180]


def _walk_draft_conditions(items: list[DraftCondition]):
    for item in items:
        yield item
        yield from _walk_draft_conditions(item.children)


def apply_business_rule_draft(
    document: SkillEditorDocument,
    draft: NaturalLanguageBusinessDraft | dict[str, Any],
    capabilities: BusinessCapabilityRegistry,
    *,
    requested_accept: list[str],
    final_display_name: str | None = None,
) -> SkillEditorDocument:
    """Validate and install an LLM business draft into the sole editor document."""

    draft = NaturalLanguageBusinessDraft.model_validate(draft)
    requested = set(requested_accept)
    branch_keys = {item.key for item in draft.branches}
    if len(branch_keys) != len(draft.branches):
        raise BusinessDraftError("LLM 生成了重复的条件分支键。")
    condition_ids = {
        (branch.key, condition.key): _safe_id(
            f"condition_{branch.key}", condition.key
        )
        for branch in draft.branches
        for condition in _walk_draft_conditions(branch.conditions)
    }
    if len(condition_ids) != sum(
        1
        for branch in draft.branches
        for _ in _walk_draft_conditions(branch.conditions)
    ):
        raise BusinessDraftError("同一分支中存在重复条件键。")
    branch_ids = {item.key: _safe_id("branch", item.key) for item in draft.branches}
    pattern_ids = {item.key: _safe_id("pattern", item.key) for item in draft.patterns}
    resource_ids = {
        item.key: _safe_id("resource", item.key) for item in draft.resources
    }
    result_ids = {item.key: _safe_id("result", item.key) for item in draft.results}

    selected_media = {item.media_type for item in draft.branches}
    selected_media.update(item.media_type for item in draft.patterns)
    if not selected_media.issubset(requested):
        missing = "、".join(sorted(selected_media - requested))
        raise BusinessDraftError(
            f"任务需要 {missing}，与用户选择的媒体能力冲突。"
        )
    if draft.media_requirement == "image" and selected_media != {"image"}:
        raise BusinessDraftError("LLM 的媒体结论与分支媒体不一致。")
    if draft.media_requirement == "video" and selected_media != {"video"}:
        raise BusinessDraftError("LLM 的媒体结论与分支媒体不一致。")
    if draft.media_requirement == "both" and selected_media != {"image", "video"}:
        raise BusinessDraftError(
            "声明图片和视频均支持时，必须分别生成可审核的图片与视频分支。"
        )

    result = document.model_copy(deep=True)
    template = result.skill_template
    template.rule_graphs = {item: RuleGraph() for item in sorted(selected_media)}
    template.rule_graph = template.rule_graphs[
        "video" if "video" in template.rule_graphs else "image"
    ]
    template.business_branches = []
    template.event_patterns = []
    template.result_specs = []
    template.presentation_specs = []
    template.final_decision = None
    template.resource_requirements = []
    template.pending_decisions = []
    result.scene_profiles = []
    result.active_scene_profile_id = None
    result.effective_skill_package = None

    for resource in draft.resources:
        if not set(resource.media_types).issubset(requested):
            raise BusinessDraftError(
                f"场景资源“{resource.name}”与用户选择的媒体能力冲突。"
            )
        source_id = (
            resource_ids.get(resource.paired_region_key or "")
            if resource.paired_region_key
            else None
        )
        template.resource_requirements.append(
            ResourceRequirement(
                requirement_id=resource_ids[resource.key],
                resource_type=(
                    "region_collection"
                    if resource.resource_type == "region"
                    else "direction_collection"
                ),
                display_name=resource.name,
                semantic_role=resource.semantic_role,
                cardinality=(
                    CardinalitySpec(
                        mode="match_collection", source_requirement_id=source_id
                    )
                    if source_id
                    else CardinalitySpec(
                        mode="dynamic", minimum=resource.minimum_items
                    )
                ),
                binding_policy="for_each",
                allowed_shapes=(
                    ["rectangle", "polygon"]
                    if resource.resource_type == "region"
                    else []
                ),
                pairing_policy="one_per_region" if source_id else "none",
                required_before="run",
                media_types=resource.media_types,
            )
        )

    def resolve_ref(reference: str, current_branch: str | None = None) -> str:
        if reference == "full_frame":
            return reference
        if ":" not in reference:
            return reference
        prefix, key = reference.split(":", 1)
        if prefix == "branch":
            if key not in branch_ids:
                raise BusinessDraftError(f"引用了不存在的分支：{key}")
            return f"branch:{branch_ids[key]}"
        if prefix == "condition":
            branch_key, condition_key = (
                key.split(".", 1) if "." in key else (current_branch, key)
            )
            condition_id = condition_ids.get((branch_key, condition_key))
            if condition_id is None:
                raise BusinessDraftError(f"引用了不存在的条件：{key}")
            return f"condition:{condition_id}"
        if prefix in {"resource", "region", "direction"}:
            if key not in resource_ids:
                raise BusinessDraftError(f"引用了不存在的场景资源：{key}")
            return resource_ids[key]
        if prefix == "event":
            if key not in pattern_ids:
                raise BusinessDraftError(f"引用了不存在的复杂事件：{key}")
            return f"event:{pattern_ids[key]}"
        if prefix == "result":
            if key not in result_ids:
                raise BusinessDraftError(f"引用了不存在的业务输出：{key}")
            return f"result:{result_ids[key]}"
        if prefix == "final":
            return "final:primary"
        return reference

    def transform(value: Any, branch_key: str) -> Any:
        if isinstance(value, str):
            return resolve_ref(value, branch_key)
        if isinstance(value, list):
            return [transform(item, branch_key) for item in value]
        if isinstance(value, dict):
            return {key: transform(item, branch_key) for key, item in value.items()}
        return value

    for branch in draft.branches:
        def build_expression(condition: DraftCondition) -> ConditionExpression:
            expression_id = condition_ids[(branch.key, condition.key)]
            if condition.operator != "ATOM":
                return ConditionExpression(
                    expression_id=expression_id,
                    operator=condition.operator,
                    display_name=condition.name,
                    children=[build_expression(child) for child in condition.children],
                    required_count=(
                        condition.required_count
                        if condition.operator == "N_OF_M"
                        else None
                    ),
                )
            assert condition.capability_id is not None
            try:
                definition = capabilities.require(condition.capability_id)
            except KeyError as exc:
                raise BusinessDraftError(
                    f"LLM 使用了未注册业务能力：{condition.capability_id}"
                ) from exc
            if branch.media_type not in definition.media_requirements:
                raise BusinessDraftError(
                    f"“{condition.name}”仅适用于{'/'.join(definition.media_requirements)}，"
                    f"不能放入 {branch.media_type} 分支。"
                )
            parameters = {
                item.parameter_id: item.default
                for item in definition.parameters
                if item.default is not None
            }
            parameters.update(transform(condition.parameters, branch.key))
            expression = ConditionExpression(
                expression_id=expression_id,
                operator="ATOM",
                display_name=condition.name,
                capability_id=condition.capability_id,
                parameters=parameters,
                parameter_sources={
                    key: ResolvableValue(
                        state="inferred",
                        value=value,
                        source="llm_business_draft",
                        required_before="never",
                    )
                    for key, value in parameters.items()
                    if value is not None
                },
            )
            if condition.negated:
                expression = ConditionExpression(
                    expression_id=_safe_id(
                        f"condition_{branch.key}", f"not_{condition.key}"
                    ),
                    operator="NOT",
                    display_name=f"非：{condition.name}",
                    children=[expression],
                )
            return expression

        expressions = [build_expression(item) for item in branch.conditions]
        root = expressions[0]
        if len(expressions) > 1:
            root = ConditionExpression(
                expression_id=_safe_id("group", branch.key),
                operator=branch.logic,
                display_name=f"{branch.name}条件组",
                children=expressions,
                required_count=(
                    branch.required_count if branch.logic == "N_OF_M" else None
                ),
            )
        qualifiers = []
        if branch.time.mode != "immediate":
            time = branch.time
            if time.mode in {"continuous", "cumulative"} and time.duration_seconds is None:
                raise BusinessDraftError(f"分支“{branch.name}”缺少持续/累计时间。")
            if time.mode in {"cumulative", "ratio"} and time.observation_window_seconds is None:
                raise BusinessDraftError(f"分支“{branch.name}”缺少观察窗口。")
            qualifiers.append(
                TemporalQualifierSpec(
                    qualifier_id=_safe_id("time", branch.key),
                    display_name=f"{branch.name}时间约束",
                    target_ref=f"branch:{branch_ids[branch.key]}",
                    mode=branch.time.mode,
                    duration_seconds=(
                        ResolvableValue(
                            state="explicit",
                            value=branch.time.duration_seconds,
                            source="llm_business_draft",
                        )
                        if branch.time.mode in {"continuous", "cumulative"}
                        else ResolvableValue(
                            state="not_applicable",
                            value=None,
                            source="system",
                            required_before="never",
                        )
                    ),
                    observation_window_seconds=(
                        ResolvableValue(
                            state="explicit",
                            value=branch.time.observation_window_seconds,
                            source="llm_business_draft",
                        )
                        if branch.time.mode in {"cumulative", "ratio"}
                        else ResolvableValue(
                            state="not_applicable",
                            value=None,
                            source="system",
                            required_before="never",
                        )
                    ),
                    required_ratio=branch.time.required_ratio,
                    allowed_gap_seconds=branch.time.allowed_gap_seconds,
                    identity_scope=branch.time.identity_scope,
                )
            )
        template.business_branches.append(
            BusinessBranch(
                branch_id=branch_ids[branch.key],
                display_name=branch.name,
                media_type=branch.media_type,
                condition_root=root,
                temporal_qualifiers=qualifiers,
            )
        )

    for pattern in draft.patterns:
        unknown = set(pattern.branch_keys) - branch_keys
        if unknown:
            raise BusinessDraftError(
                "复杂事件引用未知分支：" + "、".join(sorted(unknown))
            )
        selected = [
            item for item in draft.branches if item.key in pattern.branch_keys
        ]
        if any(item.media_type != "video" for item in selected):
            raise BusinessDraftError("复杂事件阶段必须全部属于同一视频流程。")
        stages = [
            PatternStage(
                stage_id=_safe_id("stage", key),
                display_name=next(item.name for item in selected if item.key == key),
                source_rule_id=branch_ids[key],
                source_ref=f"branch:{branch_ids[key]}",
            )
            for key in pattern.branch_keys
        ]
        transitions = []
        gateways = []
        if pattern.mode == "sequence":
            if len(stages) < 2:
                raise BusinessDraftError("顺序事件至少需要两个阶段。")
            transitions = [
                PatternTransition(
                    source_stage_id=stages[index].stage_id,
                    target_stage_id=stages[index + 1].stage_id,
                    maximum_delay_seconds=(
                        ResolvableValue(
                            state="explicit",
                            value=pattern.window_seconds,
                            source="llm_business_draft",
                        )
                        if pattern.window_seconds is not None
                        else ResolvableValue(
                            state="unresolved",
                            source="llm_business_draft",
                            recommended_value=60.0,
                            reason="顺序事件未给出阶段时间窗",
                            required_before="run",
                        )
                    ),
                )
                for index in range(len(stages) - 1)
            ]
        elif pattern.mode not in {"absence", "repeat"}:
            if len(stages) < 2:
                raise BusinessDraftError("多分支汇合至少需要两个分支。")
            gateways = [
                PatternGateway(
                    gateway_id=_safe_id("gateway", pattern.key),
                    mode=pattern.mode,
                    stage_ids=[item.stage_id for item in stages],
                    required_count=pattern.required_count,
                    window_seconds=(
                        ResolvableValue(
                            state="explicit",
                            value=pattern.window_seconds,
                            source="llm_business_draft",
                        )
                        if pattern.window_seconds is not None
                        else ResolvableValue(
                            state="not_applicable",
                            value=None,
                            source="system",
                            required_before="never",
                        )
                    ),
                )
            ]
        template.event_patterns.append(
            EventPattern(
                pattern_id=pattern_ids[pattern.key],
                display_name=pattern.name,
                media_type=pattern.media_type,
                pattern_type=(
                    pattern.mode
                    if pattern.mode in {"sequence", "absence", "repeat"}
                    else "join"
                ),
                stages=stages,
                transitions=transitions,
                gateways=gateways,
                correlation=CorrelationPolicy(scope=pattern.correlation_scope),
                instance_policy=InstancePolicy(),
                parameters={
                    "window_seconds": pattern.window_seconds,
                    "minimum_count": pattern.required_count,
                },
            )
        )

    for index, item in enumerate(draft.results):
        semantic_type, value_shape, projection = _RESULT_SCHEMA[item.result_kind]
        source_ref = resolve_ref(item.source_ref)
        scoped_media = source_media_types(template, source_ref) or set(selected_media)
        template.result_specs.append(
            ResultSpec(
                result_id=result_ids[item.key],
                display_name=item.name,
                semantic_type=semantic_type,
                value_shape=value_shape,
                source_ref=source_ref,
                media_types=sorted(scoped_media),  # type: ignore[arg-type]
                projection=ResultProjection(kind=projection),
                unit=item.unit,
                evidence_policy=item.evidence_policy,
                save_policy=item.save_policy,
                empty_policy="zero" if item.result_kind == "count" else "empty",
            )
        )
        template.presentation_specs.append(
            PresentationSpec(
                result_id=result_ids[item.key],
                preferred_renderer="generic.summary",
                show_in_overview=item.show_in_overview,
                display_order=index,
            )
        )

    final_sources = [resolve_ref(item) for item in draft.final_decision.source_refs]
    media_source_refs = partition_source_refs(
        template, final_sources, sorted(selected_media)
    )
    if any(media_type not in media_source_refs for media_type in selected_media):
        raise BusinessDraftError(
            "最终判定必须为每个图片/视频流程至少提供一个同媒体来源。"
        )
    template.final_decision = FinalDecisionSpec(
        decision_id="primary",
        display_name=(final_display_name or draft.final_decision.name).strip(),
        decision_type=draft.final_decision.decision_type,
        source_ref=final_sources[0],
        source_refs=final_sources,
        media_source_refs=media_source_refs,  # type: ignore[arg-type]
        combination=draft.final_decision.combination,
        required_count=draft.final_decision.required_count,
    )

    for pending in draft.pending_decisions:
        affected = []
        for reference in pending.affected_refs:
            resolved = resolve_ref(reference)
            affected.append(resolved.split(":", 1)[-1])
        template.pending_decisions.append(
            PendingDecision(
                decision_id=_safe_id("pending", pending.key),
                parameter_kind=pending.kind,
                prompt=pending.prompt,
                resolution=ResolvableValue(
                    state="unresolved",
                    source="llm_business_draft",
                    recommended_value=pending.recommended_value,
                    reason=pending.reason,
                    required_before=pending.required_before,
                ),
                affected_ids=affected,
            )
        )

    trigger = draft.trigger_policy
    template.trigger_policy = TriggerPolicy(
        mode=trigger.get("mode", "once"),
        cooldown_seconds=float(trigger.get("cooldown_seconds", 0.0)),
        severity=trigger.get("severity", "medium"),
        outputs=trigger.get("outputs", ["event_record", "annotated_media"]),
    )
    result.version += 1
    result.validation_report = {
        "valid": not bool(template.pending_decisions),
        "can_run": False,
        "source": "llm_business_draft",
        "pending": [item.decision_id for item in template.pending_decisions],
    }
    return refresh_document_hashes(result)


__all__ = [
    "BusinessDraftError",
    "NaturalLanguageBusinessDraft",
    "apply_business_rule_draft",
]
