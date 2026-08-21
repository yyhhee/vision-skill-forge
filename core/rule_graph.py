from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Any

from .editor_schema import RuleGraph, SkillEditorDocument, UserOverride
from .event_pattern import compile_event_patterns
from .registry import OperatorRegistry
from .schema import SkillPackage
from .semantic import WorkflowCompiler
from .validator import assert_valid_skill_package


class RuleGraphCompileError(ValueError):
    pass


def validate_rule_graph(graph: RuleGraph, registry: OperatorRegistry) -> list[str]:
    errors = []
    enabled = [node for node in graph.nodes if node.enabled]
    node_by_id = {node.node_id: node for node in enabled}
    if len(node_by_id) != len(enabled):
        errors.append("rule graph contains duplicate node ids")

    incoming: dict[str, list] = {node_id: [] for node_id in node_by_id}
    outgoing: dict[str, list] = {node_id: [] for node_id in node_by_id}
    for edge in graph.edges:
        if edge.source not in node_by_id:
            errors.append(f"edge source does not exist: {edge.source}")
            continue
        if edge.target not in node_by_id:
            errors.append(f"edge target does not exist: {edge.target}")
            continue
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)

    for node in enabled:
        if node.operator is None:
            errors.append(f"node {node.node_id}: executable operator is required")
            continue
        definition = registry.get(node.operator)
        if definition is None:
            errors.append(f"node {node.node_id}: unknown operator {node.operator}")
            continue
        for edge in incoming[node.node_id]:
            if edge.port is None and len(definition.input_types) != 1:
                errors.append(
                    f"edge {edge.source}->{edge.target}: input port is ambiguous"
                )
            elif edge.port is not None and edge.port not in definition.input_types:
                errors.append(
                    f"node {node.node_id}: unknown input port {edge.port}"
                )

    indegree = {node_id: len(edges) for node_id, edges in incoming.items()}
    queue = deque(sorted(node_id for node_id, count in indegree.items() if count == 0))
    visited = []
    while queue:
        current = queue.popleft()
        visited.append(current)
        for edge in outgoing[current]:
            indegree[edge.target] -= 1
            if indegree[edge.target] == 0:
                queue.append(edge.target)
    if len(visited) != len(enabled):
        errors.append("rule graph contains a cycle")
    return errors


def apply_user_overrides(
    graph: RuleGraph, overrides: list[UserOverride]
) -> RuleGraph:
    result = graph.model_copy(deep=True)
    node_by_id = {node.node_id: node for node in result.nodes}
    for override in overrides:
        if override.target_type not in {"rule", "atom"}:
            continue
        node = node_by_id.get(override.target_id)
        if node is None:
            raise RuleGraphCompileError(
                f"override target does not exist: {override.target_id}"
            )
        target: dict[str, Any] = node.params
        parts = override.parameter.split(".")
        for part in parts[:-1]:
            value = target.get(part)
            if not isinstance(value, dict):
                value = {}
                target[part] = value
            target = value
        target[parts[-1]] = deepcopy(override.value)
    return result


