"""Selected-group editing with ordered form steps and visible dependencies."""

from __future__ import annotations

from math import isfinite
from typing import Any

import gradio as gr

from application.v2.support import _variant_key
from core.business_rule_editor import BusinessRuleEditError
from core.editor_schema import BusinessBranch, EventPattern, SkillEditorDocument
from ui.event_rule_editor import render_branch_pattern

NEW_GROUP = "__new_group__"
PATTERN_MODES = [
    ("顺序：逐个完成", "sequence"),
    ("并行：全部完成", "all_completed"),
    ("同时满足：有效区间重叠", "all_active"),
    ("窗口内全部完成", "all_completed_within_window"),
    ("互斥选择：最先完成一个即结束", "exclusive"),
    ("任意完成（或）：任一完成即结束", "any"),
    ("部分汇聚：达到指定完成数量", "n_of_m"),
    ("锚点发生后，窗口内另一项未发生", "absence"),
    ("窗口内重复发生", "repeat"),
    ("取消当前组（需先解除引用）", "none"),
]


def pattern_source_labels(
    branches: list[BusinessBranch], patterns: list[EventPattern]
) -> dict[str, str]:
    """Disambiguate equal user names without displaying technical IDs."""
    labels = {}
    for prefix, kind, items, key in (
        ("branch", "分支", branches, "branch_id"),
        ("event", "编排组", patterns, "pattern_id"),
    ):
        for index, item in enumerate(items, 1):
            number = (
                f" {index}"
                if sum(other.display_name == item.display_name for other in items) > 1
                else ""
            )
            labels[f"{prefix}:{getattr(item, key)}"] = (
                f"{kind}{number}「{item.display_name}」"
            )
    return labels


def simple_pattern_issue(pattern: EventPattern | None) -> str:
    """Do not flatten advanced stage/edge contracts into the simple form."""
    if pattern is None:
        return ""
    refs = [s.source_ref for s in pattern.stages]
    if any(not ref or not ref.startswith(("branch:", "event:")) for ref in refs) or len(
        set(refs)
    ) != len(refs):
        return "含重复步骤或非分支输入"
    if pattern.correlation.fields or pattern.correlation.scope not in {
        "global",
        "object",
        "track",
        "pair",
        "region",
    }:
        return "含自定义关联字段"
    for stage in pattern.stages:
        if (
            stage.persist_mode != "immediate"
            or stage.duration.value not in {None, 0}
            or stage.duration.state == "unresolved"
            or stage.allowed_gap_seconds
            or stage.capture_fields
            or stage.identity_scope != "global"
            or stage.observation_window_seconds.state != "not_applicable"
            or stage.required_ratio != 1
        ):
            return "含步骤独立计时或采集字段"
    if pattern.pattern_type == "sequence":
        expected = [
            (a.stage_id, b.stage_id) for a, b in zip(pattern.stages, pattern.stages[1:])
        ]
        if (
            [(t.source_stage_id, t.target_stage_id) for t in pattern.transitions]
            != expected
            or pattern.gateways
            or pattern.parameters
        ):
            return "不是简单的相邻步骤顺序"
        windows = {
            (t.maximum_delay_seconds.state, t.maximum_delay_seconds.value)
            for t in pattern.transitions
        }
        if len(windows) > 1 or any(
            t.relation != "after"
            or t.minimum_delay_seconds != 0
            or t.source_anchor != "end"
            or t.target_anchor != "end"
            or t.timeout_behavior != "fail"
            or t.maximum_delay_seconds.state == "unresolved"
            for t in pattern.transitions
        ):
            return "含逐段不同间隔、锚点或超时策略"
    elif pattern.pattern_type == "join":
        if len(pattern.gateways) != 1 or pattern.transitions or pattern.parameters:
            return "含多个汇聚节点或额外关系"
        gateway = pattern.gateways[0]
        if (
            gateway.mode not in {value for _, value in PATTERN_MODES}
            or set(gateway.stage_ids) != {s.stage_id for s in pattern.stages}
            or gateway.window_seconds.state == "unresolved"
        ):
            return "含自定义汇聚范围或关系"
    elif (
        pattern.transitions
        or pattern.gateways
        or set(pattern.parameters) - {"window_seconds", "minimum_count"}
    ):
        return "含额外事件约束"
    return ""


