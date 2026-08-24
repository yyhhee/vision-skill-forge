from __future__ import annotations

import pytest

from core.feature_flags import load_feature_flags


def test_rule_editor_v3_defaults_to_shadow_and_has_explicit_release_modes():
    flags = load_feature_flags({})
    assert flags.rule_editor_v3 == "shadow"
    assert flags.v3_enabled
    assert not flags.v3_is_primary

    assert not load_feature_flags({"VISION_SKILL_RULE_EDITOR_V3": "off"}).v3_enabled
    assert load_feature_flags({"VISION_SKILL_RULE_EDITOR_V3": "on"}).v3_is_primary


def test_unknown_rule_editor_release_mode_is_rejected():
    with pytest.raises(ValueError, match="must be one of"):
        load_feature_flags({"VISION_SKILL_RULE_EDITOR_V3": "maybe"})
