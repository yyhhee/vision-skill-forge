from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .result_presentation_schema import PresentationSpec
from .schema import (
    CanonicalSemanticIR,
    ConfigurationSlot,
    MediaType,
    SkillPackage,
    StrictModel,
)


CURRENT_EDITOR_SCHEMA_VERSION = "3.2"

ResolutionState = Literal[
    "explicit",
    "defaulted",
    "inferred",
    "unresolved",
    "runtime_derived",
    "not_applicable",
]
RequiredBefore = Literal["compile", "run", "publish", "never"]


class ResolvableValue(StrictModel):
    state: ResolutionState
    value: Any = None
    source: str = "system"
    source_span: str | None = None
    recommended_value: Any = None
    alternatives: list[Any] = Field(default_factory=list)
    reason: str | None = None
    required_before: RequiredBefore = "run"

    @model_validator(mode="after")
    def validate_resolution(self):
        if self.state in {"explicit", "defaulted", "inferred"} and self.value is None:
            raise ValueError(f"{self.state} value requires a concrete value")
        if self.state == "unresolved" and not self.reason:
            raise ValueError("unresolved value requires a reason")
        return self

    def resolved(self, value: Any, *, source: str = "user") -> ResolvableValue:
        return self.model_copy(
            update={"state": "explicit", "value": value, "source": source, "reason": None}
        )

    def blocks(self, gate: Literal["compile", "run", "publish"]) -> bool:
        if self.state != "unresolved":
            return False
        order = {"compile": 0, "run": 1, "publish": 2, "never": 3}
        return order[self.required_before] <= order[gate]


class ResultProjection(StrictModel):
    kind: Literal[
        "identity",
        "status",
        "count",
        "value",
        "duration",
        "entities",
        "tracks",
        "events",
        "stages",
        "resource",
        "media",
    ] = "identity"
    parameters: dict[str, Any] = Field(default_factory=dict)


class ResultLabelPolicy(StrictModel):
    business_label: str | None = None
    preserve_model_label: bool = True
    fallback_to_model_label: bool = True


