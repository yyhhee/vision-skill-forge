from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Literal

from pydantic import Field, model_validator

from .business_capabilities import (
    BusinessCapabilityRegistry,
    BusinessParameterDefinition,
)
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


_DRAFT_PARAMETER_ALIASES: dict[str, dict[Any, Any]] = {
    "part": {
        "upper_body_clothing": "upper_clothing",
        "upper_body": "upper_clothing",
        "top": "upper_clothing",
        "lower_body_clothing": "lower_clothing",
        "lower_body": "lower_clothing",
        "pants": "lower_clothing",
    },
    "membership": {
        "inside": "center",
        "center_in_region": "center",
        "any_overlap": "overlap",
        "minimum_overlap": "overlap_ratio",
    },
    "inside": {"inside": True, "outside": False},
    "group_by": {
        "none": "total",
        "null": "total",
        "default": "total",
        "not_applicable": "total",
        "n/a": "total",
        "all": "total",
        "overall": "total",
        "total_count": "total",
        "by_total": "total",
        "object": "total",
        "target": "total",
        "person": "total",
        "people": "total",
        "class": "category",
        "label": "category",
        "by_category": "category",
        "scope": "region",
        "by_region": "region",
        "named_region": "region",
        "per_region": "region",
    },
    "operator": {
        "greater_than": ">",
        "greater_than_or_equal": ">=",
        "at_least": ">=",
        "equal": "==",
        "less_than_or_equal": "<=",
        "at_most": "<=",
        "less_than": "<",
        "not_equal": "!=",
    },
}


def _normalize_llm_parameter(
    parameter: BusinessParameterDefinition, value: Any
) -> Any:
    """Normalize LLM-friendly aliases to the user-facing capability schema."""

    if value is None:
        return None
    if parameter.editor in {
        "source_select",
        "scene_resource_select",
        "direction_resource_select",
    } and isinstance(value, list):
        if len(value) != 1:
            raise BusinessDraftError(f"{parameter.label}只能引用一个来源。")
        value = value[0]
    aliases = _DRAFT_PARAMETER_ALIASES.get(parameter.parameter_id, {})
    if aliases and value in aliases:
        value = aliases[value]
    if parameter.editor == "percentage":
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise BusinessDraftError(f"{parameter.label}必须是百分比数值。") from exc
        # The LLM may emit a 0..1 ratio although 03 consistently edits 0..100%.
        value = numeric * 100.0 if 0.0 <= numeric <= 1.0 else numeric
    if parameter.choices:
        values = value if isinstance(value, list) else [value]
        if not all(item in parameter.choices for item in values):
            raise BusinessDraftError(
                f"{parameter.label}收到不支持的值 {value!r}；只能选择："
                + "、".join(str(item) for item in parameter.choices)
            )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if parameter.minimum is not None and value < parameter.minimum:
            raise BusinessDraftError(f"{parameter.label}不能小于{parameter.minimum}。")
        if parameter.maximum is not None and value > parameter.maximum:
            raise BusinessDraftError(f"{parameter.label}不能大于{parameter.maximum}。")
    return value


