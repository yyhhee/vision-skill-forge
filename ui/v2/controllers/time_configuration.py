"""One time editor for existing condition timers and whole-branch policies."""

from __future__ import annotations

from math import isfinite
from typing import Any

import gradio as gr

from core.business_rule_editor import BusinessRuleEditError
from core.editor_schema import BusinessBranch, SkillEditorDocument

MODES = [
    ("不额外等待", "immediate"),
    ("连续满足一段时间", "continuous"),
    ("观察窗口内累计满足", "cumulative"),
    ("观察窗口内满足时间占比", "ratio"),
]
SCOPE_LABELS = {
    "global": "所选对象整体（不区分实例）",
    "object": "同一个目标",
    "track": "同一条轨迹",
    "pair": "同一对目标",
    "region": "同一个标注区域",
}
MODE_LABELS = {value: label for label, value in MODES}


def time_field_updates(mode: str, validity: str, target: str | None) -> tuple[Any, ...]:
    """Show only fields consumed by the selected mode, without clearing values."""
    timed = mode != "immediate"
    branch = bool(target and target.startswith("branch:"))
    return (
        gr.update(
            visible=mode in {"continuous", "cumulative"},
            label="连续满足（秒）" if mode == "continuous" else "累计满足（秒）",
        ),
        gr.update(visible=mode in {"cumulative", "ratio"}),
        gr.update(visible=mode == "ratio"),
        gr.update(visible=mode == "continuous"),
        gr.update(visible=timed),
        gr.update(
            visible=timed and branch,
            choices=[
                (
                    "每段连续成立只产生一次"
                    if mode == "continuous"
                    else "首次满足后产生一次",
                    "first",
                ),
                ("满足后每个采样时刻均可产生", "repeat"),
            ],
        ),
        gr.update(visible=branch and not timed),
        gr.update(visible=branch and not timed and validity == "hold_for"),
    )


