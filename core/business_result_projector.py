from __future__ import annotations

import operator
from copy import deepcopy
from typing import Any

from .business_result_schema import (
    BranchResult,
    BusinessOutputValue,
    FinalResult,
    RunResult,
)
from .editor_schema import (
    BusinessBranch,
    FinalDecisionSpec,
    ResultSpec,
    SkillEditorDocument,
)
from .runtime_values import RuntimeValueEnvelope


_COMPARATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}

_PROJECTION_SOURCE_TYPES = {
    "status": {"boolean", "event_set", "entity_set", "track_set", "scalar"},
    "count": {"entity_set", "track_set", "event_set", "scalar"},
    "value": {"scalar", "boolean"},
    "duration": {"event_set"},
    "entities": {"entity_set"},
    "tracks": {"track_set"},
    "events": {"event_set"},
    "stages": {"event_set", "resource"},
    "resource": {"resource"},
    "media": {"media"},
}

_IDENTITY_SOURCE_TYPES = {
    "decision": {"boolean", "event_set"},
    "boolean": {"boolean"},
    "scalar": {"scalar"},
    "entity_set": {"entity_set"},
    "track_set": {"track_set"},
    "event_set": {"event_set"},
    "timeline": {"event_set", "resource"},
    "resource": {"resource"},
    "media": {"media"},
}


