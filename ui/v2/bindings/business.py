"""Business page event registration; preserves callback order and signatures."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

from dataclasses import dataclass

import gradio as gr

from ui.event_rule_editor import (
    friendly_choice_label,
)
from ui.v2.bindings.creation import CreationBindings
from ui.v2.controllers.configuration import runtime_edit
from ui.v2.workspace import Workspace


@dataclass(frozen=True)
class BusinessBindings:
    _apply_feedback: Callable[..., Any]
    _read_atomic_updates: Callable[..., Any]
    _unified_editor_outputs: list[gr.Component]


def bind_business(
    controller: V2AppController, workspace: Workspace, creation: CreationBindings
) -> BusinessBindings:
    def _read_atomic_updates(
        effective_json, document_json, variant_name, source_mode_value
    ):
        catalog = controller.editor_service.operator_catalog()
        if not effective_json:
            empty_choice = gr.update(choices=[], value=None)
            return (
                "",
                "请先在 01 生成或加载技能；这里不会把空状态当作配置错误。",
                empty_choice,
                empty_choice,
                gr.update(
                    choices=[
                        (
                            f"{item['display_name']}（{item['operator']}）",
                            item["operator"],
                        )
                        for item in catalog
                    ],
                    value=None,
                ),
                empty_choice,
                empty_choice,
                empty_choice,
                "",
                "[]",
                empty_choice,
                [],
                "[]",
                catalog,
                "### 统一规则编排中心（专业模式）\n生成或加载技能后再读取底层原子配置。",
            )
        resolved_media = controller.preferred_executable_variant(
            effective_json,
            "video" if str(variant_name).startswith("video") else "image",
        )
        values = controller.unified_editor_controls(
            effective_json,
            document_json,
            controller.editor_variant_for_media(resolved_media),
            source_mode_value,
        )
        overview = (
            "### 统一规则编排中心（专业模式）\n"
            f"当前注册 {len(catalog)} 种可插拔原子能力；参数覆盖、图结构、业务分支、"
            "EventPattern、待确认条件与结果契约统一保存在下方 V3 文档。"
        )
        return (*values, catalog, overview)

    _unified_editor_outputs = [
        workspace.review.editor_document,
        workspace.review.unified_status,
        workspace.review.unified_branch,
        workspace.review.atomic_node,
        workspace.review.unified_operator,
        workspace.review.unified_source_node,
        workspace.review.unified_target_node,
        workspace.review.atomic_parameter,
        workspace.review.atomic_value,
        workspace.review.unified_patterns,
        workspace.review.unified_pending_choice,
        workspace.review.unified_pending,
        workspace.review.unified_results,
        workspace.review.atomic_rows,
        workspace.review.editor_overview,
    ]

    def _record_editor_change(method, editor_json, history, *args):
        updated, status = method(editor_json, *args)
        state = dict(history or {})
        undo = list(state.get("undo", []))
        if updated != editor_json:
            undo.append(editor_json)
        return updated, status, {"undo": undo[-50:], "redo": []}

    def _undo_editor(editor_json, history):
        state = dict(history or {})
        undo, redo = list(state.get("undo", [])), list(state.get("redo", []))
        if not undo:
            return editor_json, "没有可撤销的修改。", state
        previous = undo.pop()
        redo.append(editor_json)
        previous = controller._dump(
            controller.configuration_service.stage(
                controller._parse_editor_json(editor_json),
                controller._parse_editor_json(previous),
            )
        )
        return previous, "已撤销上一步配置修改。", {"undo": undo, "redo": redo[-50:]}

    def _redo_editor(editor_json, history):
        state = dict(history or {})
        undo, redo = list(state.get("undo", [])), list(state.get("redo", []))
        if not redo:
            return editor_json, "没有可重做的修改。", state
        following = redo.pop()
        undo.append(editor_json)
        following = controller._dump(
            controller.configuration_service.stage(
                controller._parse_editor_json(editor_json),
                controller._parse_editor_json(following),
            )
        )
        return following, "已重做配置修改。", {"undo": undo[-50:], "redo": redo}

    def _restore_generated(effective_json, editor_json, history, source_mode_value):
        if not effective_json:
            return editor_json, "请先在 01 生成或加载技能。", dict(history or {})
        restored, status = controller.restore_default_editor_document(
            effective_json, source_mode_value
        )
        if editor_json:
            restored = controller._dump(
                controller.configuration_service.stage(
                    controller._parse_editor_json(editor_json),
                    controller._parse_editor_json(restored),
                )
            )
        state = dict(history or {})
        undo = [*state.get("undo", []), editor_json][-50:]
        return restored, status, {"undo": undo, "redo": []}

    _business_editor_outputs = [
        workspace.review.editor_document,
        workspace.review.business_branch,
        workspace.review.business_branch_name,
        workspace.review.business_branch_overview,
        workspace.review.business_condition,
        workspace.review.business_condition_tree,
        workspace.review.business_capability,
        workspace.review.business_condition_name,
        workspace.review.business_parameter_table,
        workspace.review.business_parameter_help,
        workspace.review.business_new_logic_group,
        workspace.review.business_group_members,
    ]

    def _business_rule_updates(
        document_json,
        media_type,
        branch_id=None,
        condition_id=None,
        include_tuning=False,
    ):
        return controller.business_rule_controls(
            document_json,
            media_type,
            branch_id,
            condition_id,
            include_tuning,
        )

    def _business_rule_updates_without_document(
        document_json,
        media_type,
        branch_id=None,
        condition_id=None,
        include_tuning=False,
    ):
        return _business_rule_updates(
            document_json,
            media_type,
            branch_id,
            condition_id,
            include_tuning,
        )[1:]

    _business_imported_logic_outputs = [
        workspace.review.business_imported_logic_group,
        workspace.review.business_imported_logic_selector,
        workspace.review.business_imported_logic_operator,
        workspace.review.business_imported_logic_required,
        workspace.review.business_imported_logic_negated,
        workspace.review.business_imported_logic_summary,
    ]

    # Any generated, preset, historical or restored document is projected
    # through the same business editor view. This is intentionally a single
    # read path; no fixed-case UI is synchronized in the opposite direction.
    workspace.review.editor_document.change(
        _business_rule_updates_without_document,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs[1:],
    ).then(
        controller.business_imported_logic_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_imported_logic_outputs,
    )
    workspace.review.variant_choice.change(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    ).then(
        controller.business_imported_logic_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_imported_logic_outputs,
    )
    workspace.review.business_branch.input(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    ).then(
        controller.business_imported_logic_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_imported_logic_outputs,
    )
    workspace.review.business_condition.input(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )
    workspace.review.business_include_tuning.change(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )

    def _required_count_visibility(operator):
        return gr.update(visible=operator == "N_OF_M")

    workspace.review.business_imported_logic_operator.change(
        _required_count_visibility,
        workspace.review.business_imported_logic_operator,
        workspace.review.business_imported_logic_required,
    )
    workspace.review.business_group_operator.change(
        _required_count_visibility,
        workspace.review.business_group_operator,
        workspace.review.business_group_required,
    )
    workspace.review.business_imported_logic_selector.input(
        controller.business_imported_logic_controls,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_imported_logic_selector,
        ],
        _business_imported_logic_outputs,
    )
    workspace.review.business_imported_logic_apply.click(
        controller.business_update_imported_logic,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_imported_logic_selector,
            workspace.review.business_imported_logic_operator,
            workspace.review.business_imported_logic_required,
            workspace.review.business_imported_logic_negated,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    ).then(
        controller.business_imported_logic_controls,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_imported_logic_selector,
        ],
        _business_imported_logic_outputs,
    )

    _business_expression_logic_outputs = [
        workspace.review.business_expression_logic_group,
        workspace.review.business_expression_logic_selector,
        workspace.review.business_expression_logic_operator,
        workspace.review.business_expression_logic_required,
        workspace.review.business_expression_logic_negated,
        workspace.review.business_expression_logic_summary,
    ]
    workspace.review.editor_document.change(
        controller.business_expression_logic_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_expression_logic_outputs,
    )
    workspace.review.business_branch.input(
        controller.business_expression_logic_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_expression_logic_outputs,
    )
    workspace.review.business_expression_logic_selector.input(
        controller.business_expression_logic_controls,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_expression_logic_selector,
        ],
        _business_expression_logic_outputs,
    )
    workspace.review.business_expression_logic_operator.change(
        _required_count_visibility,
        workspace.review.business_expression_logic_operator,
        workspace.review.business_expression_logic_required,
    )
    workspace.review.business_expression_logic_apply.click(
        controller.business_update_expression_logic,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_expression_logic_selector,
            workspace.review.business_expression_logic_operator,
            workspace.review.business_expression_logic_required,
            workspace.review.business_expression_logic_negated,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    ).then(
        controller.business_expression_logic_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_expression_logic_outputs,
    )

    _business_parameter_outputs = [
        workspace.review.business_parameter_selector,
        workspace.review.business_parameter_readonly,
        workspace.review.business_parameter_select,
        workspace.review.business_parameter_multi,
        workspace.review.business_parameter_number,
        workspace.review.business_parameter_boolean,
        workspace.review.business_parameter_text,
        workspace.review.business_parameter_open_multi,
        workspace.review.business_parameter_control_help,
    ]

    def _business_parameter_updates(
        document_json,
        media_type,
        branch_id,
        condition_id,
        include_tuning,
        parameter_id=None,
    ):
        return controller.business_parameter_controls(
            document_json,
            media_type,
            branch_id,
            condition_id,
            include_tuning,
            parameter_id,
        )

    def _business_parameter_updates_reset(
        document_json,
        media_type,
        branch_id,
        condition_id,
        include_tuning,
    ):
        return controller.business_parameter_controls(
            document_json,
            media_type,
            branch_id,
            condition_id,
            include_tuning,
            None,
        )

    for component in (
        workspace.review.editor_document,
        workspace.review.business_branch,
        workspace.review.business_condition,
        workspace.review.business_include_tuning,
    ):
        component.change(
            _business_parameter_updates_reset,
            [
                workspace.review.editor_document,
                workspace.review.variant_choice,
                workspace.review.business_branch,
                workspace.review.business_condition,
                workspace.review.business_include_tuning,
            ],
            _business_parameter_outputs,
        )
    workspace.review.business_parameter_selector.input(
        _business_parameter_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
            workspace.review.business_parameter_selector,
        ],
        _business_parameter_outputs,
    )

    def _region_override_updates(effective_json, variant_name, selected_event_id=None):
        if not effective_json:
            return (
                gr.update(visible=False),
                gr.update(choices=[], value=None),
                gr.update(value=[]),
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                gr.update(value=None),
                gr.update(value=None),
            )
        media_type = "video" if str(variant_name).startswith("video") else "image"
        controls = controller.read_event_rule_controls(effective_json, media_type)
        eligible = [
            item
            for item in controls
            if item.get("regions") and item.get("regional_parameters")
        ]
        selected = next(
            (item for item in eligible if item["event_id"] == selected_event_id),
            eligible[0] if eligible else None,
        )
        if selected is None:
            return (
                gr.update(visible=False),
                gr.update(choices=[], value=None),
                gr.update(value=[]),
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                gr.update(value=None),
                gr.update(value=None),
            )
        parameters = selected["regional_parameters"]
        show_references = bool(selected.get("region_references"))
        headers = ["已标注区域"]
        if show_references:
            headers.append("该区域参考方向")
        headers.extend(item["label"] for item in parameters)
        rows = []
        for region in selected["regions"]:
            row = [f"{region['label']} ({region['id']})"]
            if show_references:
                row.append(
                    selected["region_references"].get(
                        region["id"], "待在 02 标注参考箭头"
                    )
                )
            for item in parameters:
                current = item.get("overrides", {}).get(region["id"], item["default"])
                row.append(friendly_choice_label(current))
            rows.append(row)
        first_region = selected["regions"][0]["id"]
        first = parameters[0]
        first_parameter = first["id"]
        first_value = first.get("overrides", {}).get(first_region, first["default"])
        return (
            gr.update(visible=True),
            gr.update(
                choices=[(item["event_label"], item["event_id"]) for item in eligible],
                value=selected["event_id"],
            ),
            gr.update(
                headers=headers,
                datatype=["str"] * len(headers),
                value=rows,
                visible=True,
            ),
            gr.update(
                choices=[(item["label"], item["id"]) for item in selected["regions"]],
                value=first_region,
            ),
            gr.update(
                choices=[(item["label"], item["id"]) for item in parameters],
                value=first_parameter,
            ),
            gr.update(
                choices=[
                    (friendly_choice_label(item), item)
                    for item in first.get("choices", [])
                ],
                value=first_value if first["editor"] == "select" else None,
                label=first["label"],
                visible=first["editor"] == "select",
            ),
            gr.update(
                value=first_value if first["editor"] == "number" else None,
                label=first["label"],
                visible=first["editor"] == "number",
            ),
        )

    def _region_event_updates(effective_json, variant_name, event_id):
        updates = _region_override_updates(effective_json, variant_name, event_id)
        return (updates[0], *updates[2:])

    def _region_value_updates(
        effective_json, variant_name, event_id, region_id, parameter_id
    ):
        if not all((effective_json, event_id, region_id, parameter_id)):
            return gr.update(value=None, visible=False), gr.update(
                value=None, visible=False
            )
        media_type = "video" if str(variant_name).startswith("video") else "image"
        selected = next(
            (
                item
                for item in controller.read_event_rule_controls(
                    effective_json, media_type
                )
                if item["event_id"] == event_id
            ),
            None,
        )
        parameter = next(
            (
                item
                for item in (selected or {}).get("regional_parameters", [])
                if item["id"] == parameter_id
            ),
            None,
        )
        if parameter is None:
            return gr.update(value=None, visible=False), gr.update(
                value=None, visible=False
            )
        current = parameter.get("overrides", {}).get(region_id, parameter["default"])
        return (
            gr.update(
                choices=[
                    (friendly_choice_label(item), item)
                    for item in parameter.get("choices", [])
                ],
                value=current if parameter["editor"] == "select" else None,
                label=parameter["label"],
                visible=parameter["editor"] == "select",
            ),
            gr.update(
                value=current if parameter["editor"] == "number" else None,
                label=parameter["label"],
                visible=parameter["editor"] == "number",
            ),
        )

    def _apply_region_overrides(
        effective_json,
        editor_json,
        variant_name,
        event_id,
        region_id,
        parameter_id,
        selected_value,
        number_value,
    ):
        media_type = "video" if str(variant_name).startswith("video") else "image"
        controls = controller.read_event_rule_controls(effective_json, media_type)
        selected = next(
            (item for item in controls if item["event_id"] == event_id),
            None,
        )
        if selected is None:
            raise gr.Error("当前规则没有可按区域配置的参数")
        descriptor = next(
            (
                item
                for item in selected.get("regional_parameters", [])
                if item["id"] == parameter_id
            ),
            None,
        )
        if descriptor is None:
            raise gr.Error("请选择当前事件的区域参数")
        value = selected_value if descriptor["editor"] == "select" else number_value
        updated_effective, changed_nodes = controller.apply_region_parameter_override(
            effective_json,
            media_type,
            event_id,
            region_id,
            parameter_id,
            value,
        )
        updated_editor = controller.sync_editor_region_overrides(
            editor_json,
            updated_effective,
            media_type,
            changed_nodes,
        )
        return updated_effective, updated_editor

    for component in (workspace.review.effective, workspace.review.variant_choice):
        component.change(
            _region_override_updates,
            [workspace.review.effective, workspace.review.variant_choice],
            [
                workspace.review.business_region_override_group,
                workspace.review.business_region_event,
                workspace.review.business_region_overrides,
                workspace.review.business_region_name,
                workspace.review.business_region_comparison,
                workspace.review.business_region_operator,
                workspace.review.business_region_value,
            ],
        )
    workspace.review.business_region_event.input(
        _region_event_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.business_region_event,
        ],
        [
            workspace.review.business_region_override_group,
            workspace.review.business_region_overrides,
            workspace.review.business_region_name,
            workspace.review.business_region_comparison,
            workspace.review.business_region_operator,
            workspace.review.business_region_value,
        ],
    )
    for component in (
        workspace.review.business_region_name,
        workspace.review.business_region_comparison,
    ):
        component.input(
            _region_value_updates,
            [
                workspace.review.effective,
                workspace.review.variant_choice,
                workspace.review.business_region_event,
                workspace.review.business_region_name,
                workspace.review.business_region_comparison,
            ],
            [
                workspace.review.business_region_operator,
                workspace.review.business_region_value,
            ],
        )
    workspace.review.business_region_override_apply.click(
        runtime_edit(controller, _apply_region_overrides),
        [
            workspace.review.editor_document,
            *[
                workspace.review.effective,
                workspace.review.editor_document,
                workspace.review.variant_choice,
                workspace.review.business_region_event,
                workspace.review.business_region_name,
                workspace.review.business_region_comparison,
                workspace.review.business_region_operator,
                workspace.review.business_region_value,
            ],
        ],
        [workspace.review.effective, workspace.review.editor_document],
    ).then(
        _region_override_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.business_region_event,
        ],
        [
            workspace.review.business_region_override_group,
            workspace.review.business_region_event,
            workspace.review.business_region_overrides,
            workspace.review.business_region_name,
            workspace.review.business_region_comparison,
            workspace.review.business_region_operator,
            workspace.review.business_region_value,
        ],
    )
    workspace.review.business_add_branch_button.click(
        controller.business_add_branch,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch_name,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )
    workspace.review.business_branch_action_button.click(
        controller.business_branch_action,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_branch_action,
            workspace.review.business_branch_name,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )
    workspace.review.business_add_condition_button.click(
        controller.business_add_condition,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_capability,
        ],
        [
            workspace.review.editor_document,
            workspace.review.business_condition,
            workspace.review.business_rule_status,
        ],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )

    def _business_condition_action_with_feedback(*args):
        document_json, status, selected = controller.business_condition_action(*args)
        return document_json, status, selected, status

    workspace.review.business_condition_action_button.click(
        _business_condition_action_with_feedback,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_condition_action,
        ],
        [
            workspace.review.editor_document,
            workspace.review.business_rule_status,
            workspace.review.business_condition,
            workspace.review.business_condition_action_status,
        ],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )
    workspace.review.business_restore_button.click(
        controller.restore_default_editor_document,
        [workspace.review.effective, workspace.create.source_mode],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )
    workspace.review.business_group_button.click(
        controller.business_group_conditions,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_group_members,
            workspace.review.business_group_operator,
            workspace.review.business_group_required,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )
    workspace.review.business_apply_condition_button.click(
        controller.business_apply_parameter,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_parameter_selector,
            workspace.review.business_parameter_select,
            workspace.review.business_parameter_multi,
            workspace.review.business_parameter_number,
            workspace.review.business_parameter_boolean,
            workspace.review.business_parameter_text,
            workspace.review.business_parameter_open_multi,
            workspace.review.business_include_tuning,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        _business_rule_updates,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_branch,
            workspace.review.business_condition,
            workspace.review.business_include_tuning,
        ],
        _business_editor_outputs,
    )

    _business_branch_time_outputs = [
        workspace.review.business_branch_time_mode,
        workspace.review.business_branch_duration,
        workspace.review.business_branch_window,
        workspace.review.business_branch_ratio,
        workspace.review.business_branch_gap,
        workspace.review.business_branch_identity,
        workspace.review.business_branch_emission,
        workspace.review.business_branch_validity,
        workspace.review.business_branch_hold,
        workspace.review.business_branch_time_status,
    ]
    workspace.review.editor_document.change(
        controller.business_branch_time_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_branch_time_outputs,
    )
    workspace.review.business_branch.input(
        controller.business_branch_time_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_branch_time_outputs,
    )
    workspace.review.business_branch_time_apply.click(
        controller.business_apply_branch_time,
        [
            workspace.review.editor_document,
            workspace.review.business_branch,
            workspace.review.business_branch_time_mode,
            workspace.review.business_branch_duration,
            workspace.review.business_branch_window,
            workspace.review.business_branch_ratio,
            workspace.review.business_branch_gap,
            workspace.review.business_branch_identity,
            workspace.review.business_branch_emission,
            workspace.review.business_branch_validity,
            workspace.review.business_branch_hold,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        controller.business_branch_time_controls,
        [workspace.review.editor_document, workspace.review.business_branch],
        _business_branch_time_outputs,
    )

    _business_secondary_outputs = [
        workspace.review.business_pattern_branches,
        workspace.review.business_pattern_mode,
        workspace.review.business_pattern_window,
        workspace.review.business_pattern_required,
        workspace.review.business_pattern_correlation,
        workspace.review.business_pattern_status,
        workspace.review.business_final_name,
        workspace.review.business_final_type,
        workspace.review.business_final_source,
        workspace.review.business_final_combination,
        workspace.review.business_final_required,
        workspace.review.business_final_reason,
        workspace.review.business_final_failed,
        workspace.review.business_outputs_table,
        workspace.review.business_trigger_mode,
        workspace.review.business_trigger_cooldown,
        workspace.review.business_trigger_severity,
        workspace.review.business_trigger_outputs,
        workspace.review.business_pattern_panel,
    ]
    workspace.review.editor_document.change(
        controller.business_secondary_controls,
        [workspace.review.editor_document, workspace.review.variant_choice],
        _business_secondary_outputs,
    )
    workspace.review.variant_choice.change(
        controller.business_secondary_controls,
        [workspace.review.editor_document, workspace.review.variant_choice],
        _business_secondary_outputs,
    )
    workspace.review.business_pattern_apply.click(
        controller.business_apply_pattern,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.business_pattern_mode,
            workspace.review.business_pattern_branches,
            workspace.review.business_pattern_window,
            workspace.review.business_pattern_required,
            workspace.review.business_pattern_correlation,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        controller.business_secondary_controls,
        [workspace.review.editor_document, workspace.review.variant_choice],
        _business_secondary_outputs,
    )

    def _business_pattern_parameter_visibility(mode):
        return (
            gr.update(visible=mode == "sequence"),
            gr.update(visible=mode == "n_of_m"),
        )

    workspace.review.business_pattern_mode.change(
        _business_pattern_parameter_visibility,
        workspace.review.business_pattern_mode,
        [
            workspace.review.business_pattern_window,
            workspace.review.business_pattern_required,
        ],
    )
    workspace.review.business_final_apply.click(
        controller.business_apply_final,
        [
            workspace.review.editor_document,
            workspace.review.business_final_name,
            workspace.review.business_final_type,
            workspace.review.business_final_source,
            workspace.review.business_final_combination,
            workspace.review.business_final_required,
            workspace.review.business_final_reason,
            workspace.review.business_final_failed,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        controller.business_secondary_controls,
        [workspace.review.editor_document, workspace.review.variant_choice],
        _business_secondary_outputs,
    )
    workspace.review.business_output_add.click(
        controller.business_add_output_row,
        workspace.review.business_outputs_table,
        workspace.review.business_outputs_table,
    ).then(
        controller.business_output_delete_choices,
        workspace.review.business_outputs_table,
        workspace.review.business_output_delete_select,
    )
    workspace.review.business_outputs_table.change(
        controller.business_output_delete_choices,
        workspace.review.business_outputs_table,
        workspace.review.business_output_delete_select,
    )
    workspace.review.business_output_delete.click(
        controller.business_delete_output_row,
        [
            workspace.review.business_outputs_table,
            workspace.review.business_output_delete_select,
        ],
        workspace.review.business_outputs_table,
    ).then(
        controller.business_output_delete_choices,
        workspace.review.business_outputs_table,
        workspace.review.business_output_delete_select,
    )
    workspace.review.business_outputs_apply.click(
        controller.business_apply_outputs,
        [workspace.review.editor_document, workspace.review.business_outputs_table],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        controller.business_secondary_controls,
        [workspace.review.editor_document, workspace.review.variant_choice],
        _business_secondary_outputs,
    )
    workspace.review.business_trigger_apply.click(
        controller.business_apply_trigger,
        [
            workspace.review.editor_document,
            workspace.review.business_trigger_mode,
            workspace.review.business_trigger_cooldown,
            workspace.review.business_trigger_severity,
            workspace.review.business_trigger_outputs,
        ],
        [workspace.review.editor_document, workspace.review.business_rule_status],
    ).then(
        controller.business_secondary_controls,
        [workspace.review.editor_document, workspace.review.variant_choice],
        _business_secondary_outputs,
    )
    workspace.review.business_compile_apply.click(
        controller.unified_validate_apply,
        workspace.review.editor_document,
        [
            workspace.review.editor_document,
            workspace.review.effective,
            workspace.review.business_rule_status,
        ],
    )

    workspace.review.atomic_read_button.click(
        _read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.create.source_mode,
        ],
        _unified_editor_outputs,
    )
    workspace.review.atomic_node.change(
        controller.unified_node_parameters,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.atomic_node,
        ],
        [workspace.review.atomic_parameter, workspace.review.atomic_value],
    )
    workspace.review.atomic_parameter.change(
        controller.unified_parameter_value,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.atomic_node,
            workspace.review.atomic_parameter,
        ],
        workspace.review.atomic_value,
    )
    workspace.review.atomic_apply_button.click(
        lambda doc, history, node, parameter, value: _record_editor_change(
            controller.unified_apply_parameter, doc, history, node, parameter, value
        ),
        [
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.review.atomic_node,
            workspace.review.atomic_parameter,
            workspace.review.atomic_value,
        ],
        [
            workspace.review.editor_document,
            workspace.review.atomic_status,
            workspace.review.editor_history,
        ],
    )
    workspace.review.atomic_reset_button.click(
        lambda doc, history, node, parameter: _record_editor_change(
            controller.unified_reset_parameter, doc, history, node, parameter
        ),
        [
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.review.atomic_node,
            workspace.review.atomic_parameter,
        ],
        [
            workspace.review.editor_document,
            workspace.review.atomic_status,
            workspace.review.editor_history,
        ],
    ).then(
        controller.unified_node_parameters,
        [
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.review.atomic_node,
        ],
        [workspace.review.atomic_parameter, workspace.review.atomic_value],
    )
    workspace.review.unified_mutate_button.click(
        lambda doc, history, *args: _record_editor_change(
            controller.unified_mutate_graph, doc, history, *args
        ),
        [
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.review.variant_choice,
            workspace.review.unified_action,
            workspace.review.atomic_node,
            workspace.review.unified_new_node_id,
            workspace.review.unified_operator,
            workspace.review.unified_source_node,
            workspace.review.unified_target_node,
            workspace.review.unified_port,
            workspace.review.unified_branch,
        ],
        [
            workspace.review.editor_document,
            workspace.review.unified_status,
            workspace.review.editor_history,
        ],
    ).then(
        _read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.create.source_mode,
        ],
        _unified_editor_outputs,
    )
    workspace.review.unified_branch_button.click(
        lambda doc, history, *args: _record_editor_change(
            controller.unified_mutate_branch, doc, history, *args
        ),
        [
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.review.variant_choice,
            workspace.review.unified_branch_action,
            workspace.review.unified_branch,
            workspace.review.unified_new_branch_id,
            workspace.review.unified_branch_name,
        ],
        [
            workspace.review.editor_document,
            workspace.review.unified_status,
            workspace.review.editor_history,
        ],
    ).then(
        _read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.create.source_mode,
        ],
        _unified_editor_outputs,
    )
    workspace.review.unified_recipe_button.click(
        lambda doc, history, media_type, recipe_id, branch_id: _record_editor_change(
            controller.unified_insert_recipe,
            doc,
            history,
            media_type,
            recipe_id,
            branch_id,
        ),
        [
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.review.variant_choice,
            workspace.review.unified_recipe,
            workspace.review.unified_branch,
        ],
        [
            workspace.review.editor_document,
            workspace.review.unified_status,
            workspace.review.editor_history,
        ],
    ).then(
        _read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.create.source_mode,
        ],
        _unified_editor_outputs,
    )
    workspace.review.unified_patterns_button.click(
        lambda doc, history, patterns: _record_editor_change(
            controller.unified_apply_patterns, doc, history, patterns
        ),
        [
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.review.unified_patterns,
        ],
        [
            workspace.review.editor_document,
            workspace.review.unified_status,
            workspace.review.editor_history,
        ],
    )
    workspace.review.unified_pending_button.click(
        lambda doc, history, decision, value: _record_editor_change(
            controller.unified_resolve_pending, doc, history, decision, value
        ),
        [
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.review.unified_pending_choice,
            workspace.review.unified_pending_value,
        ],
        [
            workspace.review.editor_document,
            workspace.review.unified_status,
            workspace.review.editor_history,
        ],
    ).then(
        _read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.create.source_mode,
        ],
        _unified_editor_outputs,
    )
    workspace.review.unified_results_button.click(
        lambda doc, history, results: _record_editor_change(
            controller.unified_apply_results, doc, history, results
        ),
        [
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.review.unified_results,
        ],
        [
            workspace.review.editor_document,
            workspace.review.unified_status,
            workspace.review.editor_history,
        ],
    )
    for button, handler in (
        (workspace.review.unified_undo_button, _undo_editor),
        (workspace.review.unified_redo_button, _redo_editor),
    ):
        button.click(
            handler,
            [workspace.review.editor_document, workspace.review.editor_history],
            [
                workspace.review.editor_document,
                workspace.review.unified_status,
                workspace.review.editor_history,
            ],
        ).then(
            _read_atomic_updates,
            [
                workspace.review.effective,
                workspace.review.editor_document,
                workspace.review.variant_choice,
                workspace.create.source_mode,
            ],
            _unified_editor_outputs,
        )
    workspace.review.unified_restore_button.click(
        _restore_generated,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.editor_history,
            workspace.create.source_mode,
        ],
        [
            workspace.review.editor_document,
            workspace.review.unified_status,
            workspace.review.editor_history,
        ],
    ).then(
        _read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.create.source_mode,
        ],
        _unified_editor_outputs,
    )
    workspace.review.unified_apply_button.click(
        controller.unified_validate_apply,
        workspace.review.editor_document,
        [
            workspace.review.editor_document,
            workspace.review.effective,
            workspace.review.unified_status,
        ],
    )
    workspace.review.validate_button.click(
        controller.validate_json,
        workspace.review.effective,
        workspace.review.validation,
    )
    workspace.review.diff_button.click(
        controller.diff,
        [workspace.generated_state, workspace.review.effective],
        workspace.review.diff_output,
    )
    workspace.review.save_button.click(
        controller.save_skill_bundle,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.save_id,
            workspace.review.save_display,
            workspace.create.saved_root,
        ],
        workspace.review.saved_path,
    ).then(
        lambda root: gr.update(choices=controller.saved_skill_choices(root)),
        workspace.create.saved_root,
        outputs=workspace.create.saved,
    )
    workspace.assets.asset_save_button.click(
        controller.save_skill_bundle,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.assets.asset_save_id,
            workspace.assets.asset_save_display,
            workspace.assets.asset_save_root,
        ],
        workspace.assets.asset_save_path,
    ).then(
        lambda path: f"已保存当前 Effective SkillPackage：{path}",
        workspace.assets.asset_save_path,
        workspace.assets.asset_status,
    ).then(
        creation._refresh_saved_choices,
        [workspace.create.saved_root, workspace.assets.asset_save_root],
        outputs=[workspace.create.saved, workspace.assets.asset_saved],
    )
    workspace.assets.asset_load_button.click(
        creation._load_asset,
        [workspace.assets.asset_saved, workspace.assets.asset_save_root],
        [
            workspace.generated_state,
            workspace.review.effective,
            workspace.review.semantic,
            workspace.create.source_status,
            workspace.current_source,
            workspace.create.task_target,
        ],
    ).then(
        controller.load_editor_configuration,
        [workspace.review.effective, workspace.create.source_mode],
        workspace.review.editor_document,
    ).then(
        lambda status: status,
        workspace.create.source_status,
        workspace.assets.asset_status,
    ).then(
        creation._unresolved_of,
        workspace.review.semantic,
        workspace.review.unresolved,
    ).then(
        controller.preferred_executable_variant,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.annotation.annotation_variant,
    ).then(
        creation._sync_run_variant,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.run_variant,
    ).then(
        controller.editor_variant_for_media,
        workspace.annotation.annotation_variant,
        workspace.review.variant_choice,
    ).then(
        creation._slot_updates,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        [
            workspace.annotation.annotation_slot,
            workspace.annotation.configuration_slots_view,
            workspace.annotation.annotation_overview,
            workspace.annotation.annotation_wizard,
        ],
    ).then(
        creation._temporal_summary,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.review.event_rule_summary,
    ).then(
        creation._configuration_guidance,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.configuration_guidance,
    )
    workspace.assets.asset_delete_button.click(
        controller.delete_saved_skill,
        [workspace.assets.asset_saved, workspace.assets.asset_save_root],
        workspace.assets.asset_status,
    ).then(
        creation._refresh_saved_choices,
        [workspace.create.saved_root, workspace.assets.asset_save_root],
        outputs=[workspace.create.saved, workspace.assets.asset_saved],
    )
    workspace.assets.asset_refresh_button.click(
        creation._refresh_saved_choices,
        [workspace.create.saved_root, workspace.assets.asset_save_root],
        [workspace.create.saved, workspace.assets.asset_saved],
    )
    workspace.assets.asset_save_root.change(
        creation._mirror_asset_root,
        workspace.assets.asset_save_root,
        [
            workspace.create.saved_root,
            workspace.create.saved,
            workspace.assets.asset_saved,
        ],
    )

    def _apply_feedback(effective_json):
        result = controller.validate_json(effective_json)
        return result, result

    def _sync_field_visibility(resize_m, sample_m, tile_on, size_m, fps_m):
        return (
            gr.update(visible=resize_m == "long_side"),
            gr.update(visible=resize_m in ("contain", "stretch")),
            gr.update(visible=resize_m in ("contain", "stretch")),
            gr.update(visible=sample_m == "fps"),
            gr.update(visible=sample_m == "interval"),
            gr.update(visible=sample_m == "frame_step"),
            gr.update(visible=bool(tile_on)),
            gr.update(visible=size_m == "fixed"),
            gr.update(visible=size_m == "fixed"),
            gr.update(visible=fps_m == "fixed"),
        )

    _visibility_inputs = [
        workspace.review.resize_mode,
        workspace.review.sample_mode,
        workspace.review.tile_enabled,
        workspace.review.output_size_mode,
        workspace.review.output_fps_mode,
    ]
    _visibility_outputs = [
        workspace.review.long_side,
        workspace.review.resize_width,
        workspace.review.resize_height,
        workspace.review.sample_fps,
        workspace.review.interval_seconds,
        workspace.review.frame_step,
        workspace.review.tile_options,
        workspace.review.output_width,
        workspace.review.output_height,
        workspace.review.output_fps,
    ]
    workspace.review.resize_mode.change(
        lambda m: (
            gr.update(visible=m == "long_side"),
            gr.update(visible=m in ("contain", "stretch")),
            gr.update(visible=m in ("contain", "stretch")),
        ),
        workspace.review.resize_mode,
        [
            workspace.review.long_side,
            workspace.review.resize_width,
            workspace.review.resize_height,
        ],
    )
    workspace.review.sample_mode.change(
        lambda m: (
            gr.update(visible=m == "fps"),
            gr.update(visible=m == "interval"),
            gr.update(visible=m == "frame_step"),
        ),
        workspace.review.sample_mode,
        [
            workspace.review.sample_fps,
            workspace.review.interval_seconds,
            workspace.review.frame_step,
        ],
    )
    workspace.review.tile_enabled.change(
        lambda on: gr.update(visible=bool(on)),
        workspace.review.tile_enabled,
        workspace.review.tile_options,
    )
    workspace.review.output_size_mode.change(
        lambda m: (gr.update(visible=m == "fixed"),) * 2,
        workspace.review.output_size_mode,
        [workspace.review.output_width, workspace.review.output_height],
    )
    workspace.review.output_fps_mode.change(
        lambda m: gr.update(visible=m == "fixed"),
        workspace.review.output_fps_mode,
        workspace.review.output_fps,
    )

    def _load_variant_editor(effective_json, variant_name):
        dump, status = controller.select_variant(effective_json, variant_name)
        return gr.update(value=dump, visible=True), status

    workspace.review.load_variant_button.click(
        _load_variant_editor,
        [workspace.review.effective, workspace.review.variant_choice],
        [workspace.review.variant_editor, workspace.review.variant_status],
    )

    def _read_execution_updates(effective_json, variant_name):
        media_type = controller.preferred_executable_variant(
            effective_json,
            "video" if str(variant_name).startswith("video") else "image",
        )
        values = controller.read_execution_controls(effective_json, media_type)
        if values is None:
            return (
                *(gr.skip() for _ in range(20)),
                "请先生成或加载技能，再读取当前参数。",
            )
        sample_values = tuple(
            values.get(name, gr.skip())
            for name in (
                "sample_mode",
                "fps",
                "interval_seconds",
                "frame_step",
                "start_seconds",
                "end_seconds",
                "max_frames",
            )
        )
        return (
            values["resize_mode"],
            values["long_side"],
            values["width"],
            values["height"],
            values["interpolation"],
            values["tile_enabled"],
            values["tile_width"],
            values["tile_height"],
            values["overlap_x"],
            values["overlap_y"],
            values["include_full_frame"],
            values["dedup_metric"],
            values["dedup_threshold"],
            *sample_values,
            "已读取当前 Effective 配置的真实参数。",
        )

    _execution_outputs = [
        workspace.review.resize_mode,
        workspace.review.long_side,
        workspace.review.resize_width,
        workspace.review.resize_height,
        workspace.review.resize_interpolation,
        workspace.review.tile_enabled,
        workspace.review.tile_width,
        workspace.review.tile_height,
        workspace.review.overlap_x,
        workspace.review.overlap_y,
        workspace.review.include_full,
        workspace.review.dedup_metric,
        workspace.review.dedup_threshold,
        workspace.review.sample_mode,
        workspace.review.sample_fps,
        workspace.review.interval_seconds,
        workspace.review.frame_step,
        workspace.review.start_seconds,
        workspace.review.end_seconds,
        workspace.review.max_frames,
        workspace.review.config_status,
    ]
    workspace.review.read_execution_button.click(
        _read_execution_updates,
        [workspace.review.effective, workspace.review.variant_choice],
        _execution_outputs,
    ).then(_sync_field_visibility, _visibility_inputs, _visibility_outputs)
    workspace.review.effective.change(
        _read_execution_updates,
        [workspace.review.effective, workspace.review.variant_choice],
        _execution_outputs,
    ).then(_sync_field_visibility, _visibility_inputs, _visibility_outputs)
    workspace.review.variant_choice.change(
        _read_execution_updates,
        [workspace.review.effective, workspace.review.variant_choice],
        _execution_outputs,
    ).then(_sync_field_visibility, _visibility_inputs, _visibility_outputs)

    return BusinessBindings(
        _apply_feedback=_apply_feedback,
        _read_atomic_updates=_read_atomic_updates,
        _unified_editor_outputs=_unified_editor_outputs,
    )
