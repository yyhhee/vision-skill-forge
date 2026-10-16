"""Bindings for explicit pattern identity, live preview and form-only moves."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController
    from ui.v2.workspace import Workspace


def bind_pattern_editor(controller: V2AppController, workspace: Workspace) -> None:
    """Only saving a group changes the editor document; moving edits the form."""
    review = workspace.review
    context = [
        review.editor_document,
        review.variant_choice,
        review.pattern_editor_selector,
    ]
    fields = [
        review.pattern_editor_name,
        review.business_pattern_mode,
        review.business_pattern_branches,
        review.business_pattern_window,
        review.business_pattern_required,
        review.business_pattern_correlation,
        review.business_pattern_status,
        review.pattern_editor_step,
        review.pattern_editor_dependencies,
        review.business_pattern_panel,
        review.business_pattern_apply,
    ]
    for component in (review.editor_document, review.variant_choice):
        component.change(
            controller.pattern_group_choices, context, review.pattern_editor_selector
        ).then(controller.pattern_group_controls, context, fields)
    review.pattern_editor_selector.input(
        controller.pattern_group_controls, context, fields
    )
    preview_inputs = [
        *context,
        review.business_pattern_mode,
        review.business_pattern_branches,
        review.business_pattern_window,
        review.business_pattern_required,
        review.business_pattern_correlation,
        review.pattern_editor_step,
    ]
    preview_outputs = [
        review.business_pattern_status,
        review.pattern_editor_step,
        review.pattern_editor_dependencies,
    ]
    for component in (
        review.business_pattern_branches,
        review.business_pattern_mode,
        review.business_pattern_window,
        review.business_pattern_required,
        review.business_pattern_correlation,
    ):
        component.change(
            controller.pattern_form_preview, preview_inputs, preview_outputs
        )

    def _pattern_move_up(members: list[str], step: str | None):
        return controller.pattern_move_step(members, step, "up")

    def _pattern_move_down(members: list[str], step: str | None):
        return controller.pattern_move_step(members, step, "down")

    for button, callback in (
        (review.pattern_editor_up, _pattern_move_up),
        (review.pattern_editor_down, _pattern_move_down),
    ):
        button.click(
            callback,
            [review.business_pattern_branches, review.pattern_editor_step],
            [review.business_pattern_branches, review.pattern_editor_step],
        )
