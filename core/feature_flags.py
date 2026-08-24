from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


RuleEditorV3Mode = Literal["off", "shadow", "on"]
_VALID_MODES = {"off", "shadow", "on"}


@dataclass(frozen=True)
class FeatureFlags:
    """Release gates for the V3 business-rule path.

    shadow keeps the existing user entry point authoritative while allowing
    deterministic V3 compilation, persistence, and comparison in parallel.
    It never performs a second external notification.
    """

    rule_editor_v3: RuleEditorV3Mode = "shadow"

    @property
    def v3_enabled(self) -> bool:
        return self.rule_editor_v3 in {"shadow", "on"}

    @property
    def v3_is_primary(self) -> bool:
        return self.rule_editor_v3 == "on"


def load_feature_flags(environ: dict[str, str] | None = None) -> FeatureFlags:
    source = os.environ if environ is None else environ
    raw = source.get("VISION_SKILL_RULE_EDITOR_V3", "shadow").strip().lower()
    if raw not in _VALID_MODES:
        choices = ", ".join(sorted(_VALID_MODES))
        raise ValueError(
            f"VISION_SKILL_RULE_EDITOR_V3 must be one of: {choices}; got {raw!r}"
        )
    return FeatureFlags(rule_editor_v3=raw)  # type: ignore[arg-type]


__all__ = ["FeatureFlags", "RuleEditorV3Mode", "load_feature_flags"]
