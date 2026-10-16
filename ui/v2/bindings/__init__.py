"""Register the original event graph in the same order as the monolithic UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.v2.controller import V2AppController

from ui.v2.bindings.activation import bind_activation
from ui.v2.bindings.annotation import bind_annotation
from ui.v2.bindings.assets import bind_assets
from ui.v2.bindings.business import bind_business
from ui.v2.bindings.configuration import bind_configuration
from ui.v2.bindings.creation import bind_creation
from ui.v2.bindings.events import bind_events
from ui.v2.bindings.run import bind_run
from ui.v2.workspace import Workspace


def bind_workspace(controller: V2AppController, workspace: Workspace) -> None:
    bind_assets(controller, workspace)
    creation = bind_creation(controller, workspace)
    business = bind_business(controller, workspace, creation)
    events = bind_events(controller, workspace, business, creation)
    bind_configuration(controller, workspace, business)
    bind_annotation(controller, workspace, business, creation, events)
    bind_run(controller, workspace)
    bind_activation(controller, workspace)
