from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillInput(StrictModel):
    accept: list[Literal["image", "video"]] = Field(min_length=1)


class SkillNode(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    op: str = Field(pattern=r"^[a-z][a-z0-9_.-]+@[0-9]+\.[0-9]+$")
    inputs: dict[str, str | list[str]] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class VisualSkillSpec(StrictModel):
    version: Literal["0.1"]
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    display_name: str = Field(min_length=1)
    original_instruction: str = Field(min_length=1)
    compile_status: Literal["compiled", "degraded"] = "compiled"
    input: SkillInput
    nodes: list[SkillNode] = Field(min_length=1)
    outputs: dict[str, str] = Field(min_length=1)


MediaType = Literal["image", "video"]


class VideoGuidance(StrictModel):
    recommended_max_duration_seconds: float = Field(default=30.0, gt=0)
    enforcement: Literal["warn_only"] = "warn_only"


class PackageInput(StrictModel):
    requested_accept: list[MediaType] = Field(min_length=1)
    accept: list[MediaType] = Field(min_length=1)
    video_guidance: VideoGuidance = Field(default_factory=VideoGuidance)

    @model_validator(mode="after")
    def validate_media_sets(self):
        if len(set(self.requested_accept)) != len(self.requested_accept):
            raise ValueError("requested_accept contains duplicate media")
        if len(set(self.accept)) != len(self.accept):
            raise ValueError("accept contains duplicate media")
        if not set(self.accept).issubset(self.requested_accept):
            raise ValueError("accept must be a subset of requested_accept")
        return self


class SemanticTargetClass(StrictModel):
    label: str = Field(min_length=1)
    phrases: list[str] = Field(min_length=1)


class SemanticTarget(StrictModel):
    concept: str = Field(min_length=1)
    source_span: str = Field(min_length=1)
    phrases: list[str] = Field(min_length=1)
    classes: list[SemanticTargetClass] = Field(default_factory=list)


class SemanticConstraint(StrictModel):
    atom_id: str | None = None
    kind: str = Field(min_length=1)
    value: Any
    source: str | None = None
    source_span: str = Field(min_length=1)
    polarity: Literal["required", "absent"] = "required"
    carrier: str | None = None
    carrier_span: str | None = None
    phrases: list[str] = Field(default_factory=list)
    temporal: bool = False


class UnresolvedSemantic(StrictModel):
    source_span: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CanonicalSemanticIR(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["direct_grounding", "entity_query", "workflow"]
    target: SemanticTarget
    constraints: list[SemanticConstraint] = Field(default_factory=list)
    logic: Literal["all", "any"] = "all"
    unresolved: list[UnresolvedSemantic] = Field(default_factory=list)
    semantic_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConfigurationBinding(StrictModel):
    node_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    parameter: str = Field(min_length=1)


class ConfigurationSlot(StrictModel):
    slot_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    kind: Literal["region", "region_set", "direction", "direction_set"]
    label: str = Field(min_length=1)
    required: bool = True
    binding: ConfigurationBinding
    allowed_shapes: list[Literal["rectangle", "polygon"]] = Field(
        default_factory=list
    )
    minimum_items: int = Field(default=1, ge=1)
    source_atom_ids: list[str] = Field(default_factory=list)
    help_text: str = ""
    active_when_op: list[str] | None = None
    key_source_slot_id: str | None = None


class WorkflowVariant(StrictModel):
    media_type: MediaType
    status: Literal[
        "executable", "unsupported", "degraded_semantics", "needs_configuration"
    ] = "executable"
    nodes: list[SkillNode] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    atom_bindings: dict[str, list[str]] = Field(default_factory=dict)
    configuration_slots: list[ConfigurationSlot] = Field(default_factory=list)
    issue: str | None = None

    @model_validator(mode="after")
    def validate_variant(self):
        if self.status == "unsupported":
            if self.nodes or self.outputs:
                raise ValueError("unsupported variant cannot contain executable workflow")
            if not self.issue:
                raise ValueError("unsupported variant requires an issue")
            return self
        if not self.nodes or not self.outputs:
            raise ValueError("executable variant requires nodes and outputs")
        expected = f"media.{self.media_type}"
        first_enabled = next((node for node in self.nodes if node.enabled), None)
        if first_enabled is None or not first_enabled.op.startswith(expected + "@"):
            raise ValueError(f"{self.media_type} variant must start from {expected}")
        return self


class CompatibilityIssue(StrictModel):
    media_type: MediaType
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class SkillPackage(StrictModel):
    schema_version: Literal["2.0"]
    skill_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    version: int = Field(ge=1)
    display_name: str = Field(min_length=1)
    original_instruction: str = Field(min_length=1)
    compile_status: Literal["compiled", "needs_review", "degraded"] = "compiled"
    input: PackageInput
    semantic_ir: CanonicalSemanticIR
    variants: dict[MediaType, WorkflowVariant]
    compatibility_issues: list[CompatibilityIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_variants(self):
        issues = {issue.media_type for issue in self.compatibility_issues}
        for media_type, variant in self.variants.items():
            if variant.media_type != media_type:
                raise ValueError(f"variant key {media_type} does not match media_type")
        for media_type in self.input.accept:
            variant = self.variants.get(media_type)
            if variant is None or variant.status not in {
                "executable", "degraded_semantics", "needs_configuration"
            }:
                raise ValueError(
                    f"accepted media {media_type} requires an executable variant"
                )
        for media_type in self.input.requested_accept:
            if media_type not in self.input.accept and media_type not in issues:
                raise ValueError(
                    f"requested but unsupported media {media_type} requires a compatibility issue"
                )
        return self

    def select_variant(self, media_type: MediaType) -> WorkflowVariant:
        if media_type not in self.input.accept:
            raise ValueError(f"{media_type} is not executable for this skill")
        variant = self.variants.get(media_type)
        if variant is None or variant.status not in {"executable", "degraded_semantics"}:
            raise ValueError(f"{media_type} is not executable for this skill")
        return variant


__all__ = [
    "CanonicalSemanticIR",
    "CompatibilityIssue",
    "ConfigurationBinding",
    "ConfigurationSlot",
    "MediaType",
    "PackageInput",
    "SemanticConstraint",
    "SemanticTarget",
    "SkillInput",
    "SkillPackage",
    "SkillNode",
    "UnresolvedSemantic",
    "ValidationError",
    "VideoGuidance",
    "VisualSkillSpec",
    "WorkflowVariant",
]