def build_runtime_contract(
    document: SkillEditorDocument,
    media_type: str,
) -> dict[str, Any]:
    package = document.effective_skill_package
    if package is None:
        raise ValueError("SkillEditorDocument has no Effective SkillPackage")
    variant = package.select_variant(media_type)
    variant_node_ids = {item.id for item in variant.nodes if item.enabled}
    published_sources: dict[str, str] = {}
    output_bindings: dict[str, str] = {}

    def final_output_name(prefix: str, decision_id: str) -> str:
        safe = "".join(
            character
            if character.isalnum() or character in "_-"
            else "_"
            for character in decision_id
        )
        if not safe or not safe[0].isalpha():
            safe = "decision_" + safe
        return f"{prefix}_{safe}"[:180]

    def requires_event_value(spec: ResultSpec) -> bool:
        """Whether a business result must bind to an EventSet, not a verdict."""

        return (
            spec.semantic_type in {"event_set", "timeline"}
            or spec.projection.kind in {"events", "duration", "stages"}
        )

    def publish(source_ref: str, node_id: str | None, *, replace: bool = True) -> None:
        if not node_id or node_id not in variant_node_ids:
            return
        if replace:
            published_sources[source_ref] = node_id
        else:
            published_sources.setdefault(source_ref, node_id)
        published_sources.setdefault(f"node:{node_id}", node_id)

    for output_name, ref in variant.outputs.items():
        node_id = ref[1:] if ref.startswith("$") else ref
        output_bindings[output_name] = node_id
        publish(f"output:{output_name}", node_id)

    # The editable RuleGraph is the only place where deterministic compiler
    # nodes retain their stable business-source aliases.  Rebuild the same
    # last-writer-wins map used by RuleGraphCompiler, but only for nodes that
    # survived into the selected executable variant.
    graph = document.skill_template.rule_graphs.get(media_type)
    if graph is not None:
        for node in graph.nodes:
            if not node.enabled:
                continue
            for source_ref in node.business_source_refs:
                publish(source_ref, node.node_id)

    branches = [
        branch
        for branch in document.skill_template.business_branches
        if branch.media_type == media_type and branch.enabled
    ]
    for branch in branches:
        if branch.root_node_id:
            publish(f"branch:{branch.branch_id}", branch.root_node_id)
    if len(branches) == 1 and not branches[0].root_node_id:
        # A review document may temporarily retain its business branch while
        # the effective package is the deterministic semantic fallback. Bind
        # that single branch to the package's final typed output instead of
        # publishing a dangling branch reference. Multiple branches are never
        # guessed because their independent meanings cannot be reconstructed
        # from one aggregate output.
        fallback_node = next(
            (
                output_bindings[name]
                for name in ("condition", "events", "objects", "tracks")
                if name in output_bindings
            ),
            None,
        )
        publish(f"branch:{branches[0].branch_id}", fallback_node)

    # EventPattern and FinalDecision nodes are produced after the editable
    # RuleGraph has been lowered, so their stable aliases must be recovered
    # from deterministic output names.
    for pattern in document.skill_template.event_patterns:
        if pattern.media_type != media_type:
            continue
        prefix = f"event_{pattern.pattern_id}"
        candidates = sorted(
            name
            for name in output_bindings
            if name == prefix or name.startswith(prefix + "_")
        )
        if candidates:
            preferred = prefix if prefix in candidates else candidates[0]
            publish(f"event:{pattern.pattern_id}", output_bindings[preferred])
    decision = document.skill_template.final_decision
    if decision is not None:
        safe = "".join(
            character
            if character.isalnum() or character in "_-"
            else "_"
            for character in decision.decision_id
        )
        if not safe or not safe[0].isalpha():
            safe = "decision_" + safe
        output_name = f"final_{safe}"[:180]
        publish(f"final:{decision.decision_id}", output_bindings.get(output_name))

    # A ResultSpec may deliberately project a different typed node than its
    # canonical business source (for example, the measurement behind a count
    # comparison).  Publish that exact node under result:<id>; do not replace
    # condition:/branch: because those aliases must keep their boolean meaning.
    result_specs = [
        spec
        for spec in document.skill_template.result_specs
        if not spec.media_types or media_type in spec.media_types
    ]
    for spec in result_specs:
        result_node_id = None
        # ``final:<id>`` names the final business verdict.  A result declared
        # as events/timeline instead needs the event emitted by that verdict.
        # Prefer the alert output whenever a trigger is configured, while
        # retaining the final output as the fallback for event-native finals
        # that deliberately have no trigger.  This is type-driven and applies
        # to every generated or manually edited business rule.
        if (
            spec.source_ref
            and spec.source_ref.startswith("final:")
            and requires_event_value(spec)
        ):
            decision_id = spec.source_ref.split(":", 1)[1]
            result_node_id = output_bindings.get(
                final_output_name("alert", decision_id)
            )
        if result_node_id is None:
            result_node_id = next(
                (
                    output_bindings[name]
                    for name in spec.required_outputs
                    if name in output_bindings
                ),
                None,
            )
        if result_node_id is None and spec.source_ref:
            result_node_id = published_sources.get(spec.source_ref)
        if result_node_id is None and spec.source_ref and spec.source_ref.startswith("node:"):
            result_node_id = spec.source_ref.split(":", 1)[1]
        if result_node_id is None and len(branches) == 1:
            fallback_outputs = {
                "entities": ("objects",),
                "tracks": ("tracks",),
                "events": ("events",),
                "duration": ("events",),
                "stages": ("events",),
                "media": ("media",),
                "count": ("measurements", "objects", "tracks", "events"),
                "value": ("measurements", "condition"),
                "status": ("condition", "events", "objects", "tracks"),
                "identity": (
                    "condition", "events", "objects", "tracks", "measurements"
                ),
            }.get(spec.projection.kind, ())
            result_node_id = next(
                (
                    output_bindings[name]
                    for name in fallback_outputs
                    if name in output_bindings
                ),
                None,
            )
        publish(f"result:{spec.result_id}", result_node_id)
    return {
        "schema_version": "1.0",
        "media_type": media_type,
        "published_sources": published_sources,
        "output_bindings": output_bindings,
        "result_specs": [item.model_dump(mode="json") for item in result_specs],
        "presentation_specs": [
            item.model_dump(mode="json")
            for item in document.skill_template.presentation_specs
        ],
        "final_decision": (
            document.skill_template.final_decision.model_copy(
                update={
                    "source_ref": (
                        document.skill_template.final_decision.media_source_refs.get(
                            media_type,
                            document.skill_template.final_decision.source_refs,
                        )[0]
                    ),
                    "source_refs": document.skill_template.final_decision.media_source_refs.get(
                        media_type,
                        document.skill_template.final_decision.source_refs,
                    ),
                }
            ).model_dump(mode="json")
            if document.skill_template.final_decision
            else None
        ),
        "branches": [item.model_dump(mode="json") for item in branches],
        "scene_profile": next(
            (
                item.model_dump(mode="json")
                for item in document.scene_profiles
                if item.scene_profile_id == document.active_scene_profile_id
            ),
            None,
        ),
        "hashes": document.hashes.model_dump(mode="json"),
    }


