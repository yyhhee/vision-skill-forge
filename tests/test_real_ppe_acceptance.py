import json
from pathlib import Path

import pytest

from core.registry import build_default_registry
from core.schema import VisualSkillSpec


ROOT = Path(__file__).resolve().parents[1]


def test_saved_real_ppe_acceptance_has_zero_false_positives_and_detects_positive():
    path = ROOT / "tests" / "ppe_real_acceptance.json"
    if not path.exists():
        pytest.skip("real PPE acceptance has not been recorded")
    result = json.loads(path.read_text("utf-8"))
    assert result["all_helmeted"]["detected_no_helmet"] == 0
    assert result["one_without_helmet"]["detected_no_helmet"] >= 1
    for key in ("all_helmeted", "one_without_helmet"):
        assert Path(result[key]["media"]).exists()
        assert Path(result[key]["annotated_media"]).exists()
        spec = VisualSkillSpec.model_validate_json(
            Path(result[key]["effective_skill_path"]).read_text("utf-8")
        )
        assert not [node for node in spec.nodes if node.op not in build_default_registry()]
