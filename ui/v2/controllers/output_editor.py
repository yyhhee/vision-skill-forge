"""Business output forms: named, controlled sources and compatible projections."""

from __future__ import annotations

from html import escape
from typing import Any

import gradio as gr

from core.business_output_editor import (
    OutputSource,
    delete_output,
    output_sources,
    save_output,
)
from core.business_rule_editor import BusinessRuleEditError
from core.editor_schema import SkillEditorDocument

NEW_OUTPUT = "__new_output__"
EVIDENCE_CHOICES = [
    ("尽量保存", "optional"),
    ("必须保存", "required"),
    ("不需要", "none"),
]
SAVE_CHOICES = [
    ("每次保存", "always"),
    ("变化时保存", "on_change"),
    ("满足时保存", "on_match"),
    ("不保存", "never"),
]


class OutputEditorController:
    """Adapt the existing document and draft transaction without a second state."""

    def output_editor_choices(
        self, editor_json: str, selected: str | None
    ) -> dict[str, Any]:
        """Retain selection by stable ID, including duplicate business names."""
        choices = [("新增业务输出", NEW_OUTPUT)]
        if editor_json:
            specs = self._parse_editor_json(editor_json).skill_template.result_specs
            for index, spec in enumerate(specs, 1):
                suffix = (
                    f"（第{index}项）"
                    if sum(s.display_name == spec.display_name for s in specs) > 1
                    else ""
                )
                choices.append((spec.display_name + suffix, spec.result_id))
        valid = {v for _, v in choices}
        value = (
            selected if selected in valid else choices[1 if len(choices) > 1 else 0][1]
        )
        return gr.update(choices=choices, value=value)

    def output_editor_controls(
        self, editor_json: str, selected: str | None
    ) -> tuple[Any, ...]:
        """Load one existing output without recreating any result specification."""
        if not editor_json:
            return (
                "",
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                "",
                "optional",
                "always",
                True,
                "先在 01 生成或加载技能。",
                gr.update(interactive=False),
                gr.update(interactive=False),
            )
        document = self.business_rule_editor.prepare(
            self._parse_editor_json(editor_json)
        )
        spec = next(
            (
                s
                for s in document.skill_template.result_specs
                if s.result_id == selected
            ),
            None,
        )
        presentation = next(
            (
                p
                for p in document.skill_template.presentation_specs
                if spec and p.result_id == spec.result_id
            ),
            None,
        )
        sources, error = self._output_sources_or_error(document, selected)
        choices = [(s.label, s.ref) for s in sources]
        ref = spec.source_ref if spec else None
        source = next((s for s in sources if s.ref == ref), None)
        # Do not silently choose a different source/type for a stale document.
        if spec and source is None:
            error = error or "当前输出的来源已不可用，请重新选择结果来源。"
        kind = self.business_rule_editor._result_kind(spec) if spec else None
        kinds = source.kinds if source else ()
        if spec and source and kind not in kinds:
            error = "当前结果类型与来源不兼容，请重新选择结果类型后保存。"
        kind_value = kind if kind in kinds else None
        info = (
            error
            or "按名称选择结果来源，再选择希望看到的结果。保存后需点击【应用修改，更新运行版本】。"
        )
        return (
            spec.display_name if spec else "新业务输出",
            gr.update(choices=choices, value=ref if source else None),
            gr.update(
                choices=[(self._friendly_result_kind(k), k) for k in kinds],
                value=kind_value,
            ),
            spec.unit or "" if spec else "",
            spec.evidence_policy if spec else "optional",
            spec.save_policy if spec else "always",
            presentation.show_in_overview if presentation else True,
            info,
            gr.update(interactive=bool(sources)),
            gr.update(interactive=spec is not None),
        )

    def _output_sources_or_error(
        self, document: SkillEditorDocument, selected: str | None = None
    ) -> tuple[list[OutputSource], str]:
        try:
            return output_sources(
                document, self.business_rule_editor, result_id=selected
            ), ""
        except (ValueError, KeyError) as exc:
            return [], f"暂不能读取可用来源；请先修正条件或编排配置：{escape(str(exc))}"

    def output_editor_kinds(
        self,
        editor_json: str,
        source_ref: str | None,
        current_kind: str | None,
        selected: str | None = None,
    ) -> tuple[Any, str]:
        """A source change never keeps an incompatible or custom result type."""
        if not editor_json:
            return gr.update(choices=[], value=None), "先在 01 生成或加载技能。"
        document = self._parse_editor_json(editor_json)
        sources, error = self._output_sources_or_error(document, selected)
        source = next((s for s in sources if s.ref == source_ref), None)
        kinds = source.kinds if source else ()
        value = current_kind if current_kind in kinds else None
        return gr.update(
            choices=[(self._friendly_result_kind(k), k) for k in kinds], value=value
        ), error or ("请选择希望看到的结果类型。" if source else "请选择结果来源。")

    @staticmethod
    def output_editor_new() -> str:
        """Start a new form without changing the document."""
        return NEW_OUTPUT

    def save_output_form(
        self,
        editor_json: str,
        selected: str | None,
        name: str,
        source_ref: str | None,
        kind: str | None,
        unit: str,
        evidence: str,
        save_policy: str,
        show: bool,
    ) -> tuple[Any, ...]:
        """Validate controlled values again on the server before staging."""
        try:
            document, result_id = save_output(
                self._parse_editor_json(editor_json),
                self.business_rule_editor,
                result_id=None if selected == NEW_OUTPUT else selected,
                display_name=name,
                source_ref=source_ref or "",
                kind=kind or "",
                unit=unit,
                evidence=evidence,
                save_policy=save_policy,
                show=show,
            )
        except (BusinessRuleEditError, ValueError, KeyError) as exc:
            raise gr.Error(str(exc)) from exc
        dumped = self._dump(document)
        return (
            dumped,
            "✅ 业务输出已保存到草稿；点击【应用修改，更新运行版本】后生效。",
            self.output_editor_choices(dumped, result_id),
        )

    def delete_output_form(
        self, editor_json: str, selected: str | None
    ) -> tuple[Any, ...]:
        """Delete by ID, never by an ambiguous display name."""
        try:
            document = delete_output(
                self._parse_editor_json(editor_json),
                self.business_rule_editor,
                selected or "",
            )
        except (BusinessRuleEditError, ValueError, KeyError) as exc:
            raise gr.Error(str(exc)) from exc
        dumped = self._dump(document)
        return (
            dumped,
            "✅ 业务输出已从草稿删除；点击【应用修改，更新运行版本】后生效。",
            self.output_editor_choices(dumped, None),
        )
