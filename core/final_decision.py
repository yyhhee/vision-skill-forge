from __future__ import annotations

from copy import deepcopy
from typing import Any

from .editor_schema import FinalDecisionSpec, ResultSpec, TriggerPolicy
from .registry import OperatorRegistry


class FinalDecisionCompileError(ValueError):
    """Raised when the user-facing final decision has no executable meaning."""


def _node_id(prefix: str, value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in value)
    if not safe or not safe[0].isalpha():
        safe = "decision_" + safe
    return f"{prefix}_{safe}"[:180]


def compile_final_decision(
    nodes: list[dict[str, Any]],
    outputs: dict[str, str],
    decision: FinalDecisionSpec | None,
    result_specs: list[ResultSpec],
    registry: OperatorRegistry,
    *,
    media_type: str | None = None,
    business_sources: dict[str, str] | None = None,
    trigger_policy: TriggerPolicy | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Compile one semantic final decision after complex-event compilation.

    ResultSpec describes what a value means. This function only compiles the
    decision algebra and publishes one stable output; rendering is deliberately
    outside this layer.
    """

    if decision is None:
        return nodes, outputs

    compiled_nodes = deepcopy(nodes)
    compiled_outputs = dict(outputs)
    source_nodes = dict(business_sources or {})
    node_types = {
        item["id"]: registry.require(item["op"]).output_type
        for item in compiled_nodes
    }
    specs = {item.result_id: item for item in result_specs}
    resolving: set[str] = set()

    def output_node(reference: str) -> str | None:
        value = compiled_outputs.get(reference)
        if not value:
            return None
        return value[1:] if value.startswith("$") else value

    def resolve(reference: str) -> str:
        if reference in resolving:
            raise FinalDecisionCompileError(
                f"最终判定来源形成循环引用：{reference}"
            )
        resolving.add(reference)
        try:
            prefix, key = reference.split(":", 1)
            node_id: str | None = None
            if prefix in {"branch", "condition", "measurement"}:
                node_id = source_nodes.get(reference)
            elif prefix == "node":
                node_id = key
            elif prefix == "output":
                node_id = output_node(key)
            elif prefix == "event":
                node_id = output_node(f"event_{key}")
            elif prefix == "result":
                spec = specs.get(key)
                if spec is None:
                    raise FinalDecisionCompileError(
                        f"最终判定引用了不存在的业务输出：{key}"
                    )
                decisionable = {"decision", "boolean", "event_set"}
                if decision.decision_type in {"detection_summary", "state_summary"}:
                    decisionable.update({"entity_set", "track_set"})
                if spec.semantic_type not in decisionable:
                    raise FinalDecisionCompileError(
                        f"业务输出“{spec.display_name}”不是可判定结果；请先增加比较条件。"
                    )
                if spec.source_ref:
                    node_id = resolve(spec.source_ref)
                if node_id is None:
                    node_id = next(
                        (
                            output_node(name)
                            for name in spec.required_outputs
                            if output_node(name) is not None
                        ),
                        None,
                    )
            if node_id is None or node_id not in node_types:
                raise FinalDecisionCompileError(
                    f"最终判定来源尚未产生可执行结果：{reference}"
                )
            return node_id
        finally:
            resolving.discard(reference)

    selected_source_refs = (
        decision.media_source_refs.get(media_type, decision.source_refs)
        if media_type is not None
        else decision.source_refs
    )
    source_ids = list(dict.fromkeys(resolve(item) for item in selected_source_refs))
    if not source_ids:
        raise FinalDecisionCompileError("最终判定至少需要一个来源。")
    final_id = _node_id("final", decision.decision_id)

    # “是否检测到目标” is a real business decision, not a renderer shortcut.
    # Compile entity/track collections to an explicit count > 0 condition so
    # the runtime final value stays boolean and remains traceable to the source.
    normalized_source_ids: list[str] = []
    for index, source_id in enumerate(source_ids, start=1):
        source_type = node_types[source_id]
        if source_type not in {"ObjectSet", "EntitySet", "TrackSet"}:
            normalized_source_ids.append(source_id)
            continue
        count_id = _node_id(final_id, f"source_{index}_count")
        compare_id = _node_id(final_id, f"source_{index}_present")
        compiled_nodes.extend([
            {
                "id": count_id,
                "op": "measure.count@1.0",
                "inputs": {"entities": f"${source_id}"},
                "params": {
                    "scope": "unique" if source_type == "TrackSet" else "frame",
                    "group_by": "none",
                },
            },
            {
                "id": compare_id,
                "op": "logic.compare@1.0",
                "inputs": {"left": f"${count_id}"},
                "params": {"operator": ">", "value": 0},
            },
        ])
        node_types[count_id] = "ScalarSet"
        node_types[compare_id] = "ConditionSet"
        normalized_source_ids.append(compare_id)
    source_ids = normalized_source_ids

    if len(source_ids) == 1:
        final_ref = f"${source_ids[0]}"
    else:
        source_types = [node_types[item] for item in source_ids]
        if all(item == "ConditionSet" for item in source_types):
            if decision.combination == "AND":
                operator = "logic.all@1.0"
                params = {"combine_scope": "frame_any"}
            elif decision.combination == "OR":
                operator = "logic.any@1.0"
                params = {"combine_scope": "frame_any"}
            else:
                operator = "reduce.quantify@1.0"
                params = {
                    "mode": "n_of_m",
                    "required_count": decision.required_count,
                }
            compiled_nodes.append(
                {
                    "id": final_id,
                    "op": operator,
                    "inputs": {
                        "conditions": [f"${item}" for item in source_ids]
                    },
                    "params": params,
                }
            )
            node_types[final_id] = "ConditionSet"
            final_ref = f"${final_id}"
        else:
            event_ids: list[str] = []
            for index, (source_id, source_type) in enumerate(
                zip(source_ids, source_types), start=1
            ):
                if source_type == "EventSet":
                    event_ids.append(source_id)
                    continue
                if source_type != "ConditionSet":
                    raise FinalDecisionCompileError(
                        "最终判定只能组合条件、事件或布尔业务输出；"
                        "数量和数值必须先经过比较。"
                    )
                event_id = _node_id(final_id, f"source_{index}")
                compiled_nodes.append(
                    {
                        "id": event_id,
                        "op": "temporal.qualify@1.0",
                        "inputs": {"condition": f"${source_id}"},
                        "params": {
                            "mode": "immediate",
                            "duration_seconds": 0.0,
                            "allowed_gap_seconds": 0.0,
                            "window_seconds": None,
                            "required_ratio": 1.0,
                            "trigger_mode": "once",
                        },
                    }
                )
                node_types[event_id] = "EventSet"
                event_ids.append(event_id)
            compiled_nodes.append(
                {
                    "id": final_id,
                    "op": "temporal.join@1.0",
                    "inputs": {"events": [f"${item}" for item in event_ids]},
                    "params": {
                        "mode": {
                            "AND": "all_active",
                            "OR": "any",
                            "N_OF_M": "n_of_m",
                        }[decision.combination],
                        "required_count": (
                            decision.required_count
                            if decision.combination == "N_OF_M"
                            else None
                        ),
                        "window_seconds": None,
                        "correlation_scope": "global",
                        "correlation_fields": [],
                        "maximum_matches": 1000,
                        "label": decision.display_name,
                    },
                }
            )
            node_types[final_id] = "EventSet"
            final_ref = f"${final_id}"

    compiled_outputs[final_id] = final_ref
    if trigger_policy is not None and trigger_policy.mode != "none":
        source_id = final_ref[1:] if final_ref.startswith("$") else final_ref
        source_type = node_types[source_id]
        if source_type == "ConditionSet":
            event_id = _node_id(final_id, "event")
            compiled_nodes.append(
                {
                    "id": event_id,
                    "op": "event.from_condition@1.0",
                    "inputs": {"condition": final_ref},
                    "params": {
                        "seconds": 0.0,
                        "scope": "global",
                        "gap_tolerance_seconds": 0.0,
                        "trigger_mode": (
                            "repeat"
                            if trigger_policy.mode == "repeat"
                            else "once"
                        ),
                        "label": decision.display_name,
                    },
                }
            )
            node_types[event_id] = "EventSet"
            event_ref = f"${event_id}"
        elif source_type == "EventSet":
            event_ref = final_ref
        else:
            raise FinalDecisionCompileError(
                "触发策略需要布尔条件或事件作为最终判定来源。"
            )
        trigger_id = _node_id("trigger", decision.decision_id)
        compiled_nodes.append(
            {
                "id": trigger_id,
                "op": "event.trigger@2.0",
                "inputs": {"events": event_ref},
                "params": {
                    "repeat_policy": (
                        "allow_repeat"
                        if trigger_policy.repeat_policy in {"allow_repeat", "after_reset"}
                        else "first_only"
                    ),
                    "cooldown_seconds": trigger_policy.cooldown_seconds,
                    "cooldown_scope": (
                        "global"
                        if trigger_policy.cooldown_scope == "global"
                        else "entity"
                    ),
                    "severity": (
                        "low"
                        if trigger_policy.severity == "info"
                        else trigger_policy.severity
                    ),
                    "notification_enabled": (
                        "notification" in trigger_policy.outputs
                    ),
                    "label": decision.display_name,
                },
            }
        )
        compiled_outputs[_node_id("alert", decision.decision_id)] = (
            f"${trigger_id}"
        )
    return compiled_nodes, compiled_outputs


__all__ = ["FinalDecisionCompileError", "compile_final_decision"]