def _items(value: Any) -> list[Any]:
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return list(value["items"])
    if isinstance(value, list):
        return list(value)
    return []


def _latest_value(value: Any) -> Any:
    items = _items(value)
    if not items:
        return value
    latest = max(
        items,
        key=lambda item: (
            item.get("timestamp", 0) if isinstance(item, dict) else 0
        ),
    )
    return latest.get("value") if isinstance(latest, dict) and "value" in latest else latest


def _project_value(spec: ResultSpec, source: RuntimeValueEnvelope) -> Any:
    raw = deepcopy(source.value)
    kind = spec.projection.kind
    if kind == "identity":
        value = raw
    elif kind == "count":
        items = _items(raw)
        if items:
            value = len(items)
        else:
            latest = _latest_value(raw)
            value = latest if isinstance(latest, (int, float)) else 0
    elif kind == "value":
        value = _latest_value(raw)
    elif kind == "status":
        if source.value_type == "event_set":
            value = bool(_items(raw))
        else:
            value = bool(_latest_value(raw))
    elif kind in {"entities", "tracks", "events", "stages"}:
        value = _items(raw)
    elif kind == "duration":
        events = _items(raw)
        durations = [
            float(item["end_time"]) - float(item["start_time"])
            for item in events
            if isinstance(item, dict)
            and item.get("start_time") is not None
            and item.get("end_time") is not None
        ]
        value = max(durations, default=0.0)
    elif kind in {"resource", "media"}:
        value = raw
    else:
        value = raw
    if isinstance(value, list) and spec.semantic_type in {
        "entity_set",
        "track_set",
        "event_set",
    }:
        updated = []
        for item in value:
            if not isinstance(item, dict):
                updated.append(item)
                continue
            projected = dict(item)
            if spec.label_policy.preserve_model_label:
                projected.setdefault(
                    "model_label",
                    projected.get("phrase") or projected.get("label"),
                )
            business_label = (
                spec.label_policy.business_label or projected.get("label")
            )
            if business_label:
                projected["business_label"] = business_label
            updated.append(projected)
        value = updated
    return value


def projection_accepts_type(spec: ResultSpec, value_type: str) -> bool:
    """Shared compatibility contract for the output editor and runtime."""
    accepted = (
        _IDENTITY_SOURCE_TYPES.get(spec.semantic_type, set())
        if spec.projection.kind == "identity"
        else _PROJECTION_SOURCE_TYPES.get(spec.projection.kind, set())
    )
    return value_type in accepted


def _source_is_compatible(spec: ResultSpec, source: RuntimeValueEnvelope) -> bool:
    return projection_accepts_type(spec, source.value_type)


def _result_status(
    spec: ResultSpec, source: RuntimeValueEnvelope, value: Any
) -> tuple[str, str]:
    if source.status in {"pending", "not_evaluable", "error"}:
        return source.status, f"来源状态为 {source.status}"
    empty = value in (None, [], {}) or value is False
    if empty:
        if spec.empty_policy == "not_evaluable":
            return "not_evaluable", "当前运行没有足够信息生成该结果"
        if spec.empty_policy == "not_satisfied" or spec.semantic_type in {
            "decision",
            "boolean",
            "event_set",
        }:
            return "not_satisfied", "未发现满足条件的结果"
    return "satisfied", "结果已计算"


def _source_lookup(
    envelopes: list[RuntimeValueEnvelope],
) -> dict[str, list[RuntimeValueEnvelope]]:
    result: dict[str, list[RuntimeValueEnvelope]] = {}
    for envelope in envelopes:
        result.setdefault(envelope.business_source_ref, []).append(envelope)
        if envelope.source_node_id:
            result.setdefault(f"node:{envelope.source_node_id}", []).append(envelope)
    return result


