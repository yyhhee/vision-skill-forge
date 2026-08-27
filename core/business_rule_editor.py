from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any, Iterable
from uuid import uuid4

from .business_capabilities import (
    BusinessCapabilityDefinition,
    BusinessCapabilityRegistry,
    BusinessParameterDefinition,
    BusinessValueType,
)
from .business_source_scope import partition_source_refs, source_media_types
from .document_hashes import refresh_document_hashes
from .editor_migrations import migrate_editor_document
from .editor_schema import (
    BranchValidityPolicy,
    BusinessBranch,
    ConditionExpression,
    CorrelationPolicy,
    EventPattern,
    FinalDecisionSpec,
    InstancePolicy,
    PatternGateway,
    PatternStage,
    PatternTransition,
    ResolvableValue,
    ResultProjection,
    ResultSpec,
    RuleEdge,
    RuleNode,
    SkillEditorDocument,
    TriggerPolicy,
    TemporalQualifierSpec,
)
from .parameter_presentations import parameter_presentation
from .registry import OperatorRegistry
from .result_presentation_schema import PresentationSpec


class BusinessRuleEditError(ValueError):
    """A business-language editing error safe to show in 03."""


_OPERATOR_CAPABILITY_PRIORITY: tuple[tuple[str, str], ...] = (
    ("temporal.sequence@", "temporal.sequence"),
    ("temporal.join@", "temporal.join"),
    ("temporal.absence@", "temporal.absence"),
    ("temporal.repeat@", "temporal.repeat"),
    ("temporal.persist@", "temporal.persist"),
    ("state.transition@", "state.transition"),
    ("state.detect@", "state.current"),
    ("measure.heading@", "motion.direction"),
    ("track.iou@", "motion.track"),
    ("measure.region_count@", "measure.count"),
    ("measure.count@", "measure.count"),
    ("reduce.count@", "measure.count"),
    ("logic.compare@", "measure.statistic"),
    ("measure.region_speed@", "motion.speed"),
    ("measure.speed@", "motion.speed"),
    ("logic.heading_by_lane@", "motion.wrong_way"),
    ("spatial.inside@", "spatial.membership"),
    ("spatial.associate@", "spatial.association"),
    ("pairs.filter@", "spatial.association"),
    ("set.anti_join@", "subject.missing_equipment"),
    ("set.semi_join@", "subject.same_attributes"),
    ("visual.color_fraction@", "attribute.color"),
    ("visual.geometry@", "attribute.geometry"),
    ("objects.filter_by_label@", "target.filter_class"),
    ("rex.ground@", "target.detect"),
    ("event.from_condition@", "event.detect_or_compose"),
    ("event.relabel@", "event.detect_or_compose"),
    ("logic.all@", "logic.group"),
    ("logic.any@", "logic.group"),
    ("logic.not@", "logic.group"),
)

_IMPORTED_STEP_PREFIX = "existing_node:"
_IMPORTED_PARAMETER_PREFIX = "atom_parameter:"

_RELATION_LABELS = {
    "overlap": "与{object}重叠",
    "contains": "包含{object}",
    "inside": "位于{object}内部",
    "near": "接近{object}",
    "bidirectional": "与{object}双向匹配",
    "source_entity": "具有{object}",
    "center_in_subject_region": "位于{object}的主体指定区域",
    "center_in_object_region": "中心位于{object}的{region}",
}

