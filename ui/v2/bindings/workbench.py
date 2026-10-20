"""Read-through overview and explicit navigation; no duplicated draft state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ui.v2.controllers.workbench import NAVIGATION_FIELDS

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController
    from ui.v2.workspace import Workspace


def bind_workbench(controller: V2AppController, workspace: Workspace) -> None:
    review = workspace.review
    context = [
        review.editor_document,
        review.variant_choice,
        review.workbench_selection,
    ]
    for component in (review.editor_document, review.variant_choice):
        component.change(
            controller.workbench_controls,
            context,
            [
                review.workbench_summary,
                review.workbench_selection,
                review.workbench_edit,
            ],
        )

    def _workbench_navigate(editor_json, media_type, address, include_tuning):
        updates = controller.workbench_navigation(
            editor_json, media_type, address, include_tuning
        )
        return {getattr(review, key): value for key, value in updates.items()}

    review.workbench_edit.click(
        _workbench_navigate,
        [*context, review.business_include_tuning],
        [getattr(review, name) for name in NAVIGATION_FIELDS],
    )
