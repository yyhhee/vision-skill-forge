from __future__ import annotations

from collections import defaultdict

import pytest

from core.runtime import detect_media_type, require_single_media_source
from core.schema import SkillPackage
from scripts.run_v2_semantic_acceptance import CASES, PRESETS


EXPECTED_MEDIA = {
    "P01": {"image", "video"},
    "P02": {"image", "video"},
    "P03": {"image", "video"},
    "P04": {"video"},
    "P05": {"video"},
    "P06": {"video"},
    "P07": {"video"},
    "P08": {"image", "video"},
    "P09": {"image", "video"},
    "P10": {"image", "video"},
    "P11": {"image", "video"},
    "P12": {"video"},
    "P13": {"image", "video"},
}


def test_acceptance_matrix_has_positive_negative_confusion_for_every_variant():
    grouped = defaultdict(set)
    for case in CASES:
        grouped[(case.preset_id, case.variant)].add(case.case_kind)

    expected_variants = {
        (preset_id, media_type)
        for preset_id, media_types in EXPECTED_MEDIA.items()
        for media_type in media_types
    }
    assert set(grouped) == expected_variants
    assert all(kinds == {"positive", "negative", "confusion"} for kinds in grouped.values())
    assert len(CASES) == len(expected_variants) * 3 == 63
    assert len({case.case_id for case in CASES}) == len(CASES)


def test_acceptance_matrix_media_and_expectations_match_declared_variants():
    for case in CASES:
        assert case.media.is_file(), case.case_id
        assert detect_media_type(case.media) == case.variant
        assert case.signal in {"objects", "events"}
        assert case.minimum >= 0
        assert case.maximum is None or case.maximum >= case.minimum
        assert case.expected_note

        package_path = next(PRESETS.glob(f"{case.preset_id}_*.json"))
        package = SkillPackage.model_validate_json(package_path.read_text("utf-8"))
        assert case.variant in package.input.accept


def test_v3_runtime_rejects_multiple_media_sources_before_variant_selection():
    with pytest.raises(ValueError, match="一次运行只接受一个"):
        require_single_media_source(["a.jpg", "b.jpg"])  # type: ignore[arg-type]
