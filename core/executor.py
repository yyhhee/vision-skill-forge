from __future__ import annotations

import time
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .context import ExecutionResult, ExecutionServices, TraceEntry, summarize
from .registry import OperatorRegistry
from .schema import VisualSkillSpec
from .validator import assert_valid_skill


Implementation = Callable[[dict[str, Any], dict[str, Any], ExecutionServices, str], Any]


def _refs(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else value


def _topological_nodes(spec: VisualSkillSpec):
    nodes = {node.id: node for node in spec.nodes if node.enabled}
    deps = {node_id: set() for node_id in nodes}
    reverse = {node_id: set() for node_id in nodes}
    for node_id, node in nodes.items():
        for value in node.inputs.values():
            for ref in _refs(value):
                ref_id = ref[1:]
                if ref_id != "input":
                    deps[node_id].add(ref_id)
                    reverse[ref_id].add(node_id)
    queue = deque(node.id for node in spec.nodes if node.enabled and not deps[node.id])
    ordered = []
    while queue:
        node_id = queue.popleft()
        ordered.append(nodes[node_id])
        for dependent in reverse[node_id]:
            deps[dependent].remove(node_id)
            if not deps[dependent]:
                queue.append(dependent)
    return ordered


class ExecutionEngine:
    def __init__(
        self,
        registry: OperatorRegistry,
        implementations: dict[str, Implementation],
        services: ExecutionServices,
    ):
        self.registry = registry
        self.implementations = implementations
        self.services = services

    def execute(self, spec: VisualSkillSpec, media: Any) -> ExecutionResult:
        assert_valid_skill(spec, self.registry)
        self.services.output_dir.mkdir(parents=True, exist_ok=True)
        values: dict[str, Any] = {"input": media}
        trace: list[TraceEntry] = []
        for node in _topological_nodes(spec):
            definition = self.registry.require(node.op)
            implementation = self.implementations.get(node.op)
            if implementation is None:
                raise ValueError(f"operator is registered but not implemented: {node.op}")
            inputs = {}
            for name, ref_value in node.inputs.items():
                refs = _refs(ref_value)
                resolved = [values[ref[1:]] for ref in refs]
                inputs[name] = resolved if isinstance(ref_value, list) else resolved[0]
            params = deepcopy(definition.defaults)
            params.update(node.params)
            started = time.perf_counter()
            try:
                output = implementation(inputs, params, self.services, node.id)
            except Exception as exc:
                trace.append(
                    TraceEntry(
                        node.id,
                        node.op,
                        definition.fixed_rule_text,
                        params,
                        {name: summarize(value) for name, value in inputs.items()},
                        {},
                        (time.perf_counter() - started) * 1000,
                        "failed",
                        str(exc),
                    )
                )
                raise
            values[node.id] = output
            trace.append(
                TraceEntry(
                    node.id,
                    node.op,
                    definition.fixed_rule_text,
                    params,
                    {name: summarize(value) for name, value in inputs.items()},
                    {"result": summarize(output)},
                    (time.perf_counter() - started) * 1000,
                    "success",
                )
            )
        outputs = {name: values[ref[1:]] for name, ref in spec.outputs.items()}
        return ExecutionResult(values, outputs, trace, Path(self.services.output_dir))


__all__ = ["ExecutionEngine", "ExecutionServices"]
