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
from ui.v2.controllers.configuration import ConfigurationController, draft_edit
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
    ConfigurationController,
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

    # All business and advanced document edits share the same lifecycle gate.
    business_apply_parameter = draft_edit(
        BusinessRuleController.business_apply_parameter
    )
    business_add_branch = draft_edit(BusinessRuleController.business_add_branch)
    business_branch_action = draft_edit(BusinessRuleController.business_branch_action)
    business_add_condition = draft_edit(BusinessRuleController.business_add_condition)
    business_condition_action = draft_edit(
        BusinessRuleController.business_condition_action
    )
    business_group_conditions = draft_edit(
        BusinessRuleController.business_group_conditions
    )
    business_update_expression_logic = draft_edit(
        BusinessRuleController.business_update_expression_logic
    )
    business_update_imported_logic = draft_edit(
        BusinessRuleController.business_update_imported_logic
    )
    business_apply_condition = draft_edit(
        BusinessRuleController.business_apply_condition
    )
    business_apply_branch_time = draft_edit(
        BusinessRuleController.business_apply_branch_time
    )
    business_apply_pattern = draft_edit(BusinessRuleController.business_apply_pattern)
    business_apply_final = draft_edit(BusinessRuleController.business_apply_final)
    business_apply_outputs = draft_edit(BusinessRuleController.business_apply_outputs)
    business_apply_trigger = draft_edit(BusinessRuleController.business_apply_trigger)
    unified_apply_parameter = draft_edit(EditorController.unified_apply_parameter)
    unified_reset_parameter = draft_edit(EditorController.unified_reset_parameter)
    unified_mutate_graph = draft_edit(EditorController.unified_mutate_graph)
    unified_mutate_branch = draft_edit(EditorController.unified_mutate_branch)
    unified_insert_recipe = draft_edit(EditorController.unified_insert_recipe)
    unified_apply_patterns = draft_edit(EditorController.unified_apply_patterns)
    unified_resolve_pending = draft_edit(EditorController.unified_resolve_pending)
    unified_apply_results = draft_edit(EditorController.unified_apply_results)
