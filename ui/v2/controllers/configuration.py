"""Shared transaction adapter and user-facing activation state."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from html import escape
from inspect import Parameter, signature
from typing import TYPE_CHECKING, Any

import gradio as gr

from application.v2.support import ApplicationError
from core.schema import SkillPackage

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController


def draft_edit(
    method: Callable[..., tuple[Any, ...]],
) -> Callable[..., tuple[Any, ...]]:
    """Route an existing editor command through one copy/validate/stage boundary.

    The command's public signature, feedback and selected-condition outputs are
    retained. Only the returned document is committed, after success.
    """
    parameters = signature(method)

    @wraps(method)
    def transaction(
        self: V2AppController, *args: Any, **kwargs: Any
    ) -> tuple[Any, ...]:
        bound = parameters.bind(self, *args, **kwargs)
        before = self._parse_editor_json(bound.arguments["editor_json"])
        result = method(self, *args, **kwargs)
        updated = self._parse_editor_json(result[0])
        try:
            staged = self.configuration_service.stage(before, updated)
        except ApplicationError as exc:
            raise gr.Error(str(exc)) from None
        feedback = result[1]
        if isinstance(feedback, str):
            feedback = feedback.replace(
                "校验并生成当前运行版本（使修改生效）", "应用修改，更新运行版本"
            )
        return (self._dump(staged), feedback, *result[2:])

    return transaction


def runtime_edit(
    controller: V2AppController, method: Callable[..., Any]
) -> Callable[..., Any]:
    """Protect explicit execution-card/annotation updates from mixed draft edits."""

    @wraps(method)
    def transaction(configuration_document: str, *args: Any, **kwargs: Any) -> Any:
        if configuration_document and args and args[0]:
            try:
                controller.configuration_service.require_current(
                    controller._parse_editor_json(configuration_document),
                    SkillPackage.model_validate_json(args[0]),
                )
            except ApplicationError as exc:
                raise gr.Error(str(exc)) from None
        return method(*args, **kwargs)

    original = signature(method)
    transaction.__signature__ = original.replace(  # type: ignore[attr-defined]
        parameters=[
            Parameter("configuration_document", Parameter.POSITIONAL_OR_KEYWORD),
            *original.parameters.values(),
        ]
    )
    transaction.configuration_guard = True  # type: ignore[attr-defined]
    return transaction


class ConfigurationController:
    def load_editor_configuration(self, effective_json: str, source_mode: str) -> str:
        """Explicit loading starts from the selected package, not a stale draft."""
        source_type = {
            "自然语言生成": "natural_language",
            "预置演示技能": "preset",
            "已保存技能": "legacy",
        }.get(source_mode, "legacy")
        return self._dump(
            self._editor_document(effective_json, "", source_type=source_type)
        )

    def configuration_state_view(self, effective_json: str, editor_json: str) -> str:
        """Describe the actual published package independently from form feedback."""
        if not effective_json:
            return "<div class='status-card'><b>尚未加载运行版本</b><p>先在 01 生成或加载技能。</p></div>"
        try:
            package = SkillPackage.model_validate_json(effective_json)
            if not editor_json:
                return (
                    "<div class='status-card'><b>当前运行版本：已加载</b><p>"
                    + escape(package.display_name)
                    + "；03 编辑器正在读取配置。</p></div>"
                )
            document = self._parse_editor_json(editor_json)
            state = self.configuration_service.status(document, package)
        except (ValueError, TypeError, ApplicationError):
            return "<div class='status-card'><b>配置暂不可运行</b><p>请检查 03 中的配置文档。</p></div>"
        revision = (
            f"R{state.running_revision}" if state.running_revision else "尚未生成"
        )
        running = f"当前运行版本：{revision} · {escape(package.display_name)}"
        if state.dirty:
            return (
                "<div class='status-card'><b>有未应用修改</b><p>"
                + running
                + "（保持不变）。先保存卡片内容到草稿，再点击“应用修改，更新运行版本”。"
                "应用前 04 暂不可运行。</p></div>"
            )
        if not state.package_matches:
            return "<div class='status-card'><b>配置版本不一致</b><p>请重新读取配置并应用后再运行。</p></div>"
        blockers = document.validation_report.get("resource_blockers", [])
        suffix = (
            "仍需完成 02 标注后才能运行。" if blockers else "已应用；04 使用此版本。"
        )
        return f"<div class='status-card'><b>{running}</b><p>{suffix}</p></div>"
