"""Stable original application entry point; implementation is split by responsibility."""

from __future__ import annotations

# Legacy imports intentionally re-export the same names.
# ruff: noqa: PLC0414
import os

from application.v2.support import ROOT
from application.v2.support import (
    _variant_key as _variant_key,
)
from application.v2.support import (
    json_object_or_empty as json_object_or_empty,
)
from clients.rex_client import RexGateway
from clients.v2_planner import DeepSeekSemanticPlanner
from core.preset_media import seed_builtin_preset_media
from core.registry import build_default_registry
from ui.v2.app import (
    build_v2_app as build_v2_app,
)
from ui.v2.controller import (
    V2AppController as V2AppController,
)
from ui.v2.presentation import (
    ANNOTATION_GUIDANCE_MARKDOWN as ANNOTATION_GUIDANCE_MARKDOWN,
)
from ui.v2.presentation import (
    MEDIA_CHOICES as MEDIA_CHOICES,
)
from ui.v2.presentation import (
    NO_ANNOTATION_SLOT as NO_ANNOTATION_SLOT,
)
from ui.v2.presentation import (
    SUPPORTED_BUSINESS_PARAMETER_EDITORS as SUPPORTED_BUSINESS_PARAMETER_EDITORS,
)
from ui.v2.presentation import (
    effective_condition_config_rows as effective_condition_config_rows,
)


def default_v2_controller() -> V2AppController:
    registry = build_default_registry()
    controller = V2AppController(
        registry=registry,
        package_root=ROOT / "data" / "generated_packages",
        run_root=ROOT / "data" / "runs",
        planner=DeepSeekSemanticPlanner(registry),
        rex=RexGateway(),
    )
    seed_builtin_preset_media(controller.preset_media_catalog, ROOT)
    return controller


if __name__ == "__main__":
    build_v2_app(default_v2_controller()).launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("VISION_SKILL_PORT", "6122")),
        show_error=True,
    )


__all__ = [
    "V2AppController",
    "build_v2_app",
    "default_v2_controller",
    "effective_condition_config_rows",
    "json_object_or_empty",
]