class ResultSpec(StrictModel):
    result_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    semantic_type: Literal[
        "decision",
        "boolean",
        "scalar",
        "entity_set",
        "track_set",
        "event_set",
        "timeline",
        "resource",
        "media",
    ] = "scalar"
    value_shape: Literal["single", "list", "grouped", "interval", "series"] = "single"
    source_ref: str | None = Field(
        default=None,
        pattern=r"^(final|branch|condition|event|measurement|resource|result|node|output):[^:]+(?:[:][^:]+)*$",
    )
    # Empty keeps historical package-global behavior. New business drafts
    # populate this when a skill owns independent image and video variants.
    media_types: list[MediaType] = Field(default_factory=list)
    projection: ResultProjection = Field(default_factory=ResultProjection)
    unit: str | None = None
    grouping: list[str] = Field(default_factory=list)
    condition_snapshot_policy: Literal["none", "on_result", "always"] = "on_result"
    label_policy: ResultLabelPolicy = Field(default_factory=ResultLabelPolicy)
    save_policy: Literal["always", "on_change", "on_match", "never"] = "always"
    evidence_policy: Literal["required", "optional", "none"] = "optional"
    empty_policy: Literal[
        "empty",
        "not_satisfied",
        "not_evaluable",
        "zero",
        "hide",
    ] = "empty"

    # Compatibility-only fields from SkillEditorDocument@3.0. They remain
    # readable until all historical documents have been migrated.
    result_type: Literal[
        "boolean",
        "object_list",
        "count",
        "measurement",
        "direction",
        "track",
        "event",
        "timeline",
        "notification",
        "annotated_media",
    ] | None = None
    required_outputs: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_result_type(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy = data.get("result_type")
        mapping = {
            "boolean": ("boolean", "single", "status"),
            "object_list": ("entity_set", "list", "entities"),
            "count": ("scalar", "single", "count"),
            "measurement": ("scalar", "single", "value"),
            "direction": ("scalar", "single", "value"),
            "track": ("track_set", "list", "tracks"),
            "event": ("event_set", "list", "events"),
            "timeline": ("timeline", "series", "stages"),
            "notification": ("decision", "single", "status"),
            "annotated_media": ("media", "single", "media"),
        }
        if legacy in mapping:
            semantic_type, value_shape, projection = mapping[legacy]
            data.setdefault("semantic_type", semantic_type)
            data.setdefault("value_shape", value_shape)
            data.setdefault("projection", {"kind": projection})
        return data

    @model_validator(mode="after")
    def validate_semantic_contract(self):
        projection_semantics = {
            "status": {"decision", "boolean"},
            "count": {"scalar"},
            "value": {"scalar"},
            "duration": {"scalar"},
            "entities": {"entity_set"},
            "tracks": {"track_set"},
            "events": {"event_set"},
            "stages": {"timeline"},
            "resource": {"resource"},
            "media": {"media"},
        }
        accepted = projection_semantics.get(self.projection.kind)
        if accepted is not None and self.semantic_type not in accepted:
            raise ValueError(
                f"结果“{self.display_name}”的内容类型与取值方式不一致"
            )
        accepted_shapes = {
            "decision": {"single", "series"},
            "boolean": {"single", "series"},
            "scalar": {"single", "grouped", "series"},
            "entity_set": {"list", "grouped"},
            "track_set": {"list", "grouped"},
            "event_set": {"list", "grouped", "interval"},
            "timeline": {"list", "interval", "series"},
            "resource": {"single", "list", "grouped"},
            # V3 一次运行只消费一个媒体源，因此媒体结果也是单值。
            "media": {"single"},
        }
        if self.value_shape not in accepted_shapes[self.semantic_type]:
            raise ValueError(
                f"结果“{self.display_name}”的内容类型与结果结构不一致"
            )
        if self.grouping and self.value_shape not in {"list", "grouped", "series"}:
            raise ValueError(
                f"结果“{self.display_name}”不是可分组结构，不能设置分组字段"
            )
        return self


class RuleNode(StrictModel):
    node_id: str = Field(min_length=1)
    kind: Literal[
        "target",
        "attribute",
        "binding",
        "scope",
        "region",
        "relation",
        "exclusion",
        "aggregate",
        "condition",
        "logic_group",
        "temporal_qualifier",
        "output",
    ]
    display_name: str = Field(min_length=1)
    operator: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+$"
    )
    input_bindings: dict[str, str | list[str]] = Field(default_factory=dict)
    semantic_atom_ids: list[str] = Field(default_factory=list)
    business_source_refs: list[str] = Field(default_factory=list)
    output_name: str | None = None
    output_names: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    parameter_sources: dict[str, ResolvableValue] = Field(default_factory=dict)
    # Configuration slots are part of the deterministic compiler contract.
    # They are not shown as editable node metadata in the product UI, but they
    # must survive package import -> business edit -> package recompile so 02
    # annotations continue to bind to the same business resource.
    configuration_slots: list[ConfigurationSlot] = Field(default_factory=list)
    enabled: bool = True


