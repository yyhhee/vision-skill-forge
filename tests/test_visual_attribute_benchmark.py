from PIL import Image

from core.context import Frame, FrameSet, ObjectSet, VisualObject
from operators.appearance import visual_color_fraction, visual_geometry


COLORS = ["black", "white", "gray", "red", "orange", "yellow",
          "green", "cyan", "blue", "purple", "pink", "brown"]


def _objects():
    output = []
    for index, color in enumerate(COLORS):
        column, row = index % 6, index // 6
        x0, y0 = 40 + column * 195, 40 + row * 280
        size = 80 if column < 2 else 130 if column < 4 else 180
        output.append(VisualObject(
            id=color, label=color, phrase=color,
            bbox=(x0 / 1200, y0 / 600, (x0 + size) / 1200, (y0 + size) / 600),
            frame_index=0, timestamp=0.0, source_node="gold", original_size=(1200, 600),
        ))
    return ObjectSet(output)


def test_generated_color_grid_is_recognized_by_all_twelve_catalog_colors():
    path = __import__("pathlib").Path(__file__).parent / "assets" / "visual_attribute_benchmark.png"
    image = Image.open(path).convert("RGB")
    frames = FrameSet([Frame(image, image.size)])
    objects = _objects()
    for expected in COLORS:
        result = visual_color_fraction(
            {"frames": frames, "objects": objects},
            {"color": expected, "subject_region": [0, 0, 1, 1], "min_fraction": 0.75},
            None, expected,
        )
        selected = [item.key for item in result.items if item.value]
        assert selected == [expected]


def test_generated_grid_size_and_position_rules_have_literal_gold_results():
    objects = _objects()
    small = visual_geometry(
        {"objects": objects},
        {"dimension": "size", "value": "small", "small_max_area": 0.012,
         "large_min_area": 0.04, "position_margin": 0.33}, None, "small",
    )
    left = visual_geometry(
        {"objects": objects},
        {"dimension": "position", "value": "left", "small_max_area": 0.012,
         "large_min_area": 0.04, "position_margin": 0.33}, None, "left",
    )
    assert [item.key for item in small.items if item.value] == ["black", "white", "green", "cyan"]
    assert [item.key for item in left.items if item.value] == ["black", "white", "green", "cyan"]
