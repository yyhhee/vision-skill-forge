"""Events page event registration; preserves callback order and signatures."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

import json
from dataclasses import dataclass

import gradio as gr

from ui.v2.bindings.business import BusinessBindings
from ui.v2.bindings.creation import CreationBindings
from ui.v2.controllers.configuration import runtime_edit
from ui.v2.workspace import Workspace


@dataclass(frozen=True)
class EventsBindings:
    _event_card_updates: Callable[..., Any]
    _read_event_rule_updates: Callable[..., Any]
    event_rule_card_outputs: list[gr.Component]
    event_rule_outputs: list[gr.Component]


def bind_events(
    controller: V2AppController,
    workspace: Workspace,
    business: BusinessBindings,
    creation: CreationBindings,
) -> EventsBindings:
    def _read_event_rule_updates(effective_json, variant_name, selected_id=None):
        empty = (
            gr.update(choices=[], value=None),
            "",
            gr.update(choices=[], value=[]),
            gr.update(choices=[], value=None),
            gr.update(choices=[], value=None),
            ">=",
            0.0,
            gr.update(visible=False),
            gr.update(choices=[], value=None),
            ">=",
            0.0,
            "all",
            1.0,
            0.5,
            "once",
            "",
            "当前流程没有可编辑事件；普通检测无需配置事件规则。",
            gr.update(value=[], visible=False),
        )
        if not effective_json:
            return empty
        media_type = "video" if variant_name.startswith("video") else "image"
        controls = controller.read_event_rule_controls(effective_json, media_type)
        if not controls:
            return empty
        selected = next(
            (item for item in controls if item["event_id"] == selected_id),
            controls[0],
        )
        comparisons = selected["comparisons"]
        first = comparisons[0] if comparisons else None
        second = comparisons[1] if len(comparisons) > 1 else None
        choices = [
            (f"{item['event_label']}（{item['event_id']}）", item["event_id"])
            for item in controls
        ]
        comparison_choices = []
        for item in comparisons:
            region_choices = item.get("region_choices", [])
            if region_choices:
                comparison_choices.extend(
                    (
                        f"{item['measure']} · 区域{region_index}：{region['label']} ({region['id']})",
                        f"{item['node_id']}@@{region['id']}",
                    )
                    for region_index, region in enumerate(region_choices, start=1)
                )
                comparison_choices.append(
                    (
                        f"{item['measure']} · 全部手工标注区域",
                        item["node_id"],
                    )
                )
            else:
                comparison_choices.append((item["measure"], item["node_id"]))

        def _comparison_selection(item):
            if not item:
                return None
            region_id = item.get("region_id")
            return (
                f"{item['node_id']}@@{region_id}"
                if region_id is not None
                else item["node_id"]
            )

        scope_labels = {
            "global": "全画面",
            "region": "每个命名区域（在“02 标注”绘制或修改区域）",
            "track": "每条目标轨迹",
        }
        more_conditions = max(0, len(comparisons) - 2)
        suffix = (
            f"；另有 {more_conditions} 条条件保留原值，可在高级 JSON 中编辑"
            if more_conditions
            else ""
        )
        status = (
            f"当前规则：{selected['event_label']}；范围为 {selected['scope_label']}；"
            f"共 {len(comparisons)} 条可比较条件{suffix}。"
        )
        if selected["condition_kind"] == "direction":
            status = (
                f"当前规则：{selected['event_label']}；{selected['condition_summary']}；"
                "这是方向/空间关系，不是数量或速度比较。"
                "请到“02 标注”配置车道区域和参考方向箭头；"
                f"持续 {selected['seconds']:g} 秒后触发。"
            )
        elif selected["condition_kind"] == "state":
            state = selected.get("state_condition") or {}
            status = (
                f"当前规则：{selected['event_label']}；{selected['condition_summary']}；"
                f"状态原子：{state.get('label', state.get('node_id', '状态条件'))}。"
                "系统按逐帧目标关联/状态结果判断，不需要数值比较卡；"
                f"持续 {selected['seconds']:g} 秒后触发。"
            )
        return (
            gr.update(choices=choices, value=selected["event_id"]),
            selected["category_node_id"] or "",
            gr.update(
                choices=selected["categories"],
                value=selected["selected_categories"],
            ),
            gr.update(
                choices=[
                    (scope_labels[scope], scope) for scope in selected["scope_choices"]
                ],
                value=selected["scope"],
            ),
            gr.update(
                choices=comparison_choices,
                value=_comparison_selection(first),
                interactive=first is not None,
            ),
            first["operator"] if first else ">=",
            first["value"] if first else 0.0,
            gr.update(visible=second is not None),
            gr.update(
                choices=comparison_choices,
                value=_comparison_selection(second),
                interactive=second is not None,
            ),
            second["operator"] if second else ">=",
            second["value"] if second else 0.0,
            gr.update(value=selected["logic"], interactive=len(comparisons) > 1),
            selected["seconds"],
            selected["gap_tolerance_seconds"],
            selected["trigger_mode"],
            selected["event_label"],
            status,
            gr.update(
                value=[],
                visible=False,
            ),
        )

    def _read_selected_event_rule_values(
        effective_json, variant_name, selected_id=None
    ):
        values = _read_event_rule_updates(effective_json, variant_name, selected_id)
        return values[1:]

    event_rule_outputs = [
        workspace.review.event_rule_event,
        workspace.review.event_rule_category_node,
        workspace.review.event_rule_categories,
        workspace.review.event_rule_scope,
        workspace.review.event_rule_condition_1,
        workspace.review.event_rule_operator_1,
        workspace.review.event_rule_value_1,
        workspace.review.event_rule_condition_2_row,
        workspace.review.event_rule_condition_2,
        workspace.review.event_rule_operator_2,
        workspace.review.event_rule_value_2,
        workspace.review.event_rule_logic,
        workspace.review.event_rule_seconds,
        workspace.review.event_rule_gap,
        workspace.review.event_rule_trigger,
        workspace.review.event_rule_alert,
        workspace.review.event_rule_status,
        workspace.review.event_rule_region_overrides,
    ]

    event_rule_card_outputs = [workspace.review.event_rule_card_state]
    for card in workspace.review.event_rule_cards:
        event_rule_card_outputs.extend(
            [
                card["group"],
                card["enabled"],
                card["source"],
                card["categories"],
                card["operator"],
                card["value"],
            ]
        )

    def _card_selection(item):
        if item is None:
            return None
        region_id = item.get("region_id")
        return (
            f"{item['source_template_id']}@@{region_id}"
            if region_id is not None
            else item["source_template_id"]
        )

    def _event_card_updates(effective_json, variant_name, selected_id=None):
        if not effective_json:
            empty = [json.dumps([False] * len(workspace.review.event_rule_cards))]
            for _ in workspace.review.event_rule_cards:
                empty.extend(
                    [
                        gr.update(visible=False),
                        False,
                        gr.update(choices=[], value=None),
                        gr.update(choices=[], value=[]),
                        ">=",
                        0.0,
                    ]
                )
            return tuple(empty)
        media_type = "video" if variant_name.startswith("video") else "image"
        controls = controller.read_event_rule_controls(effective_json, media_type)
        selected = next(
            (item for item in controls if item["event_id"] == selected_id),
            controls[0] if controls else None,
        )
        if selected is None or selected["condition_kind"] != "comparison":
            return _event_card_updates("", variant_name)
        canonical_source_ids: dict[tuple[str, tuple[str, ...]], str] = {}
        source_items = []
        for item in selected["comparisons"]:
            fixed_region = item.get("fixed_region") or {}
            source_key = (
                item["measure"],
                tuple(region["id"] for region in item.get("region_choices", [])),
                fixed_region.get("id"),
            )
            canonical_id = canonical_source_ids.setdefault(source_key, item["node_id"])
            item["source_template_id"] = canonical_id
            if canonical_id == item["node_id"]:
                source_items.append(item)

        choices = []
        for item in source_items:
            regions = item.get("region_choices", [])
            fixed_region = item.get("fixed_region")
            if fixed_region:
                choices.append(
                    (
                        f"{item['measure']} · {fixed_region['label']} ({fixed_region['id']})",
                        item["source_template_id"],
                    )
                )
            elif regions:
                # A regional count can be converted into the separate
                # measure.count atom.  Other regional measures (such as
                # region speed) do not yet have a compatible global atom,
                # so never present an option that would be misleading.
                if item["measure"] == "每个命名区域内目标数量":
                    choices.append(
                        (
                            "全画面目标数量",
                            f"{item['source_template_id']}@@__global__",
                        )
                    )
                choices.extend(
                    [
                        (
                            f"{item['measure']} · 区域{position}：{region['label']} ({region['id']})",
                            f"{item['source_template_id']}@@{region['id']}",
                        )
                        for position, region in enumerate(regions, start=1)
                    ]
                )
                choices.append(
                    (
                        f"{item['measure']} · 全部手工标注区域",
                        item["source_template_id"],
                    )
                )
            else:
                choices.append(
                    (
                        f"{item['measure']} · 全部手工标注区域（请先在“02 标注”绘制）",
                        item["source_template_id"],
                    )
                )
        comparisons = selected["comparisons"]
        values = [
            json.dumps(
                [
                    index < len(comparisons)
                    for index in range(len(workspace.review.event_rule_cards))
                ]
            )
        ]
        default = comparisons[0] if comparisons else None
        for index, _ in enumerate(workspace.review.event_rule_cards):
            item = comparisons[index] if index < len(comparisons) else default
            active = item is not None and index < len(comparisons)
            values.extend(
                [
                    gr.update(visible=active),
                    active,
                    gr.update(
                        choices=choices,
                        value=_card_selection(item),
                        interactive=item is not None,
                    ),
                    gr.update(
                        choices=selected["categories"],
                        value=selected["selected_categories"],
                    ),
                    item["operator"] if item else ">=",
                    item["value"] if item else 0.0,
                ]
            )
        return tuple(values)

    association_card_outputs = [
        workspace.review.event_rule_association_group,
        workspace.review.event_rule_association,
        workspace.review.event_rule_association_subject,
        workspace.review.event_rule_association_object,
        workspace.review.event_rule_association_threshold,
    ]

    def _association_card_updates(
        effective_json, variant_name, event_id=None, association_id=None
    ):
        empty = (
            gr.update(visible=False),
            gr.update(choices=[], value=None),
            gr.update(choices=[], value=None),
            gr.update(choices=[], value=None),
            0.3,
        )
        if not effective_json:
            return empty
        media_type = "video" if variant_name.startswith("video") else "image"
        controls = controller.read_event_rule_controls(effective_json, media_type)
        event = next(
            (item for item in controls if item["event_id"] == event_id),
            controls[0] if controls else None,
        )
        associations = (event or {}).get("associations", [])
        if not associations:
            return empty
        selected = next(
            (item for item in associations if item["node_id"] == association_id),
            associations[0],
        )
        association_choices = [
            (f"{item['label']}（{item['node_id']}）", item["node_id"])
            for item in associations
        ]
        candidate_choices = [
            (f"{item['label']}（{item['key']}）", item["key"])
            for item in selected["candidates"]
        ]
        return (
            gr.update(visible=True),
            gr.update(choices=association_choices, value=selected["node_id"]),
            gr.update(choices=candidate_choices, value=selected["subject"]["key"]),
            gr.update(choices=candidate_choices, value=selected["object"]["key"]),
            selected["threshold"],
        )

    def _add_event_card(card_state):
        try:
            state = json.loads(card_state or "[]")
        except (TypeError, json.JSONDecodeError):
            state = []
        state = [
            bool(state[index]) if index < len(state) else False
            for index in range(len(workspace.review.event_rule_cards))
        ]
        try:
            state[state.index(False)] = True
        except ValueError as exc:
            raise gr.Error("单个事件最多配置 6 个条件") from exc
        return [json.dumps(state), *[gr.update(visible=active) for active in state]]

    def _remove_event_card(index, card_state):
        try:
            state = json.loads(card_state or "[]")
        except (TypeError, json.JSONDecodeError):
            state = []
        state = [
            bool(state[position]) if position < len(state) else False
            for position in range(len(workspace.review.event_rule_cards))
        ]
        state[index] = False
        return [json.dumps(state), *[gr.update(visible=active) for active in state]]

    workspace.review.event_rule_add_condition.click(
        _add_event_card,
        workspace.review.event_rule_card_state,
        [
            workspace.review.event_rule_card_state,
            *[card["group"] for card in workspace.review.event_rule_cards],
        ],
    )
    for card_index, card in enumerate(workspace.review.event_rule_cards):
        card["delete"].click(
            lambda state, index=card_index: _remove_event_card(index, state),
            workspace.review.event_rule_card_state,
            [
                workspace.review.event_rule_card_state,
                *[item["group"] for item in workspace.review.event_rule_cards],
            ],
        )
    workspace.review.event_rule_read_button.click(
        _read_event_rule_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        event_rule_outputs,
    ).then(
        _event_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        event_rule_card_outputs,
    ).then(
        _association_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        association_card_outputs,
    )
    workspace.review.event_rule_event.input(
        _read_selected_event_rule_values,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        event_rule_outputs[1:],
    ).then(
        _event_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        event_rule_card_outputs,
    ).then(
        _association_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        association_card_outputs,
    )
    workspace.review.event_rule_association.input(
        _association_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
            workspace.review.event_rule_association,
        ],
        association_card_outputs,
    )

    def _region_overrides_from_table(
        effective_json, variant_name, event_id, comparison_ids, table
    ):
        controls = controller.read_event_rule_controls(
            effective_json,
            "video" if variant_name.startswith("video") else "image",
        )
        selected = next(
            (item for item in controls if item["event_id"] == event_id),
            None,
        )
        if selected is None:
            raise gr.Error("找不到要编辑的事件规则")
        display_to_id = {
            f"{item['label']} ({item['id']})": item["id"]
            for item in selected.get("regions", [])
        }
        display_to_id.update(
            {item["id"]: item["id"] for item in selected.get("regions", [])}
        )
        rows = table.tolist() if hasattr(table, "tolist") else (table or [])
        overrides = {}
        operator_overrides = {}
        uses_operator_columns = any(
            len(row) >= 1 + 2 * len(comparison_ids) for row in rows if row
        )
        for row in rows:
            if not row or row[0] is None:
                continue
            region_id = display_to_id.get(str(row[0]).strip())
            if region_id is None:
                raise gr.Error("区域行必须保留已标注区域名称，不能自行修改")
            values = {}
            operators = {}
            for index, comparison_id in enumerate(comparison_ids, start=1):
                if uses_operator_columns:
                    operator_index = 1 + 2 * (index - 1)
                    value_index = operator_index + 1
                    operator = (
                        row[operator_index] if operator_index < len(row) else None
                    )
                    value = row[value_index] if value_index < len(row) else None
                else:
                    operator = None
                    value = row[index] if index < len(row) else None
                if operator is not None and str(operator).strip():
                    normalized = str(operator).strip()
                    if normalized not in {">", ">=", "=", "<=", "<", "==", "!="}:
                        raise gr.Error("区域专属比较符必须是 >、>=、=、<=、<、== 或 !=")
                    operators[comparison_id] = normalized
                if value is None or str(value).strip().lower() in {"", "nan"}:
                    continue
                try:
                    values[comparison_id] = float(value)
                except (TypeError, ValueError) as exc:
                    raise gr.Error("区域覆盖阈值必须是数字") from exc
            if values:
                overrides[region_id] = values
            if operators:
                operator_overrides[region_id] = operators
        return overrides, operator_overrides

    def _apply_event_rule(
        effective_json,
        variant_name,
        event_id,
        category_node_id,
        categories,
        scope,
        first_id,
        first_operator,
        first_value,
        second_id,
        second_operator,
        second_value,
        logic_mode,
        seconds,
        gap,
        trigger_mode,
        alert_label,
        region_overrides_table,
    ):
        def _decode_selection(selection):
            if not selection:
                return None, None
            if "@@" not in str(selection):
                return str(selection), None
            comparison_id, region_id = str(selection).split("@@", 1)
            return comparison_id, region_id

        first_comparison_id, first_region_id = _decode_selection(first_id)
        second_comparison_id, second_region_id = _decode_selection(second_id)
        selected_comparisons = [
            (first_comparison_id, first_region_id),
            (second_comparison_id, second_region_id),
        ]
        selected_comparisons = [item for item in selected_comparisons if item[0]]
        comparison_ids = [item[0] for item in selected_comparisons]
        region_bindings = [item[1] for item in selected_comparisons]
        comparison_operators = [first_operator]
        comparison_values = [first_value]
        if second_id:
            comparison_operators.append(second_operator)
            comparison_values.append(second_value)
        region_overrides, region_operator_overrides = _region_overrides_from_table(
            effective_json,
            variant_name,
            event_id,
            comparison_ids,
            region_overrides_table,
        )
        return controller.apply_event_rule_control(
            effective_json,
            variant_name,
            event_id,
            category_node_id or None,
            categories,
            comparison_ids,
            comparison_operators[: len(comparison_ids)],
            comparison_values[: len(comparison_ids)],
            logic_mode,
            seconds,
            gap,
            trigger_mode,
            alert_label,
            scope=scope,
            region_overrides=region_overrides,
            region_operator_overrides=region_operator_overrides,
            region_bindings=region_bindings,
        )

    event_rule_card_inputs = []
    for card in workspace.review.event_rule_cards:
        event_rule_card_inputs.extend(
            [
                card["enabled"],
                card["source"],
                card["categories"],
                card["operator"],
                card["value"],
            ]
        )

    def _apply_event_rule_cards(
        effective_json,
        variant_name,
        event_id,
        card_state,
        logic_mode,
        seconds,
        gap,
        trigger_mode,
        alert_label,
        association_id,
        association_subject,
        association_object,
        association_threshold,
        *card_values,
    ):
        try:
            state = json.loads(card_state or "[]")
        except (TypeError, json.JSONDecodeError):
            state = []
        cards = []
        for index, active in enumerate(state[: len(workspace.review.event_rule_cards)]):
            offset = index * 5
            enabled, source, categories, operator, value = card_values[
                offset : offset + 5
            ]
            if not active or not enabled:
                continue
            if not source:
                raise gr.Error(f"条件 {index + 1} 需要选择区域与统计量")
            if "@@" in str(source):
                template_id, region_id = str(source).split("@@", 1)
            else:
                template_id, region_id = str(source), None
            cards.append(
                {
                    "template_id": template_id,
                    "region_id": region_id,
                    "categories": list(categories or []),
                    "operator": operator,
                    "value": value,
                }
            )
        updated = controller.apply_event_rule_cards(
            effective_json,
            variant_name,
            event_id,
            cards,
            logic_mode,
            seconds,
            gap,
            trigger_mode,
            alert_label,
        )
        if not association_id:
            return updated
        media_type = "video" if variant_name.startswith("video") else "image"
        return controller.apply_event_association(
            updated,
            media_type,
            event_id,
            association_id,
            association_subject,
            association_object,
            association_threshold,
        )

    # Retains the stable internal API used by saved UI-client integrations.
    # It is intentionally not connected to a visible control.
    workspace.review.event_rule_legacy_apply_probe.click(
        runtime_edit(controller, _apply_event_rule),
        [
            workspace.review.editor_document,
            *[
                workspace.review.effective,
                workspace.review.variant_choice,
                workspace.review.event_rule_event,
                workspace.review.event_rule_category_node,
                workspace.review.event_rule_categories,
                workspace.review.event_rule_scope,
                workspace.review.event_rule_condition_1,
                workspace.review.event_rule_operator_1,
                workspace.review.event_rule_value_1,
                workspace.review.event_rule_condition_2,
                workspace.review.event_rule_operator_2,
                workspace.review.event_rule_value_2,
                workspace.review.event_rule_logic,
                workspace.review.event_rule_seconds,
                workspace.review.event_rule_gap,
                workspace.review.event_rule_trigger,
                workspace.review.event_rule_alert,
                workspace.review.event_rule_region_overrides,
            ],
        ],
        workspace.review.effective,
    )

    workspace.review.event_rule_apply_button.click(
        runtime_edit(controller, _apply_event_rule_cards),
        [
            workspace.review.editor_document,
            *[
                workspace.review.effective,
                workspace.review.variant_choice,
                workspace.review.event_rule_event,
                workspace.review.event_rule_card_state,
                workspace.review.event_rule_logic,
                workspace.review.event_rule_seconds,
                workspace.review.event_rule_gap,
                workspace.review.event_rule_trigger,
                workspace.review.event_rule_alert,
                workspace.review.event_rule_association,
                workspace.review.event_rule_association_subject,
                workspace.review.event_rule_association_object,
                workspace.review.event_rule_association_threshold,
                *event_rule_card_inputs,
            ],
        ],
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    ).then(
        _read_event_rule_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        event_rule_outputs,
    ).then(
        _event_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        event_rule_card_outputs,
    ).then(
        _association_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        association_card_outputs,
    ).then(
        lambda effective_json, variant_name: controller.temporal_rules_markdown(
            effective_json,
            "video" if variant_name.startswith("video") else "image",
        ),
        [workspace.review.effective, workspace.review.variant_choice],
        workspace.review.event_rule_summary,
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
        creation._configuration_guidance,
        [workspace.review.effective, workspace.annotation.annotation_variant],
        workspace.create.configuration_guidance,
    )
    workspace.review.effective.change(
        _read_event_rule_updates,
        [workspace.review.effective, workspace.review.variant_choice],
        event_rule_outputs,
    ).then(
        _event_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        event_rule_card_outputs,
    ).then(
        _association_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        association_card_outputs,
    ).then(
        business._read_atomic_updates,
        [
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.review.variant_choice,
            workspace.create.source_mode,
        ],
        business._unified_editor_outputs,
    )
    workspace.review.variant_choice.change(
        _read_event_rule_updates,
        [workspace.review.effective, workspace.review.variant_choice],
        event_rule_outputs,
    ).then(
        _event_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        event_rule_card_outputs,
    ).then(
        _association_card_updates,
        [
            workspace.review.effective,
            workspace.review.variant_choice,
            workspace.review.event_rule_event,
        ],
        association_card_outputs,
    )
    workspace.review.variant_choice.change(
        creation._configuration_guidance,
        [workspace.review.effective, workspace.review.variant_choice],
        workspace.create.configuration_guidance,
    )

    workspace.review.variant_choice.change(
        lambda effective_json, variant_name: controller.temporal_rules_markdown(
            effective_json,
            "video" if variant_name.startswith("video") else "image",
        ),
        [workspace.review.effective, workspace.review.variant_choice],
        workspace.review.event_rule_summary,
    )
    workspace.review.apply_variant_button.click(
        runtime_edit(controller, controller.apply_variant_json),
        [
            workspace.review.editor_document,
            *[
                workspace.review.effective,
                workspace.review.variant_choice,
                workspace.review.variant_editor,
            ],
        ],
        workspace.review.effective,
    ).then(
        business._apply_feedback,
        workspace.review.effective,
        [workspace.review.config_status, workspace.review.validation],
    )

    return EventsBindings(
        _event_card_updates=_event_card_updates,
        _read_event_rule_updates=_read_event_rule_updates,
        event_rule_card_outputs=event_rule_card_outputs,
        event_rule_outputs=event_rule_outputs,
    )
