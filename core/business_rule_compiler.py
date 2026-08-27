from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import cos, radians
from typing import Any, Iterable

from .business_capabilities import BusinessCapabilityRegistry
from .document_hashes import refresh_document_hashes
from .editor_schema import (
    BusinessBranch,
    ConditionExpression,
    RuleEdge,
    RuleGraph,
    RuleNode,
    SkillEditorDocument,
)
from .registry import OperatorRegistry
from .schema import ConfigurationBinding, ConfigurationSlot
from .visual_catalog import (
    CARRIER_ALIASES,
    CARRIER_CATALOG,
    CARRIER_TEXT_ALIASES,
    COLOR_ALIASES,
    COLOR_MIN_FRACTIONS,
)


class BusinessRuleCompileError(ValueError):
    """A deterministic business compiler failure safe to expose in 03."""


@dataclass
class CompiledValue:
    node_id: str
    output_type: str
    node_ids: set[str] = field(default_factory=set)
    measurement_node_id: str | None = None
    entity_node_id: str | None = None
    track_node_id: str | None = None
    event_node_id: str | None = None

    def with_nodes(self, *node_ids: str) -> "CompiledValue":
        self.node_ids.update(node_ids)
        return self


def _walk(expression: ConditionExpression | None) -> Iterable[ConditionExpression]:
    if expression is None:
        return
    yield expression
    for child in expression.children:
        yield from _walk(child)


def _safe_id(*parts: str) -> str:
    text = "_".join(parts)
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    if not text or not text[0].isalpha():
        text = "rule_" + text
    return text[:180]


def _float_or_default(value: Any, default: float) -> float:
    """Treat an explicit JSON null like an omitted optional numeric parameter."""
    return float(default if value is None else value)


def _canonical_color(value: Any) -> str:
    """Normalize Chinese/English color aliases before an operator executes.

    The business editor normally stores catalog values (``red``, ``white``,
    ...), but imported or hand-authored drafts can still contain values such
    as ``白色`` or ``grey``.  Keeping this normalization at the compiler
    boundary makes every color condition use the same operator vocabulary.
    Unknown open-vocabulary values are preserved so validation can report the
    unsupported value instead of silently changing the user's intent.
    """

    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    compact = text.replace(" ", "")
    return COLOR_ALIASES.get(text, COLOR_ALIASES.get(compact, text))


def _kind_for_output(output_type: str) -> str:
    if output_type in {"ObjectSet", "EntitySet", "TrackSet"}:
        return "target"
    if output_type == "ConditionSet":
        return "condition"
    if output_type == "EventSet":
        return "temporal_qualifier"
    if output_type in {"ScalarSet", "VectorSet"}:
        return "aggregate"
    if output_type in {"RegionSet"}:
        return "region"
    if output_type in {"PairSet"}:
        return "relation"
    if output_type in {"StateSet"}:
        return "condition"
    return "scope"


class _GraphBuilder:
    def __init__(self, graph: RuleGraph, registry: OperatorRegistry):
        self.graph = graph
        self.registry = registry
        self.nodes = {node.node_id: node for node in graph.nodes}

    def add(
        self,
        *,
        node_id: str,
        operator: str,
        display_name: str,
        inputs: dict[str, CompiledValue | list[CompiledValue]] | None = None,
        params: dict[str, Any] | None = None,
        business_source_refs: list[str] | None = None,
        configuration_slots: list[ConfigurationSlot] | None = None,
    ) -> CompiledValue:
        definition = self.registry.require(operator)
        if node_id in self.nodes:
            raise BusinessRuleCompileError(
                f"编译生成了重复条件标识“{node_id}”；请复制条件后重试。"
            )
        node = RuleNode(
            node_id=node_id,
            kind=_kind_for_output(definition.output_type),  # type: ignore[arg-type]
            display_name=display_name,
            operator=operator,
            params=params or {},
            business_source_refs=business_source_refs or [],
            configuration_slots=configuration_slots or [],
        )
        self.graph.nodes.append(node)
        self.nodes[node_id] = node
        dependencies = {node_id}
        for port, source in (inputs or {}).items():
            values = source if isinstance(source, list) else [source]
            for value in values:
                self.graph.edges.append(
                    RuleEdge(source=value.node_id, target=node_id, port=port)
                )
                dependencies.update(value.node_ids or {value.node_id})
        return CompiledValue(
            node_id=node_id,
            output_type=definition.output_type,
            node_ids=dependencies,
            measurement_node_id=(node_id if definition.output_type == "ScalarSet" else None),
            entity_node_id=(
                node_id
                if definition.output_type in {"ObjectSet", "EntitySet"}
                else None
            ),
            track_node_id=(node_id if definition.output_type == "TrackSet" else None),
            event_node_id=(node_id if definition.output_type == "EventSet" else None),
        )

    def existing(self, node_id: str) -> CompiledValue:
        node = self.nodes.get(node_id)
        if node is None or node.operator is None:
            raise BusinessRuleCompileError(
                "历史条件引用的执行节点已不存在；请重新新增该业务条件。"
            )
        output_type = self.registry.require(node.operator).output_type
        # Imported/pre-set business branches proxy an already verified graph node.
        # The branch owns the full dependency closure, not just its root.  Keeping
        # only the root made the 03 condition tree collapse to “0 conditions” after
        # validate/apply even though the runtime graph was still present.
        dependencies = {node_id}
        changed = True
        while changed:
            changed = False
            for edge in self.graph.edges:
                if edge.target in dependencies and edge.source not in dependencies:
                    dependencies.add(edge.source)
                    changed = True
        return CompiledValue(
            node_id=node_id,
            output_type=output_type,
            node_ids=dependencies,
            measurement_node_id=node_id if output_type == "ScalarSet" else None,
            entity_node_id=node_id if output_type in {"ObjectSet", "EntitySet"} else None,
            track_node_id=node_id if output_type == "TrackSet" else None,
            event_node_id=node_id if output_type == "EventSet" else None,
        )

    def expose(self, node_id: str, output_name: str) -> None:
        node = self.nodes[node_id]
        existing = [node.output_name, *node.output_names]
        if output_name in existing:
            return
        if node.output_name is None:
            node.output_name = output_name
        else:
            node.output_names.append(output_name)


