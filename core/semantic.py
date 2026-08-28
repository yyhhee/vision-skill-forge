from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from .registry import OperatorRegistry
from .schema import CanonicalSemanticIR, SemanticConstraint, SkillPackage
from .validator import assert_valid_skill_package
from .visual_catalog import (
    ATTRIBUTE_CATALOG,
    CARRIER_CATALOG,
    CARRIER_TEXT_ALIASES,
    COLOR_ALIASES,
    COLOR_NAMES,
    COLOR_MIN_FRACTIONS,
    COUNT_OPERATORS,
    SPATIAL_RELATIONS,
)


class SemanticValidationError(ValueError):
    pass


_ATOMIC_NEGATIONS = ("没有", "未", "无", "没", "不", "非", "缺失")
_COLLECTION_NEGATIONS = ("排除", "去除", "剔除", "负样本")
_NUMERIC_NEGATION = re.compile(
    r"不(?:少于|低于|超过|高于|等于|大于|小于|早于|晚于|短于|长于)"
)
_NAMED_REGION_HINT = re.compile(r"固定区域|指定区域|标注区域|命名区域|区域内")
_FULL_FRAME_HINT = re.compile(r"全画面|整个画面|画面中|视频里|视野内")
_OPEN_ENGLISH_CARRIER = re.compile(r"^[a-z][a-z0-9 _-]{0,63}$")
_CLAUSE_SEPARATORS = "，,、；;。"
_FORBIDDEN_GROUNDING = re.compile(
    r"\b(not|without|unsupported|exclude|except|rather\s+than)\b", re.I
)
_CHINESE_COLOR_PATTERN = "|".join(
    re.escape(name)
    for name in sorted(COLOR_ALIASES, key=len, reverse=True)
    if re.search(r"[\u4e00-\u9fff]", name)
)
_POSE_ACTION = re.compile(
    r"\b(standing|walking|running|sitting|squatting|crouching|kneeling|"
    r"lying|bending|falling|climbing|jumping|waving|reaching|carrying)\b",
    re.I,
)
_WEARABLE_SOURCE = re.compile(
    r"(?:未|没|无|不)?(?:佩戴|配戴|戴着?|带着?|穿着?|系着?|挂着?|套着?|装备)"
)
_WEARABLE_SUBJECT = re.compile(
    r"\b(person|worker|pedestrian|rider|man|woman|child|operator)\b",
    re.I,
)
_WEARING_PHRASE = re.compile(
    r"\b(?:is\s+)?(?:wearing|wears|with)\s+(?:an?\s+|the\s+)?(.+)$",
    re.I,
)
_FALLEN_OR_LYING_TERMS = re.compile(
    r"(?:摔倒|跌倒|倒地|躺卧|躺在地上|fallen|falling|lying(?:\s+on\s+the\s+ground)?)",
    re.I,
)
_IMMEDIATE_EVENT_INTENT = re.compile(
    r"(?:是否|触发(?:事件|告警|报警)?|事件告警|报警|告警|预警|通知)",
    re.I,
)
_EVENT_OUTPUT_CLAUSE = re.compile(
    r"(?:发出|触发|生成|发送).*(?:事件|告警|报警|预警|通知)",
    re.I,
)
_EXPLICIT_TEMPORAL_EVIDENCE = re.compile(
    r"(?:持续|连续|累计|窗口|随后|之后|以后|先.+(?:再|后)|"
    r"\d+(?:\.\d+)?\s*(?:秒|分钟|分|帧)|徘徊|逗留|停留|滞留)",
    re.I,
)
_COUNT_COMPARISON_WITHOUT_VALUE = re.compile(
    r"(?:人的数量|人员数量|车辆数量|目标数量|人数|车辆数|目标数|数量|计数)\s*"
    r"(?P<operator>大于等于|小于等于|不小于|不大于|不超过|至少|至多|大于|超过|等于|小于|少于)\s*"
    r"(?=(?:，|,|；|;|。|则|并且|且|$))"
)
_COUNT_OPERATOR_ALIASES = {
    "大于等于": ">=", "不小于": ">=", "至少": ">=",
    "大于": ">", "超过": ">",
    "等于": "==",
    "小于等于": "<=", "不大于": "<=", "不超过": "<=", "至多": "<=",
    "小于": "<", "少于": "<",
}
_NUMBERED_REGION = re.compile(r"区域\s*(?P<number>\d+)", re.I)


def _canonical_region_role(value: Any) -> str | None:
    """Return a stable role for common numbered-region spellings."""

    match = re.search(r"(?:区域|region)[ _-]*(\d+)", str(value or ""), re.I)
    return f"region{match.group(1)}" if match else None


def _repair_explicit_numbered_regions(
    data: dict[str, Any], instruction: str
) -> None:
    """Normalize recoverable planner variations for explicit ``区域N`` clauses."""

    constraints = data.get("constraints") or []
    if not isinstance(constraints, list):
        return
    needs_repair = any(
        isinstance(item, dict)
        and (
            "group_by" in item
            or "region_role" in item
            or (
                str(item.get("kind", "")).strip().lower() == "position"
                and _canonical_region_role(item.get("value")) is not None
            )
        )
        for item in constraints
    ) or any(
        "unknown position" in str(item.get("reason", "")).lower()
        and _canonical_region_role(item.get("source_span") or item.get("reason"))
        for item in (data.get("unresolved") or [])
    )
    if not needs_repair:
        return

    # Some planners put these value fields beside ``value``. Accept that
    # harmless shape variation, then keep the canonical IR strict.
    for item in constraints:
        if not isinstance(item, dict) or item.get("kind") not in {"quantity", "motion"}:
            continue
        value = item.get("value")
        value = dict(value) if isinstance(value, dict) else {}
        for key in ("group_by", "region_role"):
            if key in item and key not in value:
                value[key] = item[key]
            item.pop(key, None)
        if _canonical_region_role(value.get("region_role")):
            value["group_by"] = "named_region"
        item["value"] = value

    explicit = [
        (match.group(0), f"region{match.group('number')}")
        for match in _NUMBERED_REGION.finditer(instruction)
    ]
    if not explicit:
        return

    repaired: list[dict[str, Any]] = []
    required_roles: set[str] = set()
    for item in constraints:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip().lower()
        span = str(item.get("source_span", ""))
        position_role = _canonical_region_role(item.get("value")) if kind == "position" else None
        if kind == "position" and position_role:
            required_roles.add(position_role)
            region_span = next(
                (visible for visible, role in explicit if role == position_role),
                span,
            )
            repaired.append({
                "kind": "region_requirement",
                "value": {
                    "source": "manual",
                    "cardinality": "one",
                    "semantic_role": position_role,
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": _source_clause(instruction, region_span),
                "source_span": region_span,
                "phrases": [],
                "temporal": False,
            })
            continue
        repaired.append(item)
    constraints[:] = repaired

    existing_role_values = {
        _canonical_region_role(item.get("value", {}).get("semantic_role")):
        item.get("value", {}).get("semantic_role")
        for item in constraints
        if isinstance(item, dict)
        and item.get("kind") == "region_requirement"
        and isinstance(item.get("value"), dict)
    }
    existing_roles = set(existing_role_values)
    for item in constraints:
        if not isinstance(item, dict) or item.get("kind") not in {"quantity", "motion"}:
            continue
        source = str(item.get("source") or item.get("source_span") or "")
        matched_role = next(
            (role for visible, role in explicit if visible in source),
            None,
        )
        value = item.get("value")
        value_role = (
            _canonical_region_role(value.get("region_role"))
            if isinstance(value, dict)
            else None
        )
        role = matched_role or value_role
        if role and isinstance(value, dict):
            required_roles.add(role)
            value["group_by"] = "named_region"
            if matched_role:
                value["region_role"] = existing_role_values.get(
                    matched_role, matched_role
                )

    for region_span, role in explicit:
        if role not in required_roles:
            continue
        if role in existing_roles:
            continue
        constraints.append({
            "kind": "region_requirement",
            "value": {
                "source": "manual",
                "cardinality": "one",
                "semantic_role": role,
                "allowed_shapes": ["rectangle", "polygon"],
            },
            "source": _source_clause(instruction, region_span),
            "source_span": region_span,
            "phrases": [],
            "temporal": False,
        })

    configured_roles = {role for _visible, role in explicit}
    data["unresolved"] = [
        item
        for item in (data.get("unresolved") or [])
        if not (
            "unknown position" in str(item.get("reason", "")).lower()
            and _canonical_region_role(
                item.get("source_span") or item.get("reason")
            ) in configured_roles
        )
    ]


def _has_immediate_event_intent(instruction: str) -> bool:
    """Return whether a video query asks for a boolean event outcome.

    Object detection remains detection-only unless the user explicitly asks a
    yes/no or alert-style question.  This keeps ordinary phrases such as
    ``检测视频中的车辆`` from silently acquiring an event stream while
    making ``识别视频中是否有人摔倒`` executable as an immediate event.
    """

    return bool(_IMMEDIATE_EVENT_INTENT.search(instruction))


def find_incomplete_count_comparisons(instruction: str) -> list[tuple[str, str]]:
    """Return explicit count operators whose numeric threshold is missing."""

    return [
        (match.group(0).strip(), _COUNT_OPERATOR_ALIASES[match.group("operator")])
        for match in _COUNT_COMPARISON_WITHOUT_VALUE.finditer(instruction)
    ]


def _repair_incomplete_count_comparisons(
    data: dict[str, Any], instruction: str
) -> None:
    """Keep an incomplete comparison compilable until step 03 confirms it."""

    matches = find_incomplete_count_comparisons(instruction)
    if not matches:
        return
    matched_spans = [span for span, _operator in matches]
    data["unresolved"] = [
        item
        for item in (data.get("unresolved") or [])
        if not any(
            (item_span := str(item.get("source_span", "")).strip())
            and (item_span in span or span in item_span)
            for span in matched_spans
        )
    ]
    constraints = data.setdefault("constraints", [])
    quantity_constraints = [
        item for item in constraints if item.get("kind") == "quantity"
    ]
    for index, (span, operator) in enumerate(matches):
        if index < len(quantity_constraints):
            item = quantity_constraints[index]
            value = item.get("value")
            value = dict(value) if isinstance(value, dict) else {}
            value.update({"measure": "count", "operator": operator, "value": 1})
            item["value"] = value
            continue
        constraints.append({
            "kind": "quantity",
            "value": {"measure": "count", "operator": operator, "value": 1},
            "source": span,
            "source_span": span,
            "phrases": [],
            "temporal": False,
        })


def _canonical_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _append_grounding(
    nodes: list[dict[str, Any]],
    node_id: str,
    frames: str,
    targets: list[dict[str, Any]],
    *,
    semantic_node: bool = False,
) -> tuple[str, list[str]]:
    raw_id = node_id if semantic_node else f"{node_id}_raw"
    dedup_id = f"{node_id}_dedup" if semantic_node else node_id
    nodes.extend([
        {
            "id": raw_id,
            "op": "rex.ground@1.1",
            "inputs": {"frames": frames},
            "params": {"targets": targets},
        },
        {
            "id": dedup_id,
            "op": "objects.deduplicate@1.0",
            "inputs": {"objects": f"${raw_id}"},
            "params": {"metric": "ios", "threshold": 0.5, "keep": "first"},
        },
    ])
    return f"${dedup_id}", [raw_id, dedup_id]


def _final_polarity(source: str, source_span: str) -> str:
    # “不少于 / 不超过 / 不等于” encode comparison operators; they are not
    # absence predicates and must not invert the resulting condition again.
    predicate_span = _NUMERIC_NEGATION.sub("", source_span)
    atomic_negative = any(marker in predicate_span for marker in _ATOMIC_NEGATIONS)
    collection_negative = any(marker in source for marker in _COLLECTION_NEGATIONS)
    return "absent" if atomic_negative ^ collection_negative else "required"


def _base_entity_phrases(phrases: list[str], concept: str) -> list[str]:
    """Remove attribute adjectives when an LLM leaks them into base targets."""

    cleaned = []
    color_pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(value) for value in COLOR_NAMES) + r")\b",
        re.I,
    )
    for phrase in phrases:
        value = re.sub(r"\s+", " ", color_pattern.sub(" ", phrase)).strip()
        if value:
            cleaned.append(value)
    return list(dict.fromkeys(cleaned)) or [concept]


