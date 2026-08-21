import importlib
from pathlib import Path

import pytest
from PIL import Image

from core.registry import build_default_registry
from core.schema import VisualSkillSpec


def load_runtime_api():
    try:
        executor = importlib.import_module("core.executor")
        operators = importlib.import_module("operators")
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"image runtime is not implemented: {exc}")
    return executor, operators


class FakeRexGateway:
    def __init__(self):
        self.calls = []

    def detect(self, image, phrases):
        self.calls.append((image.size, list(phrases)))
        return [
            {
                "phrase": phrases[0],
                "bbox": [0.1, 0.2, 0.4, 0.8],
                "raw_output": "fake-rex-output",
            }
        ]


def image_skill(image_path: Path, output_dir: Path):
    return VisualSkillSpec.model_validate(
        {
            "version": "0.1",
            "name": "image_demo",
            "display_name": "图片演示",
            "original_instruction": "检测目标",
            "compile_status": "compiled",
            "input": {"accept": ["image"]},
            "nodes": [
                {
                    "id": "frames",
                    "op": "media.image@1.0",
                    "inputs": {"media": "$input"},
                    "params": {},
                },
                {
                    "id": "resized",
                    "op": "image.resize@1.0",
                    "inputs": {"frames": "$frames"},
                    "params": {"mode": "long_side", "long_side": 50},
                },
                {
                    "id": "targets",
                    "op": "rex.ground@1.0",
                    "inputs": {"frames": "$resized"},
                    "params": {
                        "targets": [
                            {"label": "目标", "phrases": ["target object"]}
                        ]
                    },
                },
                {
                    "id": "drawn",
                    "op": "output.draw@1.0",
                    "inputs": {"frames": "$frames", "objects": "$targets"},
                    "params": {"show_labels": True},
                },
            ],
            "outputs": {"media": "$drawn"},
        }
    )


def test_image_pipeline_resizes_calls_rex_and_writes_traceable_result(tmp_path):
    executor_module, operators_module = load_runtime_api()
    image_path = tmp_path / "input.png"
    Image.new("RGB", (100, 50), "white").save(image_path)
    gateway = FakeRexGateway()
    services = executor_module.ExecutionServices(
        rex=gateway, output_dir=tmp_path / "outputs"
    )
    engine = executor_module.ExecutionEngine(
        build_default_registry(),
        operators_module.build_default_implementations(),
        services,
    )

    result = engine.execute(image_skill(image_path, tmp_path), str(image_path))

    assert gateway.calls == [((50, 25), ["target object"])]
    objects = result.values["targets"]
    assert len(objects.items) == 1
    assert objects.items[0].label == "目标"
    assert objects.items[0].bbox == pytest.approx((0.1, 0.2, 0.4, 0.8))
    rendered = result.outputs["media"]
    assert Path(rendered.path).is_file()
    assert Image.open(rendered.path).size == (100, 50)
    assert [entry.node_id for entry in result.trace] == [
        "frames",
        "resized",
        "targets",
        "drawn",
    ]
    assert all(entry.status == "success" for entry in result.trace)
    assert result.trace[2].effective_params["targets"][0]["label"] == "目标"


def test_tile_grounding_maps_tile_boxes_back_to_original_coordinates(tmp_path):
    executor_module, operators_module = load_runtime_api()
    image_path = tmp_path / "wide.png"
    Image.new("RGB", (120, 60), "white").save(image_path)
    gateway = FakeRexGateway()
    services = executor_module.ExecutionServices(
        rex=gateway, output_dir=tmp_path / "outputs"
    )
    engine = executor_module.ExecutionEngine(
        build_default_registry(),
        operators_module.build_default_implementations(),
        services,
    )
    raw = image_skill(image_path, tmp_path).model_dump()
    raw["nodes"][1] = {
        "id": "resized",
        "op": "image.tile@1.0",
        "inputs": {"frames": "$frames"},
        "params": {
            "tile_width": 60,
            "tile_height": 60,
            "overlap": 0.0,
            "deduplicate_iou": 0.7,
            "deduplicate_mode": "keep_larger",
        },
    }
    spec = VisualSkillSpec.model_validate(raw)

    result = engine.execute(spec, str(image_path))

    assert gateway.calls == [
        ((60, 60), ["target object"]),
        ((60, 60), ["target object"]),
    ]
    boxes = [item.bbox for item in result.values["targets"].items]
    assert boxes == pytest.approx(
        [(0.05, 0.2, 0.2, 0.8), (0.55, 0.2, 0.7, 0.8)]
    )


def test_grounding_deduplicates_overlapping_alias_boxes_per_label(tmp_path):
    executor_module, operators_module = load_runtime_api()

    class AliasGateway:
        def detect(self, image, phrases):
            return [
                {"phrase": phrases[0], "bbox": [0.1, 0.1, 0.5, 0.5]},
                {"phrase": phrases[1], "bbox": [0.11, 0.11, 0.51, 0.51]},
            ]

    image_path = tmp_path / "aliases.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    data = image_skill(image_path, tmp_path).model_dump(mode="json")
    ground = next(node for node in data["nodes"] if node["op"] == "rex.ground@1.0")
    ground["params"] = {
        "targets": [{"label": "车辆", "phrases": ["vehicle", "car"]}],
        "deduplicate_iou": 0.7,
    }
    spec = VisualSkillSpec.model_validate(data)
    result = executor_module.ExecutionEngine(
        build_default_registry(), operators_module.build_default_implementations(),
        executor_module.ExecutionServices(AliasGateway(), tmp_path / "out"),
    ).execute(spec, str(image_path))
    assert len(result.values["targets"].items) == 1