def _choose_source(
    lookup: dict[str, list[RuntimeValueEnvelope]], source_ref: str | None
) -> RuntimeValueEnvelope | None:
    if not source_ref:
        return None
    candidates = lookup.get(source_ref, [])
    return candidates[0] if candidates else None


def _condition_matches(value: Any, condition: dict[str, Any]) -> bool:
    if not condition:
        return bool(value)
    comparator = _COMPARATORS.get(str(condition.get("operator")))
    if comparator is None:
        return bool(value)
    return bool(comparator(value, condition.get("value")))


def _runtime_truth(
    source: RuntimeValueEnvelope,
    decision: FinalDecisionSpec,
) -> bool:
    value = source.value
    if decision.decision_type == "measurement_decision" and decision.success_condition:
        return _condition_matches(_latest_value(value), decision.success_condition)
    if source.value_type in {"entity_set", "track_set", "event_set"}:
        return bool(_items(value))
    return bool(_latest_value(value))


def _output_truth(
    source: BusinessOutputValue,
    decision: FinalDecisionSpec,
) -> bool:
    if source.status == "not_satisfied":
        return False
    if decision.decision_type == "measurement_decision" and decision.success_condition:
        return _condition_matches(source.value, decision.success_condition)
    if source.semantic_type in {"entity_set", "track_set", "event_set", "timeline"}:
        return bool(_items(source.value) or source.value)
    return bool(source.value)


def _unresolved_status(statuses: list[str]) -> str:
    if "error" in statuses:
        return "error"
    if "pending" in statuses:
        return "pending"
    return "not_evaluable"