def _repair_named_region_constraints(data: dict[str, Any], instruction: str) -> None:
    """Make an explicit named-region phrase executable if the model omitted wiring."""

    if _FULL_FRAME_HINT.search(instruction):
        return
    region_match = _NAMED_REGION_HINT.search(instruction)
    constraints = data.get("constraints") or []
    if region_match is None or not isinstance(constraints, list):
        return
    if not any(
        item.get("kind") in {"quantity", "motion"}
        for item in constraints
    ):
        return
    if any(
        item.get("kind") == "spatial_relation"
        and isinstance(item.get("value"), dict)
        and item["value"].get("region", {}).get("source") == "manual"
        for item in constraints
    ):
        return
    region_constraints = [
        item for item in constraints
        if item.get("kind") == "region_requirement"
        and isinstance(item.get("value"), dict)
        and item["value"].get("source") == "manual"
    ]
    if region_constraints:
        region_role = str(
            region_constraints[0]["value"].get("semantic_role") or "area"
        )
    else:
        region_role = "area"
        constraints.append({
            "kind": "region_requirement",
            "value": {
                "source": "manual",
                "cardinality": "one",
                "semantic_role": region_role,
                "allowed_shapes": ["rectangle", "polygon"],
            },
            "source": region_match.group(0),
            "source_span": region_match.group(0),
            "phrases": [],
            "temporal": False,
        })
    for item in constraints:
        if item.get("kind") not in {"quantity", "motion"}:
            continue
        value = item.get("value")
        if not isinstance(value, dict) or value.get("group_by"):
            continue
        value["group_by"] = "named_region"
        value["region_role"] = region_role
        if (
            item["kind"] == "motion"
            and value.get("aggregation")
            in {None, "per_track", "global_mean", "global_median"}
        ):
            value["aggregation"] = "region_median"


def _repair_configurable_region_unresolved(data: dict[str, Any]) -> None:
    """Treat unknown manual geometry as step-03 configuration, not semantics."""

    region_spans = [
        str(item.get("source_span", "")).strip()
        for item in (data.get("constraints") or [])
        if (
            (
                item.get("kind") == "region_requirement"
                and isinstance(item.get("value"), dict)
                and item["value"].get("source") == "manual"
            )
            or (
                item.get("kind") == "spatial_relation"
                and isinstance(item.get("value"), dict)
                and isinstance(item["value"].get("region"), dict)
                and item["value"]["region"].get("source") == "manual"
            )
        )
        and str(item.get("source_span", "")).strip()
    ]
    if not region_spans:
        return
    data["unresolved"] = [
        item
        for item in (data.get("unresolved") or [])
        if not any(
            (item_span := str(item.get("source_span", "")).strip())
            and (item_span in region_span or region_span in item_span)
            for region_span in region_spans
        )
    ]


def _repair_default_speed_unit_unresolved(data: dict[str, Any]) -> None:
    """Treat the engine's explicit pixel-speed unit as executable metadata."""

    speed_spans = [
        str(item.get("source_span", "")).strip()
        for item in (data.get("constraints") or [])
        if item.get("kind") == "motion"
        and isinstance(item.get("value"), dict)
        and item["value"].get("measure") == "speed"
        and item["value"].get("unit")
        in {"pixels_per_second", "pixel_per_second", "px/s", "pixel/s"}
    ]
    if not speed_spans:
        return
    data["unresolved"] = [
        item
        for item in (data.get("unresolved") or [])
        if not (
            "单位" in str(item.get("reason", ""))
            and any(
                (span := str(item.get("source_span", "")).strip())
                and (span in speed_span or speed_span in span)
                for speed_span in speed_spans
            )
        )
    ]


def _repair_manual_direction_references(data: dict[str, Any]) -> None:
    """Treat a requested manual direction as scene configuration."""

    spans: list[str] = []
    for item in data.get("constraints") or []:
        if not isinstance(item, dict) or item.get("kind") != "direction_relation":
            continue
        value = item.get("value")
        if not isinstance(value, dict) or value.get("reference_source") != "manual":
            continue
        # ``manual`` describes the source of the direction, not its scope.
        # A single drawn reference is global unless the model explicitly
        # requests one direction per named region.
        if value.get("reference_scope") in (None, "", "manual"):
            value["reference_scope"] = "global"
        if value.get("reference_scope") not in {"global", "per_named_region"}:
            continue
        span = str(item.get("source_span", "")).strip()
        if span:
            spans.append(span)
    if not spans:
        return
    data["unresolved"] = [
        item
        for item in (data.get("unresolved") or [])
        if not (
            any(
                (span := str(item.get("source_span", "")).strip())
                and (span in direction_span or direction_span in span)
                for direction_span in spans
            )
            or (
                "参考方向" in str(item.get("source_span", ""))
                and any(
                    token in str(item.get("reason", "")).lower()
                    for token in ("参考", "direction", "reference")
                )
            )
        )
    ]


def _repair_open_enumeration_unresolved(data: dict[str, Any]) -> None:
    """Accept an open example list when an umbrella target is also present."""

    target = data.get("target") or {}
    classes = target.get("classes") or []
    if not isinstance(classes, list) or len(classes) < 2:
        return
    target_span = str(target.get("source_span", ""))
    if not any(token in target_span for token in ("等", "etc", "such as")):
        return
    data["unresolved"] = [
        item
        for item in (data.get("unresolved") or [])
        if not (
            str(item.get("source_span", "")).strip().lower()
            in {"等", "等等", "etc", "etc."}
            and any(
                token in str(item.get("reason", "")).lower()
                for token in ("列举", "未尽", "其他", "other", "enumerat")
            )
        )
    ]


def _repair_open_position_regions(data: dict[str, Any]) -> None:
    """Turn non-screen position concepts into configurable scene regions."""

    constraints = data.get("constraints") or []
    if not isinstance(constraints, list):
        return
    known_positions = set(ATTRIBUTE_CATALOG["position"]["values"])
    repaired_spans: set[str] = set()
    used_roles: set[str] = set()
    for index, item in enumerate(list(constraints), start=1):
        if not isinstance(item, dict):
            continue
        if str(item.get("kind", "")).strip().lower() != "position":
            continue
        value = str(item.get("value", "")).strip().lower()
        if value in known_positions:
            continue
        role = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
        role = role or f"scene_region_{index}"
        base_role = role
        suffix = 2
        while role in used_roles:
            role = f"{base_role}_{suffix}"
            suffix += 1
        used_roles.add(role)
        span = str(item.get("source_span", "")).strip()
        repaired_spans.add(span)
        constraints[index - 1] = {
            "kind": "region_requirement",
            "value": {
                "source": "manual",
                "cardinality": "one",
                "semantic_role": role,
                "allowed_shapes": ["rectangle", "polygon"],
            },
            "source": item.get("source") or span,
            "source_span": span,
            "phrases": [],
            "temporal": False,
        }
    if repaired_spans:
        data["unresolved"] = [
            item
            for item in (data.get("unresolved") or [])
            if not (
                str(item.get("source_span", "")).strip() in repaired_spans
                and "unknown position" in str(item.get("reason", "")).lower()
            )
        ]


def _repair_event_output_unresolved(data: dict[str, Any]) -> None:
    """An alert-output clause is a trigger policy, not a visual predicate."""

    data["unresolved"] = [
        item
        for item in (data.get("unresolved") or [])
        if not _EVENT_OUTPUT_CLAUSE.search(
            str(item.get("source_span", "")).strip()
        )
    ]


def _wearable_retyping(
    *,
    kind: str,
    value: Any,
    source_span: str,
    phrases: list[Any],
    target_concept: str,
    target_phrases: list[str],
) -> tuple[str, Any, list[str]]:
    """Retype an LLM's category exclusion when it is grammatically a property.

    The rule is deliberately item-agnostic: a wear verb in the source, or an
    affirmative whole-subject ``person wearing X`` phrase, means the excluded
    thing is a predicate of the candidate subject. Independent classes such as
    truck/van remain ``entity_exclusion``.
    """

    normalized_phrases = [
        re.sub(r"\s+", " ", str(phrase)).strip().lower()
        for phrase in phrases
        if str(phrase).strip()
    ]
    if kind != "entity_exclusion":
        return kind, value, normalized_phrases

    phrase_has_subject_wearing = any(
        _WEARABLE_SUBJECT.search(phrase) and _WEARING_PHRASE.search(phrase)
        for phrase in normalized_phrases
    )
    if not (_WEARABLE_SOURCE.search(source_span) or phrase_has_subject_wearing):
        return kind, value, normalized_phrases

    part_phrases: list[str] = []
    for phrase in normalized_phrases:
        match = _WEARING_PHRASE.search(phrase)
        part = (match.group(1) if match else phrase).strip()
        part = re.sub(
            r"^(?:person|worker|pedestrian|rider|man|woman|child|operator)\s+",
            "",
            part,
            flags=re.I,
        )
        if part and part not in part_phrases:
            part_phrases.append(part)
    if not part_phrases:
        part = str(value).strip().lower().replace("_", " ")
        if part:
            part_phrases.append(part)

    subject_base = target_concept.strip().lower()
    if not _WEARABLE_SUBJECT.fullmatch(subject_base):
        subject_base = next(
            (
                match.group(1).lower()
                for phrase in normalized_phrases
                if (match := _WEARABLE_SUBJECT.search(phrase))
            ),
            (target_phrases[0] if target_phrases else target_concept).strip().lower(),
        )
    subject_phrases = [
        f"{subject_base} wearing {part}" for part in part_phrases
    ]

    canonical_value = value
    wearable_text = " ".join([str(value), source_span, *part_phrases]).lower()
    if any(token in wearable_text for token in ("安全帽", "hard hat", "safety helmet")):
        canonical_value = "safety_helmet"
        subject_phrases = [f"{subject_base} wearing safety helmet"]
    return "wearable", canonical_value, subject_phrases


def _fallen_pose_retyping(
    *,
    kind: str,
    value: Any,
    source_span: str,
    phrases: list[Any],
    target_concept: str,
    target_phrases: list[str],
) -> tuple[str, Any, list[Any]]:
    """Canonicalize an observed fallen state as a visible lying pose.

    A duration condition can verify that an observed pose persists, but cannot
    establish an unobserved standing-to-falling action.  This normalization
    keeps the executable evidence tied to the visible, reusable pose rather
    than an ambiguous open-vocabulary ``fallen`` wording.
    """

    if kind not in {"state", "pose"}:
        return kind, value, phrases

    evidence = " ".join(
        [str(value), source_span, *(str(phrase) for phrase in phrases)]
    )
    if not _FALLEN_OR_LYING_TERMS.search(evidence):
        return kind, value, phrases

    subject = next(
        (phrase.strip() for phrase in target_phrases if phrase.strip()),
        target_concept.strip(),
    )
    return "pose", "fallen_or_lying", [f"{subject} lying on the ground"]


def _covered_collection_negations(
    instruction: str, constraints: list[dict[str, Any]]
) -> None:
    """Reject ledgers that silently drop a user-authored exclusion clause."""

    for marker in _COLLECTION_NEGATIONS:
        if marker not in instruction:
            continue
        if not any(marker in str(item.get("source", "")) for item in constraints):
            raise SemanticValidationError(
                f"exclusion clause is not covered by any constraint: {marker}"
            )


def _audit_registered_dimension_coverage(
    instruction: str, constraints: list[dict[str, Any]]
) -> None:
    """Catch high-signal registered dimensions that an LLM silently omitted."""

    if ("数量" in instruction or "计数" in instruction) and not any(
        item.get("kind") == "quantity" for item in constraints
    ):
        raise SemanticValidationError("quantity semantics are not covered")


def _source_clause(instruction: str, source_span: str) -> str:
    start = instruction.find(source_span)
    if start < 0:
        return instruction
    left = max((instruction.rfind(mark, 0, start) for mark in _CLAUSE_SEPARATORS), default=-1)
    ends = [instruction.find(mark, start + len(source_span)) for mark in _CLAUSE_SEPARATORS]
    right = min((index for index in ends if index >= 0), default=len(instruction))
    return instruction[left + 1:right].strip()


def _canonical_signature(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        # direct_grounding/entity_query are execution-planning hints; the
        # semantic identity is determined by target + predicates.
        "mode": "workflow" if data["mode"] == "workflow" else "entity_query",
        "target": {
            "concept": data["target"]["concept"],
            "phrases": data["target"]["phrases"],
            "classes": data["target"].get("classes", []),
        },
        "constraints": [
            {
                "kind": item["kind"],
                "value": item["value"],
                "polarity": item["polarity"],
                "carrier": item.get("carrier"),
                # Closed deterministic dimensions do not execute their LLM
                # phrase aliases, so those aliases must not destabilize hash.
                "phrases": []
                if item["kind"] in {"color", "size", "position", "quantity"}
                else item.get("phrases", []),
                "temporal": item.get("temporal", False),
            }
            for item in data["constraints"]
        ],
        "logic": data["logic"],
        "unresolved": [item["reason"] for item in data["unresolved"]],
    }


