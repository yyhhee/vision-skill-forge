from __future__ import annotations

from typing import Any

from .editor_schema import SkillEditorDocument
from .parameter_presentations import parameter_presentation
from .registry import OperatorDefinition, OperatorRegistry


def _asset_layer(operator: str, business_atoms: set[str]) -> tuple[str, str]:
    if operator in business_atoms:
        return "业务组合", "由业务能力自动编译使用，可在此查看其实现说明。"
    return "系统基础", "运行时自动补全的输入、资源、证据或输出步骤，不是业务配置入口。"


def _category(definition: OperatorDefinition) -> str:
    prefix = definition.op.split(".", 1)[0]
    if prefix in {"media", "video", "image", "object", "objects", "filter"}:
        return "媒体与目标处理"
    if prefix in {"region", "regions", "direction", "spatial", "pairs", "set"}:
        return "空间、区域与关联"
    if prefix in {"measure", "reduce"}:
        return "数量与测量"
    if prefix in {"track", "tracks"}:
        return "轨迹与运动"
    if prefix in {"state", "event"}:
        return "状态与事件"
    if prefix in {"temporal", "logic"}:
        return "逻辑与时间编排"
    if prefix in {"output", "result", "evidence"}:
        return "结果、证据与输出"
    return "其它执行能力"


def _usage(document: SkillEditorDocument | None, operator: str) -> list[dict[str, str]]:
    if document is None:
        return []
    branch_by_node = {
        node_id: branch
        for branch in document.skill_template.business_branches
        for node_id in branch.node_ids
    }
    rows = []
    for media_type, graph in document.skill_template.rule_graphs.items():
        for node in graph.nodes:
            if node.operator != operator:
                continue
            branch = branch_by_node.get(node.node_id)
            rows.append(
                {
                    "media_type": media_type,
                    "node_id": node.node_id,
                    "node_name": node.display_name,
                    "branch_id": branch.branch_id if branch else "",
                    "branch_name": branch.display_name if branch else "",
                }
            )
    return rows


def build_operator_asset_catalog(
    registry: OperatorRegistry,
    document: SkillEditorDocument | None = None,
) -> list[dict[str, Any]]:
    # Keep the public catalog tied to business capabilities without changing the
    # registry or compiler choices used by existing preset skills.
    from .business_capabilities import build_business_capability_registry

    business_atoms = {
        atom
        for capability in build_business_capability_registry(registry).definitions()
        for atom in capability.atoms
    }
    assets = []
    for definition in registry.definitions():
        layer, layer_description = _asset_layer(definition.op, business_atoms)
        parameters = []
        names = sorted(set(definition.parameters) | set(definition.defaults))
        for name in names:
            spec = definition.parameters.get(name)
            presentation = parameter_presentation(
                name, spec, operator_help=definition.fixed_rule_text
            )
            parameters.append(
                {
                    "label": presentation.label,
                    "short_help": presentation.short_help,
                    "detail": presentation.detail,
                    "unit": presentation.unit,
                    "recommended": presentation.recommended,
                    "larger_effect": presentation.larger_effect,
                    "smaller_effect": presentation.smaller_effect,
                    "example": presentation.example,
                    "level": presentation.level,
                    "default": definition.defaults.get(name),
                    "required": bool(spec.required) if spec else False,
                    "choices": list(spec.choices) if spec else [],
                    "minimum": spec.minimum if spec else None,
                    "maximum": spec.maximum if spec else None,
                    "developer_info": {
                        "technical_name": name,
                        "operator": definition.op,
                        "value_transform": presentation.value_transform,
                    },
                }
            )
        assets.append(
            {
                "operator": definition.op,
                "display_name": definition.display_name,
                "category": _category(definition),
                "layer": layer,
                "layer_description": layer_description,
                "default_visible": layer == "业务组合",
                "description": definition.fixed_rule_text,
                "execution_scope": definition.execution_scope,
                "input_types": definition.input_types,
                "output_type": definition.output_type,
                "parameters": parameters,
                "current_usage": _usage(document, definition.op),
            }
        )
    return assets


__all__ = ["build_operator_asset_catalog"]