def _final_result(
    decision: FinalDecisionSpec | None,
    outputs: list[BusinessOutputValue],
    lookup: dict[str, list[RuntimeValueEnvelope]],
    branches: list[BranchResult],
) -> FinalResult:
    by_ref = {f"result:{item.result_id}": item for item in outputs}
    if decision is None:
        return FinalResult(
            decision_id="primary",
            display_name="最终结果",
            decision_type="detection_summary",
            status="not_evaluable",
            reason="技能尚未配置唯一最终判定",
            source_ref="result:unconfigured",
        )
    branch_names = {
        f"branch:{item.branch_id}": item.display_name for item in branches
    }
    evaluations: list[dict[str, Any]] = []
    for source_ref in decision.source_refs:
        output = by_ref.get(source_ref)
        envelope = None if output is not None else _choose_source(lookup, source_ref)
        if output is None and envelope is None:
            evaluations.append(
                {
                    "source_ref": source_ref,
                    "name": branch_names.get(source_ref, source_ref),
                    "status": "not_evaluable",
                    "matched": None,
                    "value": None,
                    "reason": "运行结果缺少该来源",
                    "source_value_refs": [],
                    "evidence_refs": [],
                }
            )
            continue
        if output is not None:
            status = output.status
            matched = (
                _output_truth(output, decision)
                if status in {"satisfied", "not_satisfied"}
                else None
            )
            evaluations.append(
                {
                    "source_ref": source_ref,
                    "name": output.display_name,
                    "status": status,
                    "matched": matched,
                    "value": output.value,
                    "reason": output.reason,
                    "source_value_refs": list(output.source_value_refs),
                    "evidence_refs": list(output.evidence_refs),
                }
            )
            continue
        assert envelope is not None
        status = envelope.status
        matched = (
            _runtime_truth(envelope, decision)
            if status in {"available", "satisfied", "not_satisfied"}
            else None
        )
        if status == "not_satisfied":
            matched = False
        evaluations.append(
            {
                "source_ref": source_ref,
                "name": branch_names.get(source_ref, source_ref),
                "status": status,
                "matched": matched,
                "value": envelope.value,
                "reason": None,
                "source_value_refs": [envelope.value_id],
                "evidence_refs": list(envelope.evidence_refs),
            }
        )

    failed = [item for item in evaluations if item["matched"] is False]
    matched = [item for item in evaluations if item["matched"] is True]
    unresolved = [item for item in evaluations if item["matched"] is None]
    error_sources = [item for item in unresolved if item["status"] == "error"]
    if error_sources:
        status = "error"
    elif decision.combination == "AND":
        status = (
            "not_satisfied"
            if failed
            else _unresolved_status([item["status"] for item in unresolved])
            if unresolved
            else "satisfied"
        )
    elif decision.combination == "OR":
        status = (
            "satisfied"
            if matched
            else _unresolved_status([item["status"] for item in unresolved])
            if unresolved
            else "not_satisfied"
        )
    else:
        required = decision.required_count or 1
        if len(matched) >= required:
            status = "satisfied"
        elif len(matched) + len(unresolved) < required:
            status = "not_satisfied"
        else:
            status = _unresolved_status([item["status"] for item in unresolved])

    names = lambda values: "、".join(str(item["name"]) for item in values)
    if status == "satisfied":
        if len(evaluations) == 1 and decision.decision_type == "measurement_decision":
            reason = "实际值满足要求"
        elif len(evaluations) == 1 and decision.decision_type == "event_decision":
            reason = "事件已发生"
        elif decision.combination == "AND":
            reason = f"全部 {len(evaluations)} 个来源均满足"
        elif decision.combination == "OR":
            reason = f"已有来源满足：{names(matched)}"
        else:
            reason = f"已有 {len(matched)} 个来源满足，达到要求 {decision.required_count} 个"
    elif status == "not_satisfied":
        if len(evaluations) == 1 and decision.decision_type == "measurement_decision":
            reason = "实际值未满足要求"
        elif len(evaluations) == 1 and decision.decision_type == "event_decision":
            reason = "事件未发生"
        else:
            reason = "未满足：" + names(failed or evaluations)
    elif status == "pending":
        reason = "仍在等待：" + names(unresolved)
    elif status == "error":
        reason = "来源执行错误：" + names(error_sources)
    else:
        reason = "无法判断：" + names(unresolved or evaluations)

    source_value_refs = list(
        dict.fromkeys(
            ref
            for item in evaluations
            for ref in item["source_value_refs"]
        )
    )
    evidence_refs = list(
        dict.fromkeys(
            ref for item in evaluations for ref in item["evidence_refs"]
        )
    )
    final_value: Any
    if len(evaluations) == 1:
        final_value = evaluations[0]["value"]
    else:
        final_value = {
            "matched": status == "satisfied",
            "combination": decision.combination,
            "required_count": decision.required_count,
            "sources": [
                {
                    "source_ref": item["source_ref"],
                    "status": item["status"],
                    "matched": item["matched"],
                    "value": item["value"],
                }
                for item in evaluations
            ],
        }
    return FinalResult(
        decision_id=decision.decision_id,
        display_name=decision.display_name,
        decision_type=decision.decision_type,
        status=status,
        value=final_value,
        reason=reason,
        source_ref=decision.source_ref,
        source_value_refs=source_value_refs,
        evidence_refs=evidence_refs,
    )


