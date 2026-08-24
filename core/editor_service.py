from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .business_capabilities import build_business_capability_registry
from .business_rule_compiler import BusinessRuleCompileError, BusinessRuleCompiler
from .editor_schema import (
    BusinessBranch,
    EventPattern,
    ResultSpec,
    RuleEdge,
    RuleGraph,
    RuleNode,
    SkillEditorDocument,
    UserOverride,
)
from .document_hashes import refresh_document_hashes
from .editor_migrations import migrate_editor_document
from .result_presentation_schema import PresentationSpec
from .registry import OperatorDefinition, OperatorRegistry
from .recipes import build_recipe_catalog
from .resource_requirements import requirement_status
from .rule_graph import RuleGraphCompiler, RuleGraphCompileError, validate_rule_graph

_NODE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class EditorMutationError(ValueError):
    pass


class EditorService:
    """Single mutation boundary for RuleGraph, EventPattern and user overrides."""

    def __init__(self, registry: OperatorRegistry):
        self.registry = registry
        self.compiler = RuleGraphCompiler(registry)
        self.business_compiler = BusinessRuleCompiler(
            registry, build_business_capability_registry(registry)
        )

    def operator_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "operator": item.op,
                "display_name": item.display_name,
                "scope": item.execution_scope,
                "inputs": item.input_types,
                "output": item.output_type,
                "defaults": deepcopy(item.defaults),
                "parameters": {
                    name: spec.kind for name, spec in item.parameters.items()
                },
            }
            for item in self.registry.definitions()
        ]

    def add_node(
        self,
        document: SkillEditorDocument,
        media_type: str,
        operator: str,
        node_id: str,
        display_name: str | None = None,
        branch_id: str | None = None,
    ) -> SkillEditorDocument:
        definition = self._definition(operator)
        self._validate_node_id(node_id)
        result, graph = self._copy_graph(document, media_type)
        if any(node.node_id == node_id for node in graph.nodes):
            raise EditorMutationError(f"节点 ID 已存在：{node_id}")
        node = RuleNode(
            node_id=node_id,
            kind=self._kind(definition),
            display_name=display_name or definition.display_name,
            operator=operator,
            params=deepcopy(definition.defaults),
        )
        graph.nodes.append(node)
        if branch_id:
            branch = self._branch(result, branch_id, media_type)
            branch.node_ids.append(node_id)
            branch.root_node_id = node_id
        return self._touch(result)

    def copy_node(
        self, document: SkillEditorDocument, media_type: str, node_id: str, new_node_id: str
    ) -> SkillEditorDocument:
        self._validate_node_id(new_node_id)
        result, graph = self._copy_graph(document, media_type)
        source = self._node(graph, node_id)
        if any(node.node_id == new_node_id for node in graph.nodes):
            raise EditorMutationError(f"节点 ID 已存在：{new_node_id}")
        graph.nodes.append(source.model_copy(update={"node_id": new_node_id, "display_name": f"{source.display_name} 副本"}, deep=True))
        for branch in result.skill_template.business_branches:
            if branch.media_type == media_type and node_id in branch.node_ids:
                branch.node_ids.append(new_node_id)
        return self._touch(result)

    def delete_node(self, document: SkillEditorDocument, media_type: str, node_id: str) -> SkillEditorDocument:
        result, graph = self._copy_graph(document, media_type)
        self._node(graph, node_id)
        graph.nodes = [node for node in graph.nodes if node.node_id != node_id]
        graph.edges = [edge for edge in graph.edges if edge.source != node_id and edge.target != node_id]
        for branch in result.skill_template.business_branches:
            branch.node_ids = [item for item in branch.node_ids if item != node_id]
            if branch.root_node_id == node_id:
                branch.root_node_id = branch.node_ids[-1] if branch.node_ids else None
        result.user_overrides = [item for item in result.user_overrides if item.target_id != node_id]
        return self._touch(result)

    def replace_node_operator(
        self, document: SkillEditorDocument, media_type: str, node_id: str, operator: str
    ) -> SkillEditorDocument:
        definition = self._definition(operator)
        result, graph = self._copy_graph(document, media_type)
        node = self._node(graph, node_id)
        incoming = [edge for edge in graph.edges if edge.target == node_id]
        outgoing = [edge for edge in graph.edges if edge.source == node_id]
        for edge in incoming:
            source = self._node(graph, edge.source)
            port = edge.port or self._single_port(definition)
            if port not in definition.input_types:
                raise EditorMutationError(f"替换后不存在输入端口：{port}")
            self._assert_type(source.operator, definition.input_types[port])
        for edge in outgoing:
            target = self._node(graph, edge.target)
            target_def = self._definition(target.operator or "")
            port = edge.port or self._single_port(target_def)
            self._assert_output_accepted(definition.output_type, target_def.input_types[port])
        node.operator = operator
        node.kind = self._kind(definition)
        node.display_name = definition.display_name
        node.params = deepcopy(definition.defaults)
        result.user_overrides = [item for item in result.user_overrides if item.target_id != node_id]
        return self._touch(result)

    def connect(
        self, document: SkillEditorDocument, media_type: str, source_id: str, target_id: str, port: str
    ) -> SkillEditorDocument:
        result, graph = self._copy_graph(document, media_type)
        source, target = self._node(graph, source_id), self._node(graph, target_id)
        target_def = self._definition(target.operator or "")
        if port not in target_def.input_types:
            raise EditorMutationError(f"目标节点不存在输入端口：{port}")
        self._assert_type(source.operator, target_def.input_types[port])
        candidate = RuleEdge(source=source_id, target=target_id, port=port)
        if candidate in graph.edges:
            return result
        graph.edges.append(candidate)
        errors = validate_rule_graph(graph, self.registry)
        if any("cycle" in error for error in errors):
            raise EditorMutationError("连接会形成环，规则图必须是有向无环图")
        return self._touch(result)

    def disconnect(
        self, document: SkillEditorDocument, media_type: str, source_id: str, target_id: str, port: str | None = None
    ) -> SkillEditorDocument:
        result, graph = self._copy_graph(document, media_type)
        graph.edges = [
            edge for edge in graph.edges
            if not (edge.source == source_id and edge.target == target_id and (port is None or edge.port == port))
        ]
        return self._touch(result)

    def set_parameter(
        self, document: SkillEditorDocument, node_id: str, parameter: str, value: Any
    ) -> SkillEditorDocument:
        result = document.model_copy(deep=True)
        found = False
        for graph in result.skill_template.rule_graphs.values():
            node = next((item for item in graph.nodes if item.node_id == node_id), None)
            if node is None:
                continue
            definition = self._definition(node.operator or "")
            if parameter not in set(definition.parameters) | set(node.params):
                raise EditorMutationError(f"参数不属于当前原子：{parameter}")
            found = True
        if not found:
            raise EditorMutationError(f"找不到节点：{node_id}")
        result.user_overrides = [
            item for item in result.user_overrides
            if not (item.target_id == node_id and item.parameter == parameter)
        ]
        result.user_overrides.append(
            UserOverride(target_type="rule", target_id=node_id, parameter=parameter, value=value)
        )
        return self._touch(result)

    def reset_parameter(self, document: SkillEditorDocument, node_id: str, parameter: str) -> SkillEditorDocument:
        result = document.model_copy(deep=True)
        result.user_overrides = [
            item for item in result.user_overrides
            if not (item.target_id == node_id and item.parameter == parameter)
        ]
        return self._touch(result)

    def add_branch(self, document: SkillEditorDocument, media_type: str, branch_id: str, display_name: str) -> SkillEditorDocument:
        result = document.model_copy(deep=True)
        if any(item.branch_id == branch_id for item in result.skill_template.business_branches):
            raise EditorMutationError(f"分支 ID 已存在：{branch_id}")
        result.skill_template.business_branches.append(
            BusinessBranch(branch_id=branch_id, display_name=display_name, media_type=media_type)
        )
        return self._touch(result)

    def delete_branch(self, document: SkillEditorDocument, branch_id: str, delete_nodes: bool = False) -> SkillEditorDocument:
        result = document.model_copy(deep=True)
        branch = next((item for item in result.skill_template.business_branches if item.branch_id == branch_id), None)
        if branch is None:
            raise EditorMutationError(f"找不到业务分支：{branch_id}")
        if delete_nodes:
            graph = result.skill_template.rule_graphs.get(branch.media_type)
            if graph:
                protected = {node for item in result.skill_template.business_branches if item.branch_id != branch_id for node in item.node_ids}
                removable = set(branch.node_ids) - protected
                graph.nodes = [node for node in graph.nodes if node.node_id not in removable]
                graph.edges = [edge for edge in graph.edges if edge.source not in removable and edge.target not in removable]
        result.skill_template.business_branches = [item for item in result.skill_template.business_branches if item.branch_id != branch_id]
        return self._touch(result)

    def update_branch(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        *,
        display_name: str | None = None,
        enabled: bool | None = None,
        move: int = 0,
    ) -> SkillEditorDocument:
        result = document.model_copy(deep=True)
        branches = result.skill_template.business_branches
        index = next((i for i, item in enumerate(branches) if item.branch_id == branch_id), None)
        if index is None:
            raise EditorMutationError(f"找不到业务分支：{branch_id}")
        branch = branches[index]
        if display_name is not None:
            if not display_name.strip():
                raise EditorMutationError("分支名称不能为空")
            branch.display_name = display_name.strip()
        if enabled is not None:
            branch.enabled = enabled
            graph = result.skill_template.rule_graphs.get(branch.media_type)
            if graph:
                for node in graph.nodes:
                    if node.node_id in branch.node_ids:
                        node.enabled = enabled
        if move:
            target = max(0, min(len(branches) - 1, index + move))
            branches.insert(target, branches.pop(index))
        return self._touch(result)

    def copy_branch(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        new_branch_id: str,
        display_name: str,
    ) -> SkillEditorDocument:
        self._validate_node_id(new_branch_id)
        result = document.model_copy(deep=True)
        source = next((item for item in result.skill_template.business_branches if item.branch_id == branch_id), None)
        if source is None:
            raise EditorMutationError(f"找不到业务分支：{branch_id}")
        if any(item.branch_id == new_branch_id for item in result.skill_template.business_branches):
            raise EditorMutationError(f"分支 ID 已存在：{new_branch_id}")
        graph = result.skill_template.rule_graphs[source.media_type]
        mapping = {node_id: f"{new_branch_id}_{index + 1}" for index, node_id in enumerate(source.node_ids)}
        originals = {node.node_id: node for node in graph.nodes}
        for old_id, new_id in mapping.items():
            if old_id in originals:
                graph.nodes.append(originals[old_id].model_copy(
                    update={"node_id": new_id, "display_name": f"{originals[old_id].display_name} 副本"}, deep=True
                ))
        graph.edges.extend(
            RuleEdge(source=mapping[edge.source], target=mapping[edge.target], port=edge.port)
            for edge in list(graph.edges)
            if edge.source in mapping and edge.target in mapping
        )
        result.skill_template.business_branches.append(
            BusinessBranch(
                branch_id=new_branch_id,
                display_name=display_name.strip() or f"{source.display_name} 副本",
                media_type=source.media_type,
                node_ids=list(mapping.values()),
                root_node_id=mapping.get(source.root_node_id or ""),
                description=source.description,
            )
        )
        return self._touch(result)

    def insert_recipe(
        self,
        document: SkillEditorDocument,
        media_type: str,
        recipe_id: str,
        branch_id: str | None = None,
    ) -> SkillEditorDocument:
        recipe = build_recipe_catalog().get(recipe_id)
        if recipe is None:
            raise EditorMutationError(f"未知 Recipe：{recipe_id}")
        result = document
        created = []
        existing = {
            node.node_id
            for graph in document.skill_template.rule_graphs.values()
            for node in graph.nodes
        }
        for index, operator in enumerate(recipe.atoms, start=1):
            base = f"{recipe_id}_{index}"
            node_id, suffix = base, 2
            while node_id in existing:
                node_id, suffix = f"{base}_{suffix}", suffix + 1
            result = self.add_node(
                result, media_type, operator, node_id, branch_id=branch_id
            )
            existing.add(node_id)
            created.append(node_id)
        for source_id, target_id in zip(created, created[1:]):
            graph = result.skill_template.rule_graphs[media_type]
            source, target = self._node(graph, source_id), self._node(graph, target_id)
            target_def = self._definition(target.operator or "")
            compatible_port = next(
                (
                    port for port, expected in target_def.input_types.items()
                    if self._is_output_accepted(
                        self._definition(source.operator or "").output_type, expected
                    )
                ),
                None,
            )
            if compatible_port:
                result = self.connect(result, media_type, source_id, target_id, compatible_port)
        return result

    def set_event_patterns(self, document: SkillEditorDocument, patterns: list[dict[str, Any]] | list[EventPattern]) -> SkillEditorDocument:
        result = document.model_copy(deep=True)
        try:
            result.skill_template.event_patterns = [EventPattern.model_validate(item) for item in patterns]
        except Exception as exc:
            raise EditorMutationError(f"复杂事件编排无效：{exc}") from exc
        return self._touch(result)

    def set_result_specs(
        self, document: SkillEditorDocument, specs: list[dict[str, Any]] | list[ResultSpec]
    ) -> SkillEditorDocument:
        result = document.model_copy(deep=True)
        try:
            parsed = [ResultSpec.model_validate(item) for item in specs]
        except Exception as exc:
            raise EditorMutationError(f"结果契约无效：{exc}") from exc
        if len({item.result_id for item in parsed}) != len(parsed):
            raise EditorMutationError("结果契约存在重复 result_id")
        result.skill_template.result_specs = parsed
        return self._touch(result)

    def set_presentation_specs(
        self,
        document: SkillEditorDocument,
        specs: list[dict[str, Any]] | list[PresentationSpec],
    ) -> SkillEditorDocument:
        result = migrate_editor_document(document).model_copy(deep=True)
        try:
            parsed = [PresentationSpec.model_validate(item) for item in specs]
        except Exception as exc:
            raise EditorMutationError(f"结果展示配置无效：{exc}") from exc
        result_ids = {item.result_id for item in result.skill_template.result_specs}
        presented_ids = [item.result_id for item in parsed]
        if len(set(presented_ids)) != len(presented_ids):
            raise EditorMutationError("结果展示配置存在重复 result_id")
        unknown = set(presented_ids) - result_ids
        if unknown:
            raise EditorMutationError(
                "结果展示配置引用未知结果：" + "、".join(sorted(unknown))
            )
        result.skill_template.presentation_specs = parsed
        result.version += 1
        return refresh_document_hashes(result)

    def validate(
        self,
        document: SkillEditorDocument,
        *,
        _business_compiled: bool = False,
    ) -> dict[str, Any]:
        document = migrate_editor_document(document)
        errors = []
        warnings = []
        if not _business_compiled and any(
            branch.condition_root is not None
            for branch in document.skill_template.business_branches
        ):
            try:
                document = self.business_compiler.compile_document(document)
            except BusinessRuleCompileError as exc:
                return {
                    "valid": False,
                    "errors": [str(exc)],
                    "warnings": [],
                    "pending": [],
                    "resource_blockers": [],
                }
        for media_type, graph in document.skill_template.rule_graphs.items():
            errors.extend(f"{media_type}: {item}" for item in validate_rule_graph(graph, self.registry))
            nodes = {item.node_id: item for item in graph.nodes if item.enabled}
            incoming: dict[str, set[str]] = {node_id: set() for node_id in nodes}
            outgoing: dict[str, int] = {node_id: 0 for node_id in nodes}
            for edge in graph.edges:
                if edge.source not in nodes or edge.target not in nodes:
                    continue
                target_def = self._definition(nodes[edge.target].operator or "")
                port = edge.port or (next(iter(target_def.input_types)) if len(target_def.input_types) == 1 else "")
                if port in target_def.input_types:
                    try:
                        self._assert_type(nodes[edge.source].operator, target_def.input_types[port])
                    except EditorMutationError as exc:
                        errors.append(f"{media_type}: {edge.source}->{edge.target}.{port}: {exc}")
                    incoming[edge.target].add(port)
                outgoing[edge.source] += 1
            for node_id, node in nodes.items():
                definition = self._definition(node.operator or "")
                supplied = incoming[node_id] | set(node.input_bindings)
                required = set(definition.input_types) - set(definition.optional_inputs)
                missing = required - supplied
                if missing == {"frames"} and definition.input_types.get("frames") == "FrameSet":
                    missing.clear()
                if missing:
                    errors.append(f"{media_type}: {node_id} 缺少必需输入：{', '.join(sorted(missing))}")
                if outgoing[node_id] == 0 and not node.output_name:
                    warnings.append(f"{media_type}: {node_id} 没有下游或结果输出")
        pending = [
            item.decision_id for item in document.skill_template.pending_decisions
            if item.resolution.blocks("run")
        ]
        resource_blockers = []
        profile = next(
            (
                item for item in document.scene_profiles
                if item.scene_profile_id == document.active_scene_profile_id
            ),
            None,
        )
        if document.skill_template.resource_requirements:
            if profile is None:
                resource_blockers = [
                    item.requirement_id
                    for item in document.skill_template.resource_requirements
                    if item.required_before in {"compile", "run"}
                ]
            else:
                resource_blockers = [
                    item["requirement_id"]
                    for item in requirement_status(document.skill_template, profile)
                    if not item["configured"] and item["required_before"] in {"compile", "run"}
                ]
        result_ids = {
            item.result_id for item in document.skill_template.result_specs
        }
        for spec in document.skill_template.result_specs:
            if spec.source_ref is None:
                errors.append(f"业务输出 {spec.display_name} 尚未选择结果来源")
        final = document.skill_template.final_decision
        if final is None:
            errors.append("技能必须配置一个唯一最终判定")
        elif final.source_ref.startswith("result:"):
            source_result_id = final.source_ref.split(":", 1)[1]
            if source_result_id not in result_ids:
                errors.append(
                    f"最终判定引用了不存在的业务输出：{source_result_id}"
                )
        presentation_ids = {
            item.result_id for item in document.skill_template.presentation_specs
        }
        missing_presentations = result_ids - presentation_ids
        if missing_presentations:
            warnings.append(
                "以下业务输出将使用通用展示："
                + "、".join(sorted(missing_presentations))
            )
        return {
            "valid": not errors and not pending and not resource_blockers,
            "errors": errors,
            "warnings": warnings,
            "pending": pending,
            "resource_blockers": resource_blockers,
        }

    def apply(self, document: SkillEditorDocument) -> SkillEditorDocument:
        document = migrate_editor_document(document)
        if any(
            branch.condition_root is not None
            for branch in document.skill_template.business_branches
        ):
            try:
                document = self.business_compiler.compile_document(document)
            except BusinessRuleCompileError as exc:
                raise RuleGraphCompileError(str(exc)) from exc
        report = self.validate(document, _business_compiled=True)
        if report["errors"]:
            raise RuleGraphCompileError("\n".join(report["errors"]))
        compiled = self.compiler.compile_document(document)
        run_blockers = [
            item.decision_id for item in compiled.skill_template.pending_decisions
            if item.resolution.blocks("run")
        ]
        resource_blockers = report.get("resource_blockers", [])
        result_errors = []
        package = compiled.effective_skill_package
        if package is not None:
            available = {
                output
                for variant in package.variants.values()
                if variant.status != "unsupported"
                for output in variant.outputs
            }
            for spec in compiled.skill_template.result_specs:
                missing = set(spec.required_outputs) - available
                if missing:
                    result_errors.append(
                        f"结果 {spec.display_name} 缺少输出：{', '.join(sorted(missing))}"
                    )
        can_run = not run_blockers and not resource_blockers and not result_errors
        compiled.validation_report = {
            "valid": can_run,
            "errors": result_errors,
            "warnings": report.get("warnings", []),
            "pending": run_blockers,
            "resource_blockers": resource_blockers,
            "can_run": can_run,
        }
        compiled.readiness = compiled.readiness.model_copy(
            update={
                "draft_valid": not bool(report.get("errors")),
                "review_complete": not bool(run_blockers),
                "compile_valid": package is not None and not bool(result_errors),
                "runtime_ready": can_run,
                "publish_ready": can_run,
                "reasons": [
                    *result_errors,
                    *[str(item) for item in resource_blockers],
                    *[str(item) for item in run_blockers],
                ],
            }
        )
        return refresh_document_hashes(compiled)

    def _copy_graph(self, document: SkillEditorDocument, media_type: str) -> tuple[SkillEditorDocument, RuleGraph]:
        result = document.model_copy(deep=True)
        graph = result.skill_template.rule_graphs.get(media_type)
        if graph is None:
            raise EditorMutationError(f"当前技能没有 {media_type} 规则图")
        return result, graph

    @staticmethod
    def _node(graph: RuleGraph, node_id: str) -> RuleNode:
        node = next((item for item in graph.nodes if item.node_id == node_id), None)
        if node is None:
            raise EditorMutationError(f"找不到节点：{node_id}")
        return node

    @staticmethod
    def _branch(document: SkillEditorDocument, branch_id: str, media_type: str) -> BusinessBranch:
        branch = next((item for item in document.skill_template.business_branches if item.branch_id == branch_id), None)
        if branch is None or branch.media_type != media_type:
            raise EditorMutationError(f"找不到当前流程的业务分支：{branch_id}")
        return branch

    def _definition(self, operator: str) -> OperatorDefinition:
        definition = self.registry.get(operator)
        if definition is None:
            raise EditorMutationError(f"未知原子能力：{operator}")
        return definition

    @staticmethod
    def _single_port(definition: OperatorDefinition) -> str:
        if len(definition.input_types) != 1:
            raise EditorMutationError("节点有多个输入端口，请显式选择端口")
        return next(iter(definition.input_types))

    def _assert_type(self, source_operator: str | None, expected: str) -> None:
        actual = self._definition(source_operator or "").output_type
        self._assert_output_accepted(actual, expected)

    @staticmethod
    def _assert_output_accepted(actual: str, expected: str) -> None:
        aliases = {
            "EntitySet": {"ObjectSet", "TrackSet", "EntitySet"},
            "CountableSet": {
                "ObjectSet",
                "TrackSet",
                "EventSet",
                "PairSet",
                "ScopedSet",
                "EntitySet",
            },
            "ValueSet": {"ScalarSet", "VectorSet", "ConditionSet", "ValueSet"},
        }
        if actual != expected and actual not in aliases.get(expected, set()):
            raise EditorMutationError(f"端口类型不兼容：{actual} → {expected}")

    @staticmethod
    def _is_output_accepted(actual: str, expected: str) -> bool:
        try:
            EditorService._assert_output_accepted(actual, expected)
        except EditorMutationError:
            return False
        return True

    @staticmethod
    def _validate_node_id(node_id: str) -> None:
        if not _NODE_ID.fullmatch(node_id):
            raise EditorMutationError("节点 ID 需以英文字母开头，仅包含字母、数字、_、-")

    @staticmethod
    def _kind(definition: OperatorDefinition) -> str:
        scope = definition.execution_scope
        if scope in {"aggregate"}:
            return "aggregate"
        if scope in {"condition"}:
            return "condition"
        if scope in {"event", "stream"} or definition.op.startswith("temporal."):
            return "temporal_qualifier"
        if scope == "final":
            return "output"
        if definition.output_type in {"RegionSet", "VectorSet"}:
            return "region" if definition.output_type == "RegionSet" else "scope"
        return "target" if definition.output_type in {"ObjectSet", "TrackSet", "EntitySet"} else "scope"

    @staticmethod
    def _touch(document: SkillEditorDocument) -> SkillEditorDocument:
        document.version += 1
        document.effective_skill_package = None
        document.validation_report = {"valid": False, "dirty": True, "can_run": False}
        return refresh_document_hashes(document)


__all__ = ["EditorMutationError", "EditorService"]