class TimeConfigurationController:
    """Adapt registered timing conditions; never insert a second hidden timer."""

    def _time_context(
        self, editor_json: str, branch_id: str | None
    ) -> tuple[SkillEditorDocument, BusinessBranch, list[dict[str, Any]]]:
        document = self.business_rule_editor.prepare(
            self._parse_editor_json(editor_json)
        )
        branch = next(
            (
                b
                for b in document.skill_template.business_branches
                if b.branch_id == branch_id
            ),
            None,
        )
        if branch is None:
            raise BusinessRuleEditError("请先选择要编辑的分支。")
        rows = self.business_rule_editor.condition_rows(document, branch.branch_id)
        timers = [
            row
            for row in rows
            if row.get("enabled") and row.get("capability_id") == "temporal.persist"
        ]
        return document, branch, timers

    def time_configuration_targets(
        self, editor_json: str, branch_id: str | None, selected: str | None
    ) -> tuple[dict[str, Any], str]:
        """Keep the chosen target; prefer an existing timer over adding branch time."""
        if not editor_json or not branch_id:
            return gr.update(choices=[], value=None), "请先选择分支。"
        document, branch, timers = self._time_context(editor_json, branch_id)
        branch_ref = f"branch:{branch.branch_id}"
        choices = [(f"整个分支：{branch.display_name}", branch_ref)]
        choices += [
            (f"已有计时条件：{row['name']}", row["condition_id"]) for row in timers
        ]
        ids = {value for _, value in choices}
        branch_timed = any(
            q.enabled and q.mode != "immediate" for q in branch.temporal_qualifiers
        )
        target = (
            selected
            if selected in ids
            else (
                branch_ref if branch_timed or not timers else timers[0]["condition_id"]
            )
        )
        lines = [f"**当前分支：{branch.display_name}**"]
        condition_names = {
            f"condition:{r['condition_id']}": r["name"]
            for r in self.business_rule_editor.condition_rows(
                document, branch.branch_id
            )
        }
        graph = document.skill_template.rule_graphs.get(branch.media_type)
        for row in timers:
            values = {
                p["parameter_id"]: p["value"]
                for p in self.business_rule_editor.parameter_rows(
                    document, branch.branch_id, row["condition_id"], include_tuning=True
                )
            }
            mode = values.get("mode", "continuous")
            name = MODE_LABELS.get(mode, mode)
            source = values.get("source", "")
            source_name = condition_names.get(source, "该条件已选择的输入结果")
            if row.get("imported_step") and graph:
                node_id = row["condition_id"].removeprefix("existing_node:")
                inputs = [
                    edge.source
                    for edge in graph.edges
                    if edge.target == node_id and edge.port == "condition"
                ]
                source_name = (
                    "、".join(
                        condition_names.get(
                            f"condition:existing_node:{node_id}",
                            next(
                                (
                                    node.display_name
                                    for node in graph.nodes
                                    if node.node_id == node_id
                                ),
                                "前序条件",
                            ),
                        )
                        for node_id in inputs
                    )
                    or source_name
                )
            details = (
                f"满足占比 {float(values.get('required_ratio', 1)) * 100:g}%"
                if mode == "ratio"
                else f"{float(values.get('duration') or 0):g} 秒"
            )
            if mode in {"cumulative", "ratio"}:
                details += f"；观察窗口 {values.get('window', '待填写')} 秒"
            lines.append(
                f"- 已有条件「{row['name']}」：{name}，{details}；作用于「{source_name}」。"
            )
        for q in branch.temporal_qualifiers:
            if q.enabled and q.mode != "immediate":
                name = MODE_LABELS.get(q.mode, q.mode)
                details = (
                    f"满足时间占比 {q.required_ratio * 100:g}%"
                    if q.mode == "ratio"
                    else f"{q.duration_seconds.value if q.duration_seconds.value is not None else '待填写'} 秒"
                )
                if q.mode in {"cumulative", "ratio"}:
                    details += f"；观察窗口 {q.observation_window_seconds.value if q.observation_window_seconds.value is not None else '待填写'} 秒"
                lines.append(
                    f"- 已有分支计时「{q.display_name}」：{name}，{details}；作用于「{branch.display_name}」的组合结果，按「{SCOPE_LABELS[q.identity_scope]}」分别计时。"
                )
        if not timers and not branch_timed:
            lines.append("尚未设置计时。")
        lines.append(
            "修改已有条件会原位更新，不新增计时步骤。给整个分支加计时，会在分支内条件完成后再计时。"
        )
        if branch.media_type != "video":
            lines.append("图片不支持持续、累计或窗口计时。")
        return gr.update(choices=choices, value=target), "\n\n".join(lines)

    def time_configuration_controls(
        self, editor_json: str, branch_id: str | None, target: str | None
    ) -> tuple[Any, ...]:
        """Read the selected source of truth, including imported workflow timers."""
        if not editor_json or not branch_id or not target:
            return (
                gr.update(value="immediate", choices=MODES, interactive=False),
                *time_field_updates("immediate", "current_frame", None),
                "请先选择作用对象。",
                gr.update(value=False, visible=False),
                gr.update(interactive=False),
            )
        document, branch, timers = self._time_context(editor_json, branch_id)
        whole_branch = target == f"branch:{branch.branch_id}"
        if whole_branch:
            qualifiers = [q for q in branch.temporal_qualifiers if q.enabled]
            if len(qualifiers) > 1 or any(
                q.target_ref != target
                or q.mode not in {value for _, value in MODES}
                or q.emission == "on_change"
                for q in qualifiers
            ):
                return (
                    gr.update(interactive=False),
                    *time_field_updates("immediate", "current_frame", target),
                    "此分支含多条或特殊时间策略，请在高级配置中逐项修改；本面板不会覆盖它们。",
                    gr.update(value=False, visible=False),
                    gr.update(interactive=False),
                )
            q = qualifiers[0] if qualifiers else None
            mode = q.mode if q else "immediate"
            values = [
                q.duration_seconds.value if q else None,
                q.observation_window_seconds.value if q else None,
                q.required_ratio * 100 if q else 100,
                q.allowed_gap_seconds if q else 0,
                q.identity_scope if q else "global",
                q.emission if q else "first",
                branch.validity_policy.mode,
                branch.validity_policy.hold_seconds.value,
            ]
            modes = MODES
            label = f"整个分支「{branch.display_name}」"
        else:
            row = next((r for r in timers if r["condition_id"] == target), None)
            if row is None:
                raise gr.Error("该计时条件已不存在，请重新选择。")
            params = {
                p["parameter_id"]: p["value"]
                for p in self.business_rule_editor.parameter_rows(
                    document, branch.branch_id, target, include_tuning=True
                )
            }
            imported = bool(row.get("imported_step"))
            mode = (
                params.get("mode", "continuous")
                if float(params.get("duration", 0)) > 0
                else "immediate"
            )
            if params.get("mode") == "ratio":
                mode = "ratio"
            values = [
                params.get("duration"),
                params.get("window"),
                float(params.get("required_ratio", 1)) * 100,
                params.get("allowed_gap", 0),
                params.get(
                    "identity_scope", params.get("atom_parameter:scope", "global")
                ),
                "first",
                "current_frame",
                None,
            ]
            modes = MODES[:2] if imported else MODES
            label = f"条件「{row['name']}」"
        updates = time_field_updates(mode, values[6], target)
        identity_choices = list(SCOPE_LABELS.items())
        if not whole_branch and row.get("imported_step"):
            identity_rows = self.business_rule_editor.parameter_rows(
                document, branch.branch_id, target, include_tuning=True
            )
            allowed = next(
                (
                    r.get("choices")
                    for r in identity_rows
                    if r["parameter_id"] in {"identity_scope", "atom_parameter:scope"}
                ),
                [],
            )
            identity_choices = [
                (value, label) for value, label in identity_choices if value in allowed
            ]
        updates[4]["choices"] = [(label, value) for value, label in identity_choices]
        fields = [
            gr.update(
                **{k: v for k, v in update.items() if k != "__type__"}, value=value
            )
            for update, value in zip(updates, values)
        ]
        status = f"正在编辑：**{label}**。{MODE_LABELS.get(mode, mode)}。"
        if not whole_branch:
            status += "仅更新这一个已有计时条件；不改动整个分支的时间设置。0 秒表示无需等待，仍保留原有事件输出。"
        elif mode != "immediate":
            status += (
                "计时完成后按事件的实际起止区间参与后续编排；这里不再附加保持计时。"
            )
        if whole_branch and timers:
            status += "注意：分支内已有计时条件，新增分支计时会再等待一次。"
        if whole_branch and branch.media_type != "video":
            fields[6] = gr.update(visible=False, value="current_frame")
            fields[7] = gr.update(visible=False, value=None)
        elif whole_branch and timers:
            fields[6] = gr.update(visible=False, value="event_interval")
            fields[7] = gr.update(visible=False, value=None)
            status += "已有计时条件产生事件区间，本面板不再叠加成立后保持时间。"
        return (
            gr.update(
                value=mode,
                choices=modes if branch.media_type == "video" else MODES[:1],
                interactive=branch.media_type == "video",
            ),
            *fields,
            status,
            gr.update(
                value=False,
                visible=whole_branch and bool(timers) and mode != "immediate",
            ),
            gr.update(interactive=True),
        )

    def time_configuration_visibility(
        self,
        mode: str,
        validity: str,
        target: str | None,
        editor_json: str,
        branch_id: str | None,
    ) -> tuple[Any, ...]:
        updates = list(time_field_updates(mode, validity, target))
        confirm_visible = False
        if editor_json and branch_id:
            _, branch, timers = self._time_context(editor_json, branch_id)
            if timers or branch.media_type != "video":
                updates[6] = gr.update(visible=False)
                updates[7] = gr.update(visible=False)
            confirm_visible = (
                bool(timers) and target == f"branch:{branch_id}" and mode != "immediate"
            )
        return (
            *updates,
            "表单已调整，尚未保存。计时作用对象以本面板上方选择为准；保存到草稿后，仍需点击【应用修改，更新运行版本】。",
            gr.update(visible=confirm_visible),
        )

    def save_time_configuration(
        self,
        editor_json: str,
        branch_id: str,
        target: str,
        mode: str,
        duration: float | None,
        window: float | None,
        ratio: float,
        gap: float,
        identity: str,
        emission: str,
        validity: str,
        hold: float | None,
        confirm_layering: bool,
    ) -> tuple[str, str]:
        """Save one timer to the common draft transaction; reject accidental stacking."""
        try:
            document, branch, timers = self._time_context(editor_json, branch_id)
            if mode not in {value for _, value in MODES}:
                raise BusinessRuleEditError("请选择当前支持的计时方式。")
            if mode != "immediate" and branch.media_type != "video":
                raise BusinessRuleEditError("持续、累计和窗口占比需要视频。")
            if branch.media_type != "video" and validity != "current_frame":
                raise BusinessRuleEditError("图片只能按当前帧判断，不能设置时间保持。")
            required = (
                [("持续/累计时间", duration)]
                if mode in {"continuous", "cumulative"}
                else []
            )
            if mode in {"cumulative", "ratio"}:
                required += [("观察窗口", window)]
            if mode == "ratio" and (
                ratio is None or not isfinite(float(ratio)) or not 0 <= ratio <= 100
            ):
                raise BusinessRuleEditError("满足时间占比应在 0% 到 100% 之间。")
            for name, value in required:
                if value is None or not isfinite(float(value)) or float(value) <= 0:
                    raise BusinessRuleEditError(f"{name}必须大于 0 秒。")
            if mode == "cumulative" and duration > window:
                raise BusinessRuleEditError("累计满足时间不能超过观察窗口。")
            gap = float(gap or 0) if mode == "continuous" else 0
            if not isfinite(gap) or gap < 0:
                raise BusinessRuleEditError("允许短暂中断不能小于 0 秒。")
            if target == f"branch:{branch.branch_id}":
                if any(
                    q.enabled
                    and (
                        q.mode not in {value for _, value in MODES}
                        or q.emission == "on_change"
                    )
                    for q in branch.temporal_qualifiers
                ):
                    raise BusinessRuleEditError(
                        "此分支包含特殊时间策略，请在高级配置中修改。"
                    )
                if mode != "immediate" and timers and not confirm_layering:
                    raise BusinessRuleEditError(
                        "分支内已有计时条件。请优先修改该条件；确需再次计时，请勾选确认。"
                    )
                if mode != "immediate" or timers:
                    validity, hold = "event_interval", None
                elif validity == "hold_for" and (
                    hold is None or not isfinite(float(hold)) or hold <= 0
                ):
                    raise BusinessRuleEditError("成立后保持时间必须大于 0 秒。")
                document = self.business_rule_editor.set_branch_time_policy(
                    document,
                    branch_id,
                    mode=mode,
                    duration_seconds=duration,
                    observation_window_seconds=window,
                    required_ratio=float(ratio or 0) / 100 if mode == "ratio" else 1,
                    allowed_gap_seconds=gap,
                    identity_scope=identity if mode != "immediate" else "global",
                    emission=emission if mode != "immediate" else "first",
                    validity_mode=validity,
                    hold_seconds=hold,
                )
            else:
                row = next((r for r in timers if r["condition_id"] == target), None)
                if row is None:
                    raise BusinessRuleEditError("请重新选择已有计时条件。")
                if row.get("imported_step") and mode not in {"immediate", "continuous"}:
                    raise BusinessRuleEditError(
                        "原有持续判断步骤仅支持连续计时；窗口方式请使用新的业务时间条件。"
                    )
                params = {
                    p["parameter_id"]: p["value"]
                    for p in self.business_rule_editor.parameter_rows(
                        document, branch_id, target, include_tuning=True
                    )
                }
                changes = {
                    "duration": float(duration)
                    if mode in {"continuous", "cumulative"}
                    else 0,
                    "allowed_gap": gap,
                    "identity_scope": identity,
                }
                if not row.get("imported_step"):
                    changes.update(
                        mode=mode if mode != "immediate" else "continuous",
                        window=window if mode in {"cumulative", "ratio"} else None,
                        required_ratio=float(ratio or 0) / 100
                        if mode == "ratio"
                        else 1,
                    )
                if row.get("imported_step"):
                    if params.get("atom_parameter:scope_overrides"):
                        raise BusinessRuleEditError(
                            "此条件有按区域分别配置的时间，请在当前条件配置中修改，避免覆盖区域差异。"
                        )
                    if "atom_parameter:scope" in params:
                        changes["atom_parameter:scope"] = identity
                    changes = {k: v for k, v in changes.items() if k in params}
                else:
                    params.update(changes)
                    changes = params
                document = self.business_rule_editor.update_condition(
                    document, branch_id, target, parameters=changes
                )
        except (BusinessRuleEditError, ValueError, KeyError) as exc:
            raise gr.Error(str(exc)) from exc
        return self._dump(
            document
        ), "✅ 所选对象的时间设置已保存到草稿；点击【应用修改，更新运行版本】后生效。"