def project_run_result(
    *,
    run_id: str,
    media_asset_id: str | None,
    media_type: str,
    result_specs: list[ResultSpec],
    final_decision: FinalDecisionSpec | None,
    branches: list[BusinessBranch],
    envelopes: list[RuntimeValueEnvelope],
    hashes: dict[str, str | None] | None = None,
) -> RunResult:
    lookup = _source_lookup(envelopes)
    business_outputs: list[BusinessOutputValue] = []
    derived_envelopes = list(envelopes)
    for spec in result_specs:
        source = _choose_source(lookup, f"result:{spec.result_id}") or _choose_source(
            lookup, spec.source_ref
        )
        if source is None:
            output = BusinessOutputValue(
                result_id=spec.result_id,
                display_name=spec.display_name,
                semantic_type=spec.semantic_type,
                value_shape=spec.value_shape,
                status="not_evaluable",
                reason=f"找不到结果来源：{spec.source_ref or '未配置'}",
                source_ref=spec.source_ref or "node:unconfigured",
            )
            business_outputs.append(output)
            continue
        if not _source_is_compatible(spec, source):
            business_outputs.append(
                BusinessOutputValue(
                    result_id=spec.result_id,
                    display_name=spec.display_name,
                    semantic_type=spec.semantic_type,
                    value_shape=spec.value_shape,
                    status="not_evaluable",
                    reason=(
                        "结果来源的实际内容类型与已配置的业务结果类型不兼容"
                    ),
                    source_ref=spec.source_ref or source.business_source_ref,
                    source_value_refs=[source.value_id],
                    evidence_refs=list(source.evidence_refs),
                )
            )
            continue
        value = _project_value(spec, source)
        status, reason = _result_status(spec, source, value)
        if (
            status == "satisfied"
            and spec.evidence_policy == "required"
            and value not in (None, False, [], {})
            and not source.evidence_refs
        ):
            status = "not_evaluable"
            reason = "结果已计算，但缺少该结果要求保存的证据"
        output = BusinessOutputValue(
            result_id=spec.result_id,
            display_name=spec.display_name,
            semantic_type=spec.semantic_type,
            value_shape=spec.value_shape,
            status=status,
            value=value,
            unit=spec.unit,
            reason=reason,
            source_ref=spec.source_ref or source.business_source_ref,
            source_value_refs=[source.value_id],
            evidence_refs=list(source.evidence_refs),
            condition_snapshot={
                "projection": spec.projection.model_dump(mode="json"),
                "empty_policy": spec.empty_policy,
            }
            if spec.condition_snapshot_policy != "none"
            else {},
        )
        business_outputs.append(output)
        derived_envelopes.append(
            RuntimeValueEnvelope(
                value_id=f"{source.value_id}_{spec.result_id}",
                run_id=run_id,
                source_node_id=source.source_node_id,
                business_source_ref=f"result:{spec.result_id}",
                result_spec_id=spec.result_id,
                value_type=spec.semantic_type,
                value_shape=spec.value_shape,
                value=value,
                unit=spec.unit,
                status=status,
                applicability=source.applicability,
                identity_key=source.identity_key,
                time_scope=source.time_scope,
                entity_refs=source.entity_refs,
                resource_refs=source.resource_refs,
                evidence_refs=source.evidence_refs,
                diagnostics_ref=source.diagnostics_ref,
            )
        )
    lookup = _source_lookup(derived_envelopes)
    branch_results: list[BranchResult] = []
    for branch in branches:
        source_ref = f"branch:{branch.branch_id}"
        source = _choose_source(lookup, source_ref)
        if source is None:
            branch_results.append(
                BranchResult(
                    branch_id=branch.branch_id,
                    display_name=branch.display_name,
                    status="not_evaluable",
                    reason="运行结果中缺少该分支的稳定来源",
                    source_ref=source_ref,
                )
            )
            continue
        value = source.value
        if source.status in {"pending", "not_evaluable", "error"}:
            branch_status = source.status
            matched = None
        else:
            matched = _runtime_truth(
                source,
                FinalDecisionSpec(
                    decision_type="event_decision",
                    source_ref=source_ref,
                ),
            )
            branch_status = "satisfied" if matched else "not_satisfied"
        branch_results.append(
            BranchResult(
                branch_id=branch.branch_id,
                display_name=branch.display_name,
                status=branch_status,
                value=value,
                reason=(
                    "分支条件成立"
                    if matched is True
                    else "分支条件未成立"
                    if matched is False
                    else f"分支来源状态为 {source.status}"
                ),
                source_ref=source_ref,
                source_value_refs=[source.value_id],
                evidence_refs=source.evidence_refs,
            )
        )
    final = _final_result(final_decision, business_outputs, lookup, branch_results)
    status = (
        "error"
        if final.status == "error"
        else "pending"
        if final.status == "pending"
        else "not_evaluable"
        if final.status == "not_evaluable"
        else "completed"
    )
    hashes = hashes or {}
    return RunResult(
        run_id=run_id,
        media_asset_id=media_asset_id,
        media_type=media_type,  # type: ignore[arg-type]
        variant=media_type,  # type: ignore[arg-type]
        status=status,
        final_result=final,
        business_outputs=business_outputs,
        branch_results=branch_results,
        runtime_values=derived_envelopes,
        semantic_hash=hashes.get("semantic_hash"),
        compile_hash=hashes.get("compile_hash"),
        package_hash=hashes.get("package_hash"),
        presentation_hash=hashes.get("presentation_hash"),
    )


__all__ = ["build_runtime_contract", "project_run_result"]
