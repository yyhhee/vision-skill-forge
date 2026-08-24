from __future__ import annotations

from copy import deepcopy

from .editor_schema import EventPattern, ResolvableValue
from .registry import OperatorRegistry


class EventPatternCompileError(ValueError):
    pass


def _value(item: ResolvableValue, path: str):
    if item.state == "not_applicable":
        return None
    if item.state == "unresolved":
        if item.recommended_value is None:
            raise EventPatternCompileError(f"{path} is unresolved")
        return item.recommended_value
    return item.value


def compile_event_patterns(
    nodes: list[dict],
    outputs: dict[str, str],
    patterns: list[EventPattern],
    registry: OperatorRegistry,
    business_sources: dict[str, str] | None = None,
):
    compiled_nodes = deepcopy(nodes)
    compiled_outputs = dict(outputs)
    output_types = {
        node["id"]: registry.require(node["op"]).output_type for node in compiled_nodes
    }
    business_sources = business_sources or {}

    for pattern in patterns:
        stage_refs = {}
        for stage in pattern.stages:
            source_id = business_sources.get(
                stage.source_ref or "", stage.source_rule_id
            )
            source_type = output_types.get(source_id)
            if source_type not in {"ConditionSet", "EventSet"}:
                raise EventPatternCompileError(
                    f"pattern {pattern.pattern_id} stage {stage.stage_id}: "
                    f"source must output ConditionSet or EventSet"
                )
            duration = float(_value(stage.duration, f"stage {stage.stage_id}.duration") or 0)
            stage_node_id = f"pattern_{pattern.pattern_id}_{stage.stage_id}"
            if source_type == "ConditionSet":
                compiled_nodes.append(
                    {
                        "id": stage_node_id,
                        "op": "temporal.qualify@1.0",
                        "inputs": {"condition": f"${source_id}"},
                        "params": {
                            "mode": stage.persist_mode,
                            "duration_seconds": duration,
                            "allowed_gap_seconds": stage.allowed_gap_seconds,
                            "window_seconds": _value(
                                stage.observation_window_seconds,
                                f"stage {stage.stage_id}.observation_window",
                            ),
                            "required_ratio": stage.required_ratio,
                            "trigger_mode": "once",
                        },
                    }
                )
                output_types[stage_node_id] = "EventSet"
                stage_refs[stage.stage_id] = f"${stage_node_id}"
            elif duration > 0:
                compiled_nodes.append(
                    {
                        "id": stage_node_id,
                        "op": "temporal.event_duration@1.0",
                        "inputs": {"events": f"${source_id}"},
                        "params": {
                            "minimum_seconds": duration,
                            "label": stage.display_name,
                        },
                    }
                )
                output_types[stage_node_id] = "EventSet"
                stage_refs[stage.stage_id] = f"${stage_node_id}"
            else:
                stage_refs[stage.stage_id] = f"${source_id}"

        final_refs = []
        if pattern.pattern_type == "absence":
            if len(pattern.stages) != 2:
                raise EventPatternCompileError(
                    f"pattern {pattern.pattern_id}: absence requires anchor and forbidden stages"
                )
            node_id = f"pattern_{pattern.pattern_id}_absence"
            window = float(pattern.parameters.get("window_seconds") or 0.0)
            compiled_nodes.append(
                {
                    "id": node_id,
                    "op": "temporal.absence@1.0",
                    "inputs": {
                        "anchors": stage_refs[pattern.stages[0].stage_id],
                        "forbidden": stage_refs[pattern.stages[1].stage_id],
                    },
                    "params": {
                        "before_seconds": float(
                            pattern.parameters.get("before_seconds") or 0.0
                        ),
                        "after_seconds": float(
                            pattern.parameters.get("after_seconds")
                            if pattern.parameters.get("after_seconds") is not None
                            else window
                        ),
                        "same_key": pattern.correlation.scope != "global",
                        "label": pattern.display_name,
                    },
                }
            )
            output_types[node_id] = "EventSet"
            final_refs.append(f"${node_id}")
        elif pattern.pattern_type == "repeat":
            if len(pattern.stages) != 1:
                raise EventPatternCompileError(
                    f"pattern {pattern.pattern_id}: repeat requires exactly one stage"
                )
            node_id = f"pattern_{pattern.pattern_id}_repeat"
            compiled_nodes.append(
                {
                    "id": node_id,
                    "op": "temporal.repeat@1.0",
                    "inputs": {
                        "events": stage_refs[pattern.stages[0].stage_id]
                    },
                    "params": {
                        "window_seconds": float(
                            pattern.parameters.get("window_seconds") or 0.0
                        ),
                        "minimum_count": int(
                            pattern.parameters.get("minimum_count") or 2
                        ),
                        "same_key": pattern.correlation.scope != "global",
                        "label": pattern.display_name,
                    },
                }
            )
            output_types[node_id] = "EventSet"
            final_refs.append(f"${node_id}")
        if pattern.pattern_type not in {"absence", "repeat"} and pattern.transitions:
            transitions = []
            ordered_stage_ids = [pattern.stages[0].stage_id]
            current = ordered_stage_ids[0]
            remaining = list(pattern.transitions)
            while remaining:
                transition = next(
                    (item for item in remaining if item.source_stage_id == current), None
                )
                if transition is None:
                    raise EventPatternCompileError(
                        f"pattern {pattern.pattern_id}: transitions do not form one ordered path"
                    )
                transitions.append(
                    {
                        "relation": transition.relation,
                        "source_anchor": transition.source_anchor,
                        "target_anchor": transition.target_anchor,
                        "minimum_delay_seconds": transition.minimum_delay_seconds,
                        "maximum_delay_seconds": _value(
                            transition.maximum_delay_seconds,
                            f"transition {transition.source_stage_id}->{transition.target_stage_id}",
                        ),
                        "timeout_behavior": transition.timeout_behavior,
                    }
                )
                current = transition.target_stage_id
                ordered_stage_ids.append(current)
                remaining.remove(transition)
            node_id = f"pattern_{pattern.pattern_id}_sequence"
            compiled_nodes.append(
                {
                    "id": node_id,
                    "op": "temporal.sequence@2.0",
                    "inputs": {"events": [stage_refs[item] for item in ordered_stage_ids]},
                    "params": {
                        "transitions": transitions,
                        "correlation_scope": pattern.correlation.scope,
                        "correlation_fields": pattern.correlation.fields,
                        "consume_events": pattern.instance_policy.consume_events,
                        "label": pattern.display_name,
                    },
                }
            )
            output_types[node_id] = "EventSet"
            final_refs.append(f"${node_id}")

        for gateway in (
            pattern.gateways
            if pattern.pattern_type not in {"absence", "repeat"}
            else []
        ):
            node_id = f"pattern_{pattern.pattern_id}_{gateway.gateway_id}"
            compiled_nodes.append(
                {
                    "id": node_id,
                    "op": "temporal.join@1.0",
                    "inputs": {"events": [stage_refs[item] for item in gateway.stage_ids]},
                    "params": {
                        "mode": gateway.mode,
                        "required_count": gateway.required_count,
                        "window_seconds": _value(
                            gateway.window_seconds, f"gateway {gateway.gateway_id}.window"
                        ),
                        "correlation_scope": pattern.correlation.scope,
                        "correlation_fields": pattern.correlation.fields,
                        "maximum_matches": int(
                            pattern.trigger_policy.get("maximum_matches", 1000)
                        ),
                        "label": pattern.display_name,
                    },
                }
            )
            output_types[node_id] = "EventSet"
            final_refs.append(f"${node_id}")

        if not final_refs:
            if len(stage_refs) != 1:
                raise EventPatternCompileError(
                    f"pattern {pattern.pattern_id}: multiple stages require a gateway or transitions"
                )
            final_refs = [next(iter(stage_refs.values()))]
        trigger = pattern.trigger_policy
        if trigger:
            triggered_refs = []
            for index, ref in enumerate(final_refs, start=1):
                node_id = f"pattern_{pattern.pattern_id}_trigger_{index}"
                compiled_nodes.append({
                    "id": node_id,
                    "op": "event.trigger@2.0",
                    "inputs": {"events": ref},
                    "params": {
                        "repeat_policy": trigger.get("repeat_policy", "allow_repeat"),
                        "cooldown_seconds": trigger.get("cooldown_seconds", 0.0),
                        "cooldown_scope": trigger.get("cooldown_scope", "entity"),
                        "severity": trigger.get("severity", "medium"),
                        "notification_enabled": trigger.get("notification_enabled", False),
                        "label": trigger.get("label", pattern.display_name),
                    },
                })
                output_types[node_id] = "EventSet"
                triggered_refs.append(f"${node_id}")
            final_refs = triggered_refs
        for index, ref in enumerate(final_refs, start=1):
            suffix = "" if len(final_refs) == 1 else f"_{index}"
            compiled_outputs[f"event_{pattern.pattern_id}{suffix}"] = ref

    return compiled_nodes, compiled_outputs


__all__ = ["EventPatternCompileError", "compile_event_patterns"]
