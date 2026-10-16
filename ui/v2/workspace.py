"""Explicit cross-page handles; application state remains in existing components."""

from __future__ import annotations

from dataclasses import dataclass

import gradio as gr

from ui.v2.pages.annotation import AnnotationPage
from ui.v2.pages.assets import AssetsPage
from ui.v2.pages.create import CreatePage
from ui.v2.pages.review import ReviewPage
from ui.v2.pages.run import RunPage


@dataclass(frozen=True)
class Workspace:
    create: CreatePage
    annotation: AnnotationPage
    review: ReviewPage
    run: RunPage
    assets: AssetsPage
    generated_state: gr.Textbox
    annotation_state: gr.JSON
    current_preset_state: gr.Textbox
    current_source: gr.Markdown