def normalize_business_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Repair harmless JSON-shape noise while keeping semantic fields strict."""

    normalized = deepcopy(payload)

    # ``both`` is valid for the overall task, but not for an executable
    # branch: image and video have distinct media operators and must never be
    # coupled in one rule graph.  Models quite reasonably use ``both`` as a
    # shorthand when the rule itself is media independent.  Expand that
    # shorthand deterministically instead of rejecting an otherwise complete
    # business plan.  References are rewritten per clone so each media path
    # remains self-contained.
    branches = normalized.get("branches")
    if isinstance(branches, list):
        replacements: dict[str, list[str]] = {}
        expanded_branches: list[dict[str, Any]] = []
        used_keys = {
            str(item.get("key"))
            for item in branches
            if isinstance(item, dict) and item.get("key")
        }

        def clone_key(base: str, media_type: str) -> str:
            candidate = f"{base}_{media_type}"
            suffix = 2
            while candidate in used_keys:
                candidate = f"{base}_{media_type}_{suffix}"
                suffix += 1
            used_keys.add(candidate)
            return candidate

        def rewrite_local_condition_refs(value: Any, old_branch: str, new_branch: str) -> Any:
            if isinstance(value, str) and value.startswith("condition:"):
                tail = value.split(":", 1)[1]
                source_branch, dot, condition_key = tail.partition(".")
                if dot and source_branch == old_branch:
                    return f"condition:{new_branch}.{condition_key}"
                return value
            if isinstance(value, list):
                return [
                    rewrite_local_condition_refs(item, old_branch, new_branch)
                    for item in value
                ]
            if isinstance(value, dict):
                return {
                    key: rewrite_local_condition_refs(item, old_branch, new_branch)
                    for key, item in value.items()
                }
            return value

        for branch in branches:
            if not isinstance(branch, dict) or branch.get("media_type") != "both":
                expanded_branches.append(branch)
                continue
            key = str(branch.get("key") or "branch")
            clone_keys: list[str] = []
            for media_type in ("image", "video"):
                clone = deepcopy(branch)
                new_key = clone_key(key, media_type)
                clone["key"] = new_key
                clone["media_type"] = media_type
                clone["name"] = f"{clone.get('name') or key}（{'图片' if media_type == 'image' else '视频'}）"
                clone["conditions"] = rewrite_local_condition_refs(
                    clone.get("conditions", []), key, new_key
                )
                clone_keys.append(new_key)
                expanded_branches.append(clone)
            replacements[key] = clone_keys
        normalized["branches"] = expanded_branches

        if replacements:
            def rewrite_reference(value: Any, media_type: str | None = None) -> Any:
                if isinstance(value, str):
                    if value.startswith("branch:"):
                        old = value.split(":", 1)[1]
                        if old in replacements:
                            if media_type is None:
                                return [f"branch:{key}" for key in replacements[old]]
                            index = 0 if media_type == "image" else 1
                            return f"branch:{replacements[old][index]}"
                    if value.startswith("condition:"):
                        tail = value.split(":", 1)[1]
                        old, dot, condition_key = tail.partition(".")
                        if dot and old in replacements:
                            if media_type is None:
                                return [
                                    f"condition:{key}.{condition_key}"
                                    for key in replacements[old]
                                ]
                            index = 0 if media_type == "image" else 1
                            return f"condition:{replacements[old][index]}.{condition_key}"
                    return value
                if isinstance(value, list):
                    rewritten: list[Any] = []
                    for item in value:
                        candidate = rewrite_reference(item, media_type)
                        rewritten.extend(candidate if isinstance(candidate, list) else [candidate])
                    return rewritten
                if isinstance(value, dict):
                    return {
                        key: rewrite_reference(item, media_type)
                        for key, item in value.items()
                    }
                return value

            final = normalized.get("final_decision")
            if isinstance(final, dict):
                final["source_refs"] = rewrite_reference(final.get("source_refs", []))

            # An entity/count result rooted at a shorthand branch has one
            # independent result for each media type.  Decision results rooted
            # at final:primary are already media-neutral and remain singular.
            results = normalized.get("results")
            if isinstance(results, list):
                expanded_results: list[Any] = []
                result_keys = {
                    str(item.get("key"))
                    for item in results
                    if isinstance(item, dict) and item.get("key")
                }
                for result in results:
                    if not isinstance(result, dict):
                        expanded_results.append(result)
                        continue
                    source_ref = result.get("source_ref")
                    refs = rewrite_reference(source_ref)
                    if not isinstance(refs, list):
                        expanded_results.append(result)
                        continue
                    for index, (media_type, ref) in enumerate(zip(("image", "video"), refs)):
                        clone = deepcopy(result)
                        base = str(clone.get("key") or "result")
                        candidate = f"{base}_{media_type}"
                        suffix = 2
                        while candidate in result_keys:
                            candidate = f"{base}_{media_type}_{suffix}"
                            suffix += 1
                        result_keys.add(candidate)
                        clone["key"] = candidate
                        clone["name"] = f"{clone.get('name') or base}（{'图片' if index == 0 else '视频'}）"
                        clone["source_ref"] = ref
                        expanded_results.append(clone)
                normalized["results"] = expanded_results

    final_decision = normalized.get("final_decision")
    if isinstance(final_decision, dict):
        # The final decision is a singleton in this schema, so an LLM-generated
        # key carries no information and cannot be referenced independently.
        final_decision.pop("key", None)
        if isinstance(final_decision.get("source_refs"), list):
            final_decision["source_refs"] = list(dict.fromkeys(
                final_decision["source_refs"]
            ))
    trigger_policy = normalized.get("trigger_policy")
    if isinstance(trigger_policy, dict):
        trigger_aliases = {
            "on_match": "once",
            "each_match": "repeat",
            "continuous": "repeat",
            "change": "on_change",
        }
        mode = trigger_policy.get("mode")
        if mode in trigger_aliases:
            trigger_policy["mode"] = trigger_aliases[mode]

    def normalize_conditions(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            operator = item.get("operator", "ATOM")
            if operator != "ATOM" and isinstance(item.get("children"), list):
                # The prompt uses one recursive object shape, so models often
                # repeat placeholder atomic fields on a logic group.  Children
                # are the complete semantics of a group; these copied fields
                # are non-executable shape noise and must not make an otherwise
                # valid AND/OR tree fail before deterministic normalization.
                item.pop("capability_id", None)
                item.pop("parameters", None)
            if item.get("children") is None and (
                operator == "ATOM"
                or item.get("capability_id")
            ):
                item.pop("children", None)
            normalize_conditions(item.get("children"))

    for branch in normalized.get("branches", []):
        if isinstance(branch, dict):
            normalize_conditions(branch.get("conditions"))
    return normalized


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
        "exclusive",
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


def _condition_reference(branch_key: str, condition: DraftCondition) -> str:
    return f"condition:{branch_key}.{condition.key}"


def _repair_same_subject_attributes(
    draft: NaturalLanguageBusinessDraft,
) -> None:
    """Keep conjunctive entity attributes attached to one subject.

    Language models often translate "a person with A and B" into two filters
    over the same raw person set and then combine their booleans.  That permits
    A and B to be supplied by different people.  At every explicit AND scope,
    group positive ``attribute.*`` filters by their common entity source and
    synthesize (or complete) a same-subject join.  OR/N-of-M scopes and filters
    over different sources are deliberately left unchanged.
    """

    for branch in draft.branches:
        existing_keys = {
            item.key for item in _walk_draft_conditions(branch.conditions)
        }

        def repair_scope(
            conditions: list[DraftCondition], logic: str
        ) -> None:
            for condition in list(conditions):
                if condition.operator != "ATOM":
                    repair_scope(condition.children, condition.operator)
            if logic != "AND":
                return

            grouped: dict[str, list[DraftCondition]] = {}
            same_subject_conditions: list[DraftCondition] = []
            for condition in conditions:
                if condition.operator != "ATOM" or condition.negated:
                    continue
                if condition.capability_id == "subject.same_attributes":
                    same_subject_conditions.append(condition)
                    continue
                if not (condition.capability_id or "").startswith("attribute."):
                    continue
                source = condition.parameters.get("source")
                if isinstance(source, str) and source.startswith("condition:"):
                    grouped.setdefault(source, []).append(condition)

            for source, attributes in grouped.items():
                if len(attributes) < 2:
                    continue
                references = [
                    _condition_reference(branch.key, item) for item in attributes
                ]
                existing = next(
                    (
                        item
                        for item in same_subject_conditions
                        if str(item.parameters.get("subject", "")).split(".")[-1]
                        == source.split(".")[-1]
                    ),
                    None,
                )
                if existing is not None:
                    declared = existing.parameters.get("attributes", [])
                    declared = declared if isinstance(declared, list) else [declared]
                    covered_keys: set[str] = set()
                    for reference in declared:
                        if isinstance(reference, str) and reference.startswith(
                            "condition:"
                        ):
                            covered_keys.add(reference.split(".")[-1].split(":")[-1])
                            continue
                        scored = [
                            (_evidence_match_score(str(reference), item), item.key)
                            for item in attributes
                        ]
                        best_score = max((score for score, _ in scored), default=0)
                        best = [
                            key
                            for score, key in scored
                            if score == best_score and score > 0
                        ]
                        if len(best) == 1:
                            covered_keys.add(best[0])
                    existing.parameters["attributes"] = list(
                        dict.fromkeys(
                            [
                                *declared,
                                *(
                                    reference
                                    for reference, attribute in zip(
                                        references, attributes
                                    )
                                    if attribute.key not in covered_keys
                                ),
                            ]
                        )
                    )
                    continue

                base_key = "same_subject_attributes"
                key = base_key
                suffix = 2
                while key in existing_keys:
                    key = f"{base_key}_{suffix}"
                    suffix += 1
                existing_keys.add(key)
                same_subject = DraftCondition(
                    key=key,
                    name="同一目标同时满足："
                    + "、".join(item.name for item in attributes),
                    capability_id="subject.same_attributes",
                    parameters={
                        "subject": source,
                        "attributes": references,
                    },
                )
                conditions.append(same_subject)
                same_subject_conditions.append(same_subject)

            # A colour condition already grounds a colour-specific evidence
            # box and matches it back to its declared source target.  An LLM
            # sometimes adds a one-item same-subject condition after it;
            # unlike a multi-attribute join, that repeats the very same
            # association and provides no additional constraint.
            by_key = {item.key: item for item in conditions}
            for item in list(same_subject_conditions):
                references = item.parameters.get("attributes") or []
                references = references if isinstance(references, list) else [references]
                if len(references) != 1 or not isinstance(references[0], str):
                    continue
                attribute_key = references[0].split(".")[-1].split(":")[-1]
                attribute = by_key.get(attribute_key)
                if (
                    attribute is not None
                    and attribute.capability_id == "attribute.color"
                    and attribute.parameters.get("source")
                    == item.parameters.get("subject")
                ):
                    conditions.remove(item)

        repair_scope(branch.conditions, branch.logic)


def _condition_reference_keys(condition: DraftCondition) -> set[str]:
    references: set[str] = set()
    for value in condition.parameters.values():
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and item.startswith("condition:"):
                references.add(item.split(":", 1)[1].split(".")[-1])
    return references


def _repair_independent_business_branches(
    draft: NaturalLanguageBusinessDraft,
    capabilities: BusinessCapabilityRegistry,
) -> None:
    """Split independent single-subject business chains placed in one branch.

    Conjunctive/disjunctive wrappers emitted by the LLM may be nested, so the
    repair follows condition references rather than relying on a flat JSON
    shape.  A component is split only when every one of its conditions traces
    to exactly one detector and every detector has an entity-refining
    condition.  Cross-target relations and event-pattern branches are left
    intact because splitting those would change their semantics.
    """

    def produces_business_outcome(condition: DraftCondition) -> bool:
        if condition.capability_id == "target.detect":
            return False
        try:
            definition = capabilities.require(condition.capability_id or "")
        except KeyError:
            return False
        # Any typed business result beyond the base detector can terminate an
        # independent lineage: filtered entities, counts, states, tracks,
        # events or scalar decisions. Multi-subject relations are still safe
        # because their reference roots are checked separately and prevent a
        # split when they span more than one detector.
        return definition.orchestration_slot == "condition"

    used_keys = {branch.key for branch in draft.branches}
    replacements: dict[str, list[DraftBranch]] = {}
    condition_branch: dict[tuple[str, str], str] = {}
    pattern_branches = {
        key for pattern in draft.patterns for key in pattern.branch_keys
    }
    replacement_logic: dict[str, str] = {}
    for branch in draft.branches:
        if (
            branch.logic not in {"AND", "OR"}
            or branch.time.mode != "immediate"
            or branch.key in pattern_branches
        ):
            continue

        def atoms(condition: DraftCondition) -> list[DraftCondition]:
            if condition.operator == "ATOM":
                return [condition]
            return [atom for child in condition.children for atom in atoms(child)]

        # Same-operator wrappers add no semantic boundary.  Flatten only those
        # wrappers; a nested OR under AND (or vice versa) remains one unit and
        # must still trace to a single target before it can be moved.
        def top_units(condition: DraftCondition) -> list[DraftCondition]:
            if condition.operator == branch.logic:
                return [
                    unit
                    for child in condition.children
                    for unit in top_units(child)
                ]
            return [condition]

        units = [
            unit
            for condition in branch.conditions
            for unit in top_units(condition)
        ]
        all_atoms = [atom for unit in units for atom in atoms(unit)]
        by_key = {condition.key: condition for condition in all_atoms}

        # A single detector may legitimately feed several independent named
        # regions (for example, “区域 1 的着装条件” and “区域 2 的人数阈值”).
        # The detector-root split below cannot see that boundary because both
        # chains share the same raw ObjectSet.  Region references are the
        # business boundary here; duplicate only the shared prerequisites and
        # keep each region's measurable outcome in its own branch.
        region_resource_keys = {
            resource.key
            for resource in draft.resources
            if resource.resource_type == "region"
        }

        def resource_region_refs(value: Any) -> set[str]:
            refs: set[str] = set()
            if isinstance(value, str):
                if value.startswith("resource:"):
                    key = value.split(":", 1)[1]
                    if key in region_resource_keys:
                        refs.add(key)
                elif value in region_resource_keys:
                    # Accept the LLM's harmless shorthand; the resolver will
                    # canonicalize it when the cloned branch is installed.
                    refs.add(value)
            elif isinstance(value, list):
                for item in value:
                    refs.update(resource_region_refs(item))
            elif isinstance(value, dict):
                for item in value.values():
                    refs.update(resource_region_refs(item))
            return refs

        direct_region_refs = {
            condition.key: resource_region_refs(condition.parameters)
            for condition in all_atoms
        }
        region_refs_cache: dict[str, set[str]] = {}

        def condition_region_refs(
            key: str, visiting: set[str] | None = None
        ) -> set[str]:
            if key in region_refs_cache:
                return set(region_refs_cache[key])
            visiting = set() if visiting is None else visiting
            if key in visiting:
                return set()
            visiting.add(key)
            refs = set(direct_region_refs.get(key, set()))
            condition = by_key.get(key)
            if condition is not None:
                for reference in _condition_reference_keys(condition):
                    refs.update(condition_region_refs(reference, visiting))
            visiting.discard(key)
            region_refs_cache[key] = refs
            return set(refs)

        def unit_region_refs(unit: DraftCondition) -> set[str]:
            return {
                region
                for atom in atoms(unit)
                for region in condition_region_refs(atom.key)
            }

        def rewrite_local_condition_refs(
            value: Any, old_branch: str, new_branch: str, local_keys: set[str]
        ) -> Any:
            if isinstance(value, str) and value.startswith("condition:"):
                tail = value.split(":", 1)[1]
                if "." in tail:
                    source_branch, source_key = tail.split(".", 1)
                    if source_branch == old_branch and source_key in local_keys:
                        return f"condition:{new_branch}.{source_key}"
                elif tail in local_keys:
                    return f"condition:{new_branch}.{tail}"
                return value
            if isinstance(value, list):
                return [
                    rewrite_local_condition_refs(item, old_branch, new_branch, local_keys)
                    for item in value
                ]
            if isinstance(value, dict):
                return {
                    key: rewrite_local_condition_refs(item, old_branch, new_branch, local_keys)
                    for key, item in value.items()
                }
            return value

        def clone_region_branch(
            region_key: str,
            selected_units: list[DraftCondition],
        ) -> DraftBranch | None:
            selected_keys = {
                atom.key for unit in selected_units for atom in atoms(unit)
            }
            # Include every local prerequisite transitively.  This normally
            # duplicates only the shared base detector; cross-region inputs
            # are rejected rather than silently re-bound.
            changed = True
            while changed:
                changed = False
                for unit in units:
                    unit_keys = {atom.key for atom in atoms(unit)}
                    if not (unit_keys & selected_keys):
                        continue
                    for atom in atoms(unit):
                        for reference in _condition_reference_keys(atom):
                            if reference in by_key and reference not in selected_keys:
                                refs = condition_region_refs(reference)
                                if refs and refs != {region_key}:
                                    return None
                                selected_keys.add(reference)
                                changed = True
            chosen = [
                unit for unit in units
                if {atom.key for atom in atoms(unit)} & selected_keys
            ]
            if not chosen:
                return None
            local_atoms = [atom for unit in chosen for atom in atoms(unit)]
            if any(
                condition_region_refs(atom.key) != {region_key}
                and condition_region_refs(atom.key)
                for atom in local_atoms
            ):
                return None
            if not any(
                produces_business_outcome(atom)
                for atom in local_atoms
            ):
                return None
            key_base = f"{branch.key}_{region_key}"
            new_key = key_base
            suffix = 2
            while new_key in used_keys:
                new_key = f"{key_base}_{suffix}"
                suffix += 1
            used_keys.add(new_key)
            copied_units = [unit.model_copy(deep=True) for unit in chosen]
            local_keys = {
                atom.key for unit in copied_units for atom in atoms(unit)
            }
            for unit in copied_units:
                for atom in atoms(unit):
                    atom.parameters = rewrite_local_condition_refs(
                        atom.parameters, branch.key, new_key, local_keys
                    )
            region_name = next(
                (
                    resource.name for resource in draft.resources
                    if resource.key == region_key
                ),
                region_key,
            )
            refinement = next(
                atom for unit in reversed(chosen)
                for atom in reversed(atoms(unit))
                if produces_business_outcome(atom)
            )
            business_label = str(
                next(
                    (
                        atom.parameters.get("business_label")
                        for atom in local_atoms
                        if atom.capability_id == "target.detect"
                        and atom.parameters.get("business_label")
                    ),
                    "",
                ).strip()
            )
            return branch.model_copy(
                update={
                    "key": new_key,
                    "name": f"{region_name}：{business_label or refinement.name}",
                    "logic": "AND",
                    "conditions": copied_units,
                },
                deep=True,
            )

        region_units: dict[str, list[DraftCondition]] = {}
        region_split_possible = bool(region_resource_keys)
        for unit in units:
            refs = unit_region_refs(unit)
            if len(refs) > 1:
                region_split_possible = False
                break
            if refs:
                region_units.setdefault(next(iter(refs)), []).append(unit)
        unscoped_outcome_units = [
            unit for unit in units
            if not unit_region_refs(unit)
            and any(produces_business_outcome(atom) for atom in atoms(unit))
        ]
        if (
            region_split_possible
            and len(region_units) >= 2
            and not unscoped_outcome_units
        ):
            region_branches = [
                clone_region_branch(region_key, region_units[region_key])
                for region_key in region_units
            ]
            if all(item is not None for item in region_branches):
                replacements[branch.key] = [item for item in region_branches if item is not None]
                replacement_logic[branch.key] = branch.logic
                for item in replacements[branch.key]:
                    for condition in _walk_draft_conditions(item.conditions):
                        condition_branch[(branch.key, condition.key)] = item.key
                continue
        detector_keys = {
            condition.key
            for condition in all_atoms
            if condition.capability_id == "target.detect"
        }
        if len(detector_keys) < 2:
            continue

        roots_cache: dict[str, set[str]] = {}

        def detector_roots(key: str, visiting: set[str] | None = None) -> set[str]:
            if key in roots_cache:
                return roots_cache[key]
            if key in detector_keys:
                roots_cache[key] = {key}
                return roots_cache[key]
            visiting = set() if visiting is None else visiting
            if key in visiting:
                return set()
            visiting.add(key)
            roots = set()
            condition = by_key.get(key)
            if condition is not None:
                for reference in _condition_reference_keys(condition):
                    roots.update(detector_roots(reference, visiting))
            visiting.discard(key)
            roots_cache[key] = roots
            return roots

        groups: dict[str, list[DraftCondition]] = {
            key: [] for key in detector_keys
        }
        valid = True
        for unit in units:
            roots = {
                root
                for condition in atoms(unit)
                for root in detector_roots(condition.key)
            }
            if len(roots) != 1:
                valid = False
                break
            groups[next(iter(roots))].append(unit)
        if not valid or any(
            not any(
                produces_business_outcome(condition)
                for item in group
                for condition in atoms(item)
            )
            for group in groups.values()
        ):
            continue

        split_branches = []
        ordered_detectors = [
            condition
            for condition in all_atoms
            if condition.key in detector_keys
        ]
        for detector in ordered_detectors:
            if detector.key not in groups:
                continue
            key_base = f"{branch.key}_{detector.key}"
            new_key = key_base
            suffix = 2
            while new_key in used_keys:
                new_key = f"{key_base}_{suffix}"
                suffix += 1
            used_keys.add(new_key)
            group = groups[detector.key]
            refinement = next(
                condition
                for item in reversed(group)
                for condition in reversed(atoms(item))
                if produces_business_outcome(condition)
            )
            business_label = str(
                detector.parameters.get("business_label") or ""
            ).strip()
            split_branches.append(
                branch.model_copy(
                    update={
                        "key": new_key,
                        "name": business_label or refinement.name,
                        # Conditions inside one target lineage are dependency
                        # refinements and therefore conjunctive.  The old
                        # branch AND/OR is moved to the final branch decision.
                        "logic": "AND",
                        "conditions": [item.model_copy(deep=True) for item in group],
                    },
                    deep=True,
                )
            )
            for item in group:
                for condition in atoms(item):
                    condition_branch[(branch.key, condition.key)] = new_key
        replacements[branch.key] = split_branches
        replacement_logic[branch.key] = branch.logic

    if not replacements:
        return
    draft.branches = [
        replacement
        for branch in draft.branches
        for replacement in replacements.get(branch.key, [branch])
    ]

    def replace_branch_refs(references: list[str]) -> list[str]:
        result = []
        for reference in references:
            if reference.startswith("branch:"):
                branch_key = reference.split(":", 1)[1]
                if branch_key in replacements:
                    result.extend(
                        f"branch:{item.key}" for item in replacements[branch_key]
                    )
                    continue
            result.append(reference)
        return list(dict.fromkeys(result))

    original_final_refs = list(draft.final_decision.source_refs)
    draft.final_decision.source_refs = replace_branch_refs(original_final_refs)
    if len(original_final_refs) == 1 and original_final_refs[0].startswith("branch:"):
        old_key = original_final_refs[0].split(":", 1)[1]
        if old_key in replacement_logic:
            draft.final_decision.combination = replacement_logic[old_key]
    for result in draft.results:
        if result.source_ref.startswith("branch:"):
            old_key = result.source_ref.split(":", 1)[1]
            if old_key in replacements:
                # Per-branch entity outputs are synthesized below; a single
                # old-branch result cannot represent several independent sets.
                result.source_ref = "final:primary"
        elif result.source_ref.startswith("condition:"):
            value = result.source_ref.split(":", 1)[1]
            if "." in value:
                old_branch, condition_key = value.split(".", 1)
                new_branch = condition_branch.get((old_branch, condition_key))
                if new_branch:
                    result.source_ref = f"condition:{new_branch}.{condition_key}"


def _repair_independent_entity_results(
    draft: NaturalLanguageBusinessDraft,
    capabilities: BusinessCapabilityRegistry,
) -> None:
    """Ensure each independent refined target has an entity-box output."""

    refined_branches = []
    for branch in draft.branches:
        conditions = list(_walk_draft_conditions(branch.conditions))
        has_detector = any(
            item.capability_id == "target.detect" for item in conditions
        )
        has_refinement = False
        for item in conditions:
            if item.capability_id == "target.detect":
                continue
            try:
                output_type = capabilities.require(
                    item.capability_id or ""
                ).output_value_type
            except KeyError:
                continue
            if output_type in {"entity_set", "scoped_set"}:
                has_refinement = True
                break
        if has_detector and has_refinement:
            refined_branches.append(branch)
    if len(refined_branches) < 2:
        return

    refined_keys = {branch.key for branch in refined_branches}

    def result_branch(result: DraftResult) -> str | None:
        if result.source_ref.startswith("branch:"):
            return result.source_ref.split(":", 1)[1]
        if result.source_ref.startswith("condition:"):
            value = result.source_ref.split(":", 1)[1]
            return value.split(".", 1)[0] if "." in value else None
        return None

    # A final AND/OR decision is boolean evidence and cannot itself supply
    # entity boxes.  Replace only ambiguous entity projections; decision,
    # event and measurement results remain untouched.
    draft.results = [
        result
        for result in draft.results
        if not (
            result.result_kind == "entities"
            and result.source_ref == "final:primary"
            and len(draft.final_decision.source_refs) > 1
        )
    ]
    covered = {
        branch_key
        for result in draft.results
        if result.result_kind == "entities"
        and (branch_key := result_branch(result)) in refined_keys
    }
    used_result_keys = {result.key for result in draft.results}
    for branch in refined_branches:
        if branch.key in covered:
            continue
        key_base = f"{branch.key}_entities"
        key = key_base
        suffix = 2
        while key in used_result_keys:
            key = f"{key_base}_{suffix}"
            suffix += 1
        used_result_keys.add(key)
        draft.results.append(
            DraftResult(
                key=key,
                name=branch.name,
                source_ref=f"branch:{branch.key}",
                result_kind="entities",
                evidence_policy="required",
                save_policy="always",
                show_in_overview=True,
            )
        )


def _repair_inline_state_evidence(
    draft: NaturalLanguageBusinessDraft,
) -> None:
    """Materialize an inline visible state descriptor as entity evidence."""

    for branch in draft.branches:
        atoms = list(_walk_draft_conditions(branch.conditions))
        by_key = {item.key: item for item in atoms}
        for condition in atoms:
            if (
                condition.operator != "ATOM"
                or condition.negated
                or condition.capability_id != "state.current"
            ):
                continue
            parameters = condition.parameters
            state = parameters.get("state") or parameters.get("positive_state")
            if state in (None, ""):
                continue
            if parameters.get("evidence") not in (None, "", []):
                parameters.setdefault("positive_state", parameters.pop("state", state))
                continue
            source = parameters.get("source")
            if isinstance(source, list) and len(source) == 1:
                source = source[0]
            source_key = (
                source.split(".")[-1].split(":")[-1]
                if isinstance(source, str) and source.startswith("condition:")
                else ""
            )
            subject = by_key.get(source_key)
            if subject is not None and subject.capability_id != "target.detect":
                continue
            subject_phrases = (
                subject.parameters.get("phrases") or []
                if subject is not None else []
            )
            if isinstance(subject_phrases, str):
                subject_phrases = [subject_phrases]
            if not subject_phrases and subject is not None:
                targets = subject.parameters.get("targets") or []
                targets = [targets] if isinstance(targets, str) else targets
                subject_phrases = [
                    str(item.get("label") if isinstance(item, dict) else item)
                    for item in targets
                    if item
                ]
            if subject_phrases:
                base_phrase = str(subject_phrases[0])
            else:
                tokens = [
                    token
                    for token in re.split(r"[_-]+", source_key)
                    if token not in {
                        "image", "video", "detect", "detection", "target",
                        "condition", "cond",
                    }
                ]
                base_phrase = " ".join(tokens) or "object"
            state_phrase = re.sub(r"[_-]+", " ", str(state)).strip()
            condition.capability_id = "target.detect"
            condition.parameters = {
                "targets": [{
                    "label": condition.name,
                    "phrases": [f"{base_phrase} {state_phrase}".strip()],
                }],
                "business_label": condition.name,
            }


def _repair_redundant_temporal_atoms(
    draft: NaturalLanguageBusinessDraft,
) -> None:
    """Remove atomic pseudo-time conditions already represented by branch.time."""

    for branch in draft.branches:
        if branch.time.mode == "immediate":
            continue

        def repair(items: list[DraftCondition]) -> None:
            retained: list[DraftCondition] = []
            for item in items:
                if item.operator != "ATOM":
                    repair(item.children)
                parameters = item.parameters
                redundant = (
                    item.operator == "ATOM"
                    and item.capability_id == "state.current"
                    and not any(
                        parameters.get(key) not in (None, "", [])
                        for key in ("state", "positive_state", "evidence")
                    )
                )
                if not redundant:
                    retained.append(item)
            items[:] = retained

        repair(branch.conditions)


def _repair_required_tracks(
    draft: NaturalLanguageBusinessDraft,
) -> None:
    """Insert the typed track stage required by video speed measurements.

    A detector produces an ObjectSet while ``motion.speed`` consumes a
    TrackSet.  LLM drafts frequently describe the intended dependency but skip
    the mechanical tracking stage.  Add that stage only when the speed source
    resolves directly to a detector; explicit tracks and ambiguous references
    remain untouched so normal validation can still report genuine mistakes.
    """

    for branch in draft.branches:
        if branch.media_type != "video":
            continue
        atoms = list(_walk_draft_conditions(branch.conditions))
        by_key = {item.key: item for item in atoms}
        existing_keys = set(by_key)

        def source_key(value: Any) -> str | None:
            if isinstance(value, list) and len(value) == 1:
                value = value[0]
            if not isinstance(value, str) or not value.startswith("condition:"):
                return None
            return value.split(".")[-1].split(":")[-1]

        tracks_by_source: dict[str, DraftCondition] = {}
        for item in atoms:
            if item.capability_id != "motion.track":
                continue
            key = source_key(item.parameters.get("source"))
            if key:
                tracks_by_source[key] = item

        insertions: list[tuple[DraftCondition, DraftCondition]] = []

        def ensure_track(
            detector: DraftCondition,
            insert_before_item: DraftCondition,
        ) -> DraftCondition:
            track = tracks_by_source.get(detector.key)
            if track is None:
                base_key = f"auto_track_{detector.key}"
                track_key = base_key
                suffix = 2
                while track_key in existing_keys:
                    track_key = f"{base_key}_{suffix}"
                    suffix += 1
                existing_keys.add(track_key)
                track = DraftCondition(
                    key=track_key,
                    name=f"创建{detector.name}轨迹",
                    operator="ATOM",
                    capability_id="motion.track",
                    parameters={
                        "source": _condition_reference(branch.key, detector),
                    },
                )
                tracks_by_source[detector.key] = track
                insertions.append((insert_before_item, track))
            return track

        for item in atoms:
            if item.capability_id != "motion.speed":
                continue
            detector_key = source_key(item.parameters.get("source"))
            detector = by_key.get(detector_key or "")
            if detector is None or detector.capability_id != "target.detect":
                continue
            track = ensure_track(detector, item)
            item.parameters["source"] = _condition_reference(branch.key, track)

        detectors = [
            item for item in atoms if item.capability_id == "target.detect"
        ]
        needs_identity_track = (
            branch.time.mode != "immediate"
            and branch.time.identity_scope == "track"
            and len(detectors) == 1
        )
        if needs_identity_track:
            detector = detectors[0]
            first_dependent = next(
                (
                    item for item in atoms
                    if item is not detector
                    and source_key(item.parameters.get("source")) == detector.key
                ),
                atoms[-1],
            )
            track = ensure_track(detector, first_dependent)
            track_ref = _condition_reference(branch.key, track)
            for item in atoms:
                if item.capability_id in {
                    "spatial.membership", "motion.direction", "motion.speed"
                } and source_key(item.parameters.get("source")) == detector.key:
                    item.parameters["source"] = track_ref
            for result in draft.results:
                if (
                    result.result_kind == "tracks"
                    and (
                        result.source_ref == f"branch:{branch.key}"
                        or result.source_ref.startswith("condition:")
                        and branch.key in result.source_ref
                    )
                ):
                    result.source_ref = track_ref

        for speed, track in insertions:
            def insert_before(items: list[DraftCondition]) -> bool:
                for index, candidate in enumerate(items):
                    if candidate is speed:
                        items.insert(index, track)
                        return True
                    if insert_before(candidate.children):
                        return True
                return False

            insert_before(branch.conditions)


def _repair_non_actionable_geometry(
    draft: NaturalLanguageBusinessDraft,
) -> None:
    """Drop vague geometry placeholders that contain no executable rule."""

    valid_dimensions = {"size", "position", "aspect_ratio"}
    valid_values = {
        "small", "medium", "large", "left", "center", "right",
        "top", "middle", "bottom", "horizontal", "vertical",
    }
    for branch in draft.branches:
        def repair(items: list[DraftCondition]) -> None:
            retained: list[DraftCondition] = []
            for item in items:
                if item.operator != "ATOM":
                    repair(item.children)
                parameters = item.parameters
                if item.capability_id == "attribute.geometry":
                    alias = parameters.pop("geometry", None)
                    if (
                        parameters.get("dimension") in (None, "")
                        and alias in valid_dimensions
                    ):
                        parameters["dimension"] = alias
                    dimension = parameters.get("dimension")
                    value = parameters.get("value")
                    actionable = (
                        dimension in valid_dimensions
                        and (
                            value in valid_values
                            or (
                                parameters.get("operator") not in (None, "")
                                and parameters.get("threshold") is not None
                            )
                        )
                    )
                    if not actionable and alias not in valid_dimensions:
                        continue
                retained.append(item)
            items[:] = retained

        repair(branch.conditions)


def _repair_degenerate_patterns(
    draft: NaturalLanguageBusinessDraft,
) -> None:
    """Fold a one-branch pseudo-composition back into that branch."""

    multi_branch_modes = {
        "all_active", "all_completed", "all_completed_within_window",
        "any", "n_of_m", "exclusive", "sequence",
    }
    retained: list[DraftPattern] = []
    replacements: dict[str, str] = {}
    for pattern in draft.patterns:
        unique_branches = list(dict.fromkeys(pattern.branch_keys))
        pattern.branch_keys = unique_branches
        if pattern.mode in multi_branch_modes and len(unique_branches) == 1:
            replacements[f"event:{pattern.key}"] = f"branch:{unique_branches[0]}"
            continue
        retained.append(pattern)
    draft.patterns = retained
    if replacements:
        draft.final_decision.source_refs = list(dict.fromkeys(
            replacements.get(item, item)
            for item in draft.final_decision.source_refs
        ))
        for result in draft.results:
            result.source_ref = replacements.get(result.source_ref, result.source_ref)


def _repair_missing_equipment_evidence(
    draft: NaturalLanguageBusinessDraft,
) -> None:
    """Create missing visible-equipment evidence for subject anti-joins.

    ``subject.missing_equipment`` needs both a subject set and an equipment set.
    A planner may supply only a visible descriptor such as ``safety helmet``.
    When no existing condition uniquely matches that descriptor, materialize a
    normal target detection and bind the anti-join to it.  This applies to any
    visible equipment phrase and does not encode PPE-specific categories.
    """

    def unwrap_double_negative(items: list[DraftCondition]) -> list[DraftCondition]:
        """A missing-relation atom already denotes absence; NOT would invert it."""

        repaired: list[DraftCondition] = []
        for item in items:
            if item.operator != "ATOM":
                item.children = unwrap_double_negative(item.children)
            if (
                item.operator == "NOT"
                and len(item.children) == 1
                and item.children[0].operator == "ATOM"
                and item.children[0].capability_id == "subject.missing_equipment"
            ):
                repaired.append(item.children[0])
            else:
                repaired.append(item)
        return repaired

    def descriptor_from_positive_phrase(phrase: str, subject_phrase: str) -> str:
        """Extract the associated object from a positive subject relation.

        This is deliberately relation-word based rather than PPE-specific, so
        it works for wearing, carrying, containing, loading, attachment and
        connection statements alike.  It is only used when a planner has
        incorrectly pointed both subject and associated-object at one box.
        """

        value = phrase.strip()
        if subject_phrase:
            value = re.sub(re.escape(subject_phrase), "", value, count=1, flags=re.I)
        value = re.sub(
            r"^\s*(?:is\s+)?(?:wearing|with|carrying|containing|loaded\s+with|"
            r"attached\s+to|connected\s+to)\s+",
            "",
            value,
            flags=re.I,
        )
        value = re.sub(
            r"\s+(?:is\s+)?(?:worn|carried|contained|loaded|attached|connected)\s*$",
            "",
            value,
            flags=re.I,
        )
        return value.strip(" ,.;:，。；：")

    def condition_primary_phrase(item: DraftCondition | None) -> str:
        if item is None:
            return ""
        targets = item.parameters.get("targets") or []
        targets = targets if isinstance(targets, list) else [targets]
        for target in targets:
            if isinstance(target, dict):
                phrases = target.get("phrases") or []
                phrases = phrases if isinstance(phrases, list) else [phrases]
                if phrases and str(phrases[0]).strip():
                    return str(phrases[0]).strip()
                if str(target.get("label") or "").strip():
                    return str(target["label"]).strip()
            elif str(target).strip():
                return str(target).strip()
        phrases = item.parameters.get("phrases") or []
        phrases = phrases if isinstance(phrases, list) else [phrases]
        return str(phrases[0]).strip() if phrases else ""

    for branch in draft.branches:
        branch.conditions = unwrap_double_negative(branch.conditions)
        existing_keys = {
            item.key for item in _walk_draft_conditions(branch.conditions)
        }
        additions: list[DraftCondition] = []
        atoms = list(_walk_draft_conditions(branch.conditions))
        for condition in atoms:
            if (
                condition.operator != "ATOM"
                or condition.negated
                or condition.capability_id != "subject.missing_equipment"
            ):
                continue
            equipment = condition.parameters.get("equipment")
            if isinstance(equipment, list) and len(equipment) == 1:
                equipment = equipment[0]
                condition.parameters["equipment"] = equipment
            if not isinstance(equipment, str) or not equipment.strip():
                continue
            subject_reference = condition.parameters.get("subject")
            if (
                equipment.startswith("condition:")
                and isinstance(subject_reference, str)
                and equipment == subject_reference
            ):
                # The LLM reused the subject detector for the associated
                # object.  Recover a separate object detector from its own
                # affirmative semantic relation, never by guessing a domain
                # category.  A stale same-subject semantic evidence reference
                # is equally unusable and is rebuilt below.
                subject = next(
                    (
                        item for item in atoms
                        if _condition_reference(branch.key, item) == subject_reference
                    ),
                    None,
                )
                descriptor = descriptor_from_positive_phrase(
                    str(condition.parameters.get("positive_semantic_phrase") or ""),
                    condition_primary_phrase(subject),
                )
                if not descriptor:
                    raise BusinessDraftError(
                        f"条件“{condition.name}”把主体同时作为关联物，且缺少可见正向关系描述。"
                    )
                equipment = descriptor
                condition.parameters["equipment"] = descriptor
                if condition.parameters.get("semantic_evidence") == subject_reference:
                    condition.parameters.pop("semantic_evidence", None)
            if equipment.startswith("condition:"):
                continue
            candidates = [
                item
                for item in atoms
                if item is not condition
                and item.operator == "ATOM"
                and item.capability_id not in {
                    "subject.same_attributes",
                    "subject.missing_equipment",
                }
            ]
            scored = [
                (_evidence_match_score(equipment, item), item)
                for item in candidates
            ]
            best_score = max((score for score, _ in scored), default=0)
            best = [
                item for score, item in scored if score == best_score and score > 0
            ]
            if len(best) == 1:
                condition.parameters["equipment"] = _condition_reference(
                    branch.key, best[0]
                )
                continue
            if best_score > 0:
                # Preserve ambiguity for the normal binder to report; creating
                # a third detector would conceal an unclear planner decision.
                continue

            phrase = re.sub(r"[_-]+", " ", equipment).strip()
            base_key = f"{condition.key}_equipment"
            key = base_key
            suffix = 2
            while key in existing_keys:
                key = f"{base_key}_{suffix}"
                suffix += 1
            existing_keys.add(key)
            evidence = DraftCondition(
                key=key,
                name=f"检测装备：{phrase}",
                capability_id="target.detect",
                parameters={
                    "targets": [{"label": phrase, "phrases": [phrase]}],
                    "business_label": phrase,
                },
            )
            additions.append(evidence)
            atoms.append(evidence)
            condition.parameters["equipment"] = _condition_reference(
                branch.key, evidence
            )
        branch.conditions.extend(additions)

        # Prefer a model-visible positive predicate whenever a simple fact can
        # be represented by one full-subject box.  This is relation-agnostic:
        # wearing, carrying, containing, loading, attaching and connecting are
        # all accepted when the planner supplies an affirmative phrase.  The
        # negative business meaning remains on ``subject.missing_equipment``;
        # rule-based association is only a fallback or explicit verifier.
        atoms = list(_walk_draft_conditions(branch.conditions))
        by_key = {item.key: item for item in atoms}

        def referenced_condition(value: Any) -> DraftCondition | None:
            values = value if isinstance(value, list) else [value]
            if len(values) != 1 or not isinstance(values[0], str):
                return None
            reference = values[0]
            if not reference.startswith("condition:"):
                return None
            return by_key.get(reference.split(":", 1)[1].split(".")[-1])

        def primary_phrase(item: DraftCondition | None) -> str:
            if item is None:
                return ""
            targets = item.parameters.get("targets") or []
            targets = targets if isinstance(targets, list) else [targets]
            for target in targets:
                if isinstance(target, dict):
                    phrases = target.get("phrases") or []
                    phrases = phrases if isinstance(phrases, list) else [phrases]
                    if phrases and str(phrases[0]).strip():
                        return str(phrases[0]).strip()
                    if str(target.get("label") or "").strip():
                        return str(target["label"]).strip()
                elif str(target).strip():
                    return str(target).strip()
            phrases = item.parameters.get("phrases") or []
            phrases = phrases if isinstance(phrases, list) else [phrases]
            return str(phrases[0]).strip() if phrases else ""

        wearable_markers = (
            "helmet", "hard hat", "headwear", "hat", "cap",
            "glove", "mitt", "shoe", "boot", "footwear",
            "vest", "harness", "mask", "goggle", "glasses",
            "earplug", "earmuff", "collar", "clothing", "uniform",
            "安全帽", "头盔", "帽子", "手套", "鞋", "靴",
            "背心", "反光衣", "安全带", "口罩", "护目镜", "耳塞",
        )
        semantic_additions: list[DraftCondition] = []
        for condition in atoms:
            if (
                condition.operator != "ATOM"
                or condition.negated
                or condition.capability_id != "subject.missing_equipment"
                or condition.parameters.get("semantic_evidence")
            ):
                continue
            # A visible positive fact alone is not sufficient when the natural
            # language constrains *where* the associated object belongs on the
            # subject.  Keep this generic: it applies to any declared
            # subject-relative location, not to a particular PPE class.  The
            # planner may still explicitly select another evidence policy.
            if (
                "verification_mode" not in condition.parameters
                and str(condition.parameters.get("wear_location") or "auto")
                .strip()
                .lower()
                in {"head", "upper_body", "lower_body", "hands", "feet"}
            ):
                condition.parameters["verification_mode"] = "模型语义且关系复核"
            subject_condition = referenced_condition(
                condition.parameters.get("subject")
            )
            equipment_condition = referenced_condition(
                condition.parameters.get("equipment")
            )
            subject_phrase = primary_phrase(subject_condition)
            equipment_phrase = primary_phrase(equipment_condition)
            normalized_equipment = re.sub(
                r"[_-]+", " ", equipment_phrase
            ).strip().lower()
            if not subject_phrase or not normalized_equipment:
                continue

            if subject_phrase.lower() in normalized_equipment:
                condition.parameters["semantic_evidence"] = _condition_reference(
                    branch.key, equipment_condition
                )
                continue

            # Reuse any explicit full-subject semantic detector the planner
            # already created, regardless of the relation verb or object type.
            existing_semantic = next(
                (
                    item
                    for item in atoms
                    if item is not subject_condition
                    and item is not equipment_condition
                    and item.capability_id == "target.detect"
                    and subject_phrase.lower() in primary_phrase(item).lower()
                    and normalized_equipment in primary_phrase(item).lower()
                ),
                None,
            )
            if existing_semantic is not None:
                condition.parameters["semantic_evidence"] = _condition_reference(
                    branch.key, existing_semantic
                )
                continue

            semantic_phrase = str(
                condition.parameters.get("positive_semantic_phrase") or ""
            ).strip()
            if semantic_phrase and re.search(
                r"\b(?:not|without|no)\b", semantic_phrase, flags=re.IGNORECASE
            ):
                raise BusinessDraftError(
                    f"条件“{condition.name}”的正向可见语义不能包含 not/without/no。"
                )
            if not semantic_phrase:
                # Only this synthesis is carrier-specific: "wearing" is safe
                # for known wearables.  Other relations require an explicit
                # positive phrase so the system never guesses with/connected/
                # attached semantics from an object name alone.
                if not any(
                    marker in normalized_equipment for marker in wearable_markers
                ):
                    continue
                semantic_phrase = (
                    f"{subject_phrase} wearing {normalized_equipment}"
                )
            base_key = f"{condition.key}_semantic_evidence"
            key = base_key
            suffix = 2
            while key in existing_keys:
                key = f"{base_key}_{suffix}"
                suffix += 1
            existing_keys.add(key)
            evidence = DraftCondition(
                key=key,
                name=f"模型识别正向语义：{semantic_phrase}",
                capability_id="target.detect",
                parameters={
                    "targets": [{
                        "label": semantic_phrase,
                        "phrases": [semantic_phrase],
                    }],
                    "business_label": semantic_phrase,
                },
            )
            semantic_additions.append(evidence)
            condition.parameters["semantic_evidence"] = _condition_reference(
                branch.key, evidence
            )
        branch.conditions.extend(semantic_additions)


def _repair_entity_result_sources(
    draft: NaturalLanguageBusinessDraft,
    capabilities: BusinessCapabilityRegistry,
) -> None:
    """Point entity results at the most reduced entity evidence in a branch."""

    branches = {item.key: item for item in draft.branches}

    def condition_key_from_ref(reference: str) -> tuple[str, str] | None:
        if not reference.startswith("condition:"):
            return None
        value = reference.split(":", 1)[1]
        if "." not in value:
            return None
        branch_key, condition_key = value.split(".", 1)
        return branch_key, condition_key

    def depends_on(
        condition: DraftCondition,
        ancestor_key: str,
        by_key: dict[str, DraftCondition],
        visiting: set[str] | None = None,
    ) -> bool:
        visiting = set() if visiting is None else visiting
        if condition.key in visiting:
            return False
        visiting.add(condition.key)
        for reference in _condition_reference_keys(condition):
            if reference == ancestor_key:
                return True
            upstream = by_key.get(reference)
            if upstream is not None and depends_on(upstream, ancestor_key, by_key, visiting):
                return True
        return False

    for result in draft.results:
        if result.result_kind != "entities":
            continue
        source_ref = result.source_ref
        if source_ref == "final:primary":
            final_sources = draft.final_decision.source_refs
            if len(final_sources) != 1:
                continue
            source_ref = final_sources[0]
        branch_key: str | None = None
        source_condition_key: str | None = None
        if source_ref.startswith("branch:"):
            branch_key = source_ref.split(":", 1)[1]
        else:
            parsed = condition_key_from_ref(source_ref)
            if parsed is not None:
                branch_key, source_condition_key = parsed
        if branch_key is None:
            continue
        branch = branches.get(branch_key)
        if branch is None:
            continue
        by_key = {item.key: item for item in _walk_draft_conditions(branch.conditions)}
        source_condition = by_key.get(source_condition_key or "")
        candidates: list[tuple[tuple[int, int, int], DraftCondition]] = []
        for index, condition in enumerate(_walk_draft_conditions(branch.conditions)):
            if condition.operator != "ATOM" or condition.negated:
                continue
            try:
                output_type = capabilities.require(
                    condition.capability_id or ""
                ).output_value_type
            except KeyError:
                continue
            if output_type not in {"entity_set", "scoped_set"}:
                continue
            if (
                source_condition is not None
                and source_condition.capability_id != "target.detect"
            ):
                continue
            if (
                source_condition is not None
                and condition.key != source_condition.key
                and not depends_on(condition, source_condition.key, by_key)
            ):
                continue
            capability = condition.capability_id or ""
            semantic_priority = (
                50
                if output_type == "scoped_set"
                else 40
                if capability.startswith("subject.")
                else 30
                if capability.startswith("attribute.")
                else 20
                if capability != "target.detect"
                else 10
            )
            dependency_count = sum(
                1
                for value in condition.parameters.values()
                for item in (value if isinstance(value, list) else [value])
                if isinstance(item, str) and item.startswith("condition:")
            )
            candidates.append(
                ((semantic_priority, dependency_count, index), condition)
            )
        if candidates:
            # Prefer a terminal node in the dependency graph.  A terminal
            # entity node is the last available refinement of the referenced
            # source (colour, geometry, class, equipment, spatial membership,
            # or any future entity-set capability), so a projection cannot
            # accidentally regress to the raw detector.  If several terminal
            # nodes are independent siblings, retain the capability priority
            # and declaration order as deterministic tie-breakers.
            candidate_keys = {condition.key for _, condition in candidates}
            terminal_candidates = [
                item
                for item in candidates
                if not any(
                    other.key != item[1].key
                    and other.key in candidate_keys
                    and depends_on(other, item[1].key, by_key)
                    for _, other in candidates
                )
            ]
            selection_pool = terminal_candidates or candidates
            selected = max(selection_pool, key=lambda item: item[0])[1]
            result.source_ref = _condition_reference(branch.key, selected)


def _validate_business_orchestration_invariants(
    draft: NaturalLanguageBusinessDraft,
    capabilities: BusinessCapabilityRegistry,
) -> None:
    """Reject output typing that remains invalid after deterministic repair."""

    branches = {branch.key: branch for branch in draft.branches}
    final_branch_keys = [
        reference.split(":", 1)[1]
        for reference in draft.final_decision.source_refs
        if reference.startswith("branch:")
    ]

    def has_entity_refinement(branch: DraftBranch) -> bool:
        for condition in _walk_draft_conditions(branch.conditions):
            if condition.capability_id == "target.detect":
                continue
            try:
                output_type = capabilities.require(
                    condition.capability_id or ""
                ).output_value_type
            except KeyError:
                continue
            if output_type in {"entity_set", "scoped_set"}:
                return True
        return False

    refined_keys = {
        key
        for key in final_branch_keys
        if key in branches and has_entity_refinement(branches[key])
    }
    if len(refined_keys) < 2:
        return
    if any(
        result.result_kind == "entities"
        and result.source_ref == "final:primary"
        for result in draft.results
    ):
        raise BusinessDraftError(
            "多分支最终判定是布尔来源，不能作为实体框结果来源。"
        )

    covered = set()
    for result in draft.results:
        if result.result_kind != "entities":
            continue
        if result.source_ref.startswith("branch:"):
            covered.add(result.source_ref.split(":", 1)[1])
        elif result.source_ref.startswith("condition:"):
            value = result.source_ref.split(":", 1)[1]
            if "." in value:
                covered.add(value.split(".", 1)[0])
    missing = refined_keys - covered
    if missing:
        raise BusinessDraftError(
            "独立实体分支缺少可绘制的 entities 结果："
            + "、".join(sorted(missing))
        )


def _descriptor_tokens(value: Any) -> set[str]:
    """Return comparable words from an LLM evidence description."""

    if value is None:
        return set()
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", str(value))
    }


def _evidence_match_score(reference: str, candidate: DraftCondition) -> int:
    """Score a plain evidence description against a sibling condition.

    The draft schema requires typed condition references at runtime, but an LLM
    often emits the human-readable evidence phrase instead.  Matching both the
    display name and normalized parameters keeps this conversion generic across
    colors, clothing parts, equipment, and future evidence capabilities.
    """

    reference_tokens = _descriptor_tokens(reference)
    if not reference_tokens:
        return 0
    compact_reference = re.sub(r"[\s_\-]+", "", str(reference)).lower()
    compact_name = re.sub(r"[\s_\-]+", "", candidate.name).lower()
    if compact_reference == compact_name or compact_reference in compact_name:
        return 900 + len(compact_name)
    candidate_text = " ".join(
        [
            candidate.key,
            candidate.name,
            candidate.capability_id or "",
            *(
                str(value)
                for key, value in candidate.parameters.items()
                if key not in {"source", "minimum_fraction", "minimum_overlap", "association"}
                and value is not None
            ),
        ]
    )
    candidate_tokens = _descriptor_tokens(candidate_text)
    parameter_tokens = _descriptor_tokens(
        " ".join(
            str(value)
            for key, value in candidate.parameters.items()
            if key not in {"source", "minimum_fraction", "minimum_overlap", "association"}
            and value is not None
        )
    )
    if reference.strip().lower() in {
        candidate.key.lower(),
        candidate.name.lower(),
    }:
        return 1000
    # Parameter semantics are stronger than a shared generic word such as
    # "color" or "attribute".  Requiring all parameter tokens prevents two
    # same-type conditions from being selected accidentally.
    if parameter_tokens and parameter_tokens.issubset(reference_tokens):
        return 100 + len(parameter_tokens)
    if candidate_tokens and candidate_tokens.issubset(reference_tokens):
        return 50 + len(candidate_tokens)
    return 0


def _bind_plain_evidence_reference(
    reference: Any,
    *,
    branch: DraftBranch,
    current_condition: DraftCondition,
    condition_ids: dict[tuple[str, str], str],
) -> Any:
    """Convert an LLM evidence phrase into an executable condition reference."""

    if not isinstance(reference, str) or ":" in reference:
        return reference
    candidates = [
        item
        for item in _walk_draft_conditions(branch.conditions)
        if item is not current_condition
        and item.operator == "ATOM"
        and item.capability_id not in {"subject.same_attributes", "subject.missing_equipment"}
    ]
    scored = [
        (score, item)
        for item in candidates
        if (score := _evidence_match_score(reference, item)) > 0
    ]
    if not scored:
        raise BusinessDraftError(
            f"分支“{branch.name}”中的属性或装备证据“{reference}”无法绑定到已有条件。"
            "请让生成结果引用 condition:key，或先生成对应的属性/装备条件。"
        )
    best_score = max(score for score, _ in scored)
    best = [item for score, item in scored if score == best_score]
    if len(best) != 1:
        names = "、".join(item.name for item in best)
        raise BusinessDraftError(
            f"属性或装备证据“{reference}”匹配到多个条件：{names}。"
            "请使用 condition:key 明确指定。"
        )
    candidate = best[0]
    return f"condition:{branch.key}.{candidate.key}"


def _bind_evidence_parameters(
    condition: DraftCondition,
    *,
    branch: DraftBranch,
    condition_ids: dict[tuple[str, str], str],
) -> dict[str, Any]:
    """Normalize typed evidence inputs before the draft becomes editor data."""

    parameters = dict(condition.parameters)
    if condition.capability_id == "subject.same_attributes":
        references = parameters.get("attributes", [])
        references = references if isinstance(references, list) else [references]
        parameters["attributes"] = [
            _bind_plain_evidence_reference(
                item,
                branch=branch,
                current_condition=condition,
                condition_ids=condition_ids,
            )
            for item in references
        ]
    elif condition.capability_id == "subject.missing_equipment":
        parameters["equipment"] = _bind_plain_evidence_reference(
            parameters.get("equipment"),
            branch=branch,
            current_condition=condition,
            condition_ids=condition_ids,
        )
        if parameters.get("semantic_evidence"):
            parameters["semantic_evidence"] = _bind_plain_evidence_reference(
                parameters.get("semantic_evidence"),
                branch=branch,
                current_condition=condition,
                condition_ids=condition_ids,
            )
    return parameters


def _lift_misplaced_target_scopes(draft: NaturalLanguageBusinessDraft) -> None:
    """Turn an LLM's ``target.detect(scope=region)`` into membership.

    Detection deliberately has no spatial scope: it produces the reusable raw
    entity set.  Models still commonly attach a region directly to detection.
    The intended business meaning is unambiguous, so repair it deterministically
    instead of asking the user to correct an internal schema detail.
    """

    for branch in draft.branches:
        existing_keys = {
            item.key for item in _walk_draft_conditions(branch.conditions)
        }
        additions: list[DraftCondition] = []
        atoms = list(_walk_draft_conditions(branch.conditions))
        for condition in atoms:
            if (
                condition.operator != "ATOM"
                or condition.capability_id != "target.detect"
                or "scope" not in condition.parameters
            ):
                continue
            scope = condition.parameters.pop("scope")
            if scope in {None, "", "full_frame"}:
                continue
            source_refs = {
                f"condition:{condition.key}",
                f"condition:{branch.key}.{condition.key}",
            }
            existing = next(
                (
                    item
                    for item in atoms
                    if item.operator == "ATOM"
                    and item.capability_id == "spatial.membership"
                    and item.parameters.get("scope") == scope
                    and item.parameters.get("source") in source_refs
                ),
                None,
            )
            if existing is not None:
                continue
            base_key = f"{condition.key}_scope_membership"
            key = base_key
            suffix = 2
            while key in existing_keys:
                key = f"{base_key}_{suffix}"
                suffix += 1
            existing_keys.add(key)
            membership = DraftCondition(
                key=key,
                name=f"{condition.name}属于指定区域",
                capability_id="spatial.membership",
                parameters={
                    "source": f"condition:{condition.key}",
                    "scope": scope,
                    "membership": "center",
                    "inside": True,
                },
            )
            additions.append(membership)
            atoms.append(membership)
        branch.conditions.extend(additions)


def apply_business_rule_draft(
    document: SkillEditorDocument,
    draft: NaturalLanguageBusinessDraft | dict[str, Any],
    capabilities: BusinessCapabilityRegistry,
    *,
    requested_accept: list[str],
    final_display_name: str | None = None,
) -> SkillEditorDocument:
    """Validate and install an LLM business draft into the sole editor document."""

    if isinstance(draft, dict):
        draft = normalize_business_draft_payload(draft)
    draft = NaturalLanguageBusinessDraft.model_validate(draft)
    _lift_misplaced_target_scopes(draft)
    _repair_required_tracks(draft)
    _repair_redundant_temporal_atoms(draft)
    _repair_non_actionable_geometry(draft)
    _repair_degenerate_patterns(draft)
    _repair_independent_business_branches(draft, capabilities)
    _repair_inline_state_evidence(draft)
    _repair_same_subject_attributes(draft)
    _repair_missing_equipment_evidence(draft)
    _repair_independent_entity_results(draft, capabilities)
    _repair_entity_result_sources(draft, capabilities)
    _validate_business_orchestration_invariants(draft, capabilities)
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
            # LLMs occasionally omit the ``resource:`` prefix when the
            # resource key is already unambiguous in this draft.  Canonicalize
            # that harmless shorthand before capability validation.
            if reference in resource_ids:
                return resource_ids[reference]
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
                # Result/final references have no current branch.  Recover an
                # unqualified or stale branch prefix only when the condition
                # key is globally unique; ambiguity still requires review.
                unique = [
                    value
                    for (candidate_branch, candidate_key), value in condition_ids.items()
                    if candidate_key == condition_key
                ]
                if len(unique) == 1:
                    condition_id = unique[0]
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
            if definition.orchestration_slot != "condition":
                raise BusinessDraftError(
                    f"业务能力“{condition.capability_id}”属于"
                    f"{definition.orchestration_slot} 编排槽位，不能作为普通条件。"
                )
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
            parameters.update(
                transform(
                    _bind_evidence_parameters(
                        condition,
                        branch=branch,
                        condition_ids=condition_ids,
                    ),
                    branch.key,
                )
            )
            if (
                condition.capability_id == "motion.speed"
                and parameters.get("motion_state") in (None, "")
                and parameters.get("operator") not in (None, "")
                and parameters.get("threshold") is not None
            ):
                parameters["motion_state"] = "speed"
            parameter_definitions = {
                item.parameter_id: item for item in definition.parameters
            }
            unknown_parameters = set(parameters) - set(parameter_definitions)
            # Units are display metadata owned by the capability definition;
            # they never alter execution and are not node parameters.
            if "unit" in unknown_parameters:
                parameters.pop("unit", None)
                unknown_parameters.remove("unit")
            if (
                condition.capability_id == "motion.speed"
                and "aggregation" in unknown_parameters
                and parameters.get("aggregation")
                in {None, "per_object", "per_track", "object", "track"}
            ):
                parameters.pop("aggregation", None)
                unknown_parameters.remove("aggregation")
            if unknown_parameters:
                raise BusinessDraftError(
                    f"“{condition.name}”包含不支持的参数："
                    + "、".join(sorted(unknown_parameters))
                )
            parameters = {
                key: _normalize_llm_parameter(parameter_definitions[key], value)
                for key, value in parameters.items()
            }
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
        atoms = [
            expression
            for expression in expressions
            if expression.operator == "ATOM"
        ]
        same_subject = next(
            (
                expression
                for expression in reversed(atoms)
                if expression.capability_id == "subject.same_attributes"
            ),
            None,
        )
        if same_subject is not None:
            same_subject_source = str(
                same_subject.parameters.get("subject") or ""
            ).split(".")[-1]
            for expression in atoms:
                if expression.capability_id != "spatial.membership":
                    continue
                # Only move a membership filter after the same-subject join
                # when it originally filtered that join's own source.  With
                # multiple named regions, a membership condition can be the
                # source of the clothing join; rebinding it to the join would
                # create a cycle and lose the region boundary.
                original_source = str(
                    expression.parameters.get("source") or ""
                ).split(".")[-1]
                if original_source != same_subject_source:
                    continue
                expression.parameters["source"] = (
                    f"condition:{same_subject.expression_id}"
                )
                expression.parameter_sources["source"] = ResolvableValue(
                    state="inferred",
                    value=expression.parameters["source"],
                    source="deterministic_same_subject_chain",
                    required_before="never",
                )
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
    "normalize_business_draft_payload",
]
