from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .schema import CanonicalSemanticIR, MediaType, SkillPackage, StrictModel

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


class ResultSpec(StrictModel):
    result_id: str = Field(min_length=1)
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
    ]
    display_name: str = Field(min_length=1)
    required_outputs: list[str] = Field(default_factory=list)
    evidence_policy: Literal["required", "optional", "none"] = "optional"


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
    output_name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    parameter_sources: dict[str, ResolvableValue] = Field(default_factory=dict)
    enabled: bool = True


class RuleEdge(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    port: str | None = None


class RuleGraph(StrictModel):
    nodes: list[RuleNode] = Field(default_factory=list)
    edges: list[RuleEdge] = Field(default_factory=list)


class BusinessBranch(StrictModel):
    branch_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    media_type: MediaType
    node_ids: list[str] = Field(default_factory=list)
    root_node_id: str | None = None
    enabled: bool = True
    description: str | None = None


class PatternStage(StrictModel):
    stage_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    source_rule_id: str = Field(min_length=1)
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
    stages: list[PatternStage] = Field(min_length=1)
    transitions: list[PatternTransition] = Field(default_factory=list)
    gateways: list[PatternGateway] = Field(default_factory=list)
    correlation: CorrelationPolicy = Field(default_factory=CorrelationPolicy)
    instance_policy: InstancePolicy = Field(default_factory=InstancePolicy)
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
    resource_requirements: list[ResourceRequirement] = Field(default_factory=list)
    pending_decisions: list[PendingDecision] = Field(default_factory=list)
    recipe_refs: list[str] = Field(default_factory=list)


class CompatibilityInfo(StrictModel):
    editability: Literal["full", "partial", "legacy_atomic_only"] = "full"
    issues: list[str] = Field(default_factory=list)


class SkillEditorDocument(StrictModel):
    schema_version: Literal["3.0"] = "3.0"
    version: int = Field(default=1, ge=1)
    skill_template: SkillTemplate
    scene_profiles: list[SceneProfile] = Field(default_factory=list)
    active_scene_profile_id: str | None = None
    user_overrides: list[UserOverride] = Field(default_factory=list)
    atomic_plan: dict[str, Any] = Field(default_factory=dict)
    effective_skill_package: SkillPackage | None = None
    validation_report: dict[str, Any] = Field(default_factory=dict)
    compatibility: CompatibilityInfo = Field(default_factory=CompatibilityInfo)

    @model_validator(mode="after")
    def validate_active_profile(self):
        if self.active_scene_profile_id is not None and self.active_scene_profile_id not in {
            profile.scene_profile_id for profile in self.scene_profiles
        }:
            raise ValueError("active_scene_profile_id does not exist")
        return self


__all__ = [
    "BusinessBranch",
    "CardinalitySpec",
    "CompatibilityInfo",
    "CorrelationPolicy",
    "EventPattern",
    "InstancePolicy",
    "PatternGateway",
    "PatternStage",
    "PatternTransition",
    "PendingDecision",
    "ResolvableValue",
    "ResourceCollection",
    "ResourceInstance",
    "ResourceRequirement",
    "ResultSpec",
    "RuleEdge",
    "RuleGraph",
    "RuleNode",
    "SceneProfile",
    "SkillEditorDocument",
    "SkillTemplate",
    "UserOverride",
]
