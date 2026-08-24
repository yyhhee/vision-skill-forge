from __future__ import annotations

import re
from copy import deepcopy

from .editor_schema import (
    CardinalitySpec,
    CompatibilityInfo,
    PendingDecision,
    ResolvableValue,
    ResourceRequirement,
    ResultSpec,
    SkillEditorDocument,
    UserOverride,
)
from .document_hashes import refresh_document_hashes
from .editor_migrations import migrate_editor_document
from .legacy_importer import import_skill_package
from .schema import SkillPackage
from .semantic import find_incomplete_count_comparisons

_UNKNOWN = r"(?:X{1,2}|x{1,2}|若干|一定数量|未确定)"


def build_editor_document(
    package: SkillPackage,
    *,
    source_type: str = "natural_language",
) -> SkillEditorDocument:
    document = migrate_editor_document(import_skill_package(package))
    template = document.skill_template.model_copy(deep=True)
    template.source_type = source_type
    if source_type == "natural_language":
        for graph in template.rule_graphs.values():
            for node in graph.nodes:
                node.parameter_sources = {
                    name: ResolvableValue(
                        state="inferred",
                        value=value,
                        source="llm_generated",
                        required_before="never",
                    )
                    for name, value in node.params.items()
                    if value is not None
                }
    instruction = package.original_instruction
    decisions = []

    for index, unresolved in enumerate(package.semantic_ir.unresolved, start=1):
        decisions.append(
            PendingDecision(
                decision_id=f"semantic_{index}",
                parameter_kind="generic",
                prompt=f"请确认：{unresolved.source_span}",
                resolution=ResolvableValue(
                    state="unresolved",
                    source="natural_language",
                    reason=unresolved.reason,
                    required_before="compile",
                ),
            )
        )
    if re.search(_UNKNOWN + r"\s*(?:辆|个|人|台|件|次)", instruction):
        decisions.extend([
            PendingDecision(
                decision_id="count_operator",
                parameter_kind="comparison_operator",
                prompt="数量条件使用等于、至少、大于还是其它比较方式？",
                resolution=ResolvableValue(
                    state="unresolved",
                    source="natural_language",
                    recommended_value=">=",
                    alternatives=["==", ">=", ">"],
                    reason="自然语言未给出明确数量比较符",
                    required_before="run",
                ),
            ),
            PendingDecision(
                decision_id="count_threshold",
                parameter_kind="count_threshold",
                prompt="数量阈值是多少？",
                resolution=ResolvableValue(
                    state="unresolved",
                    source="natural_language",
                    recommended_value=1,
                    reason="自然语言使用了数量占位符",
                    required_before="run",
                ),
            ),
        ])
    for index, (source_span, operator) in enumerate(
        find_incomplete_count_comparisons(instruction), start=1
    ):
        decisions.append(
            PendingDecision(
                decision_id=(
                    "count_threshold"
                    if index == 1
                    else f"count_threshold_{index}"
                ),
                parameter_kind="count_threshold",
                prompt=f"“{source_span}”的数量阈值是多少？",
                resolution=ResolvableValue(
                    state="unresolved",
                    source="natural_language",
                    recommended_value=1,
                    reason=f"比较符 {operator} 已明确，但数量阈值缺失",
                    required_before="run",
                ),
            )
        )
    if re.search(r"持续\s*" + _UNKNOWN, instruction):
        decisions.append(
            PendingDecision(
                decision_id="duration",
                parameter_kind="duration",
                prompt="该分支需要连续满足多少秒？",
                resolution=ResolvableValue(
                    state="unresolved",
                    source="natural_language",
                    recommended_value=1.0,
                    reason="持续时间未确定",
                    required_before="run",
                ),
            )
        )
    if re.search(_UNKNOWN + r"\s*秒内", instruction):
        decisions.append(
            PendingDecision(
                decision_id="time_window",
                parameter_kind="time_window",
                prompt="各阶段需要在多少秒的窗口内完成？",
                resolution=ResolvableValue(
                    state="unresolved",
                    source="natural_language",
                    recommended_value=60.0,
                    reason="组合事件时间窗未确定",
                    required_before="run",
                ),
            )
        )

    decision_operator_prefixes = {
        "comparison_operator": ("logic.compare@",),
        "count_threshold": ("logic.compare@",),
        "duration": ("temporal.qualify@", "temporal.persist@", "temporal.event_duration@"),
        "time_window": ("temporal.join@", "temporal.sequence@", "temporal.repeat@", "temporal.absence@"),
    }
    for decision in decisions:
        prefixes = decision_operator_prefixes.get(decision.parameter_kind, ())
        if prefixes:
            decision.affected_ids = list(dict.fromkeys(
                node.node_id
                for graph in template.rule_graphs.values()
                for node in graph.nodes
                if node.operator and node.operator.startswith(prefixes)
            ))

    requirements = list(template.resource_requirements)
    if re.search(r"区域|车道", instruction) and not any(
        item.resource_type.startswith("region") for item in requirements
    ):
        requirements.append(
            ResourceRequirement(
                requirement_id="scene_regions",
                resource_type="region_collection",
                display_name="场景区域",
                semantic_role="rule_scope",
                cardinality=CardinalitySpec(mode="dynamic", minimum=1),
                binding_policy="for_each",
                allowed_shapes=["rectangle", "polygon"],
                media_types=list(package.input.accept),
            )
        )
    if re.search(r"方向|逆行|同向|相反方向", instruction) and not any(
        item.resource_type.startswith("direction") for item in requirements
    ):
        source = next(
            (item for item in requirements if item.resource_type == "region_collection"),
            None,
        )
        requirements.append(
            ResourceRequirement(
                requirement_id="scene_directions",
                resource_type="direction_collection",
                display_name="参考方向",
                semantic_role="motion_reference",
                cardinality=(
                    CardinalitySpec(
                        mode="match_collection",
                        source_requirement_id=source.requirement_id,
                    )
                    if source
                    else CardinalitySpec(mode="dynamic", minimum=1)
                ),
                binding_policy="for_each",
                pairing_policy="one_per_region" if source else "none",
                media_types=["video"],
            )
        )

    declared_event = any(
        "events" in variant.outputs for variant in package.variants.values()
    )
    event_expected = any(
        marker in instruction
        for marker in ("事件", "告警", "报警", "事故", "摔倒", "逆行", "闯入")
    )
    result_specs = list(template.result_specs)
    validation_report = deepcopy(document.validation_report)
    issues = list(validation_report.get("issues", []))
    if event_expected and not declared_event:
        if not any(item.result_type == "event" for item in result_specs):
            result_specs.append(
                ResultSpec(
                    result_id="result_events",
                    result_type="event",
                    display_name="事件结果",
                    required_outputs=["events"],
                    evidence_policy="required",
                )
            )
        issues.append({
            "code": "semantic_event_output_missing",
            "message": "用户要求事件判断，但执行图尚未声明事件输出",
        })

    template.pending_decisions = decisions
    template.resource_requirements = requirements
    template.result_specs = result_specs
    validation_report.update({
        "valid": not any(item.resolution.blocks("compile") for item in decisions),
        "pending_decisions": [item.model_dump(mode="json") for item in decisions],
        "issues": issues,
    })
    return refresh_document_hashes(document.model_copy(
        update={
            "skill_template": template,
            "validation_report": validation_report,
            "compatibility": CompatibilityInfo(
                editability="full" if source_type != "legacy" else "legacy_atomic_only",
                issues=[] if source_type != "legacy" else document.compatibility.issues,
            ),
        }
    ))