class BusinessRuleCompiler:
    """Compile the user-facing business tree into the existing atomic runtime."""

    def __init__(
        self,
        registry: OperatorRegistry,
        capabilities: BusinessCapabilityRegistry,
    ):
        self.registry = registry
        self.capabilities = capabilities

    def compile_document(
        self, document: SkillEditorDocument
    ) -> SkillEditorDocument:
        result = document.model_copy(deep=True)
        self._document_for_builder = result
        template = result.skill_template
        media_types = sorted(
            {
                *template.rule_graphs,
                *(branch.media_type for branch in template.business_branches),
            }
        )
        compiled_expressions: dict[str, CompiledValue] = {}
        branch_values: dict[str, CompiledValue] = {}
        expression_index = {
            expression.expression_id: (branch, expression)
            for branch in template.business_branches
            for expression in _walk(branch.condition_root)
        }
        branch_index = {
            branch.branch_id: branch for branch in template.business_branches
        }

        for media_type in media_types:
            graph = template.rule_graphs.get(media_type, RuleGraph()).model_copy(deep=True)
            generated_ids = {
                node.node_id for node in graph.nodes if node.business_source_refs
            }
            if generated_ids:
                graph.nodes = [
                    node for node in graph.nodes if node.node_id not in generated_ids
                ]
                graph.edges = [
                    edge
                    for edge in graph.edges
                    if edge.source not in generated_ids and edge.target not in generated_ids
                ]
            builder = _GraphBuilder(graph, self.registry)
            compiling: set[str] = set()

            def compile_source(
                source_ref: str | None,
                current_branch: BusinessBranch,
                parameter_name: str,
            ) -> CompiledValue:
                if not source_ref:
                    raise BusinessRuleCompileError(
                        f"分支“{current_branch.display_name}”的{parameter_name}尚未选择输入来源。"
                    )
                if source_ref.startswith("condition:"):
                    expression_id = source_ref.split(":", 1)[1]
                    pair = expression_index.get(expression_id)
                    if pair is None:
                        raise BusinessRuleCompileError(
                            f"{parameter_name}引用的条件已不存在。"
                        )
                    source_branch, source_expression = pair
                    if source_branch.media_type != current_branch.media_type:
                        raise BusinessRuleCompileError(
                            f"{parameter_name}不能跨图片/视频流程引用。"
                        )
                    return compile_expression(source_branch, source_expression)
                if source_ref.startswith("branch:"):
                    source_branch_id = source_ref.split(":", 1)[1]
                    source_branch = branch_index.get(source_branch_id)
                    if source_branch is None:
                        raise BusinessRuleCompileError(
                            f"{parameter_name}引用的分支已不存在。"
                        )
                    return compile_branch(source_branch)
                if source_ref.startswith("node:"):
                    return builder.existing(source_ref.split(":", 1)[1])
                raise BusinessRuleCompileError(
                    f"{parameter_name}使用了当前版本不支持的来源。"
                )

            def compile_expression(
                branch: BusinessBranch, expression: ConditionExpression
            ) -> CompiledValue:
                cached = compiled_expressions.get(expression.expression_id)
                if cached is not None:
                    return cached
                if expression.expression_id in compiling:
                    raise BusinessRuleCompileError(
                        f"条件“{expression.display_name}”形成循环引用。"
                    )
                compiling.add(expression.expression_id)
                try:
                    if not expression.enabled:
                        raise BusinessRuleCompileError(
                            f"已停用条件“{expression.display_name}”仍被其它条件引用。"
                        )
                    if expression.operator == "ATOM":
                        value = self._compile_atom(
                            builder,
                            branch,
                            expression,
                            compile_source,
                        )
                    else:
                        children = [
                            compile_expression(branch, child)
                            for child in expression.children
                            if child.enabled
                        ]
                        if expression.operator == "NOT":
                            condition = self._as_condition(
                                builder, branch, expression, children[0]
                            )
                            value = builder.add(
                                node_id=_safe_id(branch.branch_id, expression.expression_id, "not"),
                                operator="logic.not@1.0",
                                display_name=expression.display_name,
                                inputs={"condition": condition},
                                business_source_refs=[
                                    f"condition:{expression.expression_id}"
                                ],
                            )
                        else:
                            conditions = [
                                self._as_condition(builder, branch, expression, child)
                                for child in children
                            ]
                            if expression.operator == "AND":
                                operator = "logic.all@1.0"
                                params = {"combine_scope": "frame_any"}
                            elif expression.operator == "OR":
                                operator = "logic.any@1.0"
                                params = {"combine_scope": "frame_any"}
                            else:
                                operator = "reduce.quantify@1.0"
                                params = {
                                    "mode": "n_of_m",
                                    "required_count": expression.required_count,
                                }
                            value = builder.add(
                                node_id=_safe_id(
                                    branch.branch_id,
                                    expression.expression_id,
                                    expression.operator.lower(),
                                ),
                                operator=operator,
                                display_name=expression.display_name,
                                inputs={"conditions": conditions},
                                params=params,
                                business_source_refs=[
                                    f"condition:{expression.expression_id}"
                                ],
                            )
                    compiled_expressions[expression.expression_id] = value
                    return value
                finally:
                    compiling.discard(expression.expression_id)

            def compile_branch(branch: BusinessBranch) -> CompiledValue:
                cached = branch_values.get(branch.branch_id)
                if cached is not None:
                    return cached
                if branch.media_type != media_type:
                    raise BusinessRuleCompileError("分支不能跨媒体流程组合。")
                if branch.condition_root is None:
                    if branch.root_node_id:
                        value = builder.existing(branch.root_node_id)
                        branch_values[branch.branch_id] = value
                        return value
                    raise BusinessRuleCompileError(
                        f"分支“{branch.display_name}”还没有业务条件。"
                    )
                source_value = compile_expression(branch, branch.condition_root)
                # A migrated historical branch may expose any typed package
                # output (region, vector, scalar, media...), not necessarily a
                # boolean condition. Preserve that proxy exactly. New business
                # trees are reduced to an explicit branch condition/event.
                is_legacy_proxy = (
                    branch.condition_root.operator == "ATOM"
                    and bool(branch.condition_root.source_ref)
                    and branch.condition_root.source_ref.startswith("node:")
                )
                value = (
                    source_value
                    if is_legacy_proxy
                    else self._as_branch_result(
                        builder, branch, branch.condition_root, source_value
                    )
                )
                for qualifier in branch.temporal_qualifiers:
                    if not qualifier.enabled or qualifier.mode == "immediate":
                        continue
                    condition = self._as_condition(
                        builder, branch, branch.condition_root, value
                    )
                    duration = (
                        qualifier.duration_seconds.value
                        if qualifier.duration_seconds.state != "unresolved"
                        else qualifier.duration_seconds.recommended_value
                    )
                    if duration is None and qualifier.mode != "ratio":
                        raise BusinessRuleCompileError(
                            f"分支“{branch.display_name}”的持续时间尚未填写。"
                        )
                    if duration is None:
                        duration = 0.0
                    window = (
                        qualifier.observation_window_seconds.value
                        if qualifier.observation_window_seconds.state
                        not in {"unresolved", "not_applicable"}
                        else None
                    )
                    value = builder.add(
                        node_id=_safe_id(
                            branch.branch_id, qualifier.qualifier_id, "temporal"
                        ),
                        operator="temporal.qualify@1.0",
                        display_name=qualifier.display_name,
                        inputs={"condition": condition},
                        params={
                            "mode": {
                                "continuous": "continuous",
                                "cumulative": "cumulative",
                                "ratio": "ratio",
                                "valid_for": "continuous",
                                "repeat": "continuous",
                            }.get(qualifier.mode, "immediate"),
                            "duration_seconds": float(duration),
                            "allowed_gap_seconds": qualifier.allowed_gap_seconds,
                            "window_seconds": window,
                            "required_ratio": qualifier.required_ratio,
                            "trigger_mode": (
                                "continuous"
                                if qualifier.emission == "repeat"
                                else "once"
                            ),
                        },
                        business_source_refs=[f"branch:{branch.branch_id}"],
                    )
                if branch.validity_policy.mode == "hold_for":
                    if value.output_type != "ConditionSet":
                        raise BusinessRuleCompileError(
                            f"分支“{branch.display_name}”已生成事件区间，不能再使用成立后保持；"
                            "请改为按事件有效区间。"
                        )
                    hold = branch.validity_policy.hold_seconds.value
                    if hold is None:
                        raise BusinessRuleCompileError(
                            f"分支“{branch.display_name}”的成立后保持时间尚未填写。"
                        )
                    value = builder.add(
                        node_id=_safe_id(branch.branch_id, "validity_hold"),
                        operator="temporal.hold@1.0",
                        display_name=f"{branch.display_name}成立后保持",
                        inputs={"condition": value},
                        params={"seconds": float(hold), "value": True},
                        business_source_refs=[f"branch:{branch.branch_id}"],
                    )
                branch.node_ids = sorted(value.node_ids)
                branch.root_node_id = value.node_id
                builder.expose(value.node_id, _safe_id("branch", branch.branch_id))
                branch_values[branch.branch_id] = value
                return value

            for branch in template.business_branches:
                if branch.media_type == media_type and branch.enabled:
                    compile_branch(branch)

            self._expose_branch_evidence(
                template.business_branches,
                media_type,
                builder,
                compiled_expressions,
            )
            self._bind_outputs(
                result,
                media_type,
                builder,
                compiled_expressions,
                branch_values,
            )
            template.rule_graphs[media_type] = graph

        result.atomic_plan = {
            "schema_version": "1.0",
            "source": "business_rule_compiler",
            "semantic_hash": result.hashes.semantic_hash,
            "condition_bindings": {
                expression_id: value.node_id
                for expression_id, value in sorted(compiled_expressions.items())
            },
            "branch_bindings": {
                branch_id: value.node_id
                for branch_id, value in sorted(branch_values.items())
            },
        }
        compiled = refresh_document_hashes(result)
        if hasattr(self, "_active_document"):
            del self._active_document
        return compiled

    @staticmethod
    def _expose_branch_evidence(
        branches: list[BusinessBranch],
        media_type: str,
        builder: _GraphBuilder,
        expressions: dict[str, CompiledValue],
    ) -> None:
        existing_outputs = {
            name
            for node in builder.graph.nodes
            for name in ([node.output_name] if node.output_name else []) + node.output_names
        }
        if "objects" not in existing_outputs:
            priorities = {
                "spatial.membership": 50,
                "subject.same_attributes": 40,
                "state.detect": 35,
                "state.transition": 35,
                "attribute.color": 30,
                "attribute.classify": 30,
                "target.detect": 10,
            }
            selected = []
            for branch in branches:
                if branch.media_type != media_type or not branch.enabled:
                    continue
                if branch.condition_root is None:
                    continue
                candidates = []
                for index, expression in enumerate(_walk(branch.condition_root)):
                    value = expressions.get(expression.expression_id)
                    if value is None or value.entity_node_id is None:
                        continue
                    candidates.append(
                        (
                            priorities.get(expression.capability_id or "", 0),
                            index,
                            value.entity_node_id,
                        )
                    )
                if candidates:
                    selected.append(max(candidates)[2])
            selected = list(dict.fromkeys(selected))
            if len(selected) == 1:
                builder.expose(selected[0], "objects")
            elif selected:
                merged = builder.add(
                    node_id=_safe_id("business", "branch_evidence", "objects"),
                    operator="objects.merge@1.0",
                    display_name="业务分支目标证据",
                    inputs={"objects": [builder.existing(item) for item in selected]},
                    business_source_refs=["node:system:branch_entity_evidence"],
                )
                builder.expose(merged.node_id, "objects")

        if "regions" not in existing_outputs:
            region_nodes = [
                node.node_id
                for node in builder.graph.nodes
                if node.operator in {"region.manual@1.0", "region.manual_set@1.0"}
            ]
            region_nodes = list(dict.fromkeys(region_nodes))
            if len(region_nodes) == 1:
                builder.expose(region_nodes[0], "regions")
            elif region_nodes:
                merged = builder.add(
                    node_id=_safe_id("business", "scene", "regions"),
                    operator="regions.merge@1.0",
                    display_name="业务场景区域",
                    inputs={"regions": [builder.existing(item) for item in region_nodes]},
                    business_source_refs=["node:system:scene_region_evidence"],
                )
                builder.expose(merged.node_id, "regions")

    def _compile_atom(
        self,
        builder: _GraphBuilder,
        branch: BusinessBranch,
        expression: ConditionExpression,
        compile_source,
    ) -> CompiledValue:
        if expression.source_ref and expression.source_ref.startswith("node:"):
            return builder.existing(expression.source_ref.split(":", 1)[1])
        if not expression.capability_id:
            raise BusinessRuleCompileError(
                f"条件“{expression.display_name}”没有选择业务能力。"
            )
        definition = self.capabilities.require(expression.capability_id)
        if branch.media_type not in definition.media_requirements:
            raise BusinessRuleCompileError(
                f"条件“{expression.display_name}”不适用于当前媒体。"
            )
        missing = [
            parameter.label
            for parameter in definition.parameters
            if parameter.required
            and expression.parameters.get(parameter.parameter_id) in (None, "", [])
        ]
        if missing:
            raise BusinessRuleCompileError(
                f"条件“{expression.display_name}”待填写：{'、'.join(missing)}。"
            )
        p = expression.parameters
        source_ref = f"condition:{expression.expression_id}"
        base = _safe_id(branch.branch_id, expression.expression_id)

        def source(name: str = "source") -> CompiledValue:
            parameter = next(
                (item for item in definition.parameters if item.parameter_id == name),
                None,
            )
            return compile_source(
                p.get(name), branch, parameter.label if parameter else "输入来源"
            )

        capability = expression.capability_id
        if capability == "target.detect":
            targets = self._target_list(p)
            value = builder.add(
                node_id=_safe_id(base, "detect"),
                operator="rex.ground@1.1",
                display_name=expression.display_name,
                params={"targets": targets},
                business_source_refs=[source_ref],
            )
            business_label = str(p.get("business_label") or "").strip()
            if business_label:
                value = builder.add(
                    node_id=_safe_id(base, "label"),
                    operator="objects.relabel@1.0",
                    display_name=f"{expression.display_name}框标签",
                    inputs={"objects": value},
                    params={"label": business_label},
                    business_source_refs=[source_ref],
                )
            return value
        if capability == "target.filter_class":
            upstream = source()
            return builder.add(
                node_id=_safe_id(base, "class_filter"),
                operator="objects.filter_by_label@1.0",
                display_name=expression.display_name,
                inputs={"objects": upstream},
                params={"labels": p["labels"], "mode": p.get("mode", "include")},
                business_source_refs=[source_ref],
            )
        if capability == "attribute.color":
            upstream = source()
            color_value = _canonical_color(p.get("color"))
            carrier_key, carrier_phrase = self._infer_color_carrier(
                p, expression.display_name
            )
            if carrier_key is not None:
                # A raw HSV crop of a person/object box contains background
                # and other attributes.  First ask the open-vocabulary model
                # for the *coloured carrier itself* (red shirt, grey trousers,
                # yellow helmet, ...), verify that tight evidence box, then
                # project it back to the original target.  This is important
                # for both generic clothing and named garments: asking for
                # “person wearing red upper body clothing” often returns the
                # whole person box and defeats the colour verification.
                generic_clothing = carrier_key == "clothing"
                subject_phrase = f"{color_value} {carrier_phrase}".strip()
                catalog_default = max(
                    10,
                    100 * COLOR_MIN_FRACTIONS.get(color_value, 0.2) * 0.75,
                )
                # Natural-language drafts materialize omitted tuning fields
                # with the capability default (20%).  For generic clothing
                # that default is too strict for small/partially visible
                # garment boxes, so only the planner-inferred value uses the
                # carrier-aware 15% baseline; an explicit editor value remains
                # authoritative.
                inferred_default = generic_clothing and getattr(
                    expression.parameter_sources.get("minimum_fraction"),
                    "source",
                    None,
                ) == "llm_business_draft"
                default_fraction = catalog_default if inferred_default else 20
                minimum_fraction = (
                    default_fraction
                    if inferred_default
                    else _float_or_default(
                        p.get("minimum_fraction"), default_fraction
                    )
                )
                evidence = builder.add(
                    node_id=_safe_id(base, "wearing_evidence"),
                    operator="rex.ground@1.1",
                    display_name=f"{expression.display_name}语义证据",
                    params={
                        "targets": [{
                            "label": expression.display_name,
                            "phrases": [subject_phrase],
                        }],
                    },
                    business_source_refs=[source_ref],
                )
                color_condition = builder.add(
                    node_id=_safe_id(base, "color"),
                    operator="visual.color_fraction@1.0",
                    display_name=expression.display_name,
                    inputs={"objects": evidence},
                    params={
                        "color": color_value,
                        # The grounding result is already the carrier box;
                        # never reapply a person-oriented upper/lower crop to
                        # it, or a small garment can be cropped away.
                        "subject_region": [0, 0, 1, 1],
                        "min_fraction": minimum_fraction / 100.0,
                        # Rex has already provided a named attribute box. A
                        # fraction is therefore a consistency check rather
                        # than the primary classifier, keeping the rule
                        # robust to multicolour, shaded and partially visible
                        # garments or equipment.
                        "selection_mode": "fraction",
                        "dominance_margin": 0.05,
                        # This check corroborates an already grounded
                        # attribute box.  It can therefore tolerate the
                        # narrow yellow/orange boundary used for mustard and
                        # golden garments without weakening raw box checks.
                        "color_tolerance": "semantic",
                    },
                    business_source_refs=[source_ref],
                )
                colored_evidence = builder.add(
                    node_id=_safe_id(base, "colored_evidence"),
                    operator="filter.apply@1.0",
                    display_name=f"{expression.display_name}颜色证据",
                    inputs={"objects": evidence, "condition": color_condition},
                    params={"output_label": None},
                    business_source_refs=[source_ref],
                )
                owner_condition = builder.add(
                    node_id=_safe_id(base, "owner"),
                    operator="spatial.associate@1.0",
                    display_name=f"{expression.display_name}归属目标",
                    inputs={
                        "subjects": upstream,
                        "objects": colored_evidence,
                    },
                    # Carrier evidence is normally smaller than its person or
                    # vehicle. Select the best enclosing target rather than
                    # requiring a symmetric overlap between two differently
                    # sized boxes.
                    params={"relation": "best_owner", "threshold": 0.1},
                    business_source_refs=[source_ref],
                )
                return builder.add(
                    node_id=_safe_id(base, "apply"),
                    operator="filter.apply@1.0",
                    display_name=f"符合{expression.display_name}的目标",
                    inputs={"objects": upstream, "condition": owner_condition},
                    params={"output_label": None},
                    business_source_refs=[source_ref],
                )
            # A colour without an explicit carrier is still an attribute of
            # the detected target (for example “红色汽车” or “蓝色背包”).
            # Do not classify the whole upstream box by HSV alone: the box
            # may include background, neighbouring objects, or a person's
            # other garments.  Ask Rex for the coloured target evidence,
            # verify that evidence deterministically, then bind the surviving
            # evidence back to the original target boxes.  This keeps the
            # result geometry/labels on the target set while making the same
            # evidence-first strategy available outside clothing tasks.
            target_phrase = self._grounding_phrase(builder, upstream)
            if target_phrase:
                evidence = builder.add(
                    node_id=_safe_id(base, "attribute_evidence"),
                    operator="rex.ground@1.1",
                    display_name=f"{expression.display_name}语义证据",
                    params={
                        "targets": [{
                            "label": expression.display_name,
                            "phrases": [f"{color_value} {target_phrase}"],
                        }],
                    },
                    business_source_refs=[source_ref],
                )
                color_condition = builder.add(
                    node_id=_safe_id(base, "color"),
                    operator="visual.color_fraction@1.0",
                    display_name=expression.display_name,
                    inputs={"objects": evidence},
                    params={
                        "color": color_value,
                        "subject_region": self._subject_region(p.get("part", "whole")),
                        "min_fraction": _float_or_default(
                            p.get("minimum_fraction"), 20
                        )
                        / 100.0,
                        # The model supplies the semantic/attribute box;
                        # fraction is only a colour-consistency check.  A
                        # fraction test tolerates multicolour objects and
                        # partial visibility without requiring one dominant
                        # hue to fill the entire evidence crop.
                        "selection_mode": "fraction",
                        "dominance_margin": 0.05,
                        "color_tolerance": "semantic",
                    },
                    business_source_refs=[source_ref],
                )
                colored_evidence = builder.add(
                    node_id=_safe_id(base, "colored_evidence"),
                    operator="filter.apply@1.0",
                    display_name=f"{expression.display_name}颜色证据",
                    inputs={"objects": evidence, "condition": color_condition},
                    params={"output_label": None},
                    business_source_refs=[source_ref],
                )
                owner_condition = builder.add(
                    node_id=_safe_id(base, "owner"),
                    operator="spatial.associate@1.0",
                    display_name=f"{expression.display_name}归属目标",
                    inputs={"subjects": upstream, "objects": colored_evidence},
                    params={"relation": "best_owner", "threshold": 0.1},
                    business_source_refs=[source_ref],
                )
                return builder.add(
                    node_id=_safe_id(base, "apply"),
                    operator="filter.apply@1.0",
                    display_name=f"符合{expression.display_name}的目标",
                    inputs={"objects": upstream, "condition": owner_condition},
                    params={"output_label": None},
                    business_source_refs=[source_ref],
                )

            # Keep a defensive fallback for hand-authored graphs whose source
            # is not a Rex grounding node and therefore has no phrase to send
            # to the open-vocabulary detector.
            condition = builder.add(
                node_id=_safe_id(base, "color"),
                operator="visual.color_fraction@1.0",
                display_name=expression.display_name,
                inputs={"objects": upstream},
                params={
                    "color": color_value,
                    "subject_region": self._subject_region(p.get("part", "whole")),
                    "min_fraction": _float_or_default(
                        p.get("minimum_fraction"), 20,
                    )
                    / 100.0,
                    "selection_mode": "fraction",
                    "dominance_margin": 0.05,
                },
                business_source_refs=[source_ref],
            )
            return builder.add(
                node_id=_safe_id(base, "apply"),
                operator="filter.apply@1.0",
                display_name=f"符合{expression.display_name}的目标",
                inputs={"objects": upstream, "condition": condition},
                params={"output_label": None},
                business_source_refs=[source_ref],
            )
        if capability == "attribute.geometry":
            upstream = source()
            dimension = p.get("dimension", "size")
            threshold = _float_or_default(p.get("threshold"), 1)
            params = {"dimension": dimension}
            if dimension == "aspect_ratio":
                params.update(
                    {
                        "value": "horizontal" if p.get("operator", ">=") in {">", ">="} else "vertical",
                        "aspect_ratio_threshold": max(threshold, 0.01),
                    }
                )
            condition = builder.add(
                node_id=_safe_id(base, "geometry"),
                operator="visual.geometry@1.0",
                display_name=expression.display_name,
                inputs={"objects": upstream},
                params=params,
                business_source_refs=[source_ref],
            )
            return builder.add(
                node_id=_safe_id(base, "apply"),
                operator="filter.apply@1.0",
                display_name=f"符合{expression.display_name}的目标",
                inputs={"objects": upstream, "condition": condition},
                business_source_refs=[source_ref],
            )
        if capability in {"subject.same_attributes", "subject.missing_equipment"}:
            subject = compile_source(p.get("subject"), branch, "主体目标")
            references = p.get("attributes") if capability == "subject.same_attributes" else [p.get("equipment")]
            current = subject
            for index, reference in enumerate(references or [], start=1):
                evidence = compile_source(reference, branch, "属性或装备证据")
                pairs = builder.add(
                    node_id=_safe_id(base, f"pairs_{index}"),
                    operator="pairs.build@1.0",
                    display_name=f"{expression.display_name}目标对",
                    inputs={"subjects": current, "objects": evidence},
                    params={
                        "same_source_only": capability
                        == "subject.same_attributes"
                    },
                    business_source_refs=[source_ref],
                )
                measured = builder.add(
                    node_id=_safe_id(base, f"measure_{index}"),
                    operator="pairs.measure@1.0",
                    display_name=f"{expression.display_name}关联测量",
                    inputs={"pairs": pairs},
                    business_source_refs=[source_ref],
                )
                filtered = builder.add(
                    node_id=_safe_id(base, f"filter_{index}"),
                    operator="pairs.filter@1.0",
                    display_name=f"{expression.display_name}关联筛选",
                    inputs={"pairs": measured},
                    params={
                        "metric": "ios",
                        "operator": ">=",
                        "threshold": _float_or_default(
                            p.get("minimum_overlap"),
                            p.get("association")
                            if p.get("association") is not None
                            else 30,
                        )
                        / 100.0,
                    },
                    business_source_refs=[source_ref],
                )
                current = builder.add(
                    node_id=_safe_id(base, f"join_{index}"),
                    operator=(
                        "set.semi_join@1.0"
                        if capability == "subject.same_attributes"
                        else "set.anti_join@1.0"
                    ),
                    display_name=expression.display_name,
                    inputs={"subjects": current, "pairs": filtered},
                    business_source_refs=[source_ref],
                )
            return current
        if capability == "spatial.membership":
            upstream = source()
            region = self._region_value(builder, branch, expression, p.get("scope"))
            condition = builder.add(
                node_id=_safe_id(base, "inside"),
                operator="spatial.inside@1.0",
                display_name=expression.display_name,
                inputs={"objects": upstream, "region": region},
                params={
                    "mode": "center" if p.get("membership") == "center" else "overlap",
                    "overlap_threshold": _float_or_default(
                        p.get("minimum_overlap"), 30
                    )
                    / 100.0,
                },
                business_source_refs=[source_ref],
            )
            if not bool(p.get("inside", True)):
                condition = builder.add(
                    node_id=_safe_id(base, "outside"),
                    operator="logic.not@1.0",
                    display_name=f"{expression.display_name}（区域外）",
                    inputs={"condition": condition},
                    business_source_refs=[source_ref],
                )
            return builder.add(
                node_id=_safe_id(base, "apply"),
                operator="filter.apply@1.0",
                display_name=expression.display_name,
                inputs={"objects": upstream, "condition": condition},
                business_source_refs=[source_ref],
            )
        if capability == "spatial.association":
            subject = compile_source(p.get("subject"), branch, "主体目标")
            object_value = compile_source(p.get("object"), branch, "关联目标")
            pairs = builder.add(
                node_id=_safe_id(base, "pairs"),
                operator="pairs.build@1.0",
                display_name=expression.display_name,
                inputs={"subjects": subject, "objects": object_value},
                business_source_refs=[source_ref],
            )
            measured = builder.add(
                node_id=_safe_id(base, "measure"),
                operator="pairs.measure@1.0",
                display_name=f"{expression.display_name}测量",
                inputs={"pairs": pairs},
                business_source_refs=[source_ref],
            )
            relation = p.get("relation", "overlap")
            metric = {
                "overlap": "iou",
                "contains": "object_coverage",
                "inside": "subject_coverage",
                "near": "center_distance",
                "bidirectional": "ios",
            }[relation]
            return builder.add(
                node_id=_safe_id(base, "filter"),
                operator="pairs.filter@1.0",
                display_name=expression.display_name,
                inputs={"pairs": measured},
                params={
                    "metric": metric,
                    "operator": "<=" if relation == "near" else ">=",
                    "threshold": _float_or_default(p.get("threshold"), 30)
                    / (1.0 if relation == "near" else 100.0),
                },
                business_source_refs=[source_ref],
            )
        if capability == "measure.count":
            upstream = source()
            scope = p.get("scope", "full_frame")
            if scope and scope != "full_frame":
                region = self._region_value(builder, branch, expression, scope)
                measurement = builder.add(
                    node_id=_safe_id(base, "region_count"),
                    operator="measure.region_count@1.0",
                    display_name=f"{expression.display_name}实际数量",
                    inputs={"objects": upstream, "regions": region},
                    params={"membership_mode": "center"},
                    business_source_refs=[source_ref],
                )
            else:
                measurement = builder.add(
                    node_id=_safe_id(base, "count"),
                    operator="measure.count@1.0",
                    display_name=f"{expression.display_name}实际数量",
                    inputs={"entities": upstream},
                    params={
                        "scope": "unique" if upstream.output_type in {"TrackSet", "EventSet"} else "frame",
                        "group_by": "label" if p.get("group_by") == "category" else "none",
                    },
                    business_source_refs=[source_ref],
                )
            condition = builder.add(
                node_id=_safe_id(base, "compare"),
                operator="logic.compare@1.0",
                display_name=expression.display_name,
                inputs={"left": measurement},
                params={
                    "operator": "==" if p.get("operator") == "=" else (p.get("operator") or ">="),
                    "value": _float_or_default(p.get("threshold"), 1),
                },
                business_source_refs=[source_ref],
            )
            condition.measurement_node_id = measurement.node_id
            condition.entity_node_id = upstream.entity_node_id
            return condition
        if capability == "measure.statistic":
            upstream = source()
            statistic = p.get("statistic", "mean")
            measurement = (
                upstream
                if statistic == "latest"
                else builder.add(
                    node_id=_safe_id(base, "statistic"),
                    operator="reduce.statistic@1.0",
                    display_name=f"{expression.display_name}统计值",
                    inputs={"values": upstream},
                    params={"statistic": statistic},
                    business_source_refs=[source_ref],
                )
            )
            condition = builder.add(
                node_id=_safe_id(base, "compare"),
                operator="logic.compare@1.0",
                display_name=expression.display_name,
                inputs={"left": measurement},
                params={
                    "operator": p.get("operator", ">="),
                    "value": _float_or_default(p.get("threshold"), 1),
                },
                business_source_refs=[source_ref],
            )
            condition.measurement_node_id = measurement.node_id
            return condition
        if capability == "motion.track":
            upstream = source()
            tracked = builder.add(
                node_id=_safe_id(base, "track"),
                operator="track.iou@1.0",
                display_name=expression.display_name,
                inputs={"objects": upstream},
                params={
                    "iou_threshold": _float_or_default(
                        p.get("match_requirement"), 40
                    )
                    / 100.0,
                    "max_missing_frames": int(p.get("missing_frames", 5)),
                    "same_label_only": True,
                    "motion_prediction": bool(p.get("motion_prediction", False)),
                },
                business_source_refs=[source_ref],
            )
            return builder.add(
                node_id=_safe_id(base, "confirm"),
                operator="track.confirm@1.0",
                display_name=f"{expression.display_name}确认",
                inputs={"tracks": tracked},
                params={"min_hits": int(p.get("minimum_hits", 2)), "min_span_seconds": 0.0},
                business_source_refs=[source_ref],
            )
        if capability in {"motion.direction", "motion.wrong_way"}:
            upstream = source()
            if capability == "motion.wrong_way":
                scope = p.get("scope")
                if scope and scope != "full_frame":
                    region = self._region_value(builder, branch, expression, scope)
                    membership = builder.add(
                        node_id=_safe_id(base, "inside"),
                        operator="spatial.inside@1.0",
                        display_name=f"{expression.display_name}区域归属",
                        inputs={"objects": upstream, "region": region},
                        params={"mode": "center", "overlap_threshold": 0.3},
                        business_source_refs=[source_ref],
                    )
                    upstream = builder.add(
                        node_id=_safe_id(base, "region_objects"),
                        operator="filter.apply@1.0",
                        display_name=f"{expression.display_name}区域目标",
                        inputs={"objects": upstream, "condition": membership},
                        business_source_refs=[source_ref],
                    )
            tracks = upstream
            if tracks.output_type != "TrackSet":
                tracks = builder.add(
                    node_id=_safe_id(base, "track"),
                    operator="track.iou@1.0",
                    display_name=f"{expression.display_name}轨迹",
                    inputs={"objects": upstream},
                    params={
                        "iou_threshold": 0.4,
                        "max_missing_frames": 5,
                        "same_label_only": True,
                        "motion_consistency": capability == "motion.wrong_way",
                        "motion_prediction": bool(
                            p.get("motion_prediction", capability == "motion.wrong_way")
                        ),
                        "min_direction_cosine": 0.0,
                        "min_motion_pixels": 5.0,
                    },
                    business_source_refs=[source_ref],
                )
            headings = builder.add(
                node_id=_safe_id(base, "heading"),
                operator="measure.heading@1.0",
                display_name=f"{expression.display_name}运动方向",
                inputs={"tracks": tracks},
                params={
                    "window_frames": 5,
                    "min_displacement_pixels": 8.0,
                    "min_displacement_box_ratio": _float_or_default(
                        p.get("small_target_displacement_ratio"), 20
                    ) / 100.0,
                },
                business_source_refs=[source_ref],
            )
            directions = self._direction_value(
                builder, branch, expression, p.get("reference")
            )
            if capability == "motion.wrong_way":
                operator = "opposite_direction"
                threshold = cos(
                    radians(
                        _float_or_default(p.get("minimum_reverse_angle"), 120)
                    )
                )
            else:
                relation = p.get("relation", "same")
                operator = "opposite_direction" if relation == "opposite" else "aligned_direction"
                threshold = cos(
                    radians(_float_or_default(p.get("angle"), 60))
                )
            value = builder.add(
                node_id=_safe_id(base, "compare"),
                operator="logic.compare@1.0",
                display_name=expression.display_name,
                inputs={"left": headings, "right": directions},
                params={"operator": operator, "threshold": threshold},
                business_source_refs=[source_ref],
            )
            value.track_node_id = tracks.node_id
            return value
        if capability == "motion.speed":
            upstream = source()
            if upstream.output_type != "TrackSet":
                raise BusinessRuleCompileError(
                    f"条件“{expression.display_name}”需要先创建目标轨迹。"
                )
            measurement = builder.add(
                node_id=_safe_id(base, "speed"),
                operator="measure.speed@1.0",
                display_name=f"{expression.display_name}实际速度",
                inputs={"tracks": upstream},
                business_source_refs=[source_ref],
            )
            condition = builder.add(
                node_id=_safe_id(base, "compare"),
                operator="logic.compare@1.0",
                display_name=expression.display_name,
                inputs={"left": measurement},
                params={
                    "operator": p.get("operator", ">="),
                    "value": _float_or_default(p.get("threshold"), 1),
                },
                business_source_refs=[source_ref],
            )
            condition.measurement_node_id = measurement.node_id
            condition.track_node_id = upstream.node_id
            return condition
        if capability == "state.current":
            upstream = source()
            return builder.add(
                node_id=_safe_id(base, "state"),
                operator="state.detect@1.0",
                display_name=expression.display_name,
                inputs={"entities": upstream},
                params={
                    "evidence_mode": "label",
                    "state_labels": {},
                    "default_state": "unknown",
                    "positive_state": p["positive_state"],
                    "threshold": 1.0,
                },
                business_source_refs=[source_ref],
            )
        if capability == "state.transition":
            upstream = source()
            return builder.add(
                node_id=_safe_id(base, "transition"),
                operator="state.transition@1.0",
                display_name=expression.display_name,
                inputs={"states": upstream},
                params={
                    "from_state": p["from_state"],
                    "to_state": p["to_state"],
                    "max_seconds": _float_or_default(p.get("maximum_seconds"), 5),
                    "consume_source": True,
                },
                business_source_refs=[source_ref],
            )
        if capability == "event.detect_or_compose":
            upstream = source()
            event_label = str(p.get("event_label") or expression.display_name)
            if upstream.output_type == "EventSet":
                return builder.add(
                    node_id=_safe_id(base, "event_label"),
                    operator="event.relabel@1.0",
                    display_name=expression.display_name,
                    inputs={"events": upstream},
                    params={"label": event_label},
                    business_source_refs=[source_ref],
                )
            condition = self._as_condition(builder, branch, expression, upstream)
            return builder.add(
                node_id=_safe_id(base, "event"),
                operator="event.from_condition@1.0",
                display_name=expression.display_name,
                inputs={"condition": condition},
                params={
                    "seconds": 0.0,
                    "scope": "global",
                    "gap_tolerance_seconds": 0.0,
                    "trigger_mode": "once",
                    "label": event_label,
                },
                business_source_refs=[source_ref],
            )
        if capability == "temporal.persist":
            upstream = source()
            condition = self._as_condition(builder, branch, expression, upstream)
            return builder.add(
                node_id=_safe_id(base, "persist"),
                operator="temporal.persist@1.0",
                display_name=expression.display_name,
                inputs={"condition": condition},
                params={
                    "seconds": _float_or_default(p.get("duration"), 1),
                    "scope": p.get("identity_scope", "global") if p.get("identity_scope") in {"global", "track", "region"} else "global",
                    "gap_tolerance_seconds": _float_or_default(
                        p.get("allowed_gap"), 0.5
                    ),
                    "trigger_mode": "once",
                },
                business_source_refs=[source_ref],
            )
        raise BusinessRuleCompileError(
            f"条件“{expression.display_name}”使用的能力尚未注册确定性编译 Recipe。"
        )

    def _as_condition(
        self,
        builder: _GraphBuilder,
        branch: BusinessBranch,
        expression: ConditionExpression,
        value: CompiledValue,
    ) -> CompiledValue:
        if value.output_type == "ConditionSet":
            return value
        if value.output_type in {
            "ObjectSet",
            "EntitySet",
            "TrackSet",
            "EventSet",
            "PairSet",
            "ScopedSet",
        }:
            return builder.add(
                node_id=_safe_id(
                    branch.branch_id, expression.expression_id, value.node_id, "exists"
                ),
                operator="reduce.exists@1.0",
                display_name=f"{expression.display_name}存在",
                inputs={"sets": value},
                business_source_refs=[f"condition:{expression.expression_id}"],
            )
        raise BusinessRuleCompileError(
            f"条件“{expression.display_name}”的结果不能直接参与 AND / OR；请先添加比较条件。"
        )

    def _as_branch_result(
        self,
        builder: _GraphBuilder,
        branch: BusinessBranch,
        expression: ConditionExpression,
        value: CompiledValue,
    ) -> CompiledValue:
        if value.output_type in {"ConditionSet", "EventSet", "StateSet"}:
            return value
        return self._as_condition(builder, branch, expression, value)

    def _bind_outputs(
        self,
        document: SkillEditorDocument,
        media_type: str,
        builder: _GraphBuilder,
        expressions: dict[str, CompiledValue],
        branches: dict[str, CompiledValue],
    ) -> None:
        for spec in document.skill_template.result_specs:
            if spec.media_types and media_type not in spec.media_types:
                continue
            source_ref = spec.source_ref or ""
            value = None
            if source_ref.startswith("condition:"):
                value = expressions.get(source_ref.split(":", 1)[1])
            elif source_ref.startswith("branch:"):
                branch_id = source_ref.split(":", 1)[1]
                branch = next(
                    (
                        item
                        for item in document.skill_template.business_branches
                        if item.branch_id == branch_id and item.media_type == media_type
                    ),
                    None,
                )
                value = branches.get(branch_id) if branch else None
            elif source_ref.startswith("node:"):
                try:
                    value = builder.existing(source_ref.split(":", 1)[1])
                except BusinessRuleCompileError:
                    value = None
            elif source_ref.startswith("output:"):
                spec.required_outputs = [source_ref.split(":", 1)[1]]
                continue
            elif source_ref.startswith("event:"):
                spec.required_outputs = [f"event_{source_ref.split(':', 1)[1]}"]
                continue
            elif source_ref.startswith("final:"):
                spec.required_outputs = [
                    _safe_id("final", source_ref.split(":", 1)[1])
                ]
                continue
            if value is None:
                continue
            node_id = value.node_id
            if spec.projection.kind in {"count", "value", "duration"} and value.measurement_node_id:
                node_id = value.measurement_node_id
            elif spec.projection.kind == "entities" and value.entity_node_id:
                node_id = value.entity_node_id
            elif spec.projection.kind == "tracks" and value.track_node_id:
                node_id = value.track_node_id
            elif spec.projection.kind == "events" and value.event_node_id:
                node_id = value.event_node_id
            output_name = _safe_id("result", spec.result_id)
            builder.expose(node_id, output_name)
            spec.required_outputs = [output_name]

    @staticmethod
    def _target_list(parameters: dict[str, Any]) -> list[dict[str, Any]]:
        targets = parameters.get("targets") or []
        if isinstance(targets, str):
            targets = [item.strip() for item in targets.replace("，", ",").split(",") if item.strip()]
        phrases_value = parameters.get("phrases") or ""
        phrases = (
            [item.strip() for item in phrases_value.replace("，", ",").split(",") if item.strip()]
            if isinstance(phrases_value, str)
            else list(phrases_value or [])
        )
        result = []
        for index, target in enumerate(targets):
            if isinstance(target, dict):
                label = str(target.get("label") or "").strip()
                target_phrases = target.get("phrases") or phrases or [label]
            else:
                label = str(target).strip()
                target_phrases = phrases if len(targets) == 1 and phrases else [label]
            if label:
                result.append({"label": label, "phrases": target_phrases})
        if not result:
            raise BusinessRuleCompileError("检测目标至少需要一个类别或短语。")
        return result

    @staticmethod
    def _grounding_phrase(builder: _GraphBuilder, value: CompiledValue) -> str | None:
        """Find the affirmative base phrase feeding an entity value.

        Business conditions can pass through relabel, class and geometry
        operators before an attribute is compiled.  Walking incoming graph
        edges keeps the garment evidence tied to the actual target without
        assuming a particular number or order of intermediate filters.
        """

        pending = [value.node_id]
        visited: set[str] = set()
        while pending:
            node_id = pending.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            node = builder.nodes.get(node_id)
            if node is None:
                continue
            if node.operator and node.operator.startswith("rex.ground@"):
                targets = node.params.get("targets") or []
                for target in targets:
                    if not isinstance(target, dict):
                        continue
                    phrases = target.get("phrases") or []
                    if phrases and str(phrases[0]).strip():
                        return str(phrases[0]).strip()
            pending.extend(
                edge.source
                for edge in builder.graph.edges
                if edge.target == node_id
            )
        return None

    @staticmethod
    def _infer_color_carrier(
        parameters: dict[str, Any], display_name: str
    ) -> tuple[str | None, str | None]:
        """Return a garment carrier when a colour describes a body part.

        The business-draft schema intentionally keeps ``attribute.color``
        compact (source/part/color/threshold).  Recover an optional specific
        garment from an LLM display name when present, and otherwise use the
        normalized part.  Whole-object colours stay on the original generic
        fraction path.
        """

        explicit = parameters.get("carrier") or parameters.get("carrier_span")
        part = str(parameters.get("part") or "whole").strip().lower()
        aliases = {
            **CARRIER_TEXT_ALIASES,
            **CARRIER_ALIASES,
        }
        # Preserve a specific visible carrier in the open-vocabulary phrase
        # whenever one is available.  The catalog still supplies the
        # canonical carrier and crop for aliases that do not have a more
        # specific English wording.
        phrase_overrides = {
            "衣服": "clothing", "衣物": "clothing", "服装": "clothing",
            "clothing": "clothing", "clothes": "clothing", "garment": "clothing",
            "上衣": "upper body clothing", "上装": "upper body clothing",
            "衬衫": "shirt", "衬衣": "shirt", "shirt": "shirt",
            "短袖": "short sleeves", "t-shirt": "t-shirt", "tee": "t-shirt",
            "夹克": "jacket", "jacket": "jacket",
            "外套": "coat", "coat": "coat",
            "裤子": "trousers", "长裤": "trousers", "短裤": "shorts",
            "pants": "pants", "trousers": "trousers",
            "裙子": "skirt", "skirt": "skirt",
            "反光衣": "reflective vest", "反光背心": "reflective vest",
            "reflective vest": "reflective vest",
            "安全帽": "helmet", "头盔": "helmet", "帽子": "hat",
            "helmet": "helmet", "safety helmet": "helmet", "hat": "hat",
            "鞋": "shoes", "鞋子": "shoes", "靴子": "boots",
            "shoe": "shoe", "shoes": "shoes", "boots": "boots",
            "车身": "vehicle body", "车辆主体": "vehicle body",
            "vehicle body": "vehicle body",
        }
        phrase_aliases = {
            **aliases,
            # These phrases are common planner output but are intentionally
            # not required as UI parameters.
            "safety helmet": "headwear",
            "short sleeves": "upper_body_clothing",
            "t-shirt": "upper_body_clothing",
            "tee": "upper_body_clothing",
        }

        def resolve(raw: Any) -> tuple[str | None, str | None]:
            text = str(raw or "").strip()
            if not text:
                return None, None
            canonical = phrase_aliases.get(
                text.lower(), text.lower().replace(" ", "_")
            )
            if canonical not in CARRIER_CATALOG:
                return None, None
            phrase = phrase_overrides.get(text.lower()) or CARRIER_CATALOG[canonical]["phrase"]
            return canonical, phrase

        if explicit:
            resolved = resolve(explicit)
            if resolved[0] is not None:
                return resolved

        # Prefer a specific named garment in the condition title, preserving
        # phrases such as “白色衬衫” instead of reducing everything to clothing.
        # Scan the complete catalog alias set so this remains open to new
        # garment/carrier names rather than being hard-coded to one example.
        title = str(display_name or "").strip().lower()
        title_aliases = set(phrase_aliases) | set(phrase_overrides)
        for raw in sorted(title_aliases, key=len, reverse=True):
            if raw.lower() in title:
                canonical = phrase_aliases.get(
                    raw.lower(), raw.lower().replace(" ", "_")
                )
                if canonical in CARRIER_CATALOG:
                    return canonical, phrase_overrides.get(
                        raw.lower(), CARRIER_CATALOG[canonical]["phrase"]
                    )

        if part in {"upper_clothing", "upper_body_clothing", "upper_body", "top"}:
            return "upper_body_clothing", CARRIER_CATALOG["upper_body_clothing"]["phrase"]
        if part in {"lower_clothing", "lower_body_clothing", "lower_body", "bottom"}:
            return "lower_body_clothing", CARRIER_CATALOG["lower_body_clothing"]["phrase"]
        return None, None

    @staticmethod
    def _subject_region(part: str) -> list[float]:
        return {
            "whole": [0.0, 0.0, 1.0, 1.0],
            "upper_clothing": [0.0, 0.05, 1.0, 0.58],
            "upper_body_clothing": [0.0, 0.05, 1.0, 0.58],
            "upper_body": [0.0, 0.05, 1.0, 0.58],
            "lower_clothing": [0.0, 0.42, 1.0, 1.0],
            "lower_body_clothing": [0.0, 0.42, 1.0, 1.0],
            "lower_body": [0.0, 0.42, 1.0, 1.0],
        }.get(part, [0.0, 0.0, 1.0, 1.0])

    def _active_profile(self, document: SkillEditorDocument):
        return next(
            (
                item
                for item in document.scene_profiles
                if item.scene_profile_id == document.active_scene_profile_id
            ),
            None,
        )

    def _resource_items(
        self,
        document: SkillEditorDocument,
        reference: str | None,
        resource_type: str,
    ):
        if not reference or reference == "full_frame":
            raise BusinessRuleCompileError(
                f"{resource_type == 'region' and '区域' or '参考方向'}尚未选择。"
            )
        key = reference.split(":", 1)[1] if ":" in reference else reference
        profile = self._active_profile(document)
        items = []
        if profile:
            for collection in profile.collections:
                for item in collection.items:
                    if item.resource_type != resource_type:
                        continue
                    if item.resource_id == key or collection.requirement_id == key:
                        items.append(item)
        requirement = next(
            (
                item
                for item in document.skill_template.resource_requirements
                if item.requirement_id == key or item.display_name == key
            ),
            None,
        )
        return key, items, requirement

    def _region_value(
        self,
        builder: _GraphBuilder,
        branch: BusinessBranch,
        expression: ConditionExpression,
        reference: str | None,
    ) -> CompiledValue:
        key, items, requirement = self._resource_items(
            self._document_for_builder, reference, "region"
        )
        node_id = _safe_id("resource", key, "regions")
        if node_id in builder.nodes:
            node = builder.nodes[node_id]
            source_ref = f"condition:{expression.expression_id}"
            if source_ref not in node.business_source_refs:
                node.business_source_refs.append(source_ref)
            return builder.existing(node_id)
        regions = [
            {
                "id": item.resource_id,
                "label": item.display_name,
                "shape": item.geometry.get("shape", "polygon"),
                "points": item.geometry.get("points", []),
            }
            for item in items
        ]
        slots = []
        if requirement is not None:
            slots.append(
                ConfigurationSlot(
                    slot_id=_safe_id("slot", requirement.requirement_id),
                    kind="region_set",
                    label=requirement.display_name,
                    binding=ConfigurationBinding(node_id=node_id, parameter="regions"),
                    allowed_shapes=requirement.allowed_shapes or ["rectangle", "polygon"],
                    minimum_items=max(1, requirement.cardinality.minimum),
                    help_text="在 02 标注中绘制实际区域；区域数量可按媒体动态增加。",
                )
            )
        elif not regions:
            raise BusinessRuleCompileError("所选区域尚未在 02 标注中配置。")
        return builder.add(
            node_id=node_id,
            operator="region.manual_set@1.0",
            display_name=requirement.display_name if requirement else items[0].display_name,
            params={"regions": regions},
            business_source_refs=[f"condition:{expression.expression_id}"],
            configuration_slots=slots,
        )

    def _direction_value(
        self,
        builder: _GraphBuilder,
        branch: BusinessBranch,
        expression: ConditionExpression,
        reference: str | None,
    ) -> CompiledValue:
        key, items, requirement = self._resource_items(
            self._document_for_builder, reference, "direction"
        )
        node_id = _safe_id("resource", key, "directions")
        if node_id in builder.nodes:
            node = builder.nodes[node_id]
            source_ref = f"condition:{expression.expression_id}"
            if source_ref not in node.business_source_refs:
                node.business_source_refs.append(source_ref)
            return builder.existing(node_id)
        directions = []
        for item in items:
            geometry = item.geometry
            start = geometry.get("start", [0.0, 0.0])
            end = geometry.get("end", [0.0, 0.0])
            vector = geometry.get("vector") or [
                float(end[0]) - float(start[0]),
                float(end[1]) - float(start[1]),
            ]
            directions.append(
                {
                    "key": item.paired_resource_id or item.resource_id,
                    "vector": vector,
                    "start": start,
                    "end": end,
                }
            )
        slots = []
        if requirement is not None:
            slots.append(
                ConfigurationSlot(
                    slot_id=_safe_id("slot", requirement.requirement_id),
                    kind="direction_set",
                    label=requirement.display_name,
                    binding=ConfigurationBinding(node_id=node_id, parameter="directions"),
                    minimum_items=max(1, requirement.cardinality.minimum),
                    help_text="在 02 标注中绘制正常参考方向；方向数量可按媒体动态增加。",
                )
            )
        elif not directions:
            raise BusinessRuleCompileError("所选参考方向尚未在 02 标注中配置。")
        return builder.add(
            node_id=node_id,
            operator="direction.manual_set@1.0",
            display_name=requirement.display_name if requirement else items[0].display_name,
            params={"directions": directions},
            business_source_refs=[f"condition:{expression.expression_id}"],
            configuration_slots=slots,
        )

    @property
    def _document_for_builder(self) -> SkillEditorDocument:
        if not hasattr(self, "_active_document"):
            raise RuntimeError("business compiler resource context is not active")
        return self._active_document

    @_document_for_builder.setter
    def _document_for_builder(self, value: SkillEditorDocument) -> None:
        self._active_document = value


__all__ = ["BusinessRuleCompileError", "BusinessRuleCompiler", "CompiledValue"]