class RuleEdge(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    port: str | None = None


class RuleGraph(StrictModel):
    nodes: list[RuleNode] = Field(default_factory=list)
    edges: list[RuleEdge] = Field(default_factory=list)


class ConditionExpression(StrictModel):
    expression_id: str = Field(min_length=1)
    operator: Literal["ATOM", "AND", "OR", "NOT", "N_OF_M"]
    display_name: str = Field(min_length=1)
    capability_id: str | None = None
    source_ref: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_sources: dict[str, ResolvableValue] = Field(default_factory=dict)
    children: list["ConditionExpression"] = Field(default_factory=list)
    required_count: int | None = Field(default=None, ge=1)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_expression(self):
        if self.operator == "ATOM":
            if self.children:
                raise ValueError("ATOM condition cannot contain children")
            if not self.capability_id and not self.source_ref:
                raise ValueError("ATOM condition requires capability_id or source_ref")
        elif self.operator == "NOT":
            if len(self.children) != 1:
                raise ValueError("NOT condition requires exactly one child")
        elif self.operator in {"AND", "OR"}:
            if len(self.children) < 2:
                raise ValueError(
                    f"{self.operator} condition requires at least two children"
                )
        elif self.operator == "N_OF_M":
            if len(self.children) < 2 or self.required_count is None:
                raise ValueError("N_OF_M condition requires children and required_count")
            if self.required_count > len(self.children):
                raise ValueError("required_count cannot exceed child count")
        return self


class TemporalQualifierSpec(StrictModel):
    qualifier_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    target_ref: str = Field(
        pattern=r"^(condition|branch|event):[^:]+(?:[:][^:]+)*$"
    )
    mode: Literal[
        "immediate",
        "continuous",
        "cumulative",
        "ratio",
        "valid_for",
        "repeat",
    ] = "immediate"
    duration_seconds: ResolvableValue = Field(
        default_factory=lambda: ResolvableValue(
            state="not_applicable",
            value=None,
            source="system",
            required_before="never",
        )
    )
    observation_window_seconds: ResolvableValue = Field(
        default_factory=lambda: ResolvableValue(
            state="not_applicable",
            value=None,
            source="system",
            required_before="never",
        )
    )
    allowed_gap_seconds: float = Field(default=0.0, ge=0)
    required_ratio: float = Field(default=1.0, ge=0, le=1)
    minimum_occurrences: int = Field(default=1, ge=1)
    identity_scope: Literal[
        "global", "object", "track", "pair", "region"
    ] = "global"
    emission: Literal["first", "repeat", "on_change"] = "first"
    enabled: bool = True

    @model_validator(mode="after")
    def validate_temporal_values(self):
        if self.mode in {"continuous", "cumulative", "valid_for"}:
            if self.duration_seconds.state == "not_applicable":
                raise ValueError(f"{self.mode} requires duration_seconds")
        if self.mode in {"cumulative", "ratio", "repeat"}:
            if self.observation_window_seconds.state == "not_applicable":
                raise ValueError(
                    f"{self.mode} requires observation_window_seconds"
                )
        return self


class BranchValidityPolicy(StrictModel):
    mode: Literal["current_frame", "event_interval", "hold_for", "until_reset"] = (
        "current_frame"
    )
    hold_seconds: ResolvableValue = Field(
        default_factory=lambda: ResolvableValue(
            state="not_applicable",
            value=None,
            source="system",
            required_before="never",
        )
    )
    reset_source_ref: str | None = Field(
        default=None,
        pattern=r"^(condition|branch|event):[^:]+(?:[:][^:]+)*$",
    )

    @model_validator(mode="after")
    def validate_hold(self):
        if self.mode == "hold_for" and self.hold_seconds.state == "not_applicable":
            raise ValueError("hold_for requires hold_seconds")
        if self.mode == "until_reset" and not self.reset_source_ref:
            raise ValueError("until_reset requires reset_source_ref")
        return self


class BusinessBranch(StrictModel):
    branch_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    media_type: MediaType
    node_ids: list[str] = Field(default_factory=list)
    root_node_id: str | None = None
    condition_root: ConditionExpression | None = None
    temporal_qualifiers: list[TemporalQualifierSpec] = Field(default_factory=list)
    validity_policy: BranchValidityPolicy = Field(default_factory=BranchValidityPolicy)
    result_ids: list[str] = Field(default_factory=list)
    evidence_policy: Literal["required", "optional", "none"] = "optional"
    save_result: bool = True
    participates_in_final_decision: bool = True
    enabled: bool = True
    description: str | None = None


class FinalDecisionSpec(StrictModel):
    decision_id: str = Field(default="primary", min_length=1)
    display_name: str = Field(default="最终结果", min_length=1)
    decision_type: Literal[
        "event_decision",
        "detection_summary",
        "measurement_decision",
        "state_summary",
        "timeline_summary",
    ]
    source_ref: str = Field(
        pattern=r"^(branch|condition|event|measurement|result|node|output):[^:]+(?:[:][^:]+)*$"
    )
    source_refs: list[str] = Field(default_factory=list)
    media_source_refs: dict[MediaType, list[str]] = Field(default_factory=dict)
    combination: Literal["AND", "OR", "N_OF_M"] = "AND"
    required_count: int | None = Field(default=None, ge=1)
    success_condition: dict[str, Any] = Field(default_factory=dict)
    show_reason: bool = True
    show_failed_or_pending_branches: bool = True
    overview_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_sources(self):
        if not self.source_refs:
            self.source_refs = [self.source_ref]
        if self.source_ref not in self.source_refs:
            self.source_refs.insert(0, self.source_ref)
        if self.combination == "N_OF_M":
            if self.required_count is None:
                raise ValueError("N_OF_M final decision requires required_count")
            if self.required_count > len(self.source_refs):
                raise ValueError("final required_count exceeds source count")
            if any(
                self.required_count > len(items)
                for items in self.media_source_refs.values()
            ):
                raise ValueError(
                    "final required_count exceeds a media variant source count"
                )
        if any(not items for items in self.media_source_refs.values()):
            raise ValueError("media-specific final decision sources cannot be empty")
        return self


class TriggerPolicy(StrictModel):
    mode: Literal["none", "once", "repeat", "on_change"] = "none"
    trigger_moment: Literal[
        "first_satisfied",
        "each_event_instance",
        "false_to_true",
        "while_satisfied",
    ] = "first_satisfied"
    repeat_policy: Literal[
        "first_only", "allow_repeat", "after_reset", "once_per_subject"
    ] = "first_only"
    cooldown_seconds: float = Field(default=0.0, ge=0)
    cooldown_scope: Literal[
        "global", "object", "track", "pair", "region", "event_instance"
    ] = "global"
    severity: Literal["info", "low", "medium", "high", "critical"] = "medium"
    outputs: list[Literal["event_record", "annotated_media", "notification"]] = Field(
        default_factory=lambda: ["event_record"]
    )
    notification_channels: list[str] = Field(default_factory=list)
    evidence_capture: Literal[
        "key_frame", "event_clip", "full_interval", "structured_only"
    ] = "key_frame"
    pre_roll_seconds: float = Field(default=0.0, ge=0)
    post_roll_seconds: float = Field(default=0.0, ge=0)
    maximum_clip_seconds: float | None = Field(default=None, gt=0)
    deduplication_scope: Literal[
        "event_instance", "object", "track", "pair", "region", "custom"
    ] = "event_instance"
    emit_recovery: bool = False


class PatternStage(StrictModel):
    stage_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    source_rule_id: str = Field(min_length=1)
    source_ref: str | None = Field(
        default=None,
        pattern=r"^(branch|condition|event):[^:]+(?:[:][^:]+)*$",
    )
    duration: ResolvableValue = Field(
        default_factory=lambda: ResolvableValue(
            state="defaulted", value=0.0, source="system", recommended_value=0.0
        )
    )
    persist_mode: Literal["immediate", "continuous", "cumulative", "ratio"] = (
        "immediate"
    )
    identity_scope: Literal[
        "global", "object", "track", "pair", "region", "camera", "scene"
    ] = "global"
    allowed_gap_seconds: float = Field(default=0.0, ge=0)
    observation_window_seconds: ResolvableValue = Field(
        default_factory=lambda: ResolvableValue(
            state="not_applicable", value=None, source="system", required_before="never"
        )
    )
    required_ratio: float = Field(default=1.0, ge=0, le=1)
    capture_fields: list[str] = Field(default_factory=list)


class PatternTransition(StrictModel):
    source_stage_id: str = Field(min_length=1)
    target_stage_id: str = Field(min_length=1)
    relation: Literal[
        "before", "after", "during", "contains", "overlaps", "until"
    ] = "after"
    source_anchor: Literal["start", "qualified", "end"] = "end"
    target_anchor: Literal["start", "qualified", "end"] = "end"
    minimum_delay_seconds: float = Field(default=0.0, ge=0)
    maximum_delay_seconds: ResolvableValue = Field(
        default_factory=lambda: ResolvableValue(
            state="not_applicable", value=None, source="system", required_before="never"
        )
    )
    timeout_behavior: Literal["fail", "emit_timeout", "reset"] = "fail"


class PatternGateway(StrictModel):
    gateway_id: str = Field(min_length=1)
    mode: Literal[
        "all_active",
        "all_completed",
        "all_completed_within_window",
        "any",
        "n_of_m",
        "exclusive",
        "overlap",
    ]
    stage_ids: list[str] = Field(min_length=1)
    required_count: int | None = Field(default=None, ge=1)
    window_seconds: ResolvableValue = Field(
        default_factory=lambda: ResolvableValue(
            state="not_applicable", value=None, source="system", required_before="never"
        )
    )

    @model_validator(mode="after")
    def validate_gateway(self):
        if self.mode == "n_of_m" and self.required_count is None:
            raise ValueError("n_of_m gateway requires required_count")
        if self.required_count is not None and self.required_count > len(self.stage_ids):
            raise ValueError("required_count cannot exceed stage count")
        return self


class CorrelationPolicy(StrictModel):
    scope: Literal[
        "global", "object", "track", "pair", "region", "camera", "scene", "field"
    ] = "global"
    fields: list[str] = Field(default_factory=list)


class InstancePolicy(StrictModel):
    allow_parallel_instances: bool = True
    maximum_active_per_key: int = Field(default=1, ge=1)
    consume_events: bool = True
    repeated_stage_selection: Literal["first", "latest", "best"] = "first"


class EventPattern(StrictModel):
    pattern_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    media_type: MediaType = "video"
    pattern_type: Literal["join", "sequence", "absence", "repeat"] = "join"
    stages: list[PatternStage] = Field(min_length=1)
    transitions: list[PatternTransition] = Field(default_factory=list)
    gateways: list[PatternGateway] = Field(default_factory=list)
    correlation: CorrelationPolicy = Field(default_factory=CorrelationPolicy)
    instance_policy: InstancePolicy = Field(default_factory=InstancePolicy)
    parameters: dict[str, Any] = Field(default_factory=dict)
    trigger_policy: dict[str, Any] = Field(default_factory=dict)


class CardinalitySpec(StrictModel):
    mode: Literal["exact", "dynamic", "match_collection"]
    minimum: int = Field(default=0, ge=0)
    maximum: int | None = Field(default=None, ge=1)
    exact: int | None = Field(default=None, ge=0)
    source_requirement_id: str | None = None

    @model_validator(mode="after")
    def validate_cardinality(self):
        if self.mode == "exact" and self.exact is None:
            raise ValueError("exact cardinality requires exact")
        if self.mode == "match_collection" and not self.source_requirement_id:
            raise ValueError("match_collection requires source_requirement_id")
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum cannot be lower than minimum")
        return self


class ResourceRequirement(StrictModel):
    requirement_id: str = Field(min_length=1)
    resource_type: Literal[
        "region", "region_collection", "direction", "direction_collection"
    ]
    display_name: str = Field(min_length=1)
    semantic_role: str = Field(min_length=1)
    cardinality: CardinalitySpec
    binding_policy: Literal[
        "direct", "for_each", "any", "all", "n_of_m", "aggregate", "selected"
    ] = "direct"
    allowed_shapes: list[Literal["rectangle", "polygon"]] = Field(default_factory=list)
    pairing_policy: Literal["none", "one_per_region"] = "none"
    required_before: RequiredBefore = "run"
    media_types: list[MediaType] = Field(default_factory=list)
    legacy_metadata: dict[str, Any] = Field(default_factory=dict)


def _resource_id() -> str:
    return "res_" + uuid4().hex


class ResourceInstance(StrictModel):
    resource_id: str = Field(default_factory=_resource_id, min_length=1)
    resource_type: Literal["region", "direction"]
    display_name: str = Field(min_length=1)
    semantic_role: str = Field(min_length=1)
    geometry: dict[str, Any]
    paired_resource_id: str | None = None
    legacy_metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceCollection(StrictModel):
    requirement_id: str = Field(min_length=1)
    items: list[ResourceInstance] = Field(default_factory=list)
    completed: bool = False


class SceneProfile(StrictModel):
    scene_profile_id: str = Field(default_factory=lambda: "scene_" + uuid4().hex)
    display_name: str = Field(min_length=1)
    media_fingerprint: str | None = None
    collections: list[ResourceCollection] = Field(default_factory=list)


class UserOverride(StrictModel):
    target_type: Literal["rule", "pattern", "atom"]
    target_id: str = Field(min_length=1)
    parameter: str = Field(min_length=1)
    value: Any
    source: Literal["user"] = "user"


class PendingDecision(StrictModel):
    decision_id: str = Field(min_length=1)
    parameter_kind: Literal[
        "target_class",
        "comparison_operator",
        "count_threshold",
        "duration",
        "time_window",
        "direction_reference",
        "correlation",
        "generic",
    ]
    prompt: str = Field(min_length=1)
    resolution: ResolvableValue
    affected_ids: list[str] = Field(default_factory=list)


class SkillTemplate(StrictModel):
    skill_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    display_name: str = Field(min_length=1)
    original_instruction: str = Field(min_length=1)
    source_type: Literal["natural_language", "preset", "legacy"]
    semantic_ir: CanonicalSemanticIR
    result_specs: list[ResultSpec] = Field(default_factory=list)
    rule_graph: RuleGraph = Field(default_factory=RuleGraph)
    rule_graphs: dict[MediaType, RuleGraph] = Field(default_factory=dict)
    business_branches: list[BusinessBranch] = Field(default_factory=list)
    event_patterns: list[EventPattern] = Field(default_factory=list)
    final_decision: FinalDecisionSpec | None = None
    resource_requirements: list[ResourceRequirement] = Field(default_factory=list)
    pending_decisions: list[PendingDecision] = Field(default_factory=list)
    recipe_refs: list[str] = Field(default_factory=list)
    trigger_policy: TriggerPolicy = Field(default_factory=TriggerPolicy)
    presentation_specs: list[PresentationSpec] = Field(default_factory=list)


class DocumentReadiness(StrictModel):
    draft_valid: bool = True
    review_complete: bool = False
    compile_valid: bool = False
    runtime_ready: bool = False
    publish_ready: bool = False
    reasons: list[str] = Field(default_factory=list)


class DocumentHashes(StrictModel):
    semantic_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compile_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    package_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    presentation_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CompatibilityInfo(StrictModel):
    editability: Literal["full", "partial", "legacy_atomic_only"] = "full"
    issues: list[str] = Field(default_factory=list)


class SkillEditorDocument(StrictModel):
    schema_version: Literal["3.0", "3.1", "3.2"] = CURRENT_EDITOR_SCHEMA_VERSION
    version: int = Field(default=1, ge=1)
    skill_template: SkillTemplate
    scene_profiles: list[SceneProfile] = Field(default_factory=list)
    active_scene_profile_id: str | None = None
    user_overrides: list[UserOverride] = Field(default_factory=list)
    atomic_plan: dict[str, Any] = Field(default_factory=dict)
    effective_skill_package: SkillPackage | None = None
    validation_report: dict[str, Any] = Field(default_factory=dict)
    compatibility: CompatibilityInfo = Field(default_factory=CompatibilityInfo)
    readiness: DocumentReadiness = Field(default_factory=DocumentReadiness)
    hashes: DocumentHashes = Field(default_factory=DocumentHashes)
    compiled_artifact_ref: str | None = None

    @model_validator(mode="after")
    def validate_active_profile(self):
        if self.active_scene_profile_id is not None and self.active_scene_profile_id not in {
            profile.scene_profile_id for profile in self.scene_profiles
        }:
            raise ValueError("active_scene_profile_id does not exist")
        return self


__all__ = [
    "BranchValidityPolicy",
    "BusinessBranch",
    "CardinalitySpec",
    "CompatibilityInfo",
    "ConditionExpression",
    "CorrelationPolicy",
    "CURRENT_EDITOR_SCHEMA_VERSION",
    "DocumentHashes",
    "DocumentReadiness",
    "EventPattern",
    "InstancePolicy",
    "FinalDecisionSpec",
    "PatternGateway",
    "PatternStage",
    "PatternTransition",
    "PendingDecision",
    "ResolvableValue",
    "ResourceCollection",
    "ResourceInstance",
    "ResourceRequirement",
    "ResultLabelPolicy",
    "ResultProjection",
    "ResultSpec",
    "RuleEdge",
    "RuleGraph",
    "RuleNode",
    "SceneProfile",
    "SkillEditorDocument",
    "SkillTemplate",
    "TriggerPolicy",
    "TemporalQualifierSpec",
    "UserOverride",
]