def resolve_pending_decision(
    document: SkillEditorDocument, decision_id: str, value
) -> SkillEditorDocument:
    updated = document.model_copy(deep=True)
    decision = next(
        (
            item
            for item in updated.skill_template.pending_decisions
            if item.decision_id == decision_id
        ),
        None,
    )
    if decision is None:
        raise ValueError(f"pending decision does not exist: {decision_id}")
    decision.resolution = decision.resolution.resolved(value)
    parameter_names = {
        "comparison_operator": ("operator",),
        "count_threshold": ("value",),
        "duration": ("duration_seconds", "minimum_seconds"),
        "time_window": ("window_seconds",),
    }.get(decision.parameter_kind, ())
    business_parameter_names = {
        "comparison_operator": ("operator",),
        "count_threshold": ("threshold",),
        "duration": ("duration", "duration_seconds"),
        "time_window": ("window", "window_seconds"),
        "direction_reference": ("reference",),
        "correlation": ("correlation_scope",),
    }.get(decision.parameter_kind, ())

    def walk(expression):
        if expression is None:
            return
        yield expression
        for child in expression.children:
            yield from walk(child)

    for branch in updated.skill_template.business_branches:
        for expression in walk(branch.condition_root):
            if expression.expression_id not in decision.affected_ids:
                continue
            parameter = next(
                (
                    name
                    for name in business_parameter_names
                    if name in expression.parameters
                ),
                business_parameter_names[0] if business_parameter_names else None,
            )
            if parameter:
                expression.parameters[parameter] = value
                expression.parameter_sources[parameter] = ResolvableValue(
                    state="explicit",
                    value=value,
                    source="user",
                    required_before="never",
                )
        if branch.branch_id in decision.affected_ids and decision.parameter_kind == "duration":
            for qualifier in branch.temporal_qualifiers:
                qualifier.duration_seconds = qualifier.duration_seconds.resolved(
                    value
                )
    if decision.parameter_kind == "time_window":
        for pattern in updated.skill_template.event_patterns:
            if pattern.pattern_id not in decision.affected_ids:
                continue
            for gateway in pattern.gateways:
                gateway.window_seconds = gateway.window_seconds.resolved(value)
            for transition in pattern.transitions:
                transition.maximum_delay_seconds = (
                    transition.maximum_delay_seconds.resolved(value)
                )
            pattern.parameters["window_seconds"] = value
    for node_id in decision.affected_ids:
        node = next(
            (
                item
                for graph in updated.skill_template.rule_graphs.values()
                for item in graph.nodes
                if item.node_id == node_id
            ),
            None,
        )
        if node is None:
            continue
        parameter = next(
            (name for name in parameter_names if name in node.params),
            parameter_names[0] if parameter_names else None,
        )
        if parameter is None:
            continue
        updated.user_overrides = [
            item
            for item in updated.user_overrides
            if not (item.target_id == node_id and item.parameter == parameter)
        ]
        updated.user_overrides.append(
            UserOverride(
                target_type="rule",
                target_id=node_id,
                parameter=parameter,
                value=value,
            )
        )
    updated.validation_report["pending_decisions"] = [
        item.model_dump(mode="json")
        for item in updated.skill_template.pending_decisions
    ]
    updated.validation_report["valid"] = not any(
        item.resolution.blocks("compile")
        for item in updated.skill_template.pending_decisions
    )
    return refresh_document_hashes(updated)


__all__ = ["build_editor_document", "resolve_pending_decision"]
