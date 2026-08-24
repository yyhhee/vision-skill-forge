from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from .schema import StrictModel


class InteractionPolicy(StrictModel):
    drilldown: bool = True
    highlight_evidence: bool = True
    default_focus: Literal["summary", "value", "evidence", "timeline"] = "summary"


class PresentationSpec(StrictModel):
    """Display-only preferences for one semantic ResultSpec."""

    result_id: str = Field(min_length=1)
    preferred_renderer: str = Field(default="generic.summary", min_length=1)
    show_in_overview: bool = True
    display_order: int = Field(default=0, ge=0)
    overview_span: Literal["compact", "normal", "wide", "full"] = "normal"
    value_format: Literal[
        "auto", "number", "percentage", "duration", "direction", "status", "text"
    ] = "auto"
    precision: int | None = Field(default=None, ge=0, le=12)
    sort_by: str | None = None
    visualization_options: dict[str, Any] = Field(default_factory=dict)
    interaction_policy: InteractionPolicy = Field(default_factory=InteractionPolicy)


def presentation_hash(specs: list[PresentationSpec]) -> str:
    payload = [
        item.model_dump(mode="json")
        for item in sorted(specs, key=lambda value: (value.display_order, value.result_id))
    ]
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = ["InteractionPolicy", "PresentationSpec", "presentation_hash"]