class SemanticNormalizer:
    def infer_target(self, instruction: str) -> dict[str, Any]:
        """Infer only the base target without validating every condition."""

        ledger = self._extract_supported_ledger(instruction.strip())
        return deepcopy(ledger["target"])

    def normalize_text(self, instruction: str) -> CanonicalSemanticIR:
        text = instruction.strip()
        ledger = self._extract_supported_ledger(text)
        return self.normalize_ledger(ledger, text)

    def normalize_ledger(
        self, ledger: dict[str, Any], instruction: str
    ) -> CanonicalSemanticIR:
        data = deepcopy(ledger)
        _repair_incomplete_count_comparisons(data, instruction)
        _repair_explicit_numbered_regions(data, instruction)
        _repair_named_region_constraints(data, instruction)
        _repair_open_position_regions(data)
        _repair_configurable_region_unresolved(data)
        _repair_default_speed_unit_unresolved(data)
        _repair_manual_direction_references(data)
        _repair_open_enumeration_unresolved(data)
        _repair_event_output_unresolved(data)
        target = data.get("target") or {}
        target_span = str(target.get("source_span", "")).strip()
        if not target_span or target_span not in instruction:
            raise SemanticValidationError("target source_span is not present in instruction")
        target["concept"] = str(target.get("concept", "")).strip().lower()
        target["phrases"] = list(dict.fromkeys(
            str(value).strip().lower() for value in target.get("phrases", []) if str(value).strip()
        ))
        if not target["concept"] or not target["phrases"]:
            raise SemanticValidationError("target concept and phrases are required")
        target_classes = []
        for raw_class in target.get("classes", []):
            label = str(raw_class.get("label", "")).strip()
            phrases = list(dict.fromkeys(
                str(value).strip().lower()
                for value in raw_class.get("phrases", [])
                if str(value).strip()
            ))
            if not label or not phrases:
                raise SemanticValidationError(
                    "target classes require non-empty label and phrases"
                )
            if any(_FORBIDDEN_GROUNDING.search(phrase) for phrase in phrases):
                raise SemanticValidationError(
                    "target class grounding evidence must be affirmative"
                )
            target_classes.append({"label": label, "phrases": phrases})
        target["classes"] = target_classes
        if any(
            str(item.get("kind", "")).strip().lower() == "color"
            for item in data.get("constraints", [])
        ):
            target["phrases"] = _base_entity_phrases(
                target["phrases"], target["concept"]
            )
            cleaned_concept = _base_entity_phrases(
                [target["concept"]], target["concept"]
            )[0]
            target["concept"] = cleaned_concept

        unresolved = list(data.get("unresolved", []))
        normalized_constraints = []
        for index, raw in enumerate(data.get("constraints", []), start=1):
            constraint = deepcopy(raw)
            span = str(constraint.get("source_span", "")).strip()
            if not span or span not in instruction:
                raise SemanticValidationError(
                    f"constraint source_span is not present in instruction: {span}"
                )
            kind = str(constraint.get("kind", "")).strip().lower()
            value = constraint.get("value")
            kind, value, retyped_phrases = _wearable_retyping(
                kind=kind,
                value=value,
                source_span=span,
                phrases=constraint.get("phrases", []),
                target_concept=target["concept"],
                target_phrases=target["phrases"],
            )
            kind, value, retyped_phrases = _fallen_pose_retyping(
                kind=kind,
                value=value,
                source_span=span,
                phrases=retyped_phrases,
                target_concept=target["concept"],
                target_phrases=target["phrases"],
            )
            constraint["phrases"] = retyped_phrases
            if kind == "color":
                value = COLOR_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())
                if value not in COLOR_NAMES:
                    unresolved.append({
                        "source_span": span,
                        "reason": f"unknown color: {raw.get('value')}",
                    })
                carrier_raw = str(constraint.get("carrier", "")).strip()
                carrier = CARRIER_TEXT_ALIASES.get(carrier_raw.lower())
                phrase_carriers = []
                for phrase in constraint.get("phrases", []):
                    visible = re.sub(
                        r"\b(?:" + "|".join(
                            re.escape(name) for name in COLOR_NAMES
                        ) + r")\b",
                        " ",
                        str(phrase).lower(),
                    )
                    visible = re.sub(
                        r"\b(?:wearing|wears|with|a|an|the)\b", " ", visible
                    )
                    visible = re.sub(r"\s+", " ", visible).strip()
                    if (
                        visible
                        and _OPEN_ENGLISH_CARRIER.fullmatch(visible)
                        and visible not in {target["concept"], *target["phrases"]}
                        and not _FORBIDDEN_GROUNDING.search(visible)
                    ):
                        phrase_carriers.append(visible)
                if (
                    phrase_carriers
                    and carrier in {None, "clothing", "object"}
                ):
                    carrier = phrase_carriers[0]
                normalized_open = carrier_raw.lower().replace("_", " ")
                target_carrier = normalized_open == target["concept"] or (
                    normalized_open in target["phrases"]
                )
                if target_carrier:
                    carrier = None
                elif carrier_raw and carrier is None and _OPEN_ENGLISH_CARRIER.fullmatch(
                    normalized_open
                ) and not _FORBIDDEN_GROUNDING.search(normalized_open):
                    carrier = normalized_open
                elif carrier_raw and carrier is None:
                    unresolved.append({
                        "source_span": str(constraint.get("carrier_span") or carrier_raw),
                        "reason": f"unknown property carrier: {carrier_raw}",
                    })
                constraint["carrier"] = carrier
            source = str(constraint.get("source") or _source_clause(instruction, span)).strip()
            if source not in instruction or span not in source:
                # The exact source span has already been verified above.  For
                # list-style sentences, planners often reconstruct a readable
                # clause that is not a literal substring; restore auditable
                # provenance from the original instruction deterministically.
                source = _source_clause(instruction, span)
                constraint["source"] = source
            if (
                kind == "temporal" or bool(constraint.get("temporal", False))
            ) and not _EXPLICIT_TEMPORAL_EVIDENCE.search(source):
                raise SemanticValidationError(
                    "temporal semantics require explicit duration, sequence, "
                    f"or stay evidence in the source clause: {source}"
                )
            phrases = list(dict.fromkeys(
                str(value).strip().lower()
                for value in constraint.get("phrases", [])
                if str(value).strip()
            ))
            if kind == "temporal":
                # Temporal atoms consume a preceding condition; they are not
                # independent Grounding evidence and must not retain phrases
                # leaked by the planner.
                phrases = []
            if any(_FORBIDDEN_GROUNDING.search(phrase) for phrase in phrases):
                raise SemanticValidationError(
                    "grounding evidence must be affirmative"
                )
            if kind in {"size", "position"}:
                allowed = ATTRIBUTE_CATALOG[kind]["values"]
                if value not in allowed:
                    unresolved.append({
                        "source_span": span,
                        "reason": f"unknown {kind}: {value}",
                    })
            if kind == "quantity":
                group_by = value.get("group_by") if isinstance(value, dict) else None
                grouping_valid = group_by in {None, "named_region"} and (
                    group_by != "named_region" or bool(value.get("region_role"))
                )
                report_only = (
                    isinstance(value, dict)
                    and value.get("measure", "count") == "count"
                    and "operator" not in value
                    and "value" not in value
                    and grouping_valid
                )
                compared = (
                    isinstance(value, dict)
                    and value.get("operator") in COUNT_OPERATORS
                    and isinstance(value.get("value"), (int, float))
                    and not isinstance(value.get("value"), bool)
                    and grouping_valid
                )
                if not (report_only or compared):
                    unresolved.append({
                        "source_span": span,
                        "reason": "quantity requires count reporting or a registered numeric comparison",
                    })
            if kind == "spatial_relation":
                relation = value.get("relation") if isinstance(value, dict) else None
                if relation not in SPATIAL_RELATIONS:
                    unresolved.append({
                        "source_span": span,
                        "reason": f"unknown spatial relation: {relation}",
                    })
            if kind == "motion":
                group_by = value.get("group_by") if isinstance(value, dict) else None
                aggregation = (
                    value.get("aggregation", "per_track")
                    if isinstance(value, dict)
                    else None
                )
                valid = (
                    isinstance(value, dict)
                    and value.get("measure") == "speed"
                    and value.get("operator") in COUNT_OPERATORS
                    and isinstance(value.get("threshold"), (int, float))
                    and not isinstance(value.get("threshold"), bool)
                    and value.get("unit", "pixels_per_second")
                    == "pixels_per_second"
                    and aggregation in {
                        "per_track", "global_mean", "global_median",
                        "region_mean", "region_median",
                    }
                    and group_by in {None, "named_region"}
                    and (
                        group_by != "named_region"
                        or bool(value.get("region_role"))
                        and aggregation in {"region_mean", "region_median"}
                    )
                )
                if not valid:
                    unresolved.append({
                        "source_span": span,
                        "reason": "motion requires a registered speed comparison",
                    })
            if kind == "region_requirement":
                valid = (
                    isinstance(value, dict)
                    and value.get("source") == "manual"
                    and value.get("cardinality") in {"one", "many"}
                    and bool(value.get("semantic_role"))
                    and set(value.get("allowed_shapes", []))
                    .issubset({"rectangle", "polygon"})
                    and bool(value.get("allowed_shapes"))
                )
                if not valid:
                    unresolved.append({
                        "source_span": span,
                        "reason": "region requirement needs a manual one/many shape contract",
                    })
            if kind == "direction_relation":
                valid = (
                    isinstance(value, dict)
                    and value.get("relation") in {"aligned", "opposite"}
                    and value.get("reference_scope")
                    in {"global", "per_named_region"}
                    and value.get("reference_source")
                    in {"whole_video_majority", "manual", "image_axis"}
                    and (
                        value.get("reference_source") != "image_axis"
                        or value.get("image_axis") in {
                            "left", "right", "up", "down",
                            "up_left", "up_right", "down_left", "down_right",
                        }
                    )
                    and isinstance(
                        value.get("cosine_threshold", -0.5), (int, float)
                    )
                )
                if not valid:
                    unresolved.append({
                        "source_span": span,
                        "reason": "direction relation requires a registered reference rule",
                    })
            if kind == "temporal":
                temporal_type = value.get("type") if isinstance(value, dict) else None
                if temporal_type not in {"persist", "sequence"}:
                    unresolved.append({
                        "source_span": span,
                        "reason": f"unknown temporal rule: {temporal_type}",
                    })
                elif temporal_type == "persist" and not isinstance(value.get("seconds"), (int, float)):
                    unresolved.append({
                        "source_span": span,
                        "reason": "persist requires numeric seconds",
                    })
                elif temporal_type == "sequence":
                    steps = value.get("steps")
                    if not isinstance(steps, list) or len(steps) < 2:
                        unresolved.append({
                            "source_span": span,
                            "reason": "sequence requires at least two steps",
                        })
                    else:
                        for step in steps:
                            step_phrases = step.get("phrases", []) if isinstance(step, dict) else []
                            if (
                                not step_phrases
                                or any(_FORBIDDEN_GROUNDING.search(str(phrase)) for phrase in step_phrases)
                            ):
                                raise SemanticValidationError(
                                    "sequence grounding evidence must be affirmative"
                                )
            constraint.update({
                "atom_id": f"atom_{index}",
                "kind": kind,
                "value": value,
                "source": source,
                "source_span": span,
                "polarity": _final_polarity(source, span),
                "phrases": phrases,
                "temporal": bool(constraint.get("temporal", False)),
            })
            normalized_constraints.append(constraint)

        # When one clause contrasts a generic Chinese "衣服/服装" color with
        # an explicit pants color, the generic garment is the upper-body
        # carrier.  Keeping it as whole-body clothing makes the pants color
        # contaminate the first predicate and breaks same-person outfits.
        lower_body_sources = {
            item.get("source")
            for item in normalized_constraints
            if item.get("kind") == "color"
            and item.get("carrier") == "lower_body_clothing"
        }
        for item in normalized_constraints:
            if (
                item.get("kind") == "color"
                and item.get("carrier") == "clothing"
                and item.get("carrier_span") in {"衣服", "衣物", "服装"}
                and item.get("source") in lower_body_sources
            ):
                item["carrier"] = "upper_body_clothing"

        _covered_collection_negations(instruction, normalized_constraints)
        _audit_registered_dimension_coverage(instruction, normalized_constraints)

        carrier_order = {
            "upper_body_clothing": 0,
            "lower_body_clothing": 1,
            "clothing": 2,
        }
        normalized_constraints.sort(key=lambda item: (
            0 if item["kind"] == "color" else 1,
            carrier_order.get(item.get("carrier"), 99),
            str(item.get("carrier") or ""),
            str(item["value"]),
            item["polarity"],
        ))
        for index, constraint in enumerate(normalized_constraints, start=1):
            constraint["atom_id"] = f"atom_{index}"
        result = {
            "schema_version": "1.0",
            "mode": (
                "workflow"
                if data.get("mode") == "workflow"
                else "entity_query"
                if normalized_constraints
                else "direct_grounding"
            ),
            "target": target,
            "constraints": normalized_constraints,
            "logic": data.get("logic", "all"),
            "unresolved": unresolved,
        }
        result["semantic_hash"] = _canonical_hash(_canonical_signature(result))
        return CanonicalSemanticIR.model_validate(result)

    @staticmethod
    def _extract_supported_ledger(text: str) -> dict[str, Any]:
        person_matches = list(re.finditer(r"人员|人", text))
        if not person_matches:
            raise SemanticValidationError("no supported target entity found")
        target_span = person_matches[-1].group(0)
        constraints: list[dict[str, Any]] = []

        garment_patterns = (
            (rf"({_CHINESE_COLOR_PATTERN})(?:的)?(上衣|上装|短袖|衬衣|衬衫|夹克|外套|衣服|衣物|服装|衣)", "upper_body_clothing"),
            (rf"({_CHINESE_COLOR_PATTERN})(?:的)?(裤子|长裤|短裤|裤)", "lower_body_clothing"),
        )
        for pattern, carrier in garment_patterns:
            for match in re.finditer(pattern, text):
                color_span, carrier_span = match.group(1), match.group(2)
                constraints.append({
                    "kind": "color",
                    "value": COLOR_ALIASES[color_span],
                    "source": _source_clause(text, match.group(0)),
                    "source_span": match.group(0),
                    "carrier": carrier,
                    "carrier_span": carrier_span,
                    "polarity": "required",
                })

        helmet_match = re.search(r"(?:未|没有|没|无|不)?(?:佩戴|戴|带)?安全帽", text)
        if helmet_match:
            constraints.append({
                "kind": "wearable",
                "value": "safety_helmet",
                "source": _source_clause(text, helmet_match.group(0)),
                "source_span": helmet_match.group(0),
                "phrases": ["safety helmet"],
                "polarity": "required",
            })

        vest_match = re.search(r"(?:穿着|穿)?(?:橙色|黄色|红色|绿色|蓝色)?(?:的)?(?:反光衣|反光背心|安全背心)", text)
        if vest_match:
            constraints.append({
                "kind": "wearable",
                "value": "reflective_vest",
                "source": _source_clause(text, vest_match.group(0)),
                "source_span": vest_match.group(0),
                "phrases": ["wearing reflective vest"],
                "polarity": "required",
            })
            color_match = re.search(r"橙色|黄色|红色|绿色|蓝色", vest_match.group(0))
            if color_match:
                constraints.append({
                    "kind": "color",
                    "value": COLOR_ALIASES[color_match.group(0)],
                    "source": _source_clause(text, color_match.group(0)),
                    "source_span": color_match.group(0),
                    "carrier": "clothing",
                    "carrier_span": "反光衣" if "反光衣" in vest_match.group(0) else "反光背心",
                    "polarity": "required",
                })
        return {
            "mode": "entity_query" if constraints else "direct_grounding",
            "target": {
                "concept": "person",
                "source_span": target_span,
                "phrases": ["person"],
            },
            "constraints": constraints,
            "logic": "all",
            "unresolved": [],
        }


