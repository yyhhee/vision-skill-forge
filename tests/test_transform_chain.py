from __future__ import annotations

import pytest
from PIL import Image

from core.context import Frame, FrameSet, ObjectSet, VisualObject


def _object(object_id: str, bbox: tuple[float, float, float, float]):
    return VisualObject(
        id=object_id,
        label="person",
        phrase="person",
        bbox=bbox,
        frame_index=0,
        timestamp=0.0,
        source_node="test",
        original_size=(100, 100),
    )


def test_contain_padding_is_removed_when_bbox_returns_to_original_coordinates():
    from operators.preprocess import image_resize

    original = FrameSet([Frame(Image.new("RGB", (200, 100)), (200, 100))])
    resized = image_resize(
        {"frames": original},
        {
            "mode": "contain",
            "width": 200,
            "height": 200,
            "long_side": 200,
            "interpolation": "bilinear",
        },
        None,
        "resize",
    )
    frame = resized.items[0]

    assert frame.image.size == (200, 200)
    assert frame.to_original_bbox((0.25, 0.25, 0.75, 0.75)) == pytest.approx(
        (0.25, 0.0, 0.75, 1.0)
    )
    assert [step.kind for step in frame.transform.steps] == ["resize_contain"]
    assert frame.transform.steps[0].parameters["padding"] == [0, 50, 0, 50]


def test_contain_then_tile_composes_transforms_instead_of_overwriting_them():
    from operators.preprocess import image_resize, image_tile

    original = FrameSet([Frame(Image.new("RGB", (200, 100)), (200, 100))])
    resized = image_resize(
        {"frames": original},
        {
            "mode": "contain",
            "width": 200,
            "height": 200,
            "long_side": 200,
            "interpolation": "bilinear",
        },
        None,
        "resize",
    )
    tiled = image_tile(
        {"frames": resized},
        {
            "tile_width": 100,
            "tile_height": 100,
            "overlap": 0.0,
            "include_full_frame": False,
        },
        None,
        "tiles",
    )

    first = tiled.items[0]
    assert first.to_original_bbox((0.5, 0.5, 1.0, 1.0)) == pytest.approx(
        (0.25, 0.0, 0.5, 0.5)
    )
    assert [step.kind for step in first.transform.steps] == [
        "resize_contain",
        "tile",
    ]


def test_stretch_records_independent_pixel_scales_but_preserves_normalized_bbox():
    from operators.preprocess import image_resize

    original = FrameSet([Frame(Image.new("RGB", (200, 100)), (200, 100))])
    resized = image_resize(
        {"frames": original},
        {
            "mode": "stretch",
            "width": 100,
            "height": 300,
            "long_side": 200,
            "interpolation": "bilinear",
        },
        None,
        "resize",
    ).items[0]

    assert resized.to_original_bbox((0.1, 0.2, 0.6, 0.8)) == pytest.approx(
        (0.1, 0.2, 0.6, 0.8)
    )
    assert resized.transform.steps[0].parameters["pixel_scale"] == [0.5, 3.0]


def test_identity_resize_preserves_pixels_dimensions_and_coordinate_chain():
    from operators.preprocess import image_resize

    image = Image.new("RGB", (203, 117), (17, 83, 149))
    original = FrameSet(
        [Frame(image, image.size)],
        source_path="source.png",
        source_kind="image",
    )

    result = image_resize(
        {"frames": original},
        {"mode": "identity", "interpolation": "bilinear"},
        None,
        "resize",
    )
    frame = result.items[0]

    assert frame.image.size == (203, 117)
    assert frame.image.tobytes() == image.tobytes()
    assert frame.transform.steps == ()
    assert frame.to_original_bbox((0.1, 0.2, 0.7, 0.9)) == pytest.approx(
        (0.1, 0.2, 0.7, 0.9)
    )
    assert result.source_path == "source.png"
    assert result.source_kind == "image"


def test_object_crop_maps_nested_grounding_box_back_to_original_entity_area():
    from operators.preprocess import object_crop

    frames = FrameSet([Frame(Image.new("RGB", (100, 100)), (100, 100))])
    people = ObjectSet([_object("person_1", (0.2, 0.3, 0.6, 0.9))])

    crops = object_crop(
        {"frames": frames, "objects": people},
        {"padding_fraction": 0.0},
        None,
        "crops",
    )

    assert len(crops.items) == 1
    crop = crops.items[0]
    assert crop.image.size == (40, 60)
    assert crop.source_entity_id == "person_1"
    assert crop.to_original_bbox((0.25, 0.25, 0.75, 0.75)) == pytest.approx(
        (0.3, 0.45, 0.5, 0.75)
    )
    assert crop.transform.steps[-1].kind == "object_crop"


def test_object_crop_supports_clipped_relative_region_outside_subject_box():
    from operators.preprocess import object_crop

    frames = FrameSet([Frame(Image.new("RGB", (100, 100)), (100, 100))])
    people = ObjectSet([_object("person_1", (0.2, 0.3, 0.6, 0.9))])

    crop = object_crop(
        {"frames": frames, "objects": people},
        {
            "padding_fraction": 0.0,
            "subject_region": [-0.5, -0.5, 1.5, 1.2],
        },
        None,
        "extended_crop",
    ).items[0]

    assert crop.image.size == (80, 100)
    assert crop.source_rect == pytest.approx((0.0, 0.0, 0.8, 1.0))
