"""Compatibility facade over application services and domain UI adapters."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import gradio as gr

from application.v2.base import ApplicationContext
from application.v2.execution import ExecutionService
from application.v2.skills import SkillService
from application.v2.support import ApplicationError
from ui.v2.controllers.annotation import AnnotationController
from ui.v2.controllers.assets import AssetController
from ui.v2.controllers.business import BusinessRuleController
from ui.v2.controllers.editor import EditorController
from ui.v2.controllers.events import EventRuleController
from ui.v2.controllers.execution import ExecutionConfigController
from ui.v2.controllers.results import ResultController

Parameters = ParamSpec("Parameters")
ReturnValue = TypeVar("ReturnValue")


def _ui_errors(
    method: Callable[Parameters, ReturnValue],
) -> Callable[Parameters, ReturnValue]:
    """Preserve Gradio error behavior while application services stay UI-free."""

    @wraps(method)
    def adapted(*args: Parameters.args, **kwargs: Parameters.kwargs) -> ReturnValue:
        try:
            return method(*args, **kwargs)
        except ApplicationError as exc:
            raise gr.Error(str(exc)) from None

    return adapted


class V2AppController(
    ApplicationContext,
    SkillService,
    BusinessRuleController,
    EditorController,
    EventRuleController,
    ExecutionConfigController,
    AnnotationController,
    ResultController,
    ExecutionService,
    AssetController,
):
    """One state owner; domain adapters never create independent skill copies."""

    preferred_executable_variant = _ui_errors(
        ApplicationContext.preferred_executable_variant
    )
    preset_default_media = _ui_errors(SkillService.preset_default_media)
    set_preset_default_media = _ui_errors(SkillService.set_preset_default_media)
    compile_skill = _ui_errors(SkillService.compile_skill)
    load_preset = _ui_errors(SkillService.load_preset)
    load_saved_skill = _ui_errors(SkillService.load_saved_skill)
    save_skill = _ui_errors(SkillService.save_skill)
    _asset_stores = _ui_errors(SkillService._asset_stores)
    save_skill_bundle = _ui_errors(SkillService.save_skill_bundle)
    delete_saved_skill = _ui_errors(SkillService.delete_saved_skill)
    restore_default_editor_document = _ui_errors(
        SkillService.restore_default_editor_document
    )
    run_skill = _ui_errors(ExecutionService.run_skill)
