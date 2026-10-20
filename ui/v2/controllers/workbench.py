"""Read-only skill overview and navigation into the existing business editors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from typing import Any

import gradio as gr

from application.v2.support import _variant_key
from ui.event_rule_editor import friendly_choice_label
from ui.v2.controllers.pattern_editor import PATTERN_MODES


@dataclass(frozen=True)
class WorkbenchItem:
    """A navigation address, never a second copy of editable configuration."""

    kind: str
    identity: str
    label: str
    detail: str
    branch_id: str = ""

    @property
    def address(self) -> str:
        return json.dumps(
            [self.kind, self.identity, self.branch_id], ensure_ascii=False
        )


SECTIONS = (
    ("branch", "分支条件", "每个分支分别判断什么"),
    ("group", "分支编排", "分支或已有组之间的关系"),
    ("final", "最终判定", "哪些结果决定整项技能成立"),
    ("output", "业务输出", "实际输出什么、取自哪里"),
    ("trigger", "触发策略", "什么时候产生记录"),
)

BRANCH_FIELDS = (
    "business_branch",
    "business_branch_name",
    "business_branch_overview",
    "business_condition",
    "business_condition_tree",
    "business_capability",
    "business_condition_name",
    "business_parameter_table",
    "business_parameter_help",
    "business_new_logic_group",
    "business_group_members",
)
PATTERN_FIELDS = (
    "pattern_editor_name",
    "business_pattern_mode",
    "business_pattern_branches",
    "business_pattern_window",
    "business_pattern_required",
    "business_pattern_correlation",
    "business_pattern_status",
    "pattern_editor_step",
    "pattern_editor_dependencies",
    "business_pattern_panel",
    "business_pattern_apply",
)
OUTPUT_FIELDS = (
    "output_editor_name",
    "output_editor_source",
    "output_editor_kind",
    "output_editor_unit",
    "output_editor_evidence",
    "output_editor_save",
    "output_editor_show",
    "output_editor_status",
    "business_outputs_apply",
    "business_output_delete",
)
PARAMETER_FIELDS = (
    "business_parameter_selector",
    "business_parameter_readonly",
    "business_parameter_select",
    "business_parameter_multi",
    "business_parameter_number",
    "business_parameter_boolean",
    "business_parameter_text",
    "business_parameter_open_multi",
    "business_parameter_control_help",
)
SECONDARY_FIELDS = (
    "business_final_name",
    "business_final_type",
    "business_final_source",
    "business_final_combination",
    "business_final_required",
    "business_final_reason",
    "business_final_failed",
    "business_outputs_table",
    "business_trigger_mode",
    "business_trigger_cooldown",
    "business_trigger_severity",
    "business_trigger_outputs",
)
TIME_FIELDS = (
    "business_branch_time_mode",
    "business_branch_duration",
    "business_branch_window",
    "business_branch_ratio",
    "business_branch_gap",
    "business_branch_identity",
    "business_branch_emission",
    "business_branch_validity",
    "business_branch_hold",
    "business_branch_time_status",
    "business_time_confirm",
    "business_branch_time_apply",
)
IMPORTED_LOGIC_FIELDS = (
    "business_imported_logic_group",
    "business_imported_logic_selector",
    "business_imported_logic_operator",
    "business_imported_logic_required",
    "business_imported_logic_negated",
    "business_imported_logic_summary",
)
EXPRESSION_LOGIC_FIELDS = (
    "business_expression_logic_group",
    "business_expression_logic_selector",
    "business_expression_logic_operator",
    "business_expression_logic_required",
    "business_expression_logic_negated",
    "business_expression_logic_summary",
)
NAVIGATION_FIELDS = (
    "business_editor_tabs",
    "workbench_status",
    *BRANCH_FIELDS,
    "pattern_editor_selector",
    *PATTERN_FIELDS,
    "output_editor_selector",
    *OUTPUT_FIELDS,
    *SECONDARY_FIELDS,
    "business_time_target",
    "business_time_inventory",
    *TIME_FIELDS,
    *IMPORTED_LOGIC_FIELDS,
    *EXPRESSION_LOGIC_FIELDS,
    *PARAMETER_FIELDS,
)


def render_workbench(items: list[WorkbenchItem], media: str) -> str:
    """Escape all names, phrases and descriptions supplied by users or models."""
    sections = []
    for kind, title, hint in SECTIONS:
        cards = "".join(
            f"<li><strong>{escape(item.label)}</strong>"
            f"<p>{escape(item.detail)}</p></li>"
            for item in items
            if item.kind == kind
        )
        sections.append(
            f"<section><h4>{title}</h4><small>{hint}</small>"
            f"<ul>{cards or '<li>尚未配置</li>'}</ul></section>"
        )
    return (
        "<style>#skill-workbench-summary .workbench-grid{display:grid;"
        "grid-template-columns:repeat(auto-fit,minmax(min(100%,270px),1fr));gap:12px}"
        "#skill-workbench-summary section{border:1px solid #ddd6fe;border-radius:10px;"
        "padding:14px;background:var(--block-background-fill,#fff)}"
        "#skill-workbench-summary h4{margin:0 0 4px;color:var(--body-text-color,#242038)}"
        "#skill-workbench-summary small{color:var(--body-text-color-subdued,#62597a)}"
        "#skill-workbench-summary ul{list-style:none;padding:0;margin:12px 0 0}"
        "#skill-workbench-summary li+li{border-top:1px solid #eee;padding-top:10px;margin-top:10px}"
        "#skill-workbench-summary p{margin:4px 0;white-space:pre-wrap;overflow-wrap:anywhere}"
        "</style>"
        f"<p>当前查看：{escape(media)} · 已保存到草稿的配置（不是执行结果）</p>"
        f'<div class="workbench-grid">{"".join(sections)}</div>'
    )


class WorkbenchController:
    """No model calls, publication, document writes or independent UI state."""

    def workbench_items(self, editor_json: str, media_type: str) -> list[WorkbenchItem]:
        if not editor_json:
            return []
        document = self.business_rule_editor.prepare(
            self._parse_editor_json(editor_json)
        )
        template = document.skill_template
        media = _variant_key(media_type)
        _, _, labels = self._business_source_choices(document)
        # Historical packages may reference compiled nodes rather than branches.
        graph = template.rule_graphs.get(media, template.rule_graph)
        for node in graph.nodes:
            labels[f"node:{node.node_id}"] = node.display_name
            labels[f"output:{node.node_id}"] = node.display_name
            labels[f"condition:existing_node:{node.node_id}"] = node.display_name
        for profile in document.scene_profiles:
            if profile.scene_profile_id == document.active_scene_profile_id:
                for collection in profile.collections:
                    for resource in collection.items:
                        labels[f"resource:{resource.resource_id}"] = (
                            resource.display_name
                        )

        def source(ref: str | None) -> str:
            if ref == "final:primary":
                return (
                    template.final_decision.display_name
                    if template.final_decision
                    else "未配置的最终判定"
                )
            return labels.get(ref or "", "未指定或不可用的来源")

        items: list[WorkbenchItem] = []
        branches = [b for b in template.business_branches if b.media_type == media]
        for index, branch in enumerate(branches, 1):
            rows = self.business_rule_editor.condition_rows(document, branch.branch_id)
            root = next((r for r in rows if r.get("parent_id") is None), {})
            formula = (
                root.get("effective_formula") or root.get("summary") or "尚未配置条件"
            )
            timing = []
            for qualifier in branch.temporal_qualifiers:
                if qualifier.enabled:
                    parts = [friendly_choice_label(qualifier.mode)]
                    for name, value in (
                        ("时长", qualifier.duration_seconds),
                        ("窗口", qualifier.observation_window_seconds),
                    ):
                        if value.state != "not_applicable":
                            parts.append(
                                f"{name} {value.value if value.value is not None else '待配置'} 秒"
                            )
                    if qualifier.mode == "ratio":
                        parts.append(f"至少 {qualifier.required_ratio * 100:g}%")
                    parts.append(friendly_choice_label(qualifier.identity_scope))
                    timing.append(" · ".join(parts))
            validity = branch.validity_policy
            validity_text = {
                "current_frame": "仅当前帧有效",
                "event_interval": "事件起止区间有效",
                "hold_for": f"成立后保持 {validity.hold_seconds.value} 秒",
                "until_reset": f"保持到 {source(validity.reset_source_ref)} 复位",
            }[validity.mode]
            label = f"分支 {index} · {branch.display_name}"
            detail = f"{formula}\n分支时间：{'；'.join(timing) if timing else '未附加分支计时（条件可独立计时）'}\n有效期：{validity_text}"
            if not branch.enabled:
                detail += "\n此分支已停用"
            if not branch.participates_in_final_decision:
                detail += "\n不参与默认最终判定"
            items.append(WorkbenchItem("branch", branch.branch_id, label, detail))
            for number, row in enumerate(
                (r for r in rows if r.get("kind") == "条件"), 1
            ):
                name = row.get("configuration_name") or row["name"]
                items.append(
                    WorkbenchItem(
                        "condition",
                        row["condition_id"],
                        f"{label} / 条件 {number} · {name}",
                        "",
                        branch.branch_id,
                    )
                )
        for index, pattern in enumerate(
            (p for p in template.event_patterns if p.media_type == media), 1
        ):
            mode = self._event_pattern_mode(pattern)
            mode_name = next(
                (name for name, value in PATTERN_MODES if value == mode),
                friendly_choice_label(mode),
            )
            stages = "、".join(
                f"{i}. {source(s.source_ref)}" for i, s in enumerate(pattern.stages, 1)
            )
            details = [
                f"关系：{mode_name}",
                f"成员：{stages}",
                f"关联范围：{friendly_choice_label(pattern.correlation.scope)}",
            ]
            for gateway in pattern.gateways:
                if gateway.required_count is not None:
                    details.append(f"至少 {gateway.required_count} 项")
                if gateway.window_seconds.state != "not_applicable":
                    details.append(f"观察窗口：{gateway.window_seconds.value} 秒")
            stage_names = {
                s.stage_id: f"步骤 {i}" for i, s in enumerate(pattern.stages, 1)
            }
            for edge in pattern.transitions:
                details.append(
                    f"{stage_names.get(edge.source_stage_id, '不可用步骤')} → {stage_names.get(edge.target_stage_id, '不可用步骤')}（{edge.relation}；最长间隔 {edge.maximum_delay_seconds.value if edge.maximum_delay_seconds.state != 'not_applicable' else '不限'} 秒）"
                )
            items.append(
                WorkbenchItem(
                    "group",
                    pattern.pattern_id,
                    f"组 {index} · {pattern.display_name}",
                    "\n".join(details),
                )
            )
        final = template.final_decision
        if final:
            refs = final.media_source_refs.get(media, final.source_refs)
            combination = (
                f"至少 {final.required_count} 项"
                if final.combination == "N_OF_M"
                else friendly_choice_label(final.combination)
            )
            items.append(
                WorkbenchItem(
                    "final",
                    final.decision_id,
                    final.display_name,
                    f"{combination}：" + "；".join(source(ref) for ref in refs),
                )
            )
        for index, spec in enumerate(template.result_specs, 1):
            if not spec.media_types or media in spec.media_types:
                kind = self._friendly_result_kind(
                    self.business_rule_editor._result_kind(spec)
                )
                items.append(
                    WorkbenchItem(
                        "output",
                        spec.result_id,
                        f"输出 {index} · {spec.display_name}",
                        f"结果：{kind}\n来源：{source(spec.source_ref)}",
                    )
                )
        policy = template.trigger_policy
        trigger_names = {
            "none": "不触发事件",
            "once": "首次满足",
            "repeat": "允许重复触发",
            "on_change": "状态变化时",
        }
        items.append(
            WorkbenchItem(
                "trigger",
                "primary",
                "触发策略",
                f"{trigger_names[policy.mode]} · 冷却 {policy.cooldown_seconds:g} 秒",
            )
        )
        return items

    def workbench_controls(
        self, editor_json: str, media_type: str, selected: str | None
    ) -> tuple[Any, ...]:
        if not editor_json:
            return (
                "先在 01 生成或加载技能，再查看整项规则。",
                gr.update(choices=[], value=None),
                gr.update(interactive=False),
            )
        try:
            items = self.workbench_items(editor_json, media_type)
        except (ValueError, KeyError) as exc:
            return (
                f"暂不能读取技能总览：{escape(str(exc))}",
                gr.update(choices=[], value=None),
                gr.update(interactive=False),
            )
        choices = [(item.label, item.address) for item in items]
        values = {value for _, value in choices}
        return (
            render_workbench(
                items, "视频" if _variant_key(media_type) == "video" else "图片"
            ),
            gr.update(choices=choices, value=selected if selected in values else None),
            gr.update(interactive=True),
        )

    def workbench_target(
        self, editor_json: str, media_type: str, address: str | None
    ) -> WorkbenchItem:
        item = next(
            (
                i
                for i in self.workbench_items(editor_json, media_type)
                if i.address == address
            ),
            None,
        )
        if item is None:
            raise gr.Error("该项目已删除或不属于当前媒体，请在总览中重新选择。")
        return item

    def workbench_navigation(
        self,
        editor_json: str,
        media_type: str,
        address: str | None,
        include_tuning: bool,
    ) -> dict[str, Any]:
        """Refresh only the destination form; never emit an editor_document update."""
        item = self.workbench_target(editor_json, media_type, address)
        tab = {
            "branch": "conditions",
            "condition": "conditions",
            "group": "groups",
            "final": "final",
            "output": "outputs",
            "trigger": "trigger",
        }[item.kind]
        updates: dict[str, Any] = {
            "business_editor_tabs": gr.update(selected=tab),
            "workbench_status": f"已定位：{escape(item.label)}。编辑后先保存到草稿，再点击【应用修改，更新运行版本】。",
        }
        if item.kind in {"branch", "condition"}:
            branch_id = item.branch_id if item.kind == "condition" else item.identity
            condition_id = item.identity if item.kind == "condition" else None
            controls = self.business_rule_controls(
                editor_json, media_type, branch_id, condition_id, include_tuning
            )
            selected_condition = self.business_rule_view(
                editor_json, media_type, branch_id, condition_id, include_tuning
            )["condition_id"]
            updates.update(zip(BRANCH_FIELDS, controls[1:], strict=True))
            updates.update(
                zip(
                    PARAMETER_FIELDS,
                    self.business_parameter_controls(
                        editor_json,
                        media_type,
                        branch_id,
                        selected_condition,
                        include_tuning,
                        None,
                    ),
                    strict=True,
                )
            )
            updates.update(
                zip(
                    IMPORTED_LOGIC_FIELDS,
                    self.business_imported_logic_controls(editor_json, branch_id),
                    strict=True,
                )
            )
            updates.update(
                zip(
                    EXPRESSION_LOGIC_FIELDS,
                    self.business_expression_logic_controls(editor_json, branch_id),
                    strict=True,
                )
            )
            target, inventory = self.time_configuration_targets(
                editor_json, branch_id, None
            )
            updates.update(
                business_time_target=target, business_time_inventory=inventory
            )
            updates.update(
                zip(
                    TIME_FIELDS,
                    self.time_configuration_controls(
                        editor_json, branch_id, target["value"]
                    ),
                    strict=True,
                )
            )
        elif item.kind == "group":
            updates["pattern_editor_selector"] = self.pattern_group_choices(
                editor_json, media_type, item.identity
            )
            updates.update(
                zip(
                    PATTERN_FIELDS,
                    self.pattern_group_controls(editor_json, media_type, item.identity),
                    strict=True,
                )
            )
        elif item.kind == "output":
            updates["output_editor_selector"] = self.output_editor_choices(
                editor_json, item.identity
            )
            updates.update(
                zip(
                    OUTPUT_FIELDS,
                    self.output_editor_controls(editor_json, item.identity),
                    strict=True,
                )
            )
        else:
            controls = self.business_secondary_controls(editor_json, media_type)
            # Do not overwrite another tab's unsaved form while navigating.
            first, last = (0, 7) if item.kind == "final" else (8, 12)
            updates.update(
                zip(
                    SECONDARY_FIELDS[first:last],
                    controls[6 + first : 6 + last],
                    strict=True,
                )
            )
        return updates