class WorkflowCompiler:
    def __init__(self, registry: OperatorRegistry):
        self.registry = registry

    def compile(
        self,
        semantic_ir: CanonicalSemanticIR,
        *,
        original_instruction: str,
        requested_accept: list[str],
        skill_id: str,
        display_name: str,
    ) -> SkillPackage:
        if semantic_ir.unresolved:
            detail = "; ".join(
                f"{item.source_span}: {item.reason}"
                for item in semantic_ir.unresolved
            )
            raise SemanticValidationError(
                f"unresolved semantics require review: {detail}"
            )
        video_required = any(
            item.temporal for item in semantic_ir.constraints
        ) or any(
            item.kind in {"motion", "direction_relation"}
            for item in semantic_ir.constraints
        )
        actual_accept = [
            media for media in requested_accept
            if media == "video" or not video_required
        ]
        issues = []
        variants: dict[str, dict[str, Any]] = {}
        for media_type in requested_accept:
            if media_type not in actual_accept:
                issues.append({
                    "media_type": media_type,
                    "code": "temporal_requires_video",
                    "message": "时序语义需要视频",
                })
                variants[media_type] = {
                    "media_type": media_type,
                    "status": "unsupported",
                    "nodes": [],
                    "outputs": {},
                    "issue": "temporal semantics require video",
                }
            else:
                variants[media_type] = self._compile_variant(
                    semantic_ir,
                    media_type,
                    display_name,
                    original_instruction=original_instruction,
                )
        if not actual_accept:
            raise SemanticValidationError("requested media cannot execute this semantic IR")
        package = SkillPackage.model_validate({
            "schema_version": "2.0",
            "skill_id": skill_id,
            "version": 1,
            "display_name": display_name,
            "original_instruction": original_instruction,
            "compile_status": "needs_review"
            if issues or any(
                item.get("status") == "needs_configuration"
                for item in variants.values()
            )
            else "compiled",
            "input": {
                "requested_accept": requested_accept,
                "accept": actual_accept,
            },
            "semantic_ir": semantic_ir.model_dump(mode="json"),
            "variants": variants,
            "compatibility_issues": issues,
        })
        assert_valid_skill_package(package, self.registry)
        return package

    @staticmethod
    def _start_nodes(media_type: str) -> tuple[list[dict[str, Any]], str]:
        if media_type == "image":
            return ([{
                "id": "media", "op": "media.image@1.0",
                "inputs": {"media": "$input"}, "params": {},
            }, {
                "id": "resized", "op": "image.resize@1.1",
                "inputs": {"frames": "$media"},
                "params": {"mode": "identity"},
            }], "$resized")
        return ([
            {"id": "media", "op": "media.video@1.0", "inputs": {"media": "$input"}, "params": {}},
            {"id": "frames", "op": "video.sample@1.1", "inputs": {"video": "$media"},
             "params": {
                 "mode": "fps",
                 "fps": 1.0,
                 "start_seconds": 0.0,
                 "end_seconds": None,
                 "max_frames": None,
             }},
            {"id": "resized", "op": "image.resize@1.1",
             "inputs": {"frames": "$frames"},
             "params": {"mode": "identity"}},
        ], "$resized")

    def _compile_variant(
        self,
        semantic_ir: CanonicalSemanticIR,
        media_type: str,
        display_name: str,
        *,
        original_instruction: str,
    ) -> dict[str, Any]:
        stream_kinds = {"motion", "region_requirement", "direction_relation"}
        has_stream_constraints = any(
            constraint.kind in stream_kinds
            for constraint in semantic_ir.constraints
        )
        if has_stream_constraints:
            video_only = any(
                constraint.temporal
                or constraint.kind in {"motion", "direction_relation"}
                for constraint in semantic_ir.constraints
            )
            if media_type != "video" and video_only:
                raise SemanticValidationError("stream constraints require video")
            return self._compile_stream_variant(
                semantic_ir, media_type, display_name
            )
        nodes, frames = self._start_nodes(media_type)
        target_label = (
            semantic_ir.target.source_span.strip()
            or semantic_ir.target.concept
        )
        _append_grounding(
            nodes,
            "candidates",
            frames,
            [item.model_dump(mode="json") for item in semantic_ir.target.classes]
            or [{"label": target_label, "phrases": semantic_ir.target.phrases}],
        )
        evidence_frames = self._append_shared_evidence_frames(
            nodes, frames, semantic_ir.constraints
        )
        entity_conditions: list[str] = []
        aggregate_conditions: list[str] = []
        measurement_refs: list[str] = []
        temporal_constraints = []
        atom_bindings: dict[str, list[str]] = {}
        configuration_slots: list[dict[str, Any]] = []
        grouped_conditions, grouped_bindings = self._compile_pose_groups(
            nodes, semantic_ir, evidence_frames, frames
        )
        entity_conditions.extend(grouped_conditions)
        atom_bindings.update(grouped_bindings)
        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            if constraint.kind in {"quantity", "temporal"}:
                if constraint.kind == "temporal":
                    temporal_constraints.append((index, constraint))
                continue
            if constraint.atom_id in grouped_bindings:
                continue
            condition, bound_nodes = self._compile_constraint(
                nodes,
                frames,
                index,
                constraint,
                configuration_slots,
                evidence_frames,
                semantic_ir.target.phrases[0],
                semantic_ir.target.concept,
            )
            if constraint.polarity == "absent":
                not_id = f"constraint_{index}_not"
                nodes.append({
                    "id": not_id, "op": "logic.not@1.0",
                    "inputs": {"condition": condition}, "params": {},
                })
                condition = f"${not_id}"
                bound_nodes.append(not_id)
            entity_conditions.append(condition)
            atom_bindings[constraint.atom_id] = bound_nodes
        result_ref = "$candidates"
        if entity_conditions:
            if len(entity_conditions) == 1:
                combined = entity_conditions[0]
            else:
                combine_op = "logic.all@1.0" if semantic_ir.logic == "all" else "logic.any@1.0"
                nodes.append({
                    "id": "constraints_all" if semantic_ir.logic == "all" else "constraints_any",
                    "op": combine_op,
                    "inputs": {"conditions": entity_conditions},
                    "params": {},
                })
                combined = "$constraints_all" if semantic_ir.logic == "all" else "$constraints_any"
            nodes.append({
                "id": "filtered", "op": "filter.apply@1.0",
                "inputs": {"objects": "$candidates", "condition": combined},
                "params": {},
            })
            result_ref = "$filtered"

        count_objects_ref = result_ref
        count_scope = "frame"
        count_track_id: str | None = None
        if media_type == "video" and any(
            constraint.kind == "quantity"
            for constraint in semantic_ir.constraints
        ):
            count_track_id = "count_tracks"
            nodes.append({
                "id": count_track_id,
                "op": "track.iou@1.0",
                "inputs": {"objects": result_ref},
                "params": {},
            })
            count_objects_ref = f"${count_track_id}"
            count_scope = "unique"

        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            if constraint.kind != "quantity":
                continue
            count_id = f"constraint_{index}_count"
            nodes.append({
                "id": count_id, "op": "measure.count@1.0",
                "inputs": {"entities": count_objects_ref},
                "params": {"scope": count_scope},
            })
            measurement_refs.append(f"${count_id}")
            if "operator" not in constraint.value:
                atom_bindings[constraint.atom_id] = [
                    *([count_track_id] if count_track_id else []), count_id
                ]
                continue
            compare_id = f"constraint_{index}_compare"
            nodes.append({
                "id": compare_id, "op": "logic.compare@1.0",
                "inputs": {"left": f"${count_id}"},
                "params": {
                    "operator": constraint.value["operator"],
                    "value": constraint.value["value"],
                },
            })
            condition_ref = f"${compare_id}"
            bound = [
                *([count_track_id] if count_track_id else []),
                count_id,
                compare_id,
            ]
            if constraint.polarity == "absent":
                not_id = f"constraint_{index}_not"
                nodes.append({"id": not_id, "op": "logic.not@1.0",
                              "inputs": {"condition": condition_ref}, "params": {}})
                condition_ref = f"${not_id}"
                bound.append(not_id)
            aggregate_conditions.append(condition_ref)
            atom_bindings[constraint.atom_id] = bound

        aggregate_ref = None
        if aggregate_conditions:
            if len(aggregate_conditions) == 1:
                aggregate_ref = aggregate_conditions[0]
            else:
                aggregate_id = "aggregate_all" if semantic_ir.logic == "all" else "aggregate_any"
                nodes.append({
                    "id": aggregate_id,
                    "op": "logic.all@1.0" if semantic_ir.logic == "all" else "logic.any@1.0",
                    "inputs": {"conditions": aggregate_conditions},
                    "params": {},
                })
                aggregate_ref = f"${aggregate_id}"

        event_refs: list[str] = []
        draw_objects_ref = result_ref
        for index, constraint in temporal_constraints:
            event_ref, bound, tracked_ref = self._compile_temporal(
                nodes, frames, result_ref, aggregate_ref, index, constraint
            )
            atom_bindings[constraint.atom_id] = bound
            event_refs.append(event_ref)
            if tracked_ref:
                draw_objects_ref = tracked_ref

        # A video question such as ``识别视频中是否有人摔倒`` asks for a
        # boolean event result even when no duration was supplied.  Compile
        # that intent as an explicit zero-second event over the matched
        # objects.  Ordinary video detection phrases remain detection-only.
        if (
            media_type == "video"
            and not event_refs
            and _has_immediate_event_intent(original_instruction)
        ):
            event_tracks_id = "event_tracks"
            event_region_id = "event_region"
            event_present_id = "event_present"
            nodes.extend([
                {
                    "id": event_tracks_id,
                    "op": "track.iou@1.0",
                    "inputs": {"objects": result_ref},
                    "params": {},
                },
                {
                    "id": event_region_id,
                    "op": "region.full_frame@1.0",
                    "inputs": {"frames": frames},
                    "params": {},
                },
                {
                    "id": event_present_id,
                    "op": "spatial.inside@1.0",
                    "inputs": {
                        "objects": f"${event_tracks_id}",
                        "region": f"${event_region_id}",
                    },
                    "params": {
                        "mode": "center",
                        "overlap_threshold": 0.5,
                    },
                },
            ])
            event_id = "condition_event"
            nodes.append({
                "id": event_id,
                "op": "event.from_condition@1.0",
                "inputs": {"condition": f"${event_present_id}"},
                "params": {
                    "seconds": 0.0,
                    "scope": "track",
                    "gap_tolerance_seconds": 0.0,
                    "trigger_mode": "once",
                    "label": display_name,
                },
            })
            alert_id = "alerts"
            nodes.append({
                "id": alert_id,
                "op": "output.alert@1.0",
                "inputs": {"events": f"${event_id}"},
                "params": {"label": display_name},
            })
            event_refs.append(f"${alert_id}")
            draw_objects_ref = f"${event_tracks_id}"

        draw_inputs = {"frames": frames, "objects": draw_objects_ref}
        if len(event_refs) == 1:
            draw_inputs["events"] = event_refs[0]
        nodes.append({
            "id": "draw", "op": "output.draw@1.0",
            "inputs": draw_inputs, "params": {},
        })
        outputs = {"media": "$draw", "objects": draw_objects_ref}
        if len(measurement_refs) == 1:
            outputs["measurements"] = measurement_refs[0]
        elif measurement_refs:
            for position, ref in enumerate(measurement_refs, start=1):
                outputs[f"measurements_{position}"] = ref
        if aggregate_ref:
            outputs["condition"] = aggregate_ref
        if len(event_refs) == 1:
            outputs["events"] = event_refs[0]
        elif event_refs:
            for position, ref in enumerate(event_refs, start=1):
                outputs[f"events_{position}"] = ref
        return {
            "media_type": media_type,
            "status": "needs_configuration"
            if configuration_slots
            else "executable",
            "nodes": nodes,
            "outputs": outputs,
            "atom_bindings": atom_bindings,
            "configuration_slots": configuration_slots,
        }

    @staticmethod
    def _append_shared_evidence_frames(nodes, frames, constraints) -> str | None:
        """Add one reusable full-frame + tiled stream for affirmative open evidence.

        Rex grounding is an open-vocabulary evidence provider.  Positive visual
        attributes benefit from full-scene context plus tiles, while pose
        evidence must retain the complete subject/context because a crop can
        hallucinate a posture.  Negative evidence must remain full-frame so a
        crop cannot hallucinate the excluded attribute for every candidate.
        Closed deterministic atoms (color/geometry/count) do not need this
        stream.
        """

        deterministic_or_relational = {
            "color",
            "size",
            "position",
            "quantity",
            "temporal",
            "spatial_relation",
            "motion",
            "region_requirement",
            "direction_relation",
        }
        needs_tiles = any(
            constraint.polarity == "required"
            and constraint.kind not in deterministic_or_relational
            for constraint in constraints
        )
        if any(
            constraint.polarity == "required"
            and constraint.kind == "pose"
            for constraint in constraints
        ):
            return None
        if not needs_tiles:
            return None
        nodes.append({
            "id": "evidence_frames",
            "op": "image.tile@1.1",
            "inputs": {"frames": frames},
            "params": {
                "tile_width": 640,
                "tile_height": 640,
                "overlap_x": 0.2,
                "overlap_y": 0.2,
                "include_full_frame": True,
            },
        })
        return "$evidence_frames"

    @staticmethod
    def _compile_pose_groups(nodes, semantic_ir, evidence_frames, frames=None):
        """Compile conjunctive pose atoms as one subject-level grounding phrase.

        Multiple fragments such as ``squatting`` and ``knees bent`` describe
        one visible pose, not two independent objects.  Combining them avoids
        losing their co-reference while preserving each atom's provenance.
        """

        if semantic_ir.logic != "all":
            return [], {}
        grounding_frames = evidence_frames or frames
        if not grounding_frames:
            return [], {}
        constraints = [
            item for item in semantic_ir.constraints
            if item.kind == "pose"
            and item.polarity == "required"
            and not item.temporal
        ]
        if len(constraints) < 2:
            return [], {}

        base = semantic_ir.target.phrases[0].strip()
        fragments = []
        for constraint in constraints:
            fragment = (constraint.phrases or [str(constraint.value)])[0].strip()
            fragment = re.sub(
                rf"\b{re.escape(base)}\b", " ", fragment, flags=re.I
            )
            fragment = re.sub(r"\s+", " ", fragment).strip()
            if fragment and fragment not in fragments:
                fragments.append(fragment)
        actions = [value for value in fragments if _POSE_ACTION.search(value)]
        details = [value for value in fragments if value not in actions]
        if not actions:
            actions, details = fragments[:1], fragments[1:]
        predicate = f"{base} {' and '.join(actions)}".strip()
        if details:
            predicate += f" with {' and '.join(details)}"

        group_id = "pose_group_1"
        objects_id = f"{group_id}_objects"
        objects_ref, bound = _append_grounding(
            nodes,
            objects_id,
            grounding_frames,
            [{
                "label": " + ".join(item.source_span for item in constraints),
                "phrases": [predicate],
            }],
            semantic_node=True,
        )
        matches_id = f"{group_id}_matches"
        nodes.append({
            "id": matches_id,
            "op": "spatial.associate@1.0",
            "inputs": {"subjects": "$candidates", "objects": objects_ref},
            "params": {"relation": "mutual_match", "threshold": 0.5},
        })
        condition_ref = f"${matches_id}"
        pose_geometry = next(
            (
                item
                for item in constraints
                if str(item.value).strip().lower() == "fallen_or_lying"
            ),
            None,
        )
        if pose_geometry is not None:
            geometry_id = f"{group_id}_geometry"
            combined_id = f"{group_id}_all"
            nodes.extend([
                {
                    "id": geometry_id,
                    "op": "visual.geometry@1.0",
                    "inputs": {"objects": "$candidates"},
                    "params": {
                        "dimension": "aspect_ratio",
                        "value": "horizontal",
                        # Keep a generic upright-pose guard without requiring
                        # a strict 1:1 box, which rejects perspective views.
                        "aspect_ratio_threshold": 0.6,
                    },
                },
                {
                    "id": combined_id,
                    "op": "logic.all@1.0",
                    "inputs": {
                        "conditions": [condition_ref, f"${geometry_id}"]
                    },
                    "params": {},
                },
            ])
            condition_ref = f"${combined_id}"
            group_bound_extra = [geometry_id, combined_id]
        else:
            group_bound_extra = []
        group_bound = [
            *(["evidence_frames"] if evidence_frames else []),
            *bound,
            matches_id,
            *group_bound_extra,
        ]
        return [condition_ref], {
            item.atom_id: list(group_bound) for item in constraints
        }

    @staticmethod
    def _compile_constraint(
        nodes,
        frames,
        index,
        constraint,
        configuration_slots=None,
        evidence_frames=None,
        target_phrase=None,
        target_concept=None,
    ) -> str:
        if constraint.kind == "color":
            carrier = constraint.carrier
            config = CARRIER_CATALOG.get(carrier) if carrier else None
            if carrier and config is None:
                config = {
                    "phrase": carrier.replace("_", " "),
                    "color_mode": "fraction",
                    "subject_region": [0.0, 0.0, 1.0, 1.0],
                }
            objects_ref = "$candidates"
            bound_nodes: list[str] = []
            if config:
                carrier_id = f"constraint_{index}_carriers"
                objects_ref, carrier_nodes = _append_grounding(
                    nodes,
                    carrier_id,
                    frames,
                    [{"label": config["phrase"], "phrases": [config["phrase"]]}],
                )
                bound_nodes.extend(carrier_nodes)
            color_id = f"constraint_{index}_color"
            nodes.append({
                "id": color_id, "op": "visual.color_fraction@1.0",
                "inputs": {"frames": frames, "objects": objects_ref},
                "params": {
                    "color": constraint.value,
                    "subject_region": [0.0, 0.0, 1.0, 1.0],
                    "min_fraction": COLOR_MIN_FRACTIONS[constraint.value],
                    "selection_mode": config["color_mode"] if config else "fraction",
                    "dominance_margin": 0.05,
                },
            })
            bound_nodes.append(color_id)
            if not config:
                if not target_phrase:
                    return f"${color_id}", bound_nodes
                entity_id = f"constraint_{index}_color_entity"
                matches_id = f"constraint_{index}_color_entity_matches"
                combined_id = f"constraint_{index}_color_all"
                color_entity_ref, color_entity_nodes = _append_grounding(
                    nodes,
                    entity_id,
                    frames,
                    [{
                        "label": constraint.source_span,
                        "phrases": [
                            f"{constraint.value} {target_concept or target_phrase}"
                        ],
                    }],
                    semantic_node=True,
                )
                nodes.extend([
                    {
                        "id": matches_id,
                        "op": "spatial.associate@1.0",
                        "inputs": {
                            "subjects": "$candidates",
                            "objects": color_entity_ref,
                        },
                        "params": {"relation": "mutual_match", "threshold": 0.5},
                    },
                    {
                        "id": combined_id,
                        "op": "logic.all@1.0",
                        "inputs": {
                            "conditions": [f"${color_id}", f"${matches_id}"]
                        },
                        "params": {},
                    },
                ])
                return f"${combined_id}", [
                    *bound_nodes,
                    *color_entity_nodes,
                    matches_id,
                    combined_id,
                ]
            colored_id = f"constraint_{index}_colored_carriers"
            match_id = f"constraint_{index}_matches"
            nodes.extend([
                {
                    "id": colored_id,
                    "op": "filter.apply@1.0",
                    "inputs": {"objects": objects_ref, "condition": f"${color_id}"},
                    "params": {},
                },
                {
                    "id": match_id,
                    "op": "spatial.associate@1.0",
                    "inputs": {"subjects": "$candidates", "objects": f"${colored_id}"},
                    "params": {"relation": "best_owner", "threshold": 0.1},
                },
            ])
            return f"${match_id}", [*bound_nodes, colored_id, match_id]

        if constraint.kind in {"size", "position"}:
            geometry_id = f"constraint_{index}_geometry"
            nodes.append({
                "id": geometry_id,
                "op": "visual.geometry@1.0",
                "inputs": {"objects": "$candidates"},
                "params": {
                    "dimension": constraint.kind,
                    "value": constraint.value,
                    "size_mode": "relative",
                    "small_max_area": 0.02,
                    "large_min_area": 0.12,
                    "position_margin": 0.33,
                },
            })
            return f"${geometry_id}", [geometry_id]

        if constraint.kind == "wearable":
            base = (target_phrase or target_concept or "entity").strip()
            original_phrases = constraint.phrases or [
                str(constraint.value).replace("_", " ")
            ]
            part_phrases: list[str] = []
            subject_phrases: list[str] = []
            for phrase in original_phrases:
                phrase = re.sub(r"\s+", " ", phrase).strip()
                part_match = re.search(
                    r"\b(?:wearing|wears|with)\s+(?:an?\s+|the\s+)?(.+)$",
                    phrase,
                    re.I,
                )
                part = (part_match.group(1) if part_match else phrase).strip()
                part = re.sub(
                    r"^(?:person|worker|man|woman|child|entity)\s+",
                    "",
                    part,
                    flags=re.I,
                )
                if part and part not in part_phrases:
                    part_phrases.append(part)
                if re.search(
                    r"\b(?:person|worker|man|woman|child|vehicle|animal)\b",
                    phrase,
                    re.I,
                ):
                    subject_phrase = phrase
                elif re.match(r"^(?:wearing|wears|with)\b", phrase, re.I):
                    subject_phrase = f"{base} {phrase}"
                else:
                    subject_phrase = f"{base} wearing {phrase}"
                if subject_phrase not in subject_phrases:
                    subject_phrases.append(subject_phrase)

            part_id = f"constraint_{index}_wearable_parts"
            part_ref, part_bound = _append_grounding(
                nodes,
                part_id,
                evidence_frames
                if constraint.polarity == "required" and evidence_frames
                else frames,
                [{"label": constraint.source_span, "phrases": part_phrases}],
                semantic_node=True,
            )
            part_match_id = f"constraint_{index}_wearable_part_matches"
            nodes.append({
                "id": part_match_id,
                "op": "spatial.associate@1.0",
                "inputs": {"subjects": "$candidates", "objects": part_ref},
                "params": {"relation": "best_owner", "threshold": 0.1},
            })

            subject_id = f"constraint_{index}_objects"
            subject_ref, subject_bound = _append_grounding(
                nodes,
                subject_id,
                evidence_frames
                if constraint.polarity == "required" and evidence_frames
                else frames,
                [{"label": constraint.source_span, "phrases": subject_phrases}],
                semantic_node=True,
            )
            subject_match_id = f"constraint_{index}_matches"
            nodes.append({
                "id": subject_match_id,
                "op": "spatial.associate@1.0",
                "inputs": {"subjects": "$candidates", "objects": subject_ref},
                "params": {"relation": "mutual_match", "threshold": 0.5},
            })
            present_id = f"constraint_{index}_wearable_present"
            nodes.append({
                "id": present_id,
                "op": "logic.any@1.0",
                "inputs": {
                    "conditions": [
                        f"${part_match_id}", f"${subject_match_id}"
                    ]
                },
                "params": {},
            })
            shared = (
                ["evidence_frames"]
                if constraint.polarity == "required" and evidence_frames
                else []
            )
            return f"${present_id}", [
                *shared,
                *part_bound,
                part_match_id,
                *subject_bound,
                subject_match_id,
                present_id,
            ]

        if constraint.kind == "spatial_relation":
            value = constraint.value
            relation = value["relation"]
            if relation in {"inside_roi", "outside_roi"}:
                region = value.get("region", {})
                source = region.get("source")
                bound = []
                if source == "grounding":
                    phrases = region.get("phrases") or []
                    if not phrases:
                        raise SemanticValidationError("grounded ROI requires affirmative phrases")
                    objects_id = f"constraint_{index}_region_objects"
                    region_id = f"constraint_{index}_region"
                    region_objects_ref, region_bound = _append_grounding(
                        nodes, objects_id, frames,
                        [{"label": constraint.source_span, "phrases": phrases}],
                        semantic_node=True,
                    )
                    bound.extend(region_bound)
                    nodes.append(
                        {"id": region_id, "op": "region.from_objects@1.0",
                         "inputs": {"objects": region_objects_ref},
                         "params": {"mode": region.get("mode", "all")}}
                    )
                    bound.append(region_id)
                elif source == "manual":
                    points = region.get("points")
                    configured = isinstance(points, list) and len(points) >= 2
                    points = points if configured else []
                    region_id = f"constraint_{index}_region"
                    nodes.append({
                        "id": region_id, "op": "region.manual@1.0", "inputs": {},
                        "params": {"shape": region.get("shape", "polygon"), "points": points},
                    })
                    bound.append(region_id)
                    if not configured:
                        if configuration_slots is None:
                            raise SemanticValidationError(
                                "manual ROI requires a configuration slot"
                            )
                        allowed_shapes = region.get(
                            "allowed_shapes", ["rectangle", "polygon"]
                        )
                        configuration_slots.append({
                            "slot_id": region_id,
                            "kind": "region",
                            "label": constraint.source_span,
                            "required": True,
                            "binding": {
                                "node_id": region_id,
                                "parameter": "points",
                            },
                            "allowed_shapes": allowed_shapes,
                            "minimum_items": 1,
                            "source_atom_ids": [constraint.atom_id],
                            "help_text": "在原图或视频标注帧上绘制区域",
                        })
                elif source == "full_frame":
                    region_id = f"constraint_{index}_region"
                    nodes.append({
                        "id": region_id, "op": "region.full_frame@1.0",
                        "inputs": {"frames": frames}, "params": {},
                    })
                    bound.append(region_id)
                else:
                    raise SemanticValidationError("ROI source must be grounding, manual, or full_frame")
                inside_id = f"constraint_{index}_inside"
                nodes.append({
                    "id": inside_id, "op": "spatial.inside@1.0",
                    "inputs": {"objects": "$candidates", "region": f"${region_id}"},
                    "params": {"mode": value.get("mode", "center"),
                               "overlap_threshold": value.get("threshold", 0.5)},
                })
                bound.append(inside_id)
                condition_ref = f"${inside_id}"
                if relation == "outside_roi":
                    outside_id = f"constraint_{index}_outside"
                    nodes.append({"id": outside_id, "op": "logic.not@1.0",
                                  "inputs": {"condition": condition_ref}, "params": {}})
                    bound.append(outside_id)
                    condition_ref = f"${outside_id}"
                return condition_ref, bound

            reference = value.get("object")
            if not isinstance(reference, dict) or not reference.get("phrases"):
                raise SemanticValidationError("relative spatial relation requires a reference entity")
            reference_id = f"constraint_{index}_reference"
            relation_id = f"constraint_{index}_relation"
            relation_map = {"inside": "inside", "overlap": "overlap", "contains": "contains"}
            reference_ref, bound = _append_grounding(nodes, reference_id, frames, [{
                "label": reference.get("concept", "reference"),
                "phrases": reference["phrases"],
            }], semantic_node=True)
            nodes.append(
                {"id": relation_id, "op": "spatial.associate@1.0",
                 "inputs": {"subjects": "$candidates", "objects": reference_ref},
                 "params": {"relation": relation_map.get(relation, relation),
                            "threshold": value.get("threshold", 0.1)}}
            )
            return f"${relation_id}", [*bound, relation_id]

        matched_id = f"constraint_{index}_objects"
        match_id = f"constraint_{index}_matches"
        phrases = constraint.phrases or [str(constraint.value).replace("_", " ")]
        if constraint.kind in {"state", "support_relation"} and target_phrase:
            phrases = [
                phrase
                if re.search(rf"\b{re.escape(target_phrase)}\b", phrase, re.I)
                else f"{target_phrase} with {phrase}"
                for phrase in phrases
            ]
        grounding_frames = (
            evidence_frames
            if constraint.polarity == "required" and evidence_frames
            else frames
        )
        matched_ref, bound = _append_grounding(
            nodes, matched_id, grounding_frames,
            [{"label": constraint.source_span, "phrases": phrases}],
            semantic_node=True,
        )
        nodes.append(
            {"id": match_id, "op": "spatial.associate@1.0",
             "inputs": {"subjects": "$candidates", "objects": matched_ref},
             "params": {"relation": "mutual_match", "threshold": 0.5}}
        )
        condition_ref = f"${match_id}"
        bound_nodes = [*bound, match_id]
        if (
            constraint.kind == "pose"
            and str(constraint.value).strip().lower() == "fallen_or_lying"
        ):
            nodes[-1]["params"]["threshold"] = 0.3
            geometry_id = f"constraint_{index}_pose_geometry"
            combined_id = f"constraint_{index}_pose_all"
            nodes.extend([
                {
                    "id": geometry_id,
                    "op": "visual.geometry@1.0",
                    "inputs": {"objects": "$candidates"},
                    "params": {
                        "dimension": "aspect_ratio",
                        "value": "horizontal",
                        "aspect_ratio_threshold": 0.6,
                    },
                },
                {
                    "id": combined_id,
                    "op": "logic.all@1.0",
                    "inputs": {
                        "conditions": [condition_ref, f"${geometry_id}"]
                    },
                    "params": {},
                },
            ])
            condition_ref = f"${combined_id}"
            bound_nodes.extend([geometry_id, combined_id])
        shared = ["evidence_frames"] if grounding_frames == "$evidence_frames" else []
        return condition_ref, [*shared, *bound_nodes]

    def _compile_stream_variant(
        self,
        semantic_ir: CanonicalSemanticIR,
        media_type: str,
        display_name: str,
    ) -> dict[str, Any]:
        nodes, frames = self._start_nodes(media_type)
        target_label = (
            semantic_ir.target.source_span.strip()
            or semantic_ir.target.concept
        )
        _append_grounding(
            nodes,
            "candidates",
            frames,
            [item.model_dump(mode="json") for item in semantic_ir.target.classes]
            or [{"label": target_label, "phrases": semantic_ir.target.phrases}],
        )
        evidence_frames = self._append_shared_evidence_frames(
            nodes, frames, semantic_ir.constraints
        )
        atom_bindings: dict[str, list[str]] = {}
        configuration_slots: list[dict[str, Any]] = []

        stream_kinds = {
            "motion", "region_requirement", "direction_relation", "temporal"
        }
        entity_conditions: list[str] = []
        grouped_conditions, grouped_bindings = self._compile_pose_groups(
            nodes, semantic_ir, evidence_frames, frames
        )
        entity_conditions.extend(grouped_conditions)
        atom_bindings.update(grouped_bindings)
        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            manual_stream_region = (
                constraint.kind == "spatial_relation"
                and isinstance(constraint.value, dict)
                and constraint.value.get("relation")
                in {"inside_roi", "outside_roi"}
                and constraint.value.get("region", {}).get("source") == "manual"
            )
            if constraint.kind in stream_kinds or manual_stream_region:
                continue
            if constraint.kind == "quantity":
                continue
            if constraint.atom_id in grouped_bindings:
                continue
            condition, bound = self._compile_constraint(
                nodes,
                frames,
                index,
                constraint,
                configuration_slots,
                evidence_frames,
                semantic_ir.target.phrases[0],
                semantic_ir.target.concept,
            )
            if constraint.polarity == "absent":
                not_id = f"constraint_{index}_not"
                nodes.append({
                    "id": not_id,
                    "op": "logic.not@1.0",
                    "inputs": {"condition": condition},
                    "params": {},
                })
                condition = f"${not_id}"
                bound.append(not_id)
            entity_conditions.append(condition)
            atom_bindings[constraint.atom_id] = bound

        candidates_ref = "$candidates"
        if entity_conditions:
            combined_id = "entity_constraints"
            if len(entity_conditions) == 1:
                combined_ref = entity_conditions[0]
            else:
                nodes.append({
                    "id": combined_id,
                    "op": "logic.all@1.0"
                    if semantic_ir.logic == "all"
                    else "logic.any@1.0",
                    "inputs": {"conditions": entity_conditions},
                    "params": {},
                })
                combined_ref = f"${combined_id}"
            nodes.append({
                "id": "entity_filtered",
                "op": "filter.apply@1.0",
                "inputs": {
                    "objects": "$candidates",
                    "condition": combined_ref,
                },
                "params": {},
            })
            candidates_ref = "$entity_filtered"

        tracks_id: str | None = None
        entities_ref = candidates_ref
        if media_type == "video":
            tracks_id = "stream_tracks"
            nodes.append({
                "id": tracks_id,
                "op": "track.iou@1.0",
                "inputs": {"objects": candidates_ref},
                "params": {},
            })
            entities_ref = f"${tracks_id}"
        conditions: list[str] = []
        condition_scopes: list[str] = []
        condition_region_sources: list[str | None] = []
        measurement_refs: list[str] = []
        region_by_role: dict[str, tuple[str, str]] = {}
        region_constraint_by_role: dict[
            str, tuple[int, SemanticConstraint, str]
        ] = {}
        label_branches: list[dict[str, Any]] = []
        draw_region_refs: list[str] = []
        draw_direction_ref: str | None = None

        business_target_label = (
            "人员"
            if semantic_ir.target.concept == "person"
            else target_label
        )

        def branch_label(source: str | None) -> str:
            spans = []
            for item in semantic_ir.constraints:
                if item.source != source or item.kind != "color":
                    continue
                span = item.source_span
                if (
                    item.carrier == "upper_body_clothing"
                    and span.endswith("衣服")
                ):
                    span = span[:-2] + "上衣"
                if span not in spans:
                    spans.append(span)
            return (
                "、".join([*spans[:-1], spans[-1] + business_target_label])
                if spans else business_target_label
            )

        def remember_draw_region(reference: str) -> None:
            if reference not in draw_region_refs:
                draw_region_refs.append(reference)

        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            if constraint.kind != "region_requirement":
                continue
            value = constraint.value
            role = str(value["semantic_role"])
            region_id = f"constraint_{index}_regions"
            many = value["cardinality"] == "many"
            node_op = "region.manual_set@1.0" if many else "region.manual@1.0"
            parameter = "regions" if many else "points"
            params = {"regions": []} if many else {"shape": "polygon", "points": []}
            nodes.append({
                "id": region_id,
                "op": node_op,
                "inputs": {},
                "params": params,
            })
            slot_id = region_id
            configuration_slots.append({
                "slot_id": slot_id,
                "kind": "region_set" if many else "region",
                "label": constraint.source_span,
                "required": True,
                "binding": {"node_id": region_id, "parameter": parameter},
                "allowed_shapes": ["rectangle", "polygon"],
                "minimum_items": 1,
                "source_atom_ids": [constraint.atom_id],
                "help_text": "在原图或视频标注帧上配置命名区域",
            })
            region_by_role[role] = (region_id, slot_id)
            region_constraint_by_role[role] = (index, constraint, region_id)
            remember_draw_region(f"${region_id}")
            atom_bindings[constraint.atom_id] = [region_id]

        consumed_region_roles = {
            str(constraint.value["region_role"])
            for constraint in semantic_ir.constraints
            if constraint.kind in {"quantity", "motion"}
            and isinstance(constraint.value, dict)
            and constraint.value.get("group_by") == "named_region"
        }
        consumed_region_roles.update(
            str(constraint.value.get("region", {}).get("semantic_role"))
            for constraint in semantic_ir.constraints
            if constraint.kind == "spatial_relation"
            and isinstance(constraint.value, dict)
            and constraint.value.get("region", {}).get("source") == "manual"
            and constraint.value.get("region", {}).get("semantic_role")
        )
        if any(
            constraint.kind == "direction_relation"
            and isinstance(constraint.value, dict)
            and constraint.value.get("reference_scope") == "per_named_region"
            for constraint in semantic_ir.constraints
        ):
            consumed_region_roles.update(region_by_role)

        # A manual region that is not merely a grouping/reference resource is
        # an independent business branch: matching entities must exist there.
        # This preserves clauses such as "区域1有红衣人" while another clause
        # independently counts all people in 区域2.
        independent_region_sources: set[str] = set()
        for role, (index, constraint, region_id) in region_constraint_by_role.items():
            if role in consumed_region_roles:
                continue
            independent_region_sources.add(constraint.source)
            inside_id = f"constraint_{index}_region_membership"
            count_id = f"constraint_{index}_region_count"
            present_id = f"constraint_{index}_region_present"
            nodes.extend([
                {
                    "id": inside_id,
                    "op": "spatial.inside@1.0",
                    "inputs": {
                        "objects": candidates_ref,
                        "region": f"${region_id}",
                    },
                    "params": {"mode": "center", "overlap_threshold": 0.5},
                },
                {
                    "id": count_id,
                    "op": "measure.region_count@1.0",
                    "inputs": {
                        "objects": candidates_ref,
                        "regions": f"${region_id}",
                        "frames": frames,
                    },
                    "params": {"membership_mode": "center"},
                },
                {
                    "id": present_id,
                    "op": "logic.compare@1.0",
                    "inputs": {"left": f"${count_id}"},
                    "params": {"operator": ">=", "value": 1},
                },
            ])
            conditions.append(f"${present_id}")
            condition_scopes.append("region")
            condition_region_sources.append(region_id)
            measurement_refs.append(f"${count_id}")
            atom_bindings[constraint.atom_id] = [
                region_id, inside_id, count_id, present_id
            ]
            label_branches.append({
                "condition": f"${inside_id}",
                "objects": candidates_ref,
                "label": branch_label(constraint.source),
                "priority": 20,
            })

        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            if constraint.kind != "spatial_relation":
                continue
            value = constraint.value
            if value.get("relation") not in {"inside_roi", "outside_roi"}:
                continue
            region = value.get("region", {})
            if region.get("source") != "manual":
                continue
            role = str(region.get("semantic_role", f"region_{index}"))
            existing = region_by_role.get(role)
            if existing is None:
                region_id = f"constraint_{index}_region"
                slot_id = region_id
                nodes.append({
                    "id": region_id,
                    "op": "region.manual@1.0",
                    "inputs": {},
                    "params": {
                        "shape": region.get("shape", "polygon"),
                        "points": region.get("points", []),
                    },
                })
                configuration_slots.append({
                    "slot_id": slot_id,
                    "kind": "region",
                    "label": constraint.source_span,
                    "required": True,
                    "binding": {"node_id": region_id, "parameter": "points"},
                    "allowed_shapes": region.get(
                        "allowed_shapes", ["rectangle", "polygon"]
                    ),
                    "minimum_items": 1,
                    "source_atom_ids": [constraint.atom_id],
                    "help_text": "在原图或视频标注帧上绘制区域",
                })
                region_by_role[role] = (region_id, slot_id)
            else:
                region_id, _slot_id = existing
            inside_id = f"constraint_{index}_inside"
            nodes.append({
                "id": inside_id,
                "op": "spatial.inside@1.0",
                "inputs": {
                    "objects": entities_ref,
                    "region": f"${region_id}",
                },
                "params": {
                    "mode": value.get("mode", "center"),
                    "overlap_threshold": value.get("threshold", 0.5),
                },
            })
            condition_ref = f"${inside_id}"
            bound = [region_id, inside_id]
            if value["relation"] == "outside_roi":
                outside_id = f"constraint_{index}_outside"
                nodes.append({
                    "id": outside_id,
                    "op": "logic.not@1.0",
                    "inputs": {"condition": condition_ref},
                    "params": {},
                })
                condition_ref = f"${outside_id}"
                bound.append(outside_id)
            conditions.append(condition_ref)
            condition_scopes.append("track" if media_type == "video" else "global")
            condition_region_sources.append(region_id)
            atom_bindings[constraint.atom_id] = bound
            remember_draw_region(f"${region_id}")

        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            if constraint.kind != "motion":
                continue
            value = constraint.value
            speed_id = f"constraint_{index}_speed"
            compare_id = f"constraint_{index}_compare"
            region_grouped = value.get("group_by") == "named_region"
            region_source_id: str | None = None
            speed_op = "measure.region_speed@1.0" if region_grouped else "measure.speed@1.0"
            speed_inputs = {"tracks": entities_ref}
            speed_params = {
                "window_frames": value.get("window_frames", 5),
                "unit": value.get("unit", "pixels_per_second"),
            }
            if region_grouped:
                role = value["region_role"]
                if role not in region_by_role:
                    raise SemanticValidationError(
                        f"named-region motion requires region role: {role}"
                    )
                region_id, _slot_id = region_by_role[role]
                speed_inputs["regions"] = f"${region_id}"
                region_source_id = region_id
                speed_params.update({
                    "aggregation": value.get("aggregation", "region_median")
                    .removeprefix("region_"),
                    "membership_mode": value.get(
                        "membership_mode", "sample_center"
                    ),
                })
                remember_draw_region(f"${region_id}")
            else:
                speed_params["aggregation"] = value.get(
                    "aggregation", "per_track"
                )
            nodes.extend([
                {
                    "id": speed_id,
                    "op": speed_op,
                    "inputs": speed_inputs,
                    "params": speed_params,
                },
                {
                    "id": compare_id,
                    "op": "logic.compare@1.0",
                    "inputs": {"left": f"${speed_id}"},
                    "params": {
                        "operator": value["operator"],
                        "value": value["threshold"],
                    },
                },
            ])
            conditions.append(f"${compare_id}")
            measurement_refs.append(f"${speed_id}")
            condition_scopes.append(
                "region" if region_grouped else (
                    "track"
                    if value.get("aggregation", "per_track") == "per_track"
                    else "global"
                )
            )
            condition_region_sources.append(region_source_id)
            atom_bindings[constraint.atom_id] = [speed_id, compare_id]

        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            if constraint.kind != "direction_relation":
                continue
            value = constraint.value
            heading_id = f"constraint_{index}_headings"
            reference_id = f"constraint_{index}_references"
            compare_id = f"constraint_{index}_direction"
            nodes.append({
                "id": heading_id,
                "op": "measure.heading@1.0",
                "inputs": {"tracks": entities_ref},
                "params": {
                    "window_frames": value.get("window_frames", 3),
                    "min_displacement_pixels": value.get(
                        "min_displacement_pixels", 5.0
                    ),
                },
            })
            source = value["reference_source"]
            scope = value["reference_scope"]
            relation = value["relation"]
            region_source_id: str | None = None
            if scope == "global":
                if source == "whole_video_majority":
                    nodes.append({
                        "id": reference_id,
                        "op": "measure.majority_heading@1.0",
                        "inputs": {"directions": f"${heading_id}"},
                        "params": {
                            "minimum_tracks": value.get("minimum_tracks", 2),
                            "aggregation": "global",
                        },
                    })
                elif source == "image_axis":
                    nodes.append({
                        "id": reference_id,
                        "op": "direction.image_axis@1.0",
                        "inputs": {},
                        "params": {"direction": value["image_axis"]},
                    })
                else:
                    nodes.append({
                        "id": reference_id,
                        "op": "direction.manual@1.0",
                        "inputs": {},
                        "params": {"vector": [0.0, 0.0]},
                    })
                    configuration_slots.append({
                        "slot_id": f"{reference_id}_manual",
                        "kind": "direction",
                        "label": "全局参考方向",
                        "required": True,
                        "binding": {
                            "node_id": reference_id,
                            "parameter": "vector",
                        },
                        "allowed_shapes": [],
                        "minimum_items": 1,
                        "source_atom_ids": [constraint.atom_id],
                        "help_text": "在原图或视频标注帧上绘制全局方向箭头",
                    })
                nodes.append({
                    "id": compare_id,
                    "op": "logic.compare@1.0",
                    "inputs": {
                        "left": f"${heading_id}",
                        "right": f"${reference_id}",
                    },
                    "params": {
                        "operator": f"{relation}_direction",
                        "threshold": value.get(
                            "cosine_threshold",
                            -0.5 if relation == "opposite" else 0.5,
                        ),
                    },
                })
            else:
                if not region_by_role:
                    raise SemanticValidationError(
                        "per_named_region direction requires a region requirement"
                    )
                lane_region_id, lane_slot_id = next(iter(region_by_role.values()))
                region_source_id = lane_region_id
                if source == "whole_video_majority":
                    nodes.append({
                        "id": reference_id,
                        "op": "measure.lane_majority_heading@1.0",
                        "inputs": {
                            "tracks": entities_ref,
                            "directions": f"${heading_id}",
                            "lanes": f"${lane_region_id}",
                        },
                        "params": {
                            "minimum_tracks": value.get("minimum_tracks", 2),
                            "membership_mode": "majority_center",
                        },
                    })
                elif source == "image_axis":
                    nodes.append({
                        "id": reference_id,
                        "op": "direction.image_axis@1.0",
                        "inputs": {},
                        "params": {"direction": value["image_axis"]},
                    })
                else:
                    nodes.append({
                        "id": reference_id,
                        "op": "direction.manual_set@1.0",
                        "inputs": {},
                        "params": {"directions": []},
                    })
                if source in {"whole_video_majority", "manual"}:
                    configuration_slots.append({
                        "slot_id": f"{reference_id}_manual",
                        "kind": "direction_set",
                        "label": "逐区域参考方向",
                        "required": True,
                        "binding": {
                            "node_id": reference_id,
                            "parameter": "directions",
                        },
                        "allowed_shapes": [],
                        "minimum_items": 1,
                        "source_atom_ids": [constraint.atom_id],
                        "help_text": "切换手工模式后，每个命名区域绘制一个方向",
                        "active_when_op": ["direction.manual_set@1.0"],
                        "key_source_slot_id": lane_slot_id,
                    })
                nodes.append({
                    "id": compare_id,
                    "op": "logic.heading_by_lane@1.0",
                    "inputs": {
                        "tracks": entities_ref,
                        "headings": f"${heading_id}",
                        "lanes": f"${lane_region_id}",
                        "references": f"${reference_id}",
                    },
                    "params": {
                        "threshold": value.get(
                            "cosine_threshold",
                            -0.5 if relation == "opposite" else 0.5,
                        ),
                        "membership_mode": "majority_center",
                        "relation": relation,
                    },
                })
            conditions.append(f"${compare_id}")
            condition_scopes.append("track")
            condition_region_sources.append(region_source_id)
            atom_bindings[constraint.atom_id] = [
                heading_id, reference_id, compare_id
            ]
            draw_direction_ref = f"${reference_id}"
            if scope == "per_named_region":
                remember_draw_region(f"${lane_region_id}")

        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            if constraint.kind != "quantity":
                continue
            count_id = f"constraint_{index}_count"
            region_grouped = constraint.value.get("group_by") == "named_region"
            region_source_id: str | None = None
            if region_grouped:
                role = constraint.value["region_role"]
                if role not in region_by_role:
                    raise SemanticValidationError(
                        f"named-region quantity requires region role: {role}"
                    )
                region_id, _slot_id = region_by_role[role]
                quantity_objects_ref = candidates_ref
                if independent_region_sources and constraint.source not in independent_region_sources:
                    quantity_objects_ref = "$candidates"
                count_op = "measure.region_count@1.0"
                count_inputs = {
                    "objects": quantity_objects_ref,
                    "regions": f"${region_id}",
                    "frames": frames,
                }
                count_params = {"membership_mode": "center"}
                region_source_id = region_id
                remember_draw_region(f"${region_id}")
                membership_id = f"constraint_{index}_region_membership"
                nodes.append({
                    "id": membership_id,
                    "op": "spatial.inside@1.0",
                    "inputs": {
                        "objects": quantity_objects_ref,
                        "region": f"${region_id}",
                    },
                    "params": {"mode": "center", "overlap_threshold": 0.5},
                })
                label_branches.append({
                    "condition": f"${membership_id}",
                    "objects": quantity_objects_ref,
                    "label": business_target_label,
                    "priority": 10,
                })
            else:
                count_op = "measure.count@1.0"
                count_inputs = {"entities": entities_ref}
                count_params = {"scope": "unique"}
            nodes.append({
                "id": count_id,
                "op": count_op,
                "inputs": count_inputs,
                "params": count_params,
            })
            measurement_refs.append(f"${count_id}")
            if "operator" not in constraint.value:
                atom_bindings[constraint.atom_id] = [
                    *([membership_id] if region_grouped else []), count_id
                ]
                continue
            compare_id = f"constraint_{index}_compare"
            nodes.append({
                "id": compare_id,
                "op": "logic.compare@1.0",
                "inputs": {"left": f"${count_id}"},
                "params": {
                    "operator": constraint.value["operator"],
                    "value": constraint.value["value"],
                },
            })
            conditions.append(f"${compare_id}")
            condition_scopes.append("region" if region_grouped else "global")
            condition_region_sources.append(region_source_id)
            atom_bindings[constraint.atom_id] = [
                *([membership_id] if region_grouped else []),
                count_id,
                compare_id,
            ]

        if not conditions and not measurement_refs:
            raise SemanticValidationError(
                "stream workflow requires at least one executable condition"
            )
        if not conditions:
            condition_ref = None
        else:
            condition_ref = ""
        mixed_condition_scopes = len(set(condition_scopes)) > 1
        if len(conditions) == 1:
            condition_ref = conditions[0]
        elif len(conditions) > 1:
            combined_id = "stream_conditions"
            unique_region_sources = {
                source for source in condition_region_sources if source is not None
            }
            nodes.append({
                "id": combined_id,
                "op": "logic.all@1.0"
                if semantic_ir.logic == "all"
                else "logic.any@1.0",
                "inputs": {"conditions": conditions},
                "params": {
                    "combine_scope": (
                        "frame_any"
                        if mixed_condition_scopes or len(unique_region_sources) > 1
                        else "by_key"
                    ),
                },
            })
            condition_ref = f"${combined_id}"

        event_refs: list[str] = []
        for index, constraint in enumerate(semantic_ir.constraints, start=1):
            if constraint.kind != "temporal":
                continue
            if condition_ref is None:
                raise SemanticValidationError(
                    "temporal workflow requires a boolean condition"
                )
            value = constraint.value
            if value["type"] != "persist":
                raise SemanticValidationError(
                    "stream condition compiler currently supports persist events"
                )
            event_id = f"constraint_{index}_event"
            nodes.append({
                "id": event_id,
                "op": "event.from_condition@1.0",
                "inputs": {"condition": condition_ref},
                "params": {
                    "seconds": value["seconds"],
                    "scope": condition_scopes[0],
                    "gap_tolerance_seconds": value.get(
                        "gap_tolerance_seconds", 0.5
                    ),
                    "trigger_mode": value.get("trigger_mode", "once"),
                    "label": display_name,
                },
            })
            event_refs.append(f"${event_id}")
            atom_bindings[constraint.atom_id] = [event_id]

        # A boolean stream condition is itself an immediate event when no
        # persistence constraint is present.  This keeps "触发事件告警" a
        # complete, reusable graph rather than merely a visual overlay.
        if condition_ref is not None and not event_refs:
            event_id = "condition_event"
            nodes.append({
                "id": event_id,
                "op": "event.from_condition@1.0",
                "inputs": {"condition": condition_ref},
                "params": {
                    "seconds": 0.0,
                    "scope": condition_scopes[0],
                    "gap_tolerance_seconds": 0.0,
                    "trigger_mode": "once",
                    "label": display_name,
                },
            })
            event_refs.append(f"${event_id}")

        alert_refs: list[str] = []
        for index, event_ref in enumerate(event_refs, start=1):
            alert_id = "alerts" if len(event_refs) == 1 else f"alert_{index}"
            nodes.append({
                "id": alert_id,
                "op": "output.alert@1.0",
                "inputs": {"events": event_ref},
                "params": {"label": display_name},
            })
            alert_refs.append(f"${alert_id}")

        projected_objects_ref: str | None = None
        if label_branches:
            effective_branches: list[str] = []
            raw_branches: list[str] = []
            for position, branch in enumerate(
                sorted(label_branches, key=lambda item: -item["priority"]),
                start=1,
            ):
                labeled_id = f"business_label_branch_{position}"
                nodes.append({
                    "id": labeled_id,
                    "op": "filter.apply@1.0",
                    "inputs": {
                        "objects": branch["objects"],
                        "condition": branch["condition"],
                    },
                    "params": {"output_label": branch["label"]},
                })
                raw_ref = f"${labeled_id}"
                effective_ref = raw_ref
                for higher_position, higher_ref in enumerate(
                    raw_branches, start=1
                ):
                    difference_id = (
                        f"business_label_branch_{position}_without_"
                        f"{higher_position}"
                    )
                    nodes.append({
                        "id": difference_id,
                        "op": "set.difference@1.0",
                        "inputs": {
                            "left": effective_ref,
                            "right": higher_ref,
                        },
                        "params": {"field": "identity"},
                    })
                    effective_ref = f"${difference_id}"
                raw_branches.append(raw_ref)
                effective_branches.append(effective_ref)

            outside_ref = "$candidates"
            for position, branch_ref in enumerate(raw_branches, start=1):
                outside_id = f"business_label_outside_{position}"
                nodes.append({
                    "id": outside_id,
                    "op": "set.difference@1.0",
                    "inputs": {"left": outside_ref, "right": branch_ref},
                    "params": {"field": "identity"},
                })
                outside_ref = f"${outside_id}"
            nodes.append({
                "id": "business_labeled_objects",
                "op": "objects.merge@1.0",
                "inputs": {
                    "objects": [outside_ref, *reversed(effective_branches)]
                },
                "params": {},
            })
            projected_objects_ref = "$business_labeled_objects"

        result_objects_ref = candidates_ref
        result_tracks_ref: str | None = None
        if media_type == "video":
            result_tracks_ref = entities_ref
            if condition_ref is not None and condition_scopes[0] == "track":
                nodes.append({
                    "id": "result_tracks",
                    "op": "tracks.filter@1.0",
                    "inputs": {
                        "tracks": entities_ref,
                        "condition": condition_ref,
                    },
                    "params": {"history_mode": "matching_samples"},
                })
                result_tracks_ref = "$result_tracks"
            if projected_objects_ref is not None:
                result_objects_ref = projected_objects_ref
            else:
                nodes.append({
                    "id": "result_boxes",
                    "op": "objects.from_tracks@1.0",
                    "inputs": {"tracks": result_tracks_ref},
                    "params": {"selection": "all"},
                })
                result_objects_ref = "$result_boxes"
        elif projected_objects_ref is not None:
            result_objects_ref = projected_objects_ref
        # Object labels are produced by target grounding and remain separate
        # from the skill/event display name.  This also preserves per-class
        # labels and labels on objects outside configured regions.
        labeled_ref = result_objects_ref
        draw_region_ref: str | None = None
        if len(draw_region_refs) == 1:
            draw_region_ref = draw_region_refs[0]
        elif len(draw_region_refs) > 1:
            nodes.append({
                "id": "draw_regions",
                "op": "regions.merge@1.0",
                "inputs": {"regions": draw_region_refs},
                "params": {},
            })
            draw_region_ref = "$draw_regions"
        draw_inputs = {"frames": frames, "objects": labeled_ref}
        if len(alert_refs) == 1:
            draw_inputs["events"] = alert_refs[0]
        if draw_region_ref is not None:
            draw_inputs["regions"] = draw_region_ref
        if draw_direction_ref is not None:
            draw_inputs["directions"] = draw_direction_ref
        if len(measurement_refs) == 1:
            draw_inputs["measurements"] = measurement_refs[0]
        nodes.append({
            "id": "draw",
            "op": "output.draw@1.0",
            "inputs": draw_inputs,
            "params": {},
        })
        outputs = {
            "media": "$draw",
            "objects": labeled_ref,
        }
        if result_tracks_ref is not None:
            outputs["tracks"] = result_tracks_ref
        if condition_ref is not None:
            outputs["condition"] = condition_ref
        if len(measurement_refs) == 1:
            outputs["measurements"] = measurement_refs[0]
        elif measurement_refs:
            for position, ref in enumerate(measurement_refs, start=1):
                outputs[f"measurements_{position}"] = ref
        if len(alert_refs) == 1:
            outputs["events"] = alert_refs[0]
        if draw_region_ref is not None:
            outputs["regions"] = draw_region_ref
        if draw_direction_ref is not None:
            outputs["directions"] = draw_direction_ref
        return {
            "media_type": media_type,
            "status": "needs_configuration"
            if any(slot["kind"].startswith("region") for slot in configuration_slots)
            or any(
                slot.get("active_when_op") is None
                and slot["kind"].startswith("direction")
                for slot in configuration_slots
            )
            else "executable",
            "nodes": nodes,
            "outputs": outputs,
            "atom_bindings": atom_bindings,
            "configuration_slots": configuration_slots,
        }

    @staticmethod
    def _compile_temporal(
        nodes, frames, result_ref, aggregate_ref, index, constraint
    ):
        value = constraint.value
        temporal_type = value["type"]
        if temporal_type == "persist":
            bound = []
            tracked_ref = None
            if aggregate_ref:
                condition_ref = aggregate_ref
                scope = "global"
            else:
                tracks_id = f"constraint_{index}_tracks"
                region_id = f"constraint_{index}_region"
                present_id = f"constraint_{index}_present"
                nodes.extend([
                    {"id": tracks_id, "op": "track.iou@1.0",
                     "inputs": {"objects": result_ref}, "params": {}},
                    {"id": region_id, "op": "region.full_frame@1.0",
                     "inputs": {"frames": frames}, "params": {}},
                    {"id": present_id, "op": "spatial.inside@1.0",
                     "inputs": {"objects": f"${tracks_id}", "region": f"${region_id}"},
                     "params": {"mode": "center", "overlap_threshold": 0.5}},
                ])
                bound.extend([tracks_id, region_id, present_id])
                tracked_ref = f"${tracks_id}"
                condition_ref = f"${present_id}"
                scope = "track"
            persist_id = f"constraint_{index}_persist"
            nodes.append({
                "id": persist_id, "op": "temporal.persist@1.0",
                "inputs": {"condition": condition_ref},
                "params": {
                    "seconds": value["seconds"],
                    "scope": scope,
                    "gap_tolerance_seconds": value.get("gap_tolerance_seconds", 0.5),
                    "trigger_mode": value.get("trigger_mode", "once"),
                },
            })
            bound.append(persist_id)
            return f"${persist_id}", bound, tracked_ref

        tracks_id = f"constraint_{index}_tracks"
        nodes.append({"id": tracks_id, "op": "track.iou@1.0",
                      "inputs": {"objects": result_ref}, "params": {}})
        bound = [tracks_id]
        step_events = []
        step_labels = []
        for step_index, step in enumerate(value["steps"], start=1):
            objects_id = f"constraint_{index}_step_{step_index}_objects"
            matches_id = f"constraint_{index}_step_{step_index}_matches"
            event_id = f"constraint_{index}_step_{step_index}_events"
            objects_ref, object_nodes = _append_grounding(
                nodes, objects_id, frames,
                [{"label": step["label"], "phrases": step["phrases"]}],
                semantic_node=True,
            )
            bound.extend(object_nodes)
            nodes.extend([
                {"id": matches_id, "op": "spatial.associate@1.0",
                 "inputs": {"subjects": f"${tracks_id}", "objects": objects_ref},
                 "params": {"relation": "overlap", "threshold": 0.5}},
                {"id": event_id, "op": "temporal.persist@1.0",
                 "inputs": {"condition": f"${matches_id}"},
                 "params": {"seconds": 0.0, "scope": "track",
                            "gap_tolerance_seconds": 0.5, "trigger_mode": "once"}},
            ])
            bound.extend([matches_id, event_id])
            step_events.append(f"${event_id}")
            step_labels.append(step["label"])
        sequence_id = f"constraint_{index}_sequence"
        nodes.append({
            "id": sequence_id, "op": "temporal.sequence@2.0",
            "inputs": {"events": step_events},
            "params": {
                "transitions": [
                    {
                        "relation": "after",
                        "source_anchor": "end",
                        "target_anchor": "start",
                        "minimum_delay_seconds": 0.0,
                        "maximum_delay_seconds": value.get("max_gap_seconds", 5.0),
                    }
                    for _ in range(len(step_events) - 1)
                ],
                "correlation_scope": "track" if value.get("same_key", True) else "global",
                "correlation_fields": [],
                "consume_events": True,
                "label": step_labels[-1] if step_labels else "顺序事件",
            },
        })
        bound.append(sequence_id)
        return f"${sequence_id}", bound, f"${tracks_id}"


__all__ = ["SemanticNormalizer", "SemanticValidationError", "WorkflowCompiler"]
