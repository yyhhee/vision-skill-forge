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
            if item.get("children") is None and (
                item.get("operator", "ATOM") == "ATOM"
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

        repair_scope(branch.conditions, branch.logic)


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
                    actionable = (
                        parameters.get("dimension") in valid_dimensions
                        and parameters.get("operator") not in (None, "")
                        and parameters.get("threshold") is not None
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

    for branch in draft.branches:
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


def _repair_entity_result_sources(
    draft: NaturalLanguageBusinessDraft,
    capabilities: BusinessCapabilityRegistry,
) -> None:
    """Point entity results at the most reduced entity evidence in a branch."""

    branches = {item.key: item for item in draft.branches}
    for result in draft.results:
        if result.result_kind != "entities":
            continue
        source_ref = result.source_ref
        if source_ref == "final:primary":
            final_sources = draft.final_decision.source_refs
            if len(final_sources) != 1:
                continue
            source_ref = final_sources[0]
        if not source_ref.startswith("branch:"):
            continue
        branch = branches.get(source_ref.split(":", 1)[1])
        if branch is None:
            continue
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
            selected = max(candidates, key=lambda item: item[0])[1]
            result.source_ref = _condition_reference(branch.key, selected)


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
    _repair_inline_state_evidence(draft)
    _repair_non_actionable_geometry(draft)
    _repair_degenerate_patterns(draft)
    _repair_same_subject_attributes(draft)
    _repair_missing_equipment_evidence(draft)
    _repair_entity_result_sources(draft, capabilities)
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
            for expression in atoms:
                if expression.capability_id != "spatial.membership":
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
