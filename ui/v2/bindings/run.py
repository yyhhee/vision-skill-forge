"""Run page event registration; preserves callback order and signatures."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

import gradio as gr

from core.runtime import detect_media_type
from core.schema import SkillPackage
from ui.v2.workspace import Workspace


def bind_run(controller: V2AppController, workspace: Workspace) -> None:
    def _run_with_media_visibility(
        generated, effective_json, editor_json, variant, media_path
    ):
        if editor_json:
            try:
                editor_json = controller.prepare_run_editor_document(
                    effective_json,
                    editor_json,
                    detect_media_type(media_path) if media_path else variant,
                )
                document = controller._parse_editor_json(editor_json)
                package = SkillPackage.model_validate_json(effective_json)
                if document.skill_template.skill_id == package.skill_id:
                    if document.effective_skill_package is None:
                        raise gr.Error(
                            "03 中存在尚未应用的配置草稿，请先完整校验并应用。"
                        )
                    if document.validation_report.get("can_run") is False:
                        raise gr.Error(
                            "03 配置尚未满足运行条件："
                            + controller.run_configuration_blocker_message(document)
                        )
                    blockers = [
                        item.prompt
                        for item in document.skill_template.pending_decisions
                        if item.resolution.blocks("run")
                    ]
                    if blockers:
                        raise gr.Error("运行前仍需确认：" + "；".join(blockers))
            except gr.Error:
                raise
            except Exception as exc:
                raise gr.Error(f"03 配置文档无效：{exc}") from exc
        img, vid, *rest = controller.run_skill(
            generated, effective_json, variant, media_path, editor_json
        )
        return (
            gr.update(value=img, visible=img is not None),
            gr.update(value=vid, visible=vid is not None),
            controller.business_result_html(rest[-2]),
            *rest,
        )

    workspace.run.run_button.click(
        _run_with_media_visibility,
        [
            workspace.generated_state,
            workspace.review.effective,
            workspace.review.editor_document,
            workspace.create.run_variant,
            workspace.create.media,
        ],
        [
            workspace.run.annotated_image,
            workspace.run.annotated_video,
            workspace.run.business_results_html,
            workspace.run.detections,
            workspace.run.tracks,
            workspace.run.events,
            workspace.run.measurements,
            workspace.run.regions,
            workspace.run.directions,
            workspace.run.constraints,
            workspace.run.trace,
            workspace.run.run_dir,
            workspace.run.run_status,
        ],
    )
