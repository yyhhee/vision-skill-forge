from __future__ import annotations

from copy import deepcopy
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
    SkillEditorDocument,
    TriggerPolicy,
    TemporalQualifierSpec,
)
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
        if operator not in {"AND", "OR", "N_OF_M"}:
            raise BusinessRuleEditError("多个条件只能使用 AND、OR 或至少N项组合。")
        ids = list(dict.fromkeys(expression_ids))
        if len(ids) < 2:
            raise BusinessRuleEditError("请至少选择两个同级条件进行组合。")
        result = self.prepare(document).model_copy(deep=True)
        branch = self._branch(result, branch_id)
        root = branch.condition_root
        if root is None:
            raise BusinessRuleEditError("当前分支没有可组合条件。")
        if root.operator not in {"AND", "OR", "N_OF_M"}:
            if set(ids) != {root.expression_id}:
                raise BusinessRuleEditError("所选条件必须位于同一条件组。")
            raise BusinessRuleEditError("请先新增第二个条件。")
        direct = {item.expression_id: item for item in root.children}
        if not set(ids).issubset(direct):
            raise BusinessRuleEditError("当前版本要求所选条件位于同一层级。")
        selected = [direct[item] for item in ids]
        group = ConditionExpression(
            expression_id=_new_id("group"),
            operator=operator,  # type: ignore[arg-type]
            display_name=self._logic_label(operator),
            capability_id="logic.group",
            parameters={"operator": operator},
            children=selected,
            required_count=(required_count or 1) if operator == "N_OF_M" else None,
        )
        data = root.model_dump(mode="python")
        new_children = []
        inserted = False
        for child in root.children:
            if child.expression_id in ids:
                if not inserted:
                    new_children.append(group.model_dump(mode="python"))
                    inserted = True
            else:
                new_children.append(child.model_dump(mode="python"))
        data["children"] = new_children
        branch.condition_root = ConditionExpression.model_validate(data)
        result.version += 1
        return refresh_document_hashes(result), group.expression_id

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
        if root.operator in {"AND", "OR", "N_OF_M"}:
            data = root.model_dump(mode="python")
            index = next(
                index
                for index, child in enumerate(root.children)
                if child.expression_id == expression_id
            )
            data["children"].insert(index + 1, clone.model_dump(mode="python"))
            branch.condition_root = ConditionExpression.model_validate(data)
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
        self, document: SkillEditorDocument, branch_id: str, expression_id: str
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
        branch.condition_root = _delete_from_tree(
            branch.condition_root, expression_id
        )
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
                known = {item.parameter_id: item for item in definition.parameters}
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
                self._apply_existing_node_parameters(node, definition, normalized)
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
        selected = list(dict.fromkeys(branch_ids or []))
        unknown = set(selected) - set(branches)
        if unknown:
            raise BusinessRuleEditError("复杂编排引用了已不存在的分支，请重新选择。")
        existing_for_media = {
            branch.branch_id for branch in branches.values()
        }
        result.skill_template.event_patterns = [
            pattern
            for pattern in result.skill_template.event_patterns
            if not any(
                stage.source_ref in {f"branch:{item}" for item in existing_for_media}
                for stage in pattern.stages
            )
        ]
        if mode == "none":
            result.version += 1
            return refresh_document_hashes(result)
        if media_type != "video":
            raise BusinessRuleEditError("跨分支时间编排需要视频流程；图片可使用 AND / OR 条件组合。")
        minimum = 1 if mode == "repeat" else 2
        if len(selected) < minimum:
            raise BusinessRuleEditError(f"当前编排方式至少需要选择{minimum}个分支。")
        if mode == "absence" and len(selected) != 2:
            raise BusinessRuleEditError("“未发生”需要依次选择锚点分支和禁止发生分支。")
        if mode in {"all_completed_within_window", "sequence", "absence", "repeat"}:
            if window_seconds is None or float(window_seconds) <= 0:
                raise BusinessRuleEditError("当前编排方式需要填写大于0秒的时间窗口。")
        if mode == "n_of_m":
            if required_count is None or not 1 <= int(required_count) <= len(selected):
                raise BusinessRuleEditError("至少完成分支数 N 必须在1和已选分支数之间。")
        stages = [
            PatternStage(
                stage_id=f"stage_{index}",
                display_name=branches[branch_id].display_name,
                source_rule_id=branches[branch_id].root_node_id or branch_id,
                source_ref=f"branch:{branch_id}",
            )
            for index, branch_id in enumerate(selected, start=1)
        ]
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
                    maximum_delay_seconds=ResolvableValue(
                        state="explicit",
                        value=float(window_seconds),
                        source="user",
                        required_before="never",
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

        def visit(item: ConditionExpression, parent: str | None, depth: int) -> None:
            definition = (
                self.capabilities.require(item.capability_id)
                if item.capability_id and item.operator == "ATOM"
                else None
            )
            rows.append(
                {
                    "condition_id": item.expression_id,
                    "parent_id": parent,
                    "depth": depth,
                    "kind": "条件" if item.operator == "ATOM" else "条件组",
                    "logic": item.operator,
                    "category": definition.category if definition else "逻辑组合",
                    "name": item.display_name,
                    "summary": self.expression_summary(item, compact=True),
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
            if is_imported_proxy:
                rows[0]["kind"] = "导入判定"
                rows[0]["category"] = "已验证业务流程"
                rows[0]["status"] = "保持原有执行效果"
                graph = prepared.skill_template.rule_graphs.get(branch.media_type)
                for node in (graph.nodes if graph else []):
                    if node.node_id not in branch.node_ids or not node.enabled:
                        continue
                    capability_id = self._matched_capability_for_operator(node.operator)
                    if capability_id is None:
                        continue
                    definition = self.capabilities.require(capability_id)
                    rows.append(
                        {
                            "condition_id": f"{_IMPORTED_STEP_PREFIX}{node.node_id}",
                            "parent_id": root.expression_id,
                            "depth": 1,
                            "kind": "条件",
                            "logic": "ATOM",
                            "category": definition.category,
                            "name": (
                                node.display_name
                                if node.display_name != node.node_id
                                else definition.display_name
                            ),
                            "summary": definition.display_name,
                            "enabled": node.enabled,
                            "status": "原有流程步骤，可修改关键参数",
                            "capability_id": capability_id,
                            "imported_step": True,
                        }
                    )
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
            values = self._parameters_from_node(capability_id, node)
            rows = []
            for parameter in definition.parameters:
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
        children = [self.expression_summary(child, compact=True) for child in expression.children]
        if expression.operator == "NOT":
            return f"NOT {children[0]}"
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

    def _parameters_from_node(self, capability_id: str, node) -> dict[str, Any]:
        if node is None:
            return {}
        definition = self.capabilities.require(capability_id)
        result = {}
        for parameter in definition.parameters:
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
