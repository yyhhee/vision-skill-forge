"""Shared activation controls for all configuration sections."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gradio as gr

from application.v2.support import ApplicationError
from core.schema import SkillPackage
from ui.v2.workspace import Workspace

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController


def bind_activation(controller: V2AppController, workspace: Workspace) -> None:
    def _refresh_configuration_state(effective_json, editor_json):
        html = controller.configuration_state_view(effective_json, editor_json)
        can_run = False
        if effective_json and editor_json:
            try:
                controller.configuration_service.require_current(
                    controller._parse_editor_json(editor_json),
                    SkillPackage.model_validate_json(effective_json),
                )
                can_run = True
            except (ValueError, TypeError, ApplicationError):
                can_run = False
        return html, html, gr.update(interactive=can_run)

    for component in (workspace.review.editor_document, workspace.review.effective):
        component.change(
            _refresh_configuration_state,
            [workspace.review.effective, workspace.review.editor_document],
            [
                workspace.review.configuration_state,
                workspace.run.configuration_state,
                workspace.run.run_button,
            ],
        )
    workspace.review.configuration_apply_button.click(
        controller.unified_validate_apply,
        workspace.review.editor_document,
        [
            workspace.review.editor_document,
            workspace.review.effective,
            workspace.review.business_rule_status,
        ],
    )