_RESULT_KIND_SCHEMA: dict[str, tuple[str, str, str]] = {
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


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def _walk(expression: ConditionExpression | None) -> Iterable[ConditionExpression]:
    if expression is None:
        return
    yield expression
    for child in expression.children:
        yield from _walk(child)


def _find(expression: ConditionExpression | None, expression_id: str) -> ConditionExpression:
    match = next(
        (item for item in _walk(expression) if item.expression_id == expression_id),
        None,
    )
    if match is None:
        raise BusinessRuleEditError("找不到要编辑的条件；请刷新当前分支后重试。")
    return match


def _replace_tree(
    expression: ConditionExpression,
    expression_id: str,
    replacement: ConditionExpression,
) -> ConditionExpression:
    if expression.expression_id == expression_id:
        return replacement
    data = expression.model_dump(mode="python")
    data["children"] = [
        _replace_tree(child, expression_id, replacement).model_dump(mode="python")
        for child in expression.children
    ]
    return ConditionExpression.model_validate(data)


def _find_parent(
    expression: ConditionExpression | None, expression_id: str
) -> ConditionExpression | None:
    """Return the direct parent of an expression in a recursive condition tree."""

    if expression is None or expression.expression_id == expression_id:
        return None
    for child in expression.children:
        if child.expression_id == expression_id:
            return expression
        parent = _find_parent(child, expression_id)
        if parent is not None:
            return parent
    return None


def _delete_from_tree(
    expression: ConditionExpression, expression_id: str
) -> ConditionExpression | None:
    if expression.expression_id == expression_id:
        return None
    children = []
    for child in expression.children:
        kept = _delete_from_tree(child, expression_id)
        if kept is not None:
            children.append(kept)
    if len(children) == len(expression.children):
        return expression
    if expression.operator == "NOT":
        return children[0] if children else None
    if expression.operator in {"AND", "OR", "N_OF_M"}:
        if not children:
            return None
        if len(children) == 1:
            return children[0]
    data = expression.model_dump(mode="python")
    data["children"] = [item.model_dump(mode="python") for item in children]
    if data["operator"] == "N_OF_M":
        data["required_count"] = min(data.get("required_count") or 1, len(children))
    return ConditionExpression.model_validate(data)


def _source_type_compatible(
    actual: BusinessValueType | None, accepted: list[BusinessValueType]
) -> bool:
    if not accepted or "any" in accepted or actual is None:
        return True
    if actual in accepted:
        return True
    return actual == "entity_set" and "scoped_set" in accepted


class BusinessRuleEditor:
    """Schema-driven editing service used by 03, independent of Gradio."""

    def __init__(
        self,
        capabilities: BusinessCapabilityRegistry,
        operators: OperatorRegistry,
    ):
        self.capabilities = capabilities
        self.operators = operators

    def prepare(self, document: SkillEditorDocument) -> SkillEditorDocument:
        """Add safe business metadata to imported 3.x documents.

        The executable graph is not changed. Historical graphs that cannot be
        reverse-projected remain represented by one traceable condition rather
        than being guessed into a different business meaning.
        """

        result = migrate_editor_document(document).model_copy(deep=True)
        graph_by_media = result.skill_template.rule_graphs
        changed = False
        for branch in result.skill_template.business_branches:
            if branch.condition_root is None and branch.root_node_id:
                graph = graph_by_media.get(branch.media_type)
                node = next(
                    (
                        item
                        for item in (graph.nodes if graph else [])
                        if item.node_id == branch.root_node_id
                    ),
                    None,
                )
                capability_id = self._capability_for_operator(
                    node.operator if node else None
                )
                branch.condition_root = ConditionExpression(
                    expression_id=f"{branch.branch_id}_root",
                    operator="ATOM",
                    display_name=branch.display_name,
                    capability_id=capability_id,
                    source_ref=f"node:{branch.root_node_id}",
                    parameters=self._parameters_from_node(capability_id, node),
                    enabled=branch.enabled,
                )
                changed = True
            elif (
                branch.condition_root is not None
                and branch.condition_root.operator == "ATOM"
                and branch.condition_root.capability_id is None
                and branch.condition_root.source_ref
                and branch.condition_root.source_ref.startswith("node:")
            ):
                node_id = branch.condition_root.source_ref.split(":", 1)[1]
                graph = graph_by_media.get(branch.media_type)
                node = next(
                    (item for item in (graph.nodes if graph else []) if item.node_id == node_id),
                    None,
                )
                capability_id = self._capability_for_operator(
                    node.operator if node else None
                )
                branch.condition_root.capability_id = capability_id
                branch.condition_root.parameters = self._parameters_from_node(
                    capability_id, node
                )
                changed = True
        if changed:
            result.version += 1
        return refresh_document_hashes(result)

    def add_branch(
        self,
        document: SkillEditorDocument,
        media_type: str,
        display_name: str,
    ) -> SkillEditorDocument:
        if media_type not in {"image", "video"}:
            raise BusinessRuleEditError("分支媒体只能选择图片或视频。")
        name = display_name.strip()
        if not name:
            raise BusinessRuleEditError("请填写分支名称。")
        result = self.prepare(document).model_copy(deep=True)
        branch_id = _new_id(f"{media_type}_branch")
        result.skill_template.business_branches.append(
            BusinessBranch(
                branch_id=branch_id,
                display_name=name,
                media_type=media_type,
            )
        )
        result.version += 1
        return refresh_document_hashes(result)

    def rename_branch(
        self, document: SkillEditorDocument, branch_id: str, display_name: str
    ) -> SkillEditorDocument:
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        name = display_name.strip()
        if not name:
            raise BusinessRuleEditError("请填写分支名称。")
        branch.display_name = name
        result.version += 1
        return refresh_document_hashes(result)

    def copy_branch(
        self, document: SkillEditorDocument, branch_id: str, display_name: str | None = None
    ) -> SkillEditorDocument:
        result = self.prepare(document).model_copy(deep=True)
        source = self._branch(result, branch_id)
        clone = source.model_copy(deep=True)
        clone.branch_id = _new_id(f"{source.media_type}_branch")
        clone.display_name = (display_name or f"{source.display_name} 副本").strip()
        if clone.condition_root is not None:
            clone.condition_root = self._clone_expression(clone.condition_root)
        clone.node_ids = []
        clone.root_node_id = None
        clone.result_ids = []
        result.skill_template.business_branches.append(clone)
        result.version += 1
        return refresh_document_hashes(result)

    def delete_branch(
        self, document: SkillEditorDocument, branch_id: str
    ) -> SkillEditorDocument:
        result = self.prepare(document).model_copy(deep=True)
        branches = result.skill_template.business_branches
        if len(branches) <= 1:
            raise BusinessRuleEditError("技能至少需要保留一个条件分支。")
        if not any(item.branch_id == branch_id for item in branches):
            raise BusinessRuleEditError("找不到要删除的分支。")
        result.skill_template.business_branches = [
            item for item in branches if item.branch_id != branch_id
        ]
        result.version += 1
        return refresh_document_hashes(result)

    def add_condition(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        capability_id: str,
        *,
        parent_group_id: str | None = None,
        display_name: str | None = None,
    ) -> tuple[SkillEditorDocument, str]:
        definition = self.capabilities.require(capability_id)
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        self._assert_media(definition, branch.media_type)
        expression = self._new_atom(definition, display_name)
        root = branch.condition_root
        if root is None:
            branch.condition_root = expression
        elif parent_group_id:
            parent = _find(root, parent_group_id)
            if parent.operator not in {"AND", "OR", "N_OF_M"}:
                raise BusinessRuleEditError("新条件只能添加到 AND、OR 或至少N项条件组。")
            data = parent.model_dump(mode="python")
            data["children"].append(expression.model_dump(mode="python"))
            if data["operator"] == "N_OF_M":
                data["required_count"] = min(
                    data.get("required_count") or 1, len(data["children"])
                )
            branch.condition_root = _replace_tree(
                root, parent_group_id, ConditionExpression.model_validate(data)
            )
        elif root.operator == "AND":
            data = root.model_dump(mode="python")
            data["children"].append(expression.model_dump(mode="python"))
            branch.condition_root = ConditionExpression.model_validate(data)
        else:
            branch.condition_root = ConditionExpression(
                expression_id=_new_id("group"),
                operator="AND",
                display_name="全部满足（AND）",
                capability_id="logic.group",
                parameters={"operator": "AND"},
                children=[root, expression],
            )
        result.version += 1
        return refresh_document_hashes(result), expression.expression_id

    def wrap_with_group(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        expression_id: str,
        operator: str,
    ) -> tuple[SkillEditorDocument, str]:
        if expression_id.startswith(_IMPORTED_STEP_PREFIX):
            raise BusinessRuleEditError(
                "导入流程的组成步骤不能单独取反；请对整个业务判定取反，或新增条件后组合。"
            )
        operator = operator.upper()
        if operator not in {"NOT", "AND", "OR", "N_OF_M"}:
            raise BusinessRuleEditError("条件组仅支持 AND、OR、NOT 或至少N项。")
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        if branch.condition_root is None:
            raise BusinessRuleEditError("请先新增一个条件。")
        target = _find(branch.condition_root, expression_id)
        if operator in {"AND", "OR", "N_OF_M"}:
            raise BusinessRuleEditError(
                "AND、OR 和至少N项组需要两个条件；请先新增条件，再选择要组合的条件。"
            )
        group = ConditionExpression(
            expression_id=_new_id("group"),
            operator="NOT",
            display_name="条件取反（NOT）",
            capability_id="logic.group",
            parameters={"operator": "NOT"},
            children=[target],
        )
        branch.condition_root = _replace_tree(
            branch.condition_root, expression_id, group
        )
        result.version += 1
        return refresh_document_hashes(result), group.expression_id

    def group_expressions(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        expression_ids: list[str],
        operator: str,
        *,
        required_count: int | None = None,
    ) -> tuple[SkillEditorDocument, str]:
        operator = operator.upper()
        if operator not in {"AND", "OR", "NOT", "N_OF_M"}:
            raise BusinessRuleEditError("条件编排仅支持 AND、OR、NOT 或至少N项。")
        ids = list(dict.fromkeys(expression_ids))
        if operator == "NOT" and len(ids) != 1:
            raise BusinessRuleEditError("NOT 只能作用于一个条件或一个条件组。")
        if operator != "NOT" and len(ids) < 2:
            raise BusinessRuleEditError("AND、OR 和至少N项需要选择两个或更多同级节点。")
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        root = branch.condition_root
        if root is None:
            raise BusinessRuleEditError("当前分支没有可组合条件。")

        if operator == "NOT":
            target = _find(root, ids[0])
            parent = _find_parent(root, target.expression_id)
            # Reapplying NOT is a user-friendly way to cancel an existing
            # negation instead of producing a confusing double-negative tree.
            if parent is not None and parent.operator == "NOT":
                branch.condition_root = _replace_tree(
                    root, parent.expression_id, target
                )
                replacement = target
            elif target.operator == "NOT":
                replacement = target.children[0]
                branch.condition_root = _replace_tree(
                    root, target.expression_id, replacement
                )
            else:
                replacement = ConditionExpression(
                    expression_id=_new_id("group"),
                    operator="NOT",
                    display_name="条件取反（NOT）",
                    capability_id="logic.group",
                    parameters={"operator": "NOT"},
                    children=[target],
                )
                branch.condition_root = _replace_tree(
                    root, target.expression_id, replacement
                )
            result.version += 1
            return refresh_document_hashes(result), replacement.expression_id

        selected_ids = set(ids)
        parent = next(
            (
                candidate
                for candidate in _walk(root)
                if candidate.operator in {"AND", "OR", "N_OF_M"}
                and selected_ids.issubset(
                    {child.expression_id for child in candidate.children}
                )
            ),
            None,
        )
        if parent is None:
            raise BusinessRuleEditError(
                "所选节点不在同一个条件组内。请按界面标注的同一层级选择后再组合。"
            )
        selected = [
            child for child in parent.children
            if child.expression_id in selected_ids
        ]
        if operator == "N_OF_M" and not 1 <= int(required_count or 1) <= len(selected):
            raise BusinessRuleEditError("至少满足项数必须在 1 和所选节点数量之间。")
        group = ConditionExpression(
            expression_id=_new_id("group"),
            operator=operator,  # type: ignore[arg-type]
            display_name=self._logic_label(operator),
            capability_id="logic.group",
            parameters={"operator": operator},
            children=selected,
            required_count=(required_count or 1) if operator == "N_OF_M" else None,
        )
        direct_ids = {item.expression_id for item in parent.children}
        if selected_ids == direct_ids:
            branch.condition_root = _replace_tree(root, parent.expression_id, group)
            result.version += 1
            return refresh_document_hashes(result), group.expression_id
        data = parent.model_dump(mode="python")
        new_children = []
        inserted = False
        for child in parent.children:
            if child.expression_id in selected_ids:
                if not inserted:
                    new_children.append(group.model_dump(mode="python"))
                    inserted = True
            else:
                new_children.append(child.model_dump(mode="python"))
        data["children"] = new_children
        if data["operator"] == "N_OF_M":
            data["required_count"] = min(
                data.get("required_count") or 1, len(new_children)
            )
        replacement = ConditionExpression.model_validate(data)
        branch.condition_root = _replace_tree(root, parent.expression_id, replacement)
        result.version += 1
        return refresh_document_hashes(result), group.expression_id

    def expression_logic_groups(
        self, document: SkillEditorDocument, branch_id: str
    ) -> list[dict[str, Any]]:
        """Describe every editable group in a generated recursive condition tree."""

        prepared = self.prepare(document)
        branch = self._branch(prepared, branch_id)
        root = branch.condition_root
        if root is None:
            return []
        depths: dict[str, int] = {}

        def record_depth(item: ConditionExpression, depth: int) -> None:
            depths[item.expression_id] = depth
            for child in item.children:
                record_depth(child, depth + 1)

        record_depth(root, 0)
        rows = []
        for item in _walk(root):
            if item.operator == "ATOM":
                continue
            parent = _find_parent(root, item.expression_id)
            # A NOT wrapper around a multi-child group is represented by the
            # child group with negated=True, so users edit one semantic group.
            if item.operator == "NOT" and item.children[0].operator != "ATOM":
                continue
            negated = bool(
                parent
                and parent.operator == "NOT"
                and len(parent.children) == 1
                and parent.children[0].expression_id == item.expression_id
            )
            rows.append(
                {
                    "group_id": item.expression_id,
                    "display_name": item.display_name,
                    "operator": item.operator,
                    "required_count": item.required_count or 1,
                    "condition_count": len(item.children),
                    "members": [child.display_name for child in item.children],
                    "negated": negated or item.operator == "NOT",
                    "summary": self.expression_summary(
                        parent if negated else item
                    ),
                    "depth": depths.get(item.expression_id, 0),
                }
            )
        return rows

    def update_expression_logic_group(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        group_id: str,
        operator: str,
        *,
        required_count: int = 1,
        negated: bool = False,
    ) -> SkillEditorDocument:
        """Edit a generated group relation and its optional NOT wrapper."""

        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        root = branch.condition_root
        if root is None:
            raise BusinessRuleEditError("当前分支没有可编辑条件组。")
        target = _find(root, group_id)
        parent = _find_parent(root, group_id)

        if target.operator == "NOT":
            if negated:
                return result
            branch.condition_root = _replace_tree(root, group_id, target.children[0])
            result.version += 1
            return refresh_document_hashes(result)

        operator = operator.upper()
        if operator not in {"AND", "OR", "N_OF_M"}:
            raise BusinessRuleEditError("多项条件组只能使用 AND、OR 或至少N项。")
        count = len(target.children)
        if count < 2:
            raise BusinessRuleEditError("多项条件组至少需要两个成员。")
        if operator == "N_OF_M" and not 1 <= int(required_count) <= count:
            raise BusinessRuleEditError("至少满足项数必须在 1 和组内成员数量之间。")
        data = target.model_dump(mode="python")
        data.update(
            operator=operator,
            display_name=self._logic_label(operator),
            capability_id="logic.group",
            parameters={"operator": operator},
            required_count=int(required_count) if operator == "N_OF_M" else None,
        )
        replacement = ConditionExpression.model_validate(data)
        updated_root = _replace_tree(root, group_id, replacement)
        currently_negated = bool(parent and parent.operator == "NOT")
        if negated and not currently_negated:
            wrapper = ConditionExpression(
                expression_id=_new_id("group"),
                operator="NOT",
                display_name="条件组取反（NOT）",
                capability_id="logic.group",
                parameters={"operator": "NOT"},
                children=[replacement],
            )
            updated_root = _replace_tree(updated_root, group_id, wrapper)
        elif not negated and currently_negated:
            updated_root = _replace_tree(updated_root, parent.expression_id, replacement)
        branch.condition_root = updated_root
        result.version += 1
        return refresh_document_hashes(result)

    def imported_logic_groups(
        self, document: SkillEditorDocument, branch_id: str
    ) -> list[dict[str, Any]]:
        """Describe editable logic groups preserved from a preset/history DAG."""

        prepared = self.prepare(document)
        branch = self._branch(prepared, branch_id)
        graph = prepared.skill_template.rule_graphs.get(branch.media_type)
        if graph is None:
            return []
        nodes = {item.node_id: item for item in graph.nodes}
        incoming = {}
        for edge in graph.edges:
            incoming.setdefault(edge.target, []).append(edge)
        supported = {
            "logic.all@1.0": "AND",
            "logic.any@1.0": "OR",
            "reduce.quantify@1.0": "N_OF_M",
        }
        rows = []
        hidden_inner = {
            edge.source
            for node in graph.nodes
            if node.operator == "logic.not@1.0"
            for edge in incoming.get(node.node_id, [])
            if edge.port == "condition"
        }

        def member_label(node_id: str) -> str:
            member = nodes.get(node_id)
            if member is None:
                return node_id
            label = member.display_name
            if not label or label == member.node_id:
                definition = self.operators.get(member.operator)
                label = definition.display_name if definition else member.node_id
            if member.operator == "logic.compare@1.0":
                source_edge = next(
                    (
                        edge for edge in incoming.get(member.node_id, [])
                        if edge.port in {
                            "lhs", "left", "value", "measurement"
                        }
                    ),
                    None,
                )
                source = nodes.get(source_edge.source) if source_edge else None
                if source is not None:
                    definition = self.operators.get(source.operator)
                    source_label = (
                        source.display_name
                        if source.display_name and source.display_name != source.node_id
                        else (definition.display_name if definition else source.node_id)
                    )
                    label = (
                        f"{source_label} {member.params.get('operator', '')} "
                        f"{member.params.get('value', '')}"
                    ).strip()
            return label
        for node in graph.nodes:
            if node.node_id not in branch.node_ids or node.node_id in hidden_inner:
                continue
            negated = node.operator == "logic.not@1.0"
            base = node
            if negated:
                child_edge = next(
                    (
                        edge for edge in incoming.get(node.node_id, [])
                        if edge.port == "condition"
                    ),
                    None,
                )
                base = nodes.get(child_edge.source) if child_edge else None
            if base is None or base.operator not in supported:
                continue
            operator = supported[base.operator]
            if base.operator == "reduce.quantify@1.0":
                mode = base.params.get("mode", "n_of_m")
                if mode == "all":
                    operator = "AND"
                elif mode == "any":
                    operator = "OR"
            count = len(
                [edge for edge in incoming.get(base.node_id, []) if edge.port == "conditions"]
            )
            member_edges = [
                edge for edge in incoming.get(base.node_id, [])
                if edge.port == "conditions"
            ]
            if not count:
                binding = base.input_bindings.get("conditions", [])
                count = len(binding) if isinstance(binding, list) else int(bool(binding))
            members = [
                member_label(edge.source)
                for edge in member_edges
            ]
            if not members:
                binding = base.input_bindings.get("conditions", [])
                refs = binding if isinstance(binding, list) else [binding]
                members = [
                    member_label(str(ref).lstrip("$"))
                    for ref in refs if ref
                ]
            rows.append(
                {
                    "group_id": node.node_id,
                    "display_name": (
                        node.display_name
                        if node.display_name != node.node_id
                        else f"{branch.display_name}条件组"
                    ),
                    "operator": operator,
                    "required_count": int(base.params.get("required_count", 1)),
                    "condition_count": count,
                    "members": members,
                    "negated": negated,
                }
            )
        return rows

    def update_imported_logic_group(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        group_id: str,
        operator: str,
        *,
        required_count: int = 1,
        negated: bool = False,
    ) -> SkillEditorDocument:
        """Change AND/OR/N-of-M and optional whole-group NOT in an imported DAG."""

        operator = operator.upper()
        if operator not in {"AND", "OR", "N_OF_M"}:
            raise BusinessRuleEditError("条件关系只能选择 AND、OR 或至少N项。")
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        graph = result.skill_template.rule_graphs.get(branch.media_type)
        if graph is None:
            raise BusinessRuleEditError("当前分支没有可编辑的执行规则。")
        nodes = {item.node_id: item for item in graph.nodes}
        wrapper = nodes.get(group_id)
        if wrapper is None or group_id not in branch.node_ids:
            raise BusinessRuleEditError("找不到当前条件组，请刷新后重试。")

        base = wrapper
        child_id = None
        if wrapper.operator == "logic.not@1.0":
            child_edge = next(
                (
                    edge for edge in graph.edges
                    if edge.target == group_id and edge.port == "condition"
                ),
                None,
            )
            child_id = child_edge.source if child_edge else None
            base = nodes.get(child_id) if child_id else None
        if base is None or base.operator not in {
            "logic.all@1.0", "logic.any@1.0", "reduce.quantify@1.0"
        }:
            raise BusinessRuleEditError("当前步骤不是可编辑的条件组。")
        incoming = [
            edge for edge in graph.edges
            if edge.target == base.node_id and edge.port == "conditions"
        ]
        count = len(incoming)
        if count < 2:
            raise BusinessRuleEditError("至少需要两个条件才能修改组合关系。")
        if operator == "N_OF_M" and not 1 <= int(required_count) <= count:
            raise BusinessRuleEditError(f"N 必须在 1 到 {count} 之间。")

        if operator == "AND":
            base.operator = "logic.all@1.0"
            base.params = {"combine_scope": base.params.get("combine_scope", "by_key")}
            base.display_name = "全部满足（AND）"
        elif operator == "OR":
            base.operator = "logic.any@1.0"
            base.params = {"combine_scope": base.params.get("combine_scope", "by_key")}
            base.display_name = "任一满足（OR）"
        else:
            base.operator = "reduce.quantify@1.0"
            base.params = {
                "mode": "n_of_m",
                "required_count": int(required_count),
                "combine_scope": base.params.get("combine_scope", "by_key"),
            }
            base.display_name = f"至少满足 {int(required_count)} 项（N-of-M）"

        currently_negated = wrapper.operator == "logic.not@1.0"
        if negated and not currently_negated:
            inner_id = f"{group_id}__positive"
            suffix = 2
            while inner_id in nodes:
                inner_id = f"{group_id}__positive_{suffix}"
                suffix += 1
            inner = base.model_copy(
                deep=True,
                update={
                    "node_id": inner_id,
                    "output_name": None,
                    "output_names": [],
                    "business_source_refs": [],
                },
            )
            graph.nodes.append(inner)
            for edge in graph.edges:
                if edge.target == group_id and edge.port == "conditions":
                    edge.target = inner_id
            graph.edges.append(
                RuleEdge(source=inner_id, target=group_id, port="condition")
            )
            wrapper.operator = "logic.not@1.0"
            wrapper.input_bindings = {}
            wrapper.params = {}
            wrapper.display_name = "条件组取反（NOT）"
            branch.node_ids.append(inner_id)
        elif not negated and currently_negated:
            assert child_id is not None
            child = nodes[child_id]
            graph.edges = [
                edge for edge in graph.edges
                if not (edge.source == child_id and edge.target == group_id)
            ]
            for edge in graph.edges:
                if edge.target == child_id:
                    edge.target = group_id
            wrapper.operator = child.operator
            wrapper.input_bindings = deepcopy(child.input_bindings)
            wrapper.params = deepcopy(child.params)
            wrapper.display_name = child.display_name
            graph.nodes = [item for item in graph.nodes if item.node_id != child_id]
            branch.node_ids = [item for item in branch.node_ids if item != child_id]
        result.version += 1
        return refresh_document_hashes(result)

    def copy_condition(
        self, document: SkillEditorDocument, branch_id: str, expression_id: str
    ) -> tuple[SkillEditorDocument, str]:
        if expression_id.startswith(_IMPORTED_STEP_PREFIX):
            raise BusinessRuleEditError(
                "导入流程的组成步骤不能脱离原流程复制；可以复制整个分支。"
            )
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        root = branch.condition_root
        if root is None:
            raise BusinessRuleEditError("当前分支没有可复制条件。")
        target = _find(root, expression_id)
        clone = self._clone_expression(target)
        parent = _find_parent(root, expression_id)
        if parent and parent.operator in {"AND", "OR", "N_OF_M"}:
            data = parent.model_dump(mode="python")
            index = next(
                index
                for index, child in enumerate(parent.children)
                if child.expression_id == expression_id
            )
            data["children"].insert(index + 1, clone.model_dump(mode="python"))
            replacement = ConditionExpression.model_validate(data)
            branch.condition_root = _replace_tree(
                root, parent.expression_id, replacement
            )
        elif parent and parent.operator == "NOT":
            raise BusinessRuleEditError(
                "NOT 组只能包含一个成员；请先取消 NOT，再复制该条件。"
            )
        else:
            branch.condition_root = ConditionExpression(
                expression_id=_new_id("group"),
                operator="AND",
                display_name="全部满足（AND）",
                capability_id="logic.group",
                parameters={"operator": "AND"},
                children=[root, clone],
            )
        result.version += 1
        return refresh_document_hashes(result), clone.expression_id

    def delete_condition(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        expression_id: str,
        *,
        cascade: bool = False,
    ) -> SkillEditorDocument:
        if expression_id.startswith(_IMPORTED_STEP_PREFIX):
            raise BusinessRuleEditError(
                "导入流程的组成步骤不能直接删除；可停用整个分支或新增业务条件替代。"
            )
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        if branch.condition_root is None:
            raise BusinessRuleEditError("当前分支没有可删除条件。")
        _find(branch.condition_root, expression_id)
        targets = {expression_id}

        def references_target(value: Any) -> bool:
            if isinstance(value, str):
                return value.startswith("condition:") and value.split(":", 1)[1] in targets
            if isinstance(value, list):
                return any(references_target(item) for item in value)
            if isinstance(value, dict):
                return any(references_target(item) for item in value.values())
            return False

        while True:
            dependents = {
                item.expression_id
                for candidate_branch in result.skill_template.business_branches
                for item in _walk(candidate_branch.condition_root)
                if item.expression_id not in targets
                and references_target(item.parameters)
            }
            new_dependents = dependents - targets
            if not new_dependents:
                break
            if not cascade:
                names = [
                    item.display_name
                    for candidate_branch in result.skill_template.business_branches
                    for item in _walk(candidate_branch.condition_root)
                    if item.expression_id in new_dependents
                ]
                raise BusinessRuleEditError(
                    "该条件仍被以下条件引用："
                    + "、".join(names)
                    + "。请先删除依赖条件，或选择“删除（含依赖）”。"
                )
            targets.update(new_dependents)

        for candidate_branch in result.skill_template.business_branches:
            root = candidate_branch.condition_root
            if root is None:
                continue
            for target_id in list(targets):
                root = _delete_from_tree(root, target_id) if root is not None else None
            candidate_branch.condition_root = root
        result.version += 1
        return refresh_document_hashes(result)

    def update_condition(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        expression_id: str,
        *,
        display_name: str | None = None,
        parameters: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> SkillEditorDocument:
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        if expression_id.startswith(_IMPORTED_STEP_PREFIX):
            node_id = expression_id[len(_IMPORTED_STEP_PREFIX):]
            graph = result.skill_template.rule_graphs.get(branch.media_type)
            node = next(
                (item for item in (graph.nodes if graph else []) if item.node_id == node_id),
                None,
            )
            capability_id = self._matched_capability_for_operator(
                node.operator if node else None
            )
            if node is None or capability_id is None:
                raise BusinessRuleEditError("当前导入步骤已不存在，请刷新后重试。")
            definition = self.capabilities.require(capability_id)
            if display_name is not None:
                name = display_name.strip()
                if not name:
                    raise BusinessRuleEditError("条件名称不能为空。")
                node.display_name = name
            if enabled is not None:
                node.enabled = enabled
            if parameters is not None:
                imported_parameters = self._imported_parameter_definitions(
                    definition, node
                )
                known = {
                    item.parameter_id: item for item in imported_parameters
                }
                unknown = set(parameters) - set(known)
                if unknown:
                    raise BusinessRuleEditError(
                        "包含当前步骤不支持的配置项：" + "、".join(sorted(unknown))
                    )
                normalized = {
                    key: self._coerce(known[key], value)
                    for key, value in parameters.items()
                    if value not in (None, "")
                }
                imported_definition = definition.model_copy(
                    update={"parameters": imported_parameters}
                )
                self._apply_existing_node_parameters(
                    node, imported_definition, normalized
                )
            result.version += 1
            return refresh_document_hashes(result)
        if branch.condition_root is None:
            raise BusinessRuleEditError("当前分支没有可编辑条件。")
        target = _find(branch.condition_root, expression_id)
        data = target.model_dump(mode="python")
        if display_name is not None:
            name = display_name.strip()
            if not name:
                raise BusinessRuleEditError("条件名称不能为空。")
            data["display_name"] = name
        if enabled is not None:
            data["enabled"] = enabled
        if parameters is not None:
            if target.operator != "ATOM" or not target.capability_id:
                raise BusinessRuleEditError("条件组请使用逻辑关系设置，不填写业务参数。")
            definition = self.capabilities.require(target.capability_id)
            normalized, sources = self._validate_parameters(definition, parameters)
            data["parameters"] = normalized
            data["parameter_sources"] = {
                key: value.model_dump(mode="python") for key, value in sources.items()
            }
            self._validate_sources(branch.condition_root, expression_id, definition, normalized)
            self._apply_parameter_mappings(result, branch, target, definition, normalized)
        replacement = ConditionExpression.model_validate(data)
        branch.condition_root = _replace_tree(
            branch.condition_root, expression_id, replacement
        )
        result.version += 1
        return refresh_document_hashes(result)

    def set_complex_pattern(
        self,
        document: SkillEditorDocument,
        media_type: str,
        mode: str,
        branch_ids: list[str],
        *,
        window_seconds: float | None = None,
        required_count: int | None = None,
        correlation_scope: str = "global",
        display_name: str = "复杂事件",
    ) -> SkillEditorDocument:
        result = self.prepare(document).model_copy(deep=True)
        branches = {
            branch.branch_id: branch
            for branch in result.skill_template.business_branches
            if branch.media_type == media_type
        }
        # Backwards compatible with the original branch-id-only API while also
        # accepting event:<pattern_id> so one orchestration group can be reused
        # as an input of another group.
        selected = list(
            dict.fromkeys(
                item if ":" in item else f"branch:{item}"
                for item in (branch_ids or [])
            )
        )
        patterns = {
            pattern.pattern_id: pattern
            for pattern in result.skill_template.event_patterns
            if pattern.media_type == media_type
        }
        unknown = []
        for source_ref in selected:
            prefix, source_id = source_ref.split(":", 1)
            if prefix == "branch" and source_id in branches:
                continue
            if prefix == "event" and source_id in patterns:
                continue
            unknown.append(source_ref)
        if unknown:
            raise BusinessRuleEditError("分支编排引用了已不存在的分支或编排组，请重新选择。")
        if mode == "none":
            result.skill_template.event_patterns = [
                pattern
                for pattern in result.skill_template.event_patterns
                if pattern.media_type != media_type
            ]
            result.version += 1
            return refresh_document_hashes(result)
        if media_type != "video" and mode == "sequence":
            raise BusinessRuleEditError("顺序关系需要视频流程；图片分支可使用并行、互斥、任意或部分汇聚。")
        minimum = 1 if mode == "repeat" else 2
        if len(selected) < minimum:
            raise BusinessRuleEditError(f"当前编排方式至少需要选择{minimum}个分支。")
        if mode == "absence" and len(selected) != 2:
            raise BusinessRuleEditError("“未发生”需要依次选择锚点分支和禁止发生分支。")
        if mode in {"all_completed_within_window", "absence", "repeat"}:
            if window_seconds is None or float(window_seconds) <= 0:
                raise BusinessRuleEditError("当前编排方式需要填写大于0秒的时间窗口。")
        if mode == "n_of_m":
            if required_count is None or not 1 <= int(required_count) <= len(selected):
                raise BusinessRuleEditError("至少完成分支数 N 必须在1和已选分支数之间。")
        stages = []
        for index, source_ref in enumerate(selected, start=1):
            prefix, source_id = source_ref.split(":", 1)
            if prefix == "branch":
                source = branches[source_id]
                source_rule_id = source.root_node_id or source_id
            else:
                source = patterns[source_id]
                source_rule_id = f"event_{source_id}"
            stages.append(
                PatternStage(
                    stage_id=f"stage_{index}",
                    display_name=source.display_name,
                    source_rule_id=source_rule_id,
                    source_ref=source_ref,
                )
            )
        transitions = []
        gateways = []
        pattern_type = "join"
        parameters: dict[str, Any] = {}
        if mode == "sequence":
            pattern_type = "sequence"
            transitions = [
                PatternTransition(
                    source_stage_id=stages[index].stage_id,
                    target_stage_id=stages[index + 1].stage_id,
                    relation="after",
                    minimum_delay_seconds=0,
                    maximum_delay_seconds=(
                        ResolvableValue(
                            state="explicit",
                            value=float(window_seconds),
                            source="user",
                            required_before="never",
                        )
                        if window_seconds is not None and float(window_seconds) > 0
                        else ResolvableValue(
                            state="not_applicable",
                            value=None,
                            source="system",
                            required_before="never",
                        )
                    ),
                )
                for index in range(len(stages) - 1)
            ]
        elif mode == "absence":
            pattern_type = "absence"
            parameters = {"window_seconds": float(window_seconds)}
        elif mode == "repeat":
            pattern_type = "repeat"
            parameters = {
                "window_seconds": float(window_seconds),
                "minimum_count": int(required_count or 2),
            }
        else:
            window = (
                ResolvableValue(
                    state="explicit",
                    value=float(window_seconds),
                    source="user",
                    required_before="never",
                )
                if mode == "all_completed_within_window"
                else ResolvableValue(
                    state="not_applicable",
                    value=None,
                    source="system",
                    required_before="never",
                )
            )
            gateways = [
                PatternGateway(
                    gateway_id="join",
                    mode=mode,  # type: ignore[arg-type]
                    stage_ids=[stage.stage_id for stage in stages],
                    required_count=(int(required_count) if mode == "n_of_m" else None),
                    window_seconds=window,
                )
            ]
        # Saving the same ordered inputs edits that group; using a different
        # set creates another reusable group.  This permits sequence(A,B) and
        # sequence(C,D) to coexist and later participate in a parent join.
        result.skill_template.event_patterns = [
            pattern
            for pattern in result.skill_template.event_patterns
            if not (
                pattern.media_type == media_type
                and [stage.source_ref for stage in pattern.stages] == selected
            )
        ]
        result.skill_template.event_patterns.append(
            EventPattern(
                pattern_id=_new_id("pattern"),
                display_name=display_name.strip() or "复杂事件",
                media_type=media_type,  # type: ignore[arg-type]
                pattern_type=pattern_type,
                stages=stages,
                transitions=transitions,
                gateways=gateways,
                correlation=CorrelationPolicy(scope=correlation_scope),  # type: ignore[arg-type]
                instance_policy=InstancePolicy(),
                parameters=parameters,
            )
        )
        result.version += 1
        return refresh_document_hashes(result)

    def set_branch_time_policy(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        *,
        mode: str = "immediate",
        duration_seconds: float | None = None,
        observation_window_seconds: float | None = None,
        required_ratio: float = 1.0,
        allowed_gap_seconds: float = 0.0,
        identity_scope: str = "global",
        emission: str = "first",
        validity_mode: str = "current_frame",
        hold_seconds: float | None = None,
    ) -> SkillEditorDocument:
        """Set the independent temporal and active-state policy of one branch."""

        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        if mode != "immediate" and branch.media_type != "video":
            raise BusinessRuleEditError(
                "持续、累计和窗口占比需要视频；图片分支只能立即判断。"
            )
        if mode in {"continuous", "cumulative"} and duration_seconds is None:
            raise BusinessRuleEditError("请填写分支需要满足的持续时间。")
        if mode in {"cumulative", "ratio"} and observation_window_seconds is None:
            raise BusinessRuleEditError("请填写累计或占比的观察窗口。")
        if mode == "ratio" and not 0 <= float(required_ratio) <= 1:
            raise BusinessRuleEditError("窗口满足比例应在 0% 到 100% 之间。")
        if validity_mode == "hold_for" and hold_seconds is None:
            raise BusinessRuleEditError("请填写分支成立后的保持时间。")
        try:
            branch.temporal_qualifiers = []
            if mode != "immediate":
                branch.temporal_qualifiers = [
                    TemporalQualifierSpec(
                        qualifier_id=f"{branch.branch_id}_time",
                        display_name=f"{branch.display_name}时间约束",
                        target_ref=f"branch:{branch.branch_id}",
                        mode=mode,  # type: ignore[arg-type]
                        duration_seconds=(
                            ResolvableValue(
                                state="explicit",
                                value=float(duration_seconds or 0.0),
                                source="user",
                                required_before="run",
                            )
                            if mode in {"continuous", "cumulative"}
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
                                value=float(observation_window_seconds),
                                source="user",
                                required_before="run",
                            )
                            if mode in {"cumulative", "ratio"}
                            else ResolvableValue(
                                state="not_applicable",
                                value=None,
                                source="system",
                                required_before="never",
                            )
                        ),
                        allowed_gap_seconds=float(allowed_gap_seconds or 0.0),
                        required_ratio=float(required_ratio),
                        identity_scope=identity_scope,  # type: ignore[arg-type]
                        emission=emission,  # type: ignore[arg-type]
                    )
                ]
            branch.validity_policy = BranchValidityPolicy(
                mode=validity_mode,  # type: ignore[arg-type]
                hold_seconds=(
                    ResolvableValue(
                        state="explicit",
                        value=float(hold_seconds),
                        source="user",
                        required_before="run",
                    )
                    if validity_mode == "hold_for"
                    else ResolvableValue(
                        state="not_applicable",
                        value=None,
                        source="system",
                        required_before="never",
                    )
                ),
            )
        except ValueError as exc:
            raise BusinessRuleEditError("分支时间配置无效，请检查时间和比例。") from exc
        result.version += 1
        return refresh_document_hashes(result)

    def set_final_decision(
        self,
        document: SkillEditorDocument,
        display_name: str,
        decision_type: str,
        source_ref: str,
        *,
        source_refs: list[str] | None = None,
        combination: str = "AND",
        required_count: int | None = None,
        show_reason: bool = True,
        show_failed_or_pending_branches: bool = True,
    ) -> SkillEditorDocument:
        result = self.prepare(document).model_copy(deep=True)
        available = {
            item["value"]
            for item in self.source_catalog(result, include_final=False)
        }
        available.update(f"result:{item.result_id}" for item in result.skill_template.result_specs)
        selected_sources = list(dict.fromkeys(source_refs or [source_ref]))
        if not selected_sources or any(item not in available for item in selected_sources):
            raise BusinessRuleEditError("最终判定来源已不存在，请重新选择。")
        try:
            media_types = sorted(
                {
                    branch.media_type
                    for branch in result.skill_template.business_branches
                    if branch.enabled
                }
            )
            media_source_refs = partition_source_refs(
                result.skill_template, selected_sources, media_types
            )
            if any(
                media_type not in media_source_refs for media_type in media_types
            ):
                raise BusinessRuleEditError(
                    "最终判定必须为每个图片/视频流程至少选择一个同媒体来源。"
                )
            result.skill_template.final_decision = FinalDecisionSpec(
                decision_id="primary",
                display_name=display_name.strip() or "最终结果",
                decision_type=decision_type,  # type: ignore[arg-type]
                source_ref=selected_sources[0],
                source_refs=selected_sources,
                media_source_refs=media_source_refs,
                combination=combination,  # type: ignore[arg-type]
                required_count=(
                    int(required_count or 1)
                    if combination == "N_OF_M"
                    else None
                ),
                show_reason=show_reason,
                show_failed_or_pending_branches=show_failed_or_pending_branches,
            )
        except ValueError as exc:
            raise BusinessRuleEditError("最终判定配置不完整，请检查类型和来源。") from exc
        result.version += 1
        return refresh_document_hashes(result)

    def set_trigger_policy(
        self,
        document: SkillEditorDocument,
        *,
        mode: str,
        cooldown_seconds: float,
        severity: str,
        outputs: list[str],
    ) -> SkillEditorDocument:
        result = self.prepare(document).model_copy(deep=True)
        try:
            result.skill_template.trigger_policy = TriggerPolicy(
                mode=mode,  # type: ignore[arg-type]
                trigger_moment={
                    "none": "first_satisfied",
                    "once": "first_satisfied",
                    "repeat": "while_satisfied",
                    "on_change": "false_to_true",
                }.get(mode, "first_satisfied"),
                repeat_policy={
                    "none": "first_only",
                    "once": "first_only",
                    "repeat": "allow_repeat",
                    "on_change": "after_reset",
                }.get(mode, "first_only"),
                cooldown_seconds=float(cooldown_seconds or 0),
                severity=severity,  # type: ignore[arg-type]
                outputs=outputs or ["event_record"],  # type: ignore[arg-type]
            )
        except ValueError as exc:
            raise BusinessRuleEditError("触发策略配置无效，请检查冷却时间和输出选项。") from exc
        result.version += 1
        return refresh_document_hashes(result)

    def set_result_rows(
        self,
        document: SkillEditorDocument,
        rows: list[dict[str, Any]],
    ) -> SkillEditorDocument:
        if not rows:
            raise BusinessRuleEditError("至少需要保留一个业务输出。")
        result = self.prepare(document).model_copy(deep=True)
        available = {item["value"] for item in self.source_catalog(result)}
        specs = []
        presentations = []
        seen_names = set()
        for index, row in enumerate(rows):
            name = str(row.get("display_name") or "").strip()
            if not name:
                raise BusinessRuleEditError(f"第{index + 1}个业务输出缺少名称。")
            if name in seen_names:
                raise BusinessRuleEditError("业务输出名称不能重复。")
            seen_names.add(name)
            source_ref = str(row.get("source_ref") or "")
            if source_ref not in available and not source_ref.startswith(("node:", "output:")):
                raise BusinessRuleEditError(f"业务输出“{name}”的来源已不存在。")
            result_kind = str(row.get("result_kind") or "decision")
            schema = _RESULT_KIND_SCHEMA.get(result_kind)
            if schema is None:
                raise BusinessRuleEditError(f"业务输出“{name}”选择了不支持的结果类型。")
            semantic_type, value_shape, projection_kind = schema
            source_media = source_media_types(result.skill_template, source_ref)
            existing_id = str(row.get("result_id") or "").strip()
            result_id = existing_id or _new_id("result")
            specs.append(
                ResultSpec(
                    result_id=result_id,
                    display_name=name,
                    semantic_type=semantic_type,  # type: ignore[arg-type]
                    value_shape=value_shape,  # type: ignore[arg-type]
                    source_ref=source_ref,
                    media_types=sorted(source_media),  # type: ignore[arg-type]
                    projection=ResultProjection(kind=projection_kind),  # type: ignore[arg-type]
                    unit=str(row.get("unit") or "").strip() or None,
                    evidence_policy=str(row.get("evidence_policy") or "optional"),  # type: ignore[arg-type]
                    save_policy=str(row.get("save_policy") or "always"),  # type: ignore[arg-type]
                    empty_policy=("zero" if result_kind == "count" else "empty"),
                )
            )
            presentations.append(
                PresentationSpec(
                    result_id=result_id,
                    preferred_renderer="generic.summary",
                    show_in_overview=bool(row.get("show_in_overview", True)),
                    display_order=index,
                )
            )
        result.skill_template.result_specs = specs
        result.skill_template.presentation_specs = presentations
        for branch in result.skill_template.business_branches:
            branch.result_ids = [
                spec.result_id
                for spec in specs
                if spec.source_ref == f"branch:{branch.branch_id}"
            ]
        final = result.skill_template.final_decision
        if final and final.source_ref.startswith("result:"):
            final_id = final.source_ref.split(":", 1)[1]
            if final_id not in {item.result_id for item in specs}:
                final.source_ref = f"result:{specs[0].result_id}"
        result.version += 1
        return refresh_document_hashes(result)

    def source_catalog(
        self, document: SkillEditorDocument, *, include_final: bool = True
    ) -> list[dict[str, str]]:
        prepared = self.prepare(document)
        result: list[dict[str, str]] = []
        for branch in prepared.skill_template.business_branches:
            result.append(
                {
                    "value": f"branch:{branch.branch_id}",
                    "label": f"分支 / {branch.display_name}",
                    "type": "branch",
                }
            )
            for expression in _walk(branch.condition_root):
                if expression.operator != "ATOM":
                    continue
                definition = (
                    self.capabilities.require(expression.capability_id)
                    if expression.capability_id
                    else None
                )
                result.append(
                    {
                        "value": f"condition:{expression.expression_id}",
                        "label": f"{branch.display_name} / {expression.display_name}",
                        "type": definition.output_value_type if definition else "any",
                    }
                )
        for pattern in prepared.skill_template.event_patterns:
            result.append(
                {
                    "value": f"event:{pattern.pattern_id}",
                    "label": f"复杂事件 / {pattern.display_name}",
                    "type": "event_set",
                }
            )
        final = prepared.skill_template.final_decision
        if include_final and final is not None:
            result.append(
                {
                    "value": f"final:{final.decision_id}",
                    "label": f"最终判定 / {final.display_name}",
                    "type": "decision",
                }
            )
        return result

    def result_rows(self, document: SkillEditorDocument) -> list[dict[str, Any]]:
        prepared = self.prepare(document)
        presentation_by_id = {
            item.result_id: item
            for item in prepared.skill_template.presentation_specs
        }
        rows = []
        for spec in prepared.skill_template.result_specs:
            presentation = presentation_by_id.get(spec.result_id)
            rows.append(
                {
                    "result_id": spec.result_id,
                    "display_name": spec.display_name,
                    "source_ref": spec.source_ref or "",
                    "result_kind": self._result_kind(spec),
                    "unit": spec.unit or "",
                    "evidence_policy": spec.evidence_policy,
                    "save_policy": spec.save_policy,
                    "show_in_overview": (
                        presentation.show_in_overview if presentation else True
                    ),
                }
            )
        return rows

    @staticmethod
    def _result_kind(spec: ResultSpec) -> str:
        for kind, schema in _RESULT_KIND_SCHEMA.items():
            if (
                spec.semantic_type,
                spec.value_shape,
                spec.projection.kind,
            ) == schema:
                return kind
        return "value"

    def branch_rows(
        self, document: SkillEditorDocument, media_type: str
    ) -> list[dict[str, Any]]:
        prepared = self.prepare(document)
        rows = []
        for branch in prepared.skill_template.business_branches:
            if branch.media_type != media_type:
                continue
            condition_count = sum(
                1
                for item in self.condition_rows(prepared, branch.branch_id)
                if item["kind"] == "条件"
            )
            rows.append({
                "branch_id": branch.branch_id,
                "display_name": branch.display_name,
                "enabled": branch.enabled,
                "condition_count": condition_count,
                "summary": self.expression_summary(branch.condition_root),
            })
        return rows

    def condition_rows(
        self, document: SkillEditorDocument, branch_id: str
    ) -> list[dict[str, Any]]:
        prepared = self.prepare(document)
        branch = self._branch(prepared, branch_id)
        rows: list[dict[str, Any]] = []
        expressions = {
            expression.expression_id: expression
            for expression in _walk(branch.condition_root)
        }

        def condition_reference(value: Any) -> str:
            if isinstance(value, str) and value.startswith("condition:"):
                source = expressions.get(value.split(":", 1)[1])
                return source.display_name if source else "前序条件"
            if isinstance(value, list):
                return "、".join(condition_reference(item) for item in value)
            return str(value)

        def condition_card_text(
            item: ConditionExpression,
            definition: BusinessCapabilityDefinition,
        ) -> tuple[str, str]:
            params = item.parameters
            object_values: list[str] = []
            for parameter_id in (
                "targets", "labels", "business_label", "source", "subject",
                "object", "equipment", "color", "part", "relation", "dimension",
            ):
                value = params.get(parameter_id)
                if value in (None, "", [], {}):
                    continue
                text = condition_reference(value)
                if text and text not in object_values:
                    object_values.append(text)
            details = "、".join(object_values)
            if item.display_name != definition.display_name:
                title = item.display_name
            elif details:
                title = f"{definition.display_name}：{details}"
            else:
                title = definition.display_name
            if details:
                summary = f"针对「{details}」执行“{definition.display_name}”。"
            else:
                configured = [
                    f"{parameter.label}={condition_reference(params.get(parameter.parameter_id))}"
                    for parameter in definition.parameters
                    if parameter.parameter_id in params
                    and params.get(parameter.parameter_id) not in (None, "", [], {})
                    and parameter.parameter_id not in {
                        "source", "scope", "operator", "threshold"
                    }
                ]
                suffix = "；".join(configured[:3])
                summary = (
                    f"执行“{definition.display_name}”"
                    + (f"（{suffix}）" if suffix else "，等待补充具体对象。")
                    + "。"
                )
            return title, summary

        def visit(item: ConditionExpression, parent: str | None, depth: int) -> None:
            definition = (
                self.capabilities.require(item.capability_id)
                if item.capability_id and item.operator == "ATOM"
                else None
            )
            name, summary = (
                condition_card_text(item, definition)
                if definition is not None
                else (item.display_name, self.expression_summary(item, compact=True))
            )
            rows.append(
                {
                    "condition_id": item.expression_id,
                    "parent_id": parent,
                    "depth": depth,
                    "kind": "条件" if item.operator == "ATOM" else "条件组",
                    "logic": item.operator,
                    "capability_id": item.capability_id,
                    "category": definition.category if definition else "逻辑组合",
                    "name": name,
                    "summary": summary,
                    "enabled": item.enabled,
                    "status": self._condition_status(item, definition),
                }
            )
            for child in item.children:
                visit(child, item.expression_id, depth + 1)

        root = branch.condition_root
        is_imported_proxy = bool(
            root
            and root.operator == "ATOM"
            and root.source_ref
            and root.source_ref.startswith("node:")
        )
        if root is not None:
            visit(root, None, 0)
            generated_rows = {
                row["condition_id"]: row
                for row in rows
                if not row.get("imported_step")
            }
            for row in list(generated_rows.values()):
                if row["kind"] != "条件组":
                    continue
                members = [
                    child
                    for child in generated_rows.values()
                    if child.get("parent_id") == row["condition_id"]
                ]
                if not members:
                    continue
                relation = row["logic"]
                if relation == "N_OF_M":
                    expression = _find(root, row["condition_id"])
                    relation = f"至少 {expression.required_count or 1} 项满足"
                row["member_summaries"] = [
                    child["summary"] for child in members
                ]
                row["logic_relation_label"] = relation
                for index, child in enumerate(members):
                    child["logic_member_label"] = (
                        f"条件 {chr(65 + index)}"
                        if index < 26
                        else f"条件 {index + 1}"
                    )
            if is_imported_proxy:
                rows[0]["kind"] = "导入判定"
                rows[0]["category"] = "已验证业务流程"
                rows[0]["status"] = "保持原有执行效果"
                rows[0]["formula_kind"] = "workflow"
                graph = prepared.skill_template.rule_graphs.get(branch.media_type)
                imported_rows: dict[str, dict[str, Any]] = {}
                logic_members: dict[str, list[str]] = {}
                graph_nodes = {
                    node.node_id: node for node in (graph.nodes if graph else [])
                }
                incoming_edges: dict[str, list[RuleEdge]] = {}
                for edge in (graph.edges if graph else []):
                    incoming_edges.setdefault(edge.target, []).append(edge)

                def incoming_nodes(node_id: str, *ports: str) -> list[RuleNode]:
                    accepted = set(ports)
                    return [
                        graph_nodes[edge.source]
                        for edge in incoming_edges.get(node_id, [])
                        if edge.source in graph_nodes
                        and (not accepted or edge.port in accepted)
                    ]

                @lru_cache(maxsize=None)
                def node_labels(node_id: str) -> tuple[str, ...]:
                    node = graph_nodes.get(node_id)
                    if node is None:
                        return ()
                    output_label = node.params.get("output_label")
                    if isinstance(output_label, str) and output_label.strip():
                        return (output_label.strip(),)
                    targets = node.params.get("targets")
                    if isinstance(targets, list):
                        labels = [
                            str(target.get("label", "")).strip()
                            for target in targets
                            if isinstance(target, dict)
                            and str(target.get("label", "")).strip()
                        ]
                        if labels:
                            return tuple(dict.fromkeys(labels))
                    selected = node.params.get("labels")
                    if isinstance(selected, list) and selected:
                        selected_labels = tuple(
                            dict.fromkeys(
                                str(label).strip()
                                for label in selected
                                if str(label).strip()
                            )
                        )
                        if node.params.get("mode", "include") == "include":
                            return selected_labels
                        upstream = [
                            label
                            for source in incoming_nodes(node_id, "objects", "entities")
                            for label in node_labels(source.node_id)
                            if label not in selected_labels
                        ]
                        if upstream:
                            return tuple(dict.fromkeys(upstream))
                    preferred_ports = (
                        "objects", "entities", "subjects", "tracks", "pairs",
                        "condition", "conditions", "value", "measurement", "left",
                    )
                    labels = [
                        label
                        for source in incoming_nodes(node_id, *preferred_ports)
                        for label in node_labels(source.node_id)
                    ]
                    return tuple(dict.fromkeys(labels))

                def input_label(
                    node: RuleNode, ports: tuple[str, ...], fallback: str
                ) -> str:
                    labels = [
                        label
                        for source in incoming_nodes(node.node_id, *ports)
                        for label in node_labels(source.node_id)
                    ]
                    return "、".join(dict.fromkeys(labels)) or fallback

                def object_region_name(value: Any) -> str:
                    if value == [0.0, 0.0, 1.0, 1.0]:
                        return "完整范围"
                    if (
                        isinstance(value, list)
                        and len(value) == 4
                        and all(isinstance(item, (int, float)) for item in value)
                        and value[1] < 0
                        and value[3] <= 0.5
                    ):
                        return "上沿区域"
                    return "指定相对区域"

                def describe_imported_node(
                    node: RuleNode, definition: BusinessCapabilityDefinition
                ) -> tuple[str, str]:
                    labels = "、".join(node_labels(node.node_id)) or "前序结果"
                    operator = node.operator or ""
                    if operator.startswith("rex.ground@"):
                        return f"检测：{labels}", f"从画面中识别「{labels}」。"
                    if operator.startswith("objects.filter_by_label@"):
                        selected = (
                            "、".join(str(item) for item in node.params.get("labels", []))
                            or "指定类别"
                        )
                        source = input_label(
                            node, ("objects", "entities"), "前序检测结果"
                        )
                        action = (
                            "保留"
                            if node.params.get("mode", "include") == "include"
                            else "排除"
                        )
                        return (
                            f"{action}：{selected}",
                            f"从「{source}」中{action}「{selected}」。",
                        )
                    if operator.startswith(
                        ("spatial.associate@", "pairs.filter@")
                    ):
                        subject = input_label(
                            node, ("subjects", "subject"), "主体目标"
                        )
                        obj = input_label(
                            node, ("objects", "object"), "关联目标"
                        )
                        relation = str(node.params.get("relation", "关联"))
                        template = _RELATION_LABELS.get(
                            relation, "与{object}满足“" + relation + "”关系"
                        )
                        relation_text = template.format(
                            object=obj,
                            region=object_region_name(
                                node.params.get("object_region")
                            ),
                        )
                        return (
                            f"判断：{subject}{relation_text}",
                            f"以「{subject}」为主体，判断其是否{relation_text}。",
                        )
                    if operator.startswith(
                        ("measure.count@", "measure.region_count@", "reduce.count@")
                    ):
                        source = input_label(
                            node, ("entities", "objects", "tracks"), labels
                        )
                        group = (
                            "，并按类别分组"
                            if node.params.get("group_by") == "label"
                            else ""
                        )
                        return (
                            f"统计：{source}数量",
                            f"统计「{source}」的数量{group}。",
                        )
                    if operator.startswith("temporal.persist@"):
                        seconds = float(node.params.get("seconds", 0))
                        source = input_label(
                            node, ("condition", "conditions"), labels
                        )
                        return (
                            f"持续判断：{source}",
                            f"要求「{source}」持续 {seconds:g} 秒。",
                        )
                    if operator.startswith("logic.not@"):
                        source = input_label(
                            node, ("condition", "conditions"), labels
                        )
                        return (
                            f"排除：{source}",
                            f"仅保留不满足「{source}」的结果。",
                        )
                    return (
                        f"{definition.display_name}：{labels}",
                        f"对「{labels}」执行“{definition.display_name}”："
                        f"{definition.description}",
                    )

                def comparison_subject(node: RuleNode) -> tuple[str, str]:
                    """Return a business label and unit for an imported comparison."""

                    source_edge = next(
                        (
                            edge
                            for edge in incoming_edges.get(node.node_id, [])
                            if edge.port in {"left", "value", "measurement"}
                        ),
                        None,
                    )
                    if source_edge is None:
                        source_edge = next(
                            iter(incoming_edges.get(node.node_id, [])), None
                        )
                    source = graph_nodes.get(source_edge.source) if source_edge else None
                    if source is None:
                        return "数值", ""
                    label_and_unit = {
                        "measure.region_count@1.0": ("每个区域的目标数量", ""),
                        "measure.count@1.0": ("目标数量", ""),
                        "reduce.count@1.0": ("目标数量", ""),
                        "measure.region_speed@1.0": (
                            "每个区域的目标速度",
                            " 像素/秒"
                            if source.params.get("unit") == "pixels_per_second"
                            else "",
                        ),
                        "measure.speed@1.0": (
                            "目标速度",
                            " 像素/秒"
                            if source.params.get("unit") == "pixels_per_second"
                            else "",
                        ),
                    }
                    if source.operator in label_and_unit:
                        return label_and_unit[source.operator]
                    capability_id = self._matched_capability_for_operator(
                        source.operator
                    )
                    if capability_id:
                        return self.capabilities.require(capability_id).display_name, ""
                    return source.display_name, ""

                for node in (graph.nodes if graph else []):
                    if node.node_id not in branch.node_ids or not node.enabled:
                        continue
                    capability_id = self._matched_capability_for_operator(node.operator)
                    if capability_id is None:
                        continue
                    definition = self.capabilities.require(capability_id)
                    logic = {
                        "logic.all@1.0": "AND",
                        "logic.any@1.0": "OR",
                        "logic.not@1.0": "NOT",
                        "reduce.quantify@1.0": "N_OF_M",
                    }.get(node.operator, "ATOM")
                    display_name, summary = describe_imported_node(node, definition)
                    if node.operator == "logic.compare@1.0":
                        value = node.params.get("value", node.params.get("threshold"))
                        subject, unit = comparison_subject(node)
                        summary = (
                            f"{subject} {node.params.get('operator', '>=')} {value:g}{unit}"
                            if isinstance(value, (int, float))
                            else definition.display_name
                        )
                        display_name = f"{subject}判断"
                    elif node.operator in {
                        "temporal.persist@1.0", "event.from_condition@1.0"
                    }:
                        summary = f"持续 {float(node.params.get('seconds', 0)):g} 秒"
                    imported_rows[node.node_id] = {
                            "condition_id": f"{_IMPORTED_STEP_PREFIX}{node.node_id}",
                            "parent_id": root.expression_id,
                            "depth": 1,
                            "kind": "条件组" if logic != "ATOM" else "条件",
                            "logic": logic,
                            "category": definition.category,
                            "name": display_name,
                            "summary": summary,
                            "enabled": node.enabled,
                            "status": (
                                "当前生效逻辑，可在下方修改"
                                if logic != "ATOM"
                                else "原有流程步骤，可修改关键参数"
                            ),
                            "capability_id": capability_id,
                            "imported_step": True,
                            # Data-flow dependency is not a user-facing nesting
                            # level. Imported executable steps are rendered as
                            # one aligned sequence; actual AND/OR/NOT nodes keep
                            # their badges and are edited in the logic control.
                            "display_depth": 0,
                        }
                if graph:
                    consumers: dict[str, list[str]] = {}
                    for edge in graph.edges:
                        if edge.source in imported_rows and edge.target in imported_rows:
                            consumers.setdefault(edge.source, []).append(edge.target)
                    for node_id, row in imported_rows.items():
                        candidates = consumers.get(node_id, [])
                        if candidates:
                            parent_node_id = candidates[-1]
                            row["parent_id"] = imported_rows[parent_node_id]["condition_id"]

                    def imported_depth(node_id: str, seen: set[str] | None = None) -> int:
                        seen = set() if seen is None else seen
                        if node_id in seen:
                            return 1
                        seen.add(node_id)
                        parent = imported_rows[node_id]["parent_id"]
                        if parent == root.expression_id:
                            return 1
                        parent_id = parent[len(_IMPORTED_STEP_PREFIX):]
                        return 1 + imported_depth(parent_id, seen)

                    for node_id, row in imported_rows.items():
                        row["depth"] = imported_depth(node_id)

                    for node_id, row in imported_rows.items():
                        if row["kind"] != "条件组":
                            continue
                        members = [
                            edge.source
                            for edge in incoming_edges.get(node_id, [])
                            if edge.source in imported_rows
                            and edge.port in {"conditions", "condition"}
                        ]
                        if not members:
                            members = [
                                child_id
                                for child_id, child in imported_rows.items()
                                if child["parent_id"] == row["condition_id"]
                            ]
                        logic_members[node_id] = members

                    def logic_summary(
                        node_id: str, seen: set[str] | None = None
                    ) -> str:
                        seen = set() if seen is None else set(seen)
                        if node_id in seen:
                            return imported_rows[node_id]["summary"]
                        seen.add(node_id)
                        row = imported_rows[node_id]
                        members = logic_members.get(node_id, [])
                        if row["kind"] != "条件组" or not members:
                            return row["summary"]
                        member_summaries = [
                            logic_summary(member_id, seen)
                            for member_id in members
                        ]
                        relation = row["logic"]
                        if relation == "N_OF_M":
                            source_node = graph_nodes[node_id]
                            relation = (
                                f"至少 {source_node.params.get('required_count', 1)} 项满足"
                            )
                        if relation == "NOT":
                            summary = f"NOT（{member_summaries[0]}）"
                            member_id = logic_members.get(node_id, [None])[0]
                            member_name = (
                                imported_rows[member_id]["name"]
                                if member_id in imported_rows
                                else member_summaries[0]
                            )
                            row["name"] = f"排除：{member_name.removeprefix('判断：')}"
                        else:
                            summary = f" {relation} ".join(member_summaries)
                        row["summary"] = summary
                        row["member_summaries"] = member_summaries
                        row["logic_relation_label"] = relation
                        for index, member_id in enumerate(members):
                            imported_rows[member_id]["logic_member_label"] = (
                                f"条件 {chr(65 + index)}"
                                if index < 26
                                else f"条件 {index + 1}"
                            )
                        return summary

                    for node_id in logic_members:
                        logic_summary(node_id)
                rows.extend(imported_rows.values())
                for index, row in enumerate(imported_rows.values(), start=1):
                    row["workflow_index"] = index
                logic_rows = [
                    row for row in imported_rows.values()
                    if row["kind"] == "条件组"
                ]
                if logic_rows:
                    logical_result = logic_rows[-1]["summary"]
                else:
                    logical_result = ""
                grouped_member_ids = {
                    member_id
                    for member_ids in logic_members.values()
                    for member_id in member_ids
                }
                workflow_parts = []
                for node_id, row in imported_rows.items():
                    # A logic operand is represented inside its parenthesized
                    # group. Repeating it as another arrow step is ambiguous.
                    if node_id in grouped_member_ids:
                        continue
                    # Label filters and NOT wrappers are executable
                    # bookkeeping, not separate business actions. Showing
                    # them as arrows made generated workflows look longer
                    # than their actual intent (for example, "保留垃圾容器
                    # → 排除垃圾堆"). Keep the concrete detection,
                    # relation, counting and temporal steps visible instead.
                    if row["name"].startswith(("保留：", "排除：")):
                        continue
                    if row["kind"] == "条件组":
                        workflow_parts.append(f"（{row['summary']}）")
                    elif row["summary"].startswith("持续 "):
                        workflow_parts.append(row["summary"])
                    else:
                        workflow_parts.append(row["name"])
                rows[0]["summary"] = " → ".join(workflow_parts) or logical_result
        return rows

    def parameter_rows(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        expression_id: str,
        *,
        include_tuning: bool = False,
    ) -> list[dict[str, Any]]:
        prepared = self.prepare(document)
        branch = self._branch(prepared, branch_id)
        if expression_id.startswith(_IMPORTED_STEP_PREFIX):
            node_id = expression_id[len(_IMPORTED_STEP_PREFIX):]
            graph = prepared.skill_template.rule_graphs.get(branch.media_type)
            node = next(
                (item for item in (graph.nodes if graph else []) if item.node_id == node_id),
                None,
            )
            capability_id = self._matched_capability_for_operator(
                node.operator if node else None
            )
            if node is None or capability_id is None:
                return []
            definition = self.capabilities.require(capability_id)
            parameter_definitions = self._imported_parameter_definitions(
                definition, node
            )
            values = self._parameters_from_node(
                capability_id, node, parameter_definitions
            )
            rows = []
            for parameter in parameter_definitions:
                if parameter.level == "derived":
                    continue
                if parameter.level == "tuning" and not include_tuning:
                    continue
                if parameter.parameter_id not in values:
                    continue
                rows.append(
                    {
                        "parameter_id": parameter.parameter_id,
                        "name": parameter.label,
                        "value": values[parameter.parameter_id],
                        "unit": parameter.unit or "",
                        "source": "预置/历史流程",
                        "required": parameter.required,
                        "help": parameter.help,
                        "editor": parameter.editor,
                        "choices": parameter.choices,
                        "minimum": parameter.minimum,
                        "maximum": parameter.maximum,
                        "level": parameter.level,
                    }
                )
            return rows
        target = _find(branch.condition_root, expression_id)
        if target.operator != "ATOM" or not target.capability_id:
            return []
        definition = self.capabilities.require(target.capability_id)
        rows = []
        for parameter in definition.parameters:
            if parameter.level == "derived":
                continue
            if parameter.level == "tuning" and not include_tuning:
                continue
            source = target.parameter_sources.get(parameter.parameter_id)
            value = target.parameters.get(parameter.parameter_id, parameter.default)
            rows.append(
                {
                    "parameter_id": parameter.parameter_id,
                    "name": parameter.label,
                    "value": value,
                    "unit": parameter.unit or "",
                    "source": self._source_label(source),
                    "required": parameter.required,
                    "help": parameter.help,
                    "editor": parameter.editor,
                    "choices": parameter.choices,
                    "minimum": parameter.minimum,
                    "maximum": parameter.maximum,
                    "level": parameter.level,
                }
            )
        return rows

    def source_choices(
        self,
        document: SkillEditorDocument,
        branch_id: str,
        expression_id: str,
    ) -> list[dict[str, str]]:
        prepared = self.prepare(document)
        current_branch = self._branch(prepared, branch_id)
        current = _find(current_branch.condition_root, expression_id)
        definition = (
            self.capabilities.require(current.capability_id)
            if current.capability_id
            else None
        )
        accepted = definition.accepted_source_types if definition else ["any"]
        choices = []
        for branch in prepared.skill_template.business_branches:
            for expression in _walk(branch.condition_root):
                if expression.expression_id == expression_id or expression.operator != "ATOM":
                    continue
                source_definition = (
                    self.capabilities.require(expression.capability_id)
                    if expression.capability_id
                    else None
                )
                output_type = source_definition.output_value_type if source_definition else None
                if _source_type_compatible(output_type, accepted):
                    choices.append(
                        {
                            "value": f"condition:{expression.expression_id}",
                            "label": f"{branch.display_name} / {expression.display_name}",
                            "type": output_type or "unknown",
                        }
                    )
        return choices

    def expression_summary(
        self, expression: ConditionExpression | None, *, compact: bool = False
    ) -> str:
        if expression is None:
            return "尚未配置条件"
        if expression.operator == "ATOM":
            params = expression.parameters
            details = []
            for key in ("targets", "part", "color", "scope", "operator", "threshold", "duration"):
                value = params.get(key)
                if value not in (None, "", [], {}):
                    details.append(str(value))
            return expression.display_name + (f"（{'，'.join(details)}）" if details else "")
        children = []
        for child in expression.children:
            summary = self.expression_summary(child, compact=True)
            if child.operator in {"AND", "OR", "N_OF_M"}:
                summary = f"({summary})"
            children.append(summary)
        if expression.operator == "NOT":
            child = children[0]
            if expression.children[0].operator == "NOT":
                child = f"({child})"
            return f"NOT {child}"
        if expression.operator == "N_OF_M":
            summary = (
                f"至少 {expression.required_count or 1} 项满足（"
                + "；".join(children)
                + "）"
            )
            return summary if compact else f"({summary})"
        connector = f" {expression.operator} "
        summary = connector.join(children)
        return summary if compact else f"({summary})"

    def _new_atom(
        self, definition: BusinessCapabilityDefinition, display_name: str | None
    ) -> ConditionExpression:
        params = {}
        sources = {}
        for parameter in definition.parameters:
            if parameter.default is not None:
                params[parameter.parameter_id] = deepcopy(parameter.default)
                sources[parameter.parameter_id] = ResolvableValue(
                    state="defaulted",
                    value=deepcopy(parameter.default),
                    source="capability_schema",
                    recommended_value=deepcopy(parameter.default),
                    required_before="never",
                )
            elif parameter.required:
                params[parameter.parameter_id] = None
                sources[parameter.parameter_id] = ResolvableValue(
                    state="unresolved",
                    value=None,
                    source="business_editor",
                    reason=f"请配置{parameter.label}",
                    required_before="run",
                )
        return ConditionExpression(
            expression_id=_new_id("condition"),
            operator="ATOM",
            display_name=(display_name or definition.display_name).strip(),
            capability_id=definition.capability_id,
            parameters=params,
            parameter_sources=sources,
        )

    def _validate_parameters(
        self,
        definition: BusinessCapabilityDefinition,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, ResolvableValue]]:
        known = {item.parameter_id: item for item in definition.parameters}
        unknown = set(values) - set(known)
        if unknown:
            raise BusinessRuleEditError(
                "包含当前条件不支持的配置项：" + "、".join(sorted(unknown))
            )
        result = {}
        sources = {}
        for parameter in definition.parameters:
            value = values.get(parameter.parameter_id, parameter.default)
            if value in (None, "") and parameter.required:
                result[parameter.parameter_id] = None
                sources[parameter.parameter_id] = ResolvableValue(
                    state="unresolved",
                    value=None,
                    source="user",
                    reason=f"请配置{parameter.label}",
                    required_before="run",
                )
                continue
            if value is not None:
                value = self._coerce(parameter, value)
                result[parameter.parameter_id] = value
                sources[parameter.parameter_id] = ResolvableValue(
                    state="explicit",
                    value=deepcopy(value),
                    source="user",
                    recommended_value=deepcopy(parameter.default),
                    required_before="never",
                )
        return result, sources

    @staticmethod
    def _coerce(parameter: BusinessParameterDefinition, value: Any) -> Any:
        if parameter.editor in {"number", "duration", "percentage", "angle_degrees"}:
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise BusinessRuleEditError(f"{parameter.label}必须填写数字。") from exc
        elif parameter.editor == "frames":
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise BusinessRuleEditError(f"{parameter.label}必须填写整数帧数。") from exc
        elif parameter.editor == "boolean":
            if isinstance(value, str):
                value = value.strip().lower() in {"1", "true", "yes", "是", "启用"}
            else:
                value = bool(value)
        elif parameter.editor == "multi_select" and not isinstance(value, list):
            value = [item.strip() for item in str(value).split(",") if item.strip()]
        if parameter.choices and value not in parameter.choices:
            if not (
                isinstance(value, list)
                and all(item in parameter.choices for item in value)
            ):
                raise BusinessRuleEditError(
                    f"{parameter.label}只能选择已提供的选项。"
                )
        numeric = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        if numeric is not None and parameter.minimum is not None and numeric < parameter.minimum:
            raise BusinessRuleEditError(f"{parameter.label}不能小于{parameter.minimum}。")
        if numeric is not None and parameter.maximum is not None and numeric > parameter.maximum:
            raise BusinessRuleEditError(f"{parameter.label}不能大于{parameter.maximum}。")
        return value

    def _validate_sources(
        self,
        root: ConditionExpression,
        expression_id: str,
        definition: BusinessCapabilityDefinition,
        parameters: dict[str, Any],
    ) -> None:
        expression_by_id = {item.expression_id: item for item in _walk(root)}
        source_parameters = [
            item
            for item in definition.parameters
            if item.editor == "source_select"
        ]
        for parameter in source_parameters:
            value = parameters.get(parameter.parameter_id)
            if not isinstance(value, str) or not value.startswith("condition:"):
                continue
            source_id = value.split(":", 1)[1]
            if source_id == expression_id:
                raise BusinessRuleEditError("条件不能把自己的结果作为输入。")
            source = expression_by_id.get(source_id)
            if source is None:
                raise BusinessRuleEditError(
                    f"{parameter.label}引用的条件已不存在，请重新选择。"
                )
            source_definition = (
                self.capabilities.require(source.capability_id)
                if source.capability_id
                else None
            )
            actual = source_definition.output_value_type if source_definition else None
            if not _source_type_compatible(actual, definition.accepted_source_types):
                raise BusinessRuleEditError(
                    f"{parameter.label}与所选条件结果类型不兼容。"
                )

    def _apply_parameter_mappings(
        self,
        document: SkillEditorDocument,
        branch: BusinessBranch,
        expression: ConditionExpression,
        definition: BusinessCapabilityDefinition,
        parameters: dict[str, Any],
    ) -> None:
        """Keep safely reversible imported-node parameters in sync.

        New business trees are compiled by BusinessRuleCompiler. This path is
        only for historical/imported expressions whose source_ref identifies a
        concrete existing node.
        """

        graph = document.skill_template.rule_graphs.get(branch.media_type)
        if graph is None:
            return
        for parameter in definition.parameters:
            if parameter.parameter_id not in parameters:
                continue
            business_value = parameters[parameter.parameter_id]
            for mapping in parameter.maps_to:
                operator, atom_parameter = mapping.rsplit(".", 1)
                candidates = [
                    node
                    for node in graph.nodes
                    if node.node_id in branch.node_ids and node.operator == operator
                ]
                if not candidates and expression.source_ref and expression.source_ref.startswith("node:"):
                    source_id = expression.source_ref.split(":", 1)[1]
                    candidates = [node for node in graph.nodes if node.node_id == source_id and node.operator == operator]
                for node in candidates:
                    node.params[atom_parameter] = self._to_compiled_value(
                        parameter, business_value
                    )
                    node.parameter_sources[atom_parameter] = ResolvableValue(
                        state="explicit",
                        value=deepcopy(node.params[atom_parameter]),
                        source="user",
                        required_before="never",
                    )

    @staticmethod
    def _to_compiled_value(parameter: BusinessParameterDefinition, value: Any) -> Any:
        if parameter.value_transform == "percent_to_ratio":
            return float(value) / 100.0
        if parameter.value_transform == "degrees_to_cosine":
            from math import cos, radians

            return cos(radians(float(value)))
        return value

    def _parameters_from_node(
        self,
        capability_id: str,
        node,
        parameters: list[BusinessParameterDefinition] | None = None,
    ) -> dict[str, Any]:
        if node is None:
            return {}
        definition = self.capabilities.require(capability_id)
        result = {}
        for parameter in parameters or definition.parameters:
            if parameter.parameter_id.startswith(_IMPORTED_PARAMETER_PREFIX):
                atom_parameter = parameter.parameter_id[len(_IMPORTED_PARAMETER_PREFIX):]
                operator = self.operators.require(node.operator)
                if atom_parameter in node.params:
                    value = node.params[atom_parameter]
                elif atom_parameter in operator.defaults:
                    value = operator.defaults[atom_parameter]
                else:
                    continue
                if parameter.value_transform == "percent_to_ratio":
                    value = float(value) * 100.0
                result[parameter.parameter_id] = value
                continue
            for mapping in parameter.maps_to:
                operator, atom_parameter = mapping.rsplit(".", 1)
                if operator == node.operator and atom_parameter in node.params:
                    value = node.params[atom_parameter]
                    if parameter.value_transform == "percent_to_ratio":
                        value = float(value) * 100.0
                    result[parameter.parameter_id] = value
                    break
        if capability_id == "target.detect" and "targets" in node.params:
            targets = node.params.get("targets") or []
            result["targets"] = [item.get("label") for item in targets if isinstance(item, dict)]
            phrases = [
                phrase
                for item in targets
                if isinstance(item, dict)
                for phrase in item.get("phrases", [])
            ]
            if phrases and len(targets) == 1:
                result["phrases"] = ", ".join(phrases)
        return result

    def _imported_parameter_definitions(
        self,
        definition: BusinessCapabilityDefinition,
        node,
    ) -> list[BusinessParameterDefinition]:
        """Expose every safe scalar atom parameter with a business-language editor.

        Capability mappings remain the preferred contract.  Historical and preset
        graphs can contain additional operator parameters, so scalar values missing
        from that contract are projected through the shared parameter-presentation
        catalog instead of disappearing or exposing technical JSON names.
        """

        result = list(definition.parameters)
        mapped = set()
        for parameter in definition.parameters:
            for mapping in parameter.maps_to:
                operator, atom_parameter = mapping.rsplit(".", 1)
                if operator == node.operator:
                    mapped.add(atom_parameter)
        operator = self.operators.require(node.operator)
        available = set(operator.parameters) | set(operator.defaults) | set(node.params)
        editable_kinds = {
            "boolean",
            "integer",
            "integer_or_null",
            "number",
            "number_or_null",
            "string",
            "string_or_null",
            "string_list",
            "nonempty_string_list",
        }
        # Structured parameters are still part of the effective atom contract, but
        # most of them are maintained by 02 annotation or a dedicated business
        # editor (for example per-region overrides).  Keep them visible as read-only
        # evidence instead of silently dropping them or exposing raw JSON editing.
        visible_readonly_kinds = {
            "direction_list",
            "json",
            "named_region_list",
            "normalized_box",
            "numeric_mapping",
            "point_list",
            "point_or_null",
            "relative_box",
            "string_mapping",
            "target_list",
            "vector2",
        }
        used_labels = {parameter.label for parameter in result}
        for name in sorted(available - mapped):
            spec = operator.parameters.get(name)
            if spec is None or spec.kind not in editable_kinds | visible_readonly_kinds:
                continue
            if name not in node.params and operator.defaults.get(name) is None:
                continue
            if (
                node.operator == "logic.compare@1.0"
                and name == "threshold"
                and "value" in node.params
                and "threshold" not in node.params
            ):
                continue
            if (
                node.operator == "logic.compare@1.0"
                and name == "value"
                and "threshold" in node.params
                and "value" not in node.params
            ):
                continue
            presentation = parameter_presentation(
                name, spec, operator_help=operator.fixed_rule_text
            )
            if spec.kind in visible_readonly_kinds:
                editor = "readonly"
            elif spec.kind == "boolean":
                editor = "boolean"
            elif spec.kind in {"integer", "integer_or_null"}:
                editor = "frames" if ("frame" in name or name == "min_hits") else "number"
            elif spec.kind in {"number", "number_or_null"}:
                editor = (
                    "percentage"
                    if presentation.value_transform == "percent_to_ratio"
                    else "duration"
                    if "seconds" in name
                    else "number"
                )
            elif spec.kind in {"string_list", "nonempty_string_list"}:
                editor = "multi_select"
            else:
                editor = "select" if spec.choices else "text"
            label = presentation.label
            if label in used_labels:
                label = f"{label}（当前步骤）"
            used_labels.add(label)
            value_transform = (
                presentation.value_transform
                if presentation.value_transform == "percent_to_ratio"
                else None
            )
            result.append(
                BusinessParameterDefinition(
                    parameter_id=f"{_IMPORTED_PARAMETER_PREFIX}{name}",
                    label=label,
                    editor=editor,
                    help=presentation.short_help,
                    unit=(
                        "像素"
                        if presentation.value_transform == "screen_diagonal_percent"
                        else presentation.unit
                    ),
                    choices=list(spec.choices),
                    minimum=(
                        spec.minimum * 100
                        if value_transform == "percent_to_ratio" and spec.minimum is not None
                        else spec.minimum
                    ),
                    maximum=(
                        spec.maximum * 100
                        if value_transform == "percent_to_ratio" and spec.maximum is not None
                        else spec.maximum
                    ),
                    required=spec.required,
                    level=presentation.level,
                    value_transform=value_transform,
                )
            )
        return result

    def _capability_for_operator(self, operator: str | None) -> str:
        return self._matched_capability_for_operator(operator) or "event.detect_or_compose"

    @staticmethod
    def _matched_capability_for_operator(operator: str | None) -> str | None:
        for prefix, capability_id in _OPERATOR_CAPABILITY_PRIORITY:
            if operator and operator.startswith(prefix):
                return capability_id
        return None

    def _apply_existing_node_parameters(
        self,
        node,
        definition: BusinessCapabilityDefinition,
        parameters: dict[str, Any],
    ) -> None:
        for parameter in definition.parameters:
            if parameter.parameter_id not in parameters:
                continue
            value = parameters[parameter.parameter_id]
            if parameter.parameter_id.startswith(_IMPORTED_PARAMETER_PREFIX):
                atom_parameter = parameter.parameter_id[len(_IMPORTED_PARAMETER_PREFIX):]
                node.params[atom_parameter] = self._to_compiled_value(parameter, value)
                node.parameter_sources[atom_parameter] = ResolvableValue(
                    state="explicit",
                    value=deepcopy(node.params[atom_parameter]),
                    source="user",
                    required_before="never",
                )
                continue
            for mapping in parameter.maps_to:
                operator, atom_parameter = mapping.rsplit(".", 1)
                if node.operator == operator:
                    node.params[atom_parameter] = self._to_compiled_value(parameter, value)
                    node.parameter_sources[atom_parameter] = ResolvableValue(
                        state="explicit",
                        value=deepcopy(node.params[atom_parameter]),
                        source="user",
                        required_before="never",
                    )
        if definition.capability_id == "target.detect" and "targets" in parameters:
            labels = parameters["targets"]
            targets = deepcopy(node.params.get("targets") or [])
            for index, label in enumerate(labels):
                if index < len(targets) and isinstance(targets[index], dict):
                    targets[index]["label"] = label
                else:
                    targets.append({"label": label, "phrases": [str(label)]})
            node.params["targets"] = targets[: len(labels)]
            node.parameter_sources["targets"] = ResolvableValue(
                state="explicit",
                value=deepcopy(node.params["targets"]),
                source="user",
                required_before="never",
            )
        if definition.capability_id == "target.detect" and "phrases" in parameters:
            targets = deepcopy(node.params.get("targets") or [])
            if len(targets) == 1 and isinstance(targets[0], dict):
                phrases = [
                    item.strip()
                    for item in str(parameters["phrases"]).split(",")
                    if item.strip()
                ]
                targets[0]["phrases"] = phrases
                node.params["targets"] = targets
                node.parameter_sources["targets"] = ResolvableValue(
                    state="explicit",
                    value=deepcopy(targets),
                    source="user",
                    required_before="never",
                )

    @staticmethod
    def _assert_media(
        definition: BusinessCapabilityDefinition, media_type: str
    ) -> None:
        if media_type not in definition.media_requirements:
            readable = "视频" if definition.media_requirements == ["video"] else "图片或视频"
            raise BusinessRuleEditError(
                f"{definition.display_name}仅适用于{readable}，请切换媒体流程。"
            )

    @staticmethod
    def _branch(document: SkillEditorDocument, branch_id: str) -> BusinessBranch:
        branch = next(
            (
                item
                for item in document.skill_template.business_branches
                if item.branch_id == branch_id
            ),
            None,
        )
        if branch is None:
            raise BusinessRuleEditError("找不到当前业务分支，请刷新后重试。")
        return branch

    @staticmethod
    def _clone_expression(expression: ConditionExpression) -> ConditionExpression:
        data = expression.model_dump(mode="python")

        def renew(item: dict[str, Any]) -> None:
            item["expression_id"] = _new_id("condition" if item["operator"] == "ATOM" else "group")
            for child in item.get("children", []):
                renew(child)

        renew(data)
        return ConditionExpression.model_validate(data)

    @staticmethod
    def _logic_label(operator: str) -> str:
        return {
            "AND": "全部满足（AND）",
            "OR": "任一满足（OR）",
            "NOT": "条件取反（NOT）",
            "N_OF_M": "至少满足 N 项",
        }[operator]

    @staticmethod
    def _source_label(value: ResolvableValue | None) -> str:
        if value is None:
            return "未记录"
        return {
            "explicit": "用户修改" if value.source == "user" else "原文明确",
            "defaulted": "系统默认",
            "inferred": "LLM建议",
            "unresolved": "待填写",
            "runtime_derived": "运行时生成",
            "not_applicable": "不适用",
        }[value.state]

    @staticmethod
    def _condition_status(
        expression: ConditionExpression,
        definition: BusinessCapabilityDefinition | None,
    ) -> str:
        if not expression.enabled:
            return "已停用"
        if definition is None:
            return "可用"
        missing = [
            parameter.label
            for parameter in definition.parameters
            if parameter.required
            and expression.parameters.get(parameter.parameter_id) in (None, "", [])
        ]
        return "待填写：" + "、".join(missing) if missing else "已配置"


__all__ = ["BusinessRuleEditError", "BusinessRuleEditor"]
