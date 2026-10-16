"""Assets page event registration; preserves callback order and signatures."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

import gradio as gr

from ui.v2.workspace import Workspace


def bind_assets(controller: V2AppController, workspace: Workspace) -> None:
    workspace.assets.capability_asset_select.change(
        controller.business_capability_detail,
        workspace.assets.capability_asset_select,
        workspace.assets.capability_asset_detail,
    )

    def _filter_operator_assets(layer: str):
        assets = workspace.assets.operator_asset_layers[layer]
        first = assets[0]
        return (
            gr.update(
                choices=[
                    (
                        f"{item['category']}｜{item['display_name']}（{item['operator']}）",
                        item["operator"],
                    )
                    for item in assets
                ],
                value=first["operator"],
            ),
            first,
        )

    workspace.assets.operator_asset_layer.change(
        _filter_operator_assets,
        workspace.assets.operator_asset_layer,
        [
            workspace.assets.operator_asset_select,
            workspace.assets.operator_asset_detail,
        ],
    )
    workspace.assets.operator_asset_select.change(
        controller.operator_asset_detail,
        [workspace.assets.operator_asset_select, workspace.review.editor_document],
        workspace.assets.operator_asset_detail,
    )
    workspace.assets.effective_asset_refresh.click(
        controller.effective_package_asset_view,
        [workspace.review.effective, workspace.review.editor_document],
        workspace.assets.effective_asset_view,
    )