def test_sahi_style_tile_keeps_full_frame_and_maps_slices_back(tmp_path):
    executor_module, operators_module = load_runtime_api()
    image_path = tmp_path / "wide.png"
    Image.new("RGB", (120, 60), "white").save(image_path)
    gateway = FakeRexGateway()
    data = image_skill(image_path, tmp_path).model_dump(mode="json")
    data["nodes"][1] = {
        "id": "sahi_tiles",
        "op": "image.tile@1.0",
        "inputs": {"frames": "$frames"},
        "params": {
            "tile_width": 60,
            "tile_height": 60,
            "overlap": 0.0,
            "include_full_frame": True,
        },
    }
    data["nodes"][2]["inputs"] = {"frames": "$sahi_tiles"}
    spec = VisualSkillSpec.model_validate(data)
    result = executor_module.ExecutionEngine(
        build_default_registry(), operators_module.build_default_implementations(),
        executor_module.ExecutionServices(gateway, tmp_path / "out"),
    ).execute(spec, str(image_path))

    assert gateway.calls == [
        ((120, 60), ["target object"]),
        ((60, 60), ["target object"]),
        ((60, 60), ["target object"]),
    ]
    assert [item.bbox for item in result.values["targets"].items] == pytest.approx([
        (0.1, 0.2, 0.4, 0.8),
        (0.05, 0.2, 0.2, 0.8),
        (0.55, 0.2, 0.7, 0.8),
    ])


def test_grounding_ios_deduplicates_contained_slice_box(tmp_path):
    executor_module, operators_module = load_runtime_api()

    class ContainedGateway:
        def detect(self, image, phrases):
            if image.size == (100, 100):
                return [{"phrase": phrases[0], "bbox": [0.1, 0.1, 0.5, 0.5]}]
            return [{"phrase": phrases[0], "bbox": [0.2, 0.2, 0.6, 0.6]}]

    image_path = tmp_path / "contained.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    data = image_skill(image_path, tmp_path).model_dump(mode="json")
    data["nodes"][1] = {
        "id": "sahi_tiles", "op": "image.tile@1.0", "inputs": {"frames": "$frames"},
        "params": {"tile_width": 50, "tile_height": 50, "overlap": 0.0, "include_full_frame": True},
    }
    data["nodes"][2]["inputs"] = {"frames": "$sahi_tiles"}
    data["nodes"][2]["params"]["deduplicate_metric"] = "ios"
    data["nodes"][2]["params"]["deduplicate_iou"] = 0.5
    spec = VisualSkillSpec.model_validate(data)
    result = executor_module.ExecutionEngine(
        build_default_registry(), operators_module.build_default_implementations(),
        executor_module.ExecutionServices(ContainedGateway(), tmp_path / "out"),
    ).execute(spec, str(image_path))

    # The first tile box is fully contained in the full-image box: IoS=1, IoU=0.25.
    assert len(result.values["targets"].items) == 4


def legacy_vehicle_exclusion_graph_does_not_draw_overlapping_truck_or_van(tmp_path):
    from clients.planner_client import DeepSeekPlanner

    executor_module, operators_module = load_runtime_api()

    class VehicleGateway:
        def detect(self, image, phrases):
            if phrases == ["coach bus", "passenger car", "person"]:
                return [
                    {"phrase": "coach bus", "bbox": [0.1, 0.1, 0.3, 0.4]},
                    {"phrase": "passenger car", "bbox": [0.4, 0.1, 0.6, 0.4]},
                    {"phrase": "passenger car", "bbox": [0.7, 0.1, 0.9, 0.4]},
                    {"phrase": "person", "bbox": [0.45, 0.5, 0.5, 0.9]},
                ]
            return [
                {"phrase": "truck", "bbox": [0.4, 0.1, 0.6, 0.4]},
                {"phrase": "van", "bbox": [0.7, 0.1, 0.9, 0.4]},
            ]

    image_path = tmp_path / "vehicles.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    spec = DeepSeekPlanner(build_default_registry(), client=object()).compile(
        "检测轿车、客车、人，排除货车、面包车。", "image"
    ).spec
    result = executor_module.ExecutionEngine(
        build_default_registry(), operators_module.build_default_implementations(),
        executor_module.ExecutionServices(VehicleGateway(), tmp_path / "out"),
    ).execute(spec, str(image_path))

    assert [item.label for item in result.outputs["objects"].items] == ["客车", "人"]
    assert [item.bbox for item in result.outputs["objects"].items] == pytest.approx([
        (0.1, 0.1, 0.3, 0.4),
        (0.45, 0.5, 0.5, 0.9),
    ])
