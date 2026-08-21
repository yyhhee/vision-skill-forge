import json
from pathlib import Path

from core.registry import build_default_registry
from core.schema import VisualSkillSpec
from core.validator import validate_skill


ROOT = Path(__file__).resolve().parents[1]


def test_all_13_preset_json_files_exist_validate_and_cover_matrix():
    matrix = json.loads((ROOT / "tests" / "preset_test_results.json").read_text("utf-8"))
    files = sorted((ROOT / "presets").glob("P*.json"))
    assert len(files) == len(matrix["tests"]) == 13
    registry = build_default_registry()
    for expected, path in zip(matrix["tests"], files):
        spec = VisualSkillSpec.model_validate_json(path.read_text("utf-8"))
        assert path.stem.startswith(expected["id"])
        assert validate_skill(spec, registry) == []
        actual_ops = {node.op for node in spec.nodes}
        assert set(expected["required_ops"]) <= actual_ops


def test_special_vehicle_preset_contains_all_12_human_editable_labels():
    path = next((ROOT / "presets").glob("P03*.json"))
    spec = VisualSkillSpec.model_validate_json(path.read_text("utf-8"))
    targets = next(node.params["targets"] for node in spec.nodes if node.op == "rex.ground@1.0")
    assert [target["label"] for target in targets] == [
        "消防车", "救护车", "警车", "工程抢险车", "道路清障车", "环卫车",
        "油罐车", "混凝土搅拌车", "混凝土泵车", "汽车吊", "高空作业车", "危险品运输车",
    ]
    assert all(target["phrases"] for target in targets)