class RuleGraphCompiler:
    def __init__(self, registry: OperatorRegistry):
        self.registry = registry

    def compile_document(
        self,
        document: SkillEditorDocument,
        requested_accept: list[str] | None = None,
    ) -> SkillEditorDocument:
        template = document.skill_template
        requested = requested_accept or self._requested_media(document)
        graphs = {}
        errors = []
        for media_type in requested:
            source_graph = template.rule_graphs.get(media_type, template.rule_graph)
            target_ids = {node.node_id for node in source_graph.nodes}
            relevant_overrides = [
                item
                for item in document.user_overrides
                if item.target_type == "pattern" or item.target_id in target_ids
            ]
            graphs[media_type] = apply_user_overrides(
                source_graph, relevant_overrides
            )
            errors.extend(
                f"{media_type}: {error}"
                for error in validate_rule_graph(graphs[media_type], self.registry)
            )
        blockers = [
            item
            for item in _unresolved_values(document.model_dump(mode="python"))
            if item[1] == "compile"
        ]
        if blockers:
            errors.extend(f"unresolved before compile: {path}" for path, _ in blockers)
        if errors:
            raise RuleGraphCompileError("\n".join(errors))

        accepted = []
        variants = {}
        issues = []
        atomic_variants = {}
        for media_type in requested:
            graph = graphs[media_type]
            stream_required = any(
                node.enabled
                and node.operator is not None
                and self.registry.require(node.operator).execution_scope == "stream"
                and not (
                    node.operator == "event.from_condition@1.0"
                    and float(node.params.get("seconds", 0.0)) == 0.0
                )
                for node in graph.nodes
            ) or bool(template.event_patterns)
            if media_type != "video" and stream_required:
                message = "规则图包含轨迹或时序原子，需要视频"
                variants[media_type] = {
                    "media_type": media_type,
                    "status": "unsupported",
                    "nodes": [],
                    "outputs": {},
                    "issue": message,
                }
                issues.append(
                    {
                        "media_type": media_type,
                        "code": "stream_requires_video",
                        "message": message,
                    }
                )
                continue
            accepted.append(media_type)
            variant = self._compile_variant(
                graph, media_type, template.semantic_ir, template.event_patterns
            )
            variants[media_type] = variant
            atomic_variants[media_type] = variant

        if not accepted:
            raise RuleGraphCompileError("no requested media can execute this rule graph")
        package = SkillPackage.model_validate(
            {
                "schema_version": "2.0",
                "skill_id": template.skill_id,
                "version": document.version,
                "display_name": template.display_name,
                "original_instruction": template.original_instruction,
                "compile_status": "needs_review" if issues else "compiled",
                "input": {"requested_accept": requested, "accept": accepted},
                "semantic_ir": template.semantic_ir.model_dump(mode="json"),
                "variants": variants,
                "compatibility_issues": issues,
            }
        )
        assert_valid_skill_package(package, self.registry)
        return document.model_copy(
            update={
                "atomic_plan": {
                    "schema_version": "1.0",
                    "source": "rule_graph",
                    "variants": atomic_variants,
                },
                "effective_skill_package": package,
                "validation_report": {"valid": True, "errors": [], "warnings": issues},
            }
        )

    def _compile_variant(self, graph, media_type, semantic_ir, event_patterns):
        enabled = {node.node_id: node for node in graph.nodes if node.enabled}
        owns_media_pipeline = any(
            node.operator is not None and node.operator.startswith(f"media.{media_type}@")
            for node in enabled.values()
        )
        if owns_media_pipeline:
            nodes, frames_ref = [], None
        else:
            nodes, frames_ref = WorkflowCompiler._start_nodes(media_type)
        incoming = {node_id: [] for node_id in enabled}
        outgoing = {node_id: [] for node_id in enabled}
        for edge in graph.edges:
            if edge.source in enabled and edge.target in enabled:
                incoming[edge.target].append(edge)
                outgoing[edge.source].append(edge)

        indegree = {node_id: len(edges) for node_id, edges in incoming.items()}
        source_order = {node.node_id: index for index, node in enumerate(graph.nodes)}
        queue = deque(sorted(
            (node_id for node_id, count in indegree.items() if count == 0),
            key=source_order.get,
        ))
        ordered = []
        while queue:
            current = queue.popleft()
            ordered.append(current)
            for edge in outgoing[current]:
                indegree[edge.target] -= 1
                if indegree[edge.target] == 0:
                    queue.append(edge.target)
            queue = deque(sorted(queue, key=source_order.get))

        atom_bindings: dict[str, list[str]] = {}
        outputs = {}
        for node_id in ordered:
            rule = enabled[node_id]
            definition = self.registry.require(rule.operator)
            bindings = deepcopy(rule.input_bindings)
            for edge in incoming[node_id]:
                port = edge.port or next(iter(definition.input_types))
                reference = f"${edge.source}"
                if port in bindings:
                    current = bindings[port]
                    bindings[port] = (
                        [*current, reference]
                        if isinstance(current, list)
                        else [current, reference]
                    )
                else:
                    bindings[port] = reference
            required = set(definition.input_types) - set(definition.optional_inputs)
            missing = required - set(bindings)
            if len(missing) == 1:
                port = next(iter(missing))
                if definition.input_types[port] == "FrameSet" and frames_ref is not None:
                    bindings[port] = frames_ref
                    missing.clear()
            if missing:
                raise RuleGraphCompileError(
                    f"node {node_id}: missing inputs {', '.join(sorted(missing))}"
                )
            nodes.append(
                {
                    "id": node_id,
                    "op": rule.operator,
                    "inputs": bindings,
                    "params": deepcopy(rule.params),
                }
            )
            for atom_id in rule.semantic_atom_ids:
                atom_bindings.setdefault(atom_id, []).append(node_id)
            if rule.output_name:
                outputs[rule.output_name] = f"${node_id}"

        if not outputs:
            leaves = [node_id for node_id in ordered if not outgoing[node_id]]
            outputs = {f"result_{index + 1}": f"${node_id}" for index, node_id in enumerate(leaves)}
        fallback = [node_id for node_id in ordered]
        for constraint in semantic_ir.constraints:
            if constraint.atom_id and constraint.atom_id not in atom_bindings:
                atom_bindings[constraint.atom_id] = fallback
        nodes, outputs = compile_event_patterns(
            nodes, outputs, event_patterns, self.registry
        )
        return {
            "media_type": media_type,
            "status": "executable",
            "nodes": nodes,
            "outputs": outputs,
            "atom_bindings": atom_bindings,
            "configuration_slots": [],
        }

    @staticmethod
    def _requested_media(document):
        package = document.effective_skill_package
        if package is not None:
            return list(package.input.requested_accept)
        if document.skill_template.rule_graphs:
            return list(document.skill_template.rule_graphs)
        requirements = document.skill_template.resource_requirements
        media = {item for requirement in requirements for item in requirement.media_types}
        return sorted(media) or ["image", "video"]


def _unresolved_values(value, path=""):
    if isinstance(value, dict):
        if value.get("state") == "unresolved":
            yield path or "$", value.get("required_before", "run")
        for key, child in value.items():
            yield from _unresolved_values(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _unresolved_values(child, f"{path}[{index}]")


__all__ = [
    "RuleGraphCompileError",
    "RuleGraphCompiler",
    "apply_user_overrides",
    "validate_rule_graph",
]