def pattern_consumers(document: SkillEditorDocument, pattern_id: str) -> list[str]:
    """Return direct consumers with business names, including media final refs."""
    template = document.skill_template
    ref = f"event:{pattern_id}"
    consumers = [
        f"编排组「{p.display_name}」"
        for p in template.event_patterns
        if any(s.source_ref == ref for s in p.stages)
    ]
    final = template.final_decision
    if final and ref in [
        final.source_ref,
        *final.source_refs,
        *(source for refs in final.media_source_refs.values() for source in refs),
    ]:
        consumers.append(f"最终判定「{final.display_name}」")
    consumers.extend(
        f"业务输出「{r.display_name}」"
        for r in template.result_specs
        if r.source_ref == ref
    )
    return consumers


class PatternEditorController:
    """Use existing EventPattern and the common draft transaction, not a new DSL."""

    def _pattern_context(
        self, editor_json: str, media_type: str
    ) -> tuple[SkillEditorDocument, str, list[EventPattern], list[BusinessBranch]]:
        document = self.business_rule_editor.prepare(
            self._parse_editor_json(editor_json)
        )
        media = _variant_key(media_type)
        patterns = [
            p for p in document.skill_template.event_patterns if p.media_type == media
        ]
        branches = [
            b
            for b in document.skill_template.business_branches
            if b.media_type == media
        ]
        return document, media, patterns, branches

    def pattern_secondary_controls(
        self, editor_json: str, media_type: str
    ) -> tuple[Any, ...]:
        """Keep output/final/trigger refreshes from replacing the selected group."""
        original = self.business_secondary_controls(editor_json, media_type)
        return (*(gr.skip() for _ in range(6)), *original[6:18], gr.skip())

    def pattern_group_choices(
        self, editor_json: str, media_type: str, selected: str | None
    ) -> dict[str, Any]:
        """Retain explicit selection across edits; default to an existing root group."""
        if not editor_json:
            return gr.update(choices=[("新建编排组", NEW_GROUP)], value=None)
        _, _, patterns, _ = self._pattern_context(editor_json, media_type)
        choices = [("新建编排组", NEW_GROUP)] + [
            (f"组 {i} · {p.display_name}", p.pattern_id)
            for i, p in enumerate(patterns, 1)
        ]
        refs = {s.source_ref for p in patterns for s in p.stages}
        roots = [p for p in patterns if f"event:{p.pattern_id}" not in refs]
        value = (
            selected
            if selected in {value for _, value in choices}
            else ((roots or patterns)[-1].pattern_id if patterns else NEW_GROUP)
        )
        return gr.update(choices=choices, value=value)

    def pattern_group_controls(
        self, editor_json: str, media_type: str, selected: str | None
    ) -> tuple[Any, ...]:
        """Load exactly the selected group and exclude inputs that would form cycles."""
        if not editor_json:
            return (
                "",
                gr.update(choices=PATTERN_MODES, value="all_completed"),
                gr.update(choices=[], value=[]),
                None,
                1,
                "global",
                "尚未加载技能。",
                gr.update(choices=[], value=None),
                "暂无依赖关系。",
                gr.update(visible=False),
                gr.update(interactive=False),
            )
        document, media, patterns, branches = self._pattern_context(
            editor_json, media_type
        )
        pattern = next((p for p in patterns if p.pattern_id == selected), None)
        if selected not in {None, NEW_GROUP} and pattern is None:
            return self.pattern_group_controls(editor_json, media_type, NEW_GROUP)
        forbidden = {f"event:{selected}"} if pattern else set()
        while True:
            expanded = forbidden | {
                f"event:{p.pattern_id}"
                for p in patterns
                if any(s.source_ref in forbidden for s in p.stages)
            }
            if expanded == forbidden:
                break
            forbidden = expanded
        labels = pattern_source_labels(branches, patterns)
        choices = [
            (label, ref) for ref, label in labels.items() if ref not in forbidden
        ]
        members = [s.source_ref for s in pattern.stages] if pattern else []
        mode = (
            self._event_pattern_mode(pattern)
            if pattern
            else ("sequence" if media == "video" else "all_completed")
        )
        modes = [
            pair
            for pair in PATTERN_MODES
            if media == "video"
            or pair[1]
            not in {"sequence", "absence", "repeat", "all_completed_within_window"}
        ]
        if mode not in {value for _, value in modes}:
            modes.append((f"高级关系：{mode}", mode))
        window, required, scope = None, 1, "global"
        if pattern:
            scope = pattern.correlation.scope
            if pattern.pattern_type == "sequence":
                window = (
                    pattern.transitions[0].maximum_delay_seconds.value
                    if pattern.transitions
                    else None
                )
            elif pattern.pattern_type in {"absence", "repeat"}:
                window, required = (
                    pattern.parameters.get("window_seconds"),
                    pattern.parameters.get("minimum_count", 1),
                )
            elif pattern.gateways:
                gateway = pattern.gateways[0]
                window, required = (
                    gateway.window_seconds.value,
                    gateway.required_count or 1,
                )
        issue = simple_pattern_issue(pattern)
        status, steps, dependencies = self._pattern_form_summary(
            document, selected, mode, members, window, required, scope, labels
        )
        if issue:
            status = (
                f"此组{issue}。普通表单只读，请使用高级配置；不会丢弃这些约束。\n\n"
                + status
            )
        return (
            pattern.display_name if pattern else "新编排组",
            gr.update(choices=modes, value=mode),
            gr.update(choices=choices, value=members),
            window,
            required,
            scope,
            status,
            gr.update(choices=steps, value=members[0] if members else None),
            dependencies,
            gr.update(visible=bool(branches or patterns)),
            gr.update(interactive=not issue),
        )

    def _pattern_form_summary(
        self,
        document: SkillEditorDocument,
        selected: str | None,
        mode: str,
        members: list[str],
        window: float | None,
        required: int,
        scope: str,
        labels: dict[str, str],
    ) -> tuple[str, list[tuple[str, str]], str]:
        names = [labels.get(ref, f"已失效来源（{ref}）") for ref in members]
        steps = [
            (f"步骤 {i} · {name}", ref)
            for i, (name, ref) in enumerate(zip(names, members), 1)
        ]
        formula = render_branch_pattern(
            mode,
            names,
            required_count=required,
            window_seconds=window,
            correlation_scope=scope,
        ).replace("当前生效分支编排", "本次编辑预览（保存后进入草稿）")
        if not members:
            formula = "**本次编辑预览**\n\n尚未选择输入。请在下方添加分支或已编排组，再调整步骤顺序。"
        inputs = (
            "\n".join(f"- 步骤 {i}：{name}" for i, name in enumerate(names, 1))
            or "尚未选择步骤。"
        )
        consumers = (
            pattern_consumers(document, selected)
            if selected and selected != NEW_GROUP
            else []
        )
        used_by = (
            "、".join(consumers)
            or "暂无直接引用；保存组不会自动修改最终判定或业务输出。"
        )
        dependencies = f"**本组使用的输入（本次设置）**\n\n{inputs}\n\n**谁在使用本组（当前草稿）**\n\n{used_by}"
        if mode == "sequence":
            dependencies += "\n\n顺序关系按步骤 1 → 2 → … 判断。修改被引用的组后，引用方会使用此组的新逻辑。"
        else:
            dependencies += (
                "\n\n此关系不要求步骤按先后发生；上移／下移不会把它改成顺序关系。"
            )
        return formula, steps, dependencies

    def pattern_form_preview(
        self,
        editor_json: str,
        media_type: str,
        selected: str | None,
        mode: str,
        members: list[str] | None,
        window: float | None,
        required: int,
        scope: str,
        step: str | None,
    ) -> tuple[Any, ...]:
        """Preview unsaved form order; moving a step does not publish a skill."""
        if not editor_json:
            return "尚未加载技能。", gr.update(choices=[], value=None), "暂无依赖关系。"
        document, _, patterns, branches = self._pattern_context(editor_json, media_type)
        labels = pattern_source_labels(branches, patterns)
        formula, steps, dependencies = self._pattern_form_summary(
            document, selected, mode, members or [], window, required, scope, labels
        )
        pattern = next((p for p in patterns if p.pattern_id == selected), None)
        issue = simple_pattern_issue(pattern)
        if issue:
            formula = (
                f"此组{issue}。普通表单只读，请使用高级配置；不会丢弃这些约束。\n\n"
                + formula
            )
        return (
            formula,
            gr.update(
                choices=steps,
                value=step
                if step in (members or [])
                else (members[0] if members else None),
            ),
            dependencies,
        )

    def pattern_move_step(
        self, members: list[str] | None, step: str | None, direction: str
    ) -> tuple[Any, Any]:
        """Reorder a form copy by source reference, including the first/last guards."""
        ordered = list(members or [])
        if step not in ordered or direction not in {"up", "down"}:
            raise gr.Error("请选择要移动的步骤。")
        index = ordered.index(step)
        destination = index + (-1 if direction == "up" else 1)
        if 0 <= destination < len(ordered):
            ordered[index], ordered[destination] = ordered[destination], ordered[index]
        return gr.update(value=ordered), gr.update(value=step)

    def save_pattern_group(
        self,
        editor_json: str,
        media_type: str,
        selected: str | None,
        name: str,
        mode: str,
        members: list[str] | None,
        window: float | None,
        required: int | None,
        scope: str,
    ) -> tuple[str, str, dict[str, Any]]:
        """Explicit group identity distinguishes update from new-group creation."""
        try:
            document, media, patterns, _ = self._pattern_context(
                editor_json, media_type
            )
            pattern = next((p for p in patterns if p.pattern_id == selected), None)
            if selected != NEW_GROUP and pattern is None:
                raise BusinessRuleEditError("所选编排组已不存在，请重新选择。")
            if simple_pattern_issue(pattern):
                raise BusinessRuleEditError(
                    "此组含高级约束，请使用高级配置，避免覆盖原有参数。"
                )
            if not (name or "").strip():
                raise BusinessRuleEditError("请填写编排组名称。")
            # Gradio can return 0 when a previously empty number is shown again.
            # Match the original sequence contract: 0/empty means no upper limit.
            if mode == "sequence" and window == 0:
                window = None
            if (
                mode in {"sequence", "all_completed_within_window", "absence", "repeat"}
                and window is not None
                and (not isfinite(float(window)) or float(window) <= 0)
            ):
                raise BusinessRuleEditError(
                    "最长间隔或窗口必须大于 0 秒；不限制时请留空。"
                )
            if mode == "none" and pattern is None:
                raise BusinessRuleEditError("新建组请选择一种组合关系。")
            if mode not in {value for _, value in PATTERN_MODES}:
                raise BusinessRuleEditError("请选择受支持的组合关系。")
            if media != "video" and mode in {
                "sequence",
                "absence",
                "repeat",
                "all_completed_within_window",
            }:
                raise BusinessRuleEditError("所选时间编排关系需要视频流程。")
            before = {p.pattern_id for p in patterns}
            updated = self.business_rule_editor.set_complex_pattern(
                document,
                media,
                mode,
                members or [],
                window_seconds=window
                if mode
                in {"sequence", "all_completed_within_window", "absence", "repeat"}
                else None,
                required_count=int(required or 1),
                correlation_scope=scope,
                display_name=name,
                pattern_id=pattern.pattern_id if pattern else None,
                create_new=pattern is None,
            )
            new_id = (
                pattern.pattern_id
                if pattern and mode != "none"
                else next(
                    (
                        p.pattern_id
                        for p in updated.skill_template.event_patterns
                        if p.pattern_id not in before
                    ),
                    NEW_GROUP,
                )
            )
            choices = [("新建编排组", NEW_GROUP)] + [
                (f"组 {i} · {p.display_name}", p.pattern_id)
                for i, p in enumerate(
                    (
                        p
                        for p in updated.skill_template.event_patterns
                        if p.media_type == media
                    ),
                    1,
                )
            ]
        except (BusinessRuleEditError, KeyError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        feedback = (
            "✅ 所选编排组已保存到草稿；原组引用保持不变。"
            if mode != "none"
            else "✅ 所选编排组已取消并保存到草稿；其他编排组不变。"
        )
        return (
            self._dump(updated),
            feedback + "点击【应用修改，更新运行版本】后生效。",
            gr.update(choices=choices, value=new_id),
        )
