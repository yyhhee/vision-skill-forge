"""Controlled single-output forms; only explicit save/delete stage a draft."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gradio as gr

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController
    from ui.v2.workspace import Workspace


def output_form_fields(workspace: Workspace) -> list[gr.Component]:
    """Ordered component handles for a single form refresh."""
    review = workspace.review
    return [
        review.output_editor_name,
        review.output_editor_source,
        review.output_editor_kind,
        review.output_editor_unit,
        review.output_editor_evidence,
        review.output_editor_save,
        review.output_editor_show,
        review.output_editor_status,
        review.business_outputs_apply,
        review.business_output_delete,
    ]


def bind_output_editor(controller: V2AppController, workspace: Workspace) -> None:
    """Refresh choices from the real document, not an editable table copy."""
    review = workspace.review
    context = [review.editor_document, review.output_editor_selector]
    fields = output_form_fields(workspace)
    review.editor_document.change(
        controller.output_editor_choices,
        context,
        review.output_editor_selector,
    ).then(controller.output_editor_controls, context, fields)
    review.output_editor_selector.input(
        controller.output_editor_controls, context, fields
    )
    review.output_editor_source.input(
        controller.output_editor_kinds,
        [
            review.editor_document,
            review.output_editor_source,
            review.output_editor_kind,
            review.output_editor_selector,
        ],
        [review.output_editor_kind, review.output_editor_status],
    )
