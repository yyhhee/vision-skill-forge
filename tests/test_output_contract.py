from __future__ import annotations

from pathlib import Path

from PIL import Image

from core.context import (
    Event,
    EventSet,
    Frame,
    ObjectSet,
    Region,
    RegionSet,
    ScalarSet,
    TimedValue,
    VectorSet,
    VisualObject,
)
from operators.output import _annotate


def test_annotated_frame_draws_roi_exact_manual_arrow_and_count_overlay(tmp_path):
    frame = Frame(
        Image.new("RGB", (200, 100), "white"),
        original_size=(200, 100),
        frame_index=0,
        timestamp=0.0,
    )
    regions = RegionSet([
        Region(
            "lane_a",
            [(0.05, 0.05), (0.45, 0.05), (0.45, 0.45), (0.05, 0.45)],
            "lane A",
        )
    ])
    directions = VectorSet([
        TimedValue(
            "lane_a",
            0.0,
            (1.0, 0.0),
            None,
            metadata={
                "source": "manual",
                "start": [0.1, 0.8],
                "end": [0.9, 0.8],
            },
        )
    ])
    measurements = ScalarSet([TimedValue("global", 0.0, 3, 0)])

    rendered = _annotate(
        frame,
        objects=None,
        regions=regions,
        directions=directions,
        measurements=measurements,
        events=None,
        params={
            "show_labels": True,
            "show_track_id": True,
            "show_trajectory": False,
            "show_regions": True,
            "show_directions": True,
            "show_measurements": True,
        },
    )
    path = tmp_path / "annotated.png"
    rendered.save(path)

    assert Path(path).is_file()
    # ROI is yellow at its top edge; the manual direction is cyan at the exact
    # user-drawn y=0.8 line. These checks verify geometry, not OCR/fonts.
    assert rendered.getpixel((50, 5)) != (255, 255, 255)
    assert rendered.getpixel((100, 80)) != (255, 255, 255)
    # The measurement badge is rendered in the upper-right area.
    assert any(
        rendered.getpixel((x, y)) != (255, 255, 255)
        for x in range(120, 195)
        for y in range(5, 35)
    )


def test_event_label_can_remain_visible_when_dense_scene_base_labels_are_hidden():
    frame = Frame(
        Image.new("RGB", (240, 120), "white"),
        original_size=(240, 120),
        frame_index=0,
        timestamp=0.0,
    )
    objects = ObjectSet([
        VisualObject(
            "vehicle_1",
            "车辆",
            "vehicle",
            (0.25, 0.35, 0.55, 0.8),
            0,
            0.0,
            "detect",
            track_id="track_1",
        )
    ])
    events = EventSet([
        Event("event_1", "逆行车辆", "track_1", 0.0, 0.0)
    ])

    rendered = _annotate(
        frame,
        objects=objects,
        regions=None,
        directions=None,
        measurements=None,
        events=events,
        params={
            "show_labels": False,
            "show_event_labels": True,
            "show_track_id": False,
            "show_trajectory": False,
            "show_regions": False,
            "show_directions": False,
            "show_measurements": False,
        },
    )

    # The event text is drawn above the box even though the repeated “车辆”
    # category and track id are suppressed.
    assert any(
        rendered.getpixel((x, y)) != (255, 255, 255)
        for x in range(60, 150)
        for y in range(18, 41)
    )


def test_confirmed_track_event_can_be_projected_back_to_first_observation():
    frame = Frame(
        Image.new("RGB", (200, 100), "white"),
        original_size=(200, 100),
        frame_index=0,
        timestamp=0.0,
    )
    objects = ObjectSet([
        VisualObject(
            "vehicle_0",
            "车辆",
            "vehicle",
            (0.2, 0.2, 0.5, 0.7),
            0,
            0.0,
            "detect",
            track_id="track_1",
        ),
        VisualObject(
            "vehicle_1",
            "车辆",
            "vehicle",
            (0.25, 0.25, 0.55, 0.75),
            1,
            1.0,
            "detect",
            track_id="track_1",
        ),
    ])
    events = EventSet([Event("event_1", "逆行车辆", "track_1", 1.0, 2.0)])

    default_render = _annotate(
        frame, objects, None, None, None, events, {"show_labels": False}
    )
    history_render = _annotate(
        frame,
        objects,
        None,
        None,
        None,
        events,
        {"show_labels": False, "event_time_window": "track_history"},
    )

    # The runtime event still starts at t=1.0.  Only offline evidence drawing
    # changes: the same track is red by default and orange when back-projected.
    assert default_render.getpixel((40, 20)) == (255, 0, 0)
    assert history_render.getpixel((40, 20)) == (255, 165, 0)
    assert events.items[0].start_time == 1.0


def test_output_video_size_and_fps_modes_are_explicit_and_use_source_metadata(tmp_path):
    import cv2

    from core.context import ExecutionServices, FrameSet
    from operators.output import output_draw

    frames = FrameSet(
        items=[
            Frame(
                Image.new("RGB", (100, 50), color),
                original_size=(200, 100),
                frame_index=index,
                timestamp=float(index),
            )
            for index, color in enumerate(("red", "blue"))
        ],
        source_kind="video",
        source_fps=10.0,
    )
    rendered = output_draw(
        {"frames": frames},
        {
            "show_labels": True,
            "show_track_id": True,
            "show_trajectory": False,
            "show_regions": True,
            "show_directions": True,
            "show_measurements": True,
            "output_size_mode": "source",
            "output_width": None,
            "output_height": None,
            "output_fps_mode": "source",
            "output_fps": None,
        },
        ExecutionServices(None, tmp_path),
        "draw_source",
    )

    capture = cv2.VideoCapture(rendered.path)
    assert capture.isOpened()
    assert int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) == 200
    assert int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 100
    assert capture.get(cv2.CAP_PROP_FPS) == 10.0
    capture.release()


def test_source_size_mode_draws_on_original_uploaded_image_pixels(tmp_path):
    from core.context import ExecutionServices, FrameSet
    from operators.output import output_draw

    source = tmp_path / "uploaded.png"
    Image.new("RGB", (80, 40), "green").save(source)
    processed = FrameSet(
        [Frame(Image.new("RGB", (20, 10), "red"), original_size=(80, 40))],
        source_path=str(source),
        source_kind="image",
    )

    rendered = output_draw(
        {"frames": processed},
        {
            "show_labels": True,
            "show_track_id": True,
            "show_trajectory": False,
            "show_regions": True,
            "show_directions": True,
            "show_measurements": True,
            "output_size_mode": "source",
            "output_width": None,
            "output_height": None,
            "output_fps_mode": "sample_timeline",
            "output_fps": None,
        },
        ExecutionServices(None, tmp_path),
        "draw_original_image",
    )

    result = Image.open(rendered.path).convert("RGB")
    assert result.size == (80, 40)
    assert result.getpixel((40, 20)) == (0, 128, 0)


def test_source_size_mode_draws_sampled_video_frames_on_original_pixels(tmp_path):
    import cv2
    import numpy as np

    from core.context import ExecutionServices, FrameSet
    from operators.output import output_draw

    source = tmp_path / "uploaded.avi"
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"MJPG"), 4.0, (80, 40)
    )
    assert writer.isOpened()
    writer.write(np.full((40, 80, 3), (0, 255, 0), dtype=np.uint8))
    writer.write(np.full((40, 80, 3), (255, 0, 0), dtype=np.uint8))
    writer.release()
    processed = FrameSet(
        [
            Frame(
                Image.new("RGB", (20, 10), "red"),
                original_size=(80, 40),
                frame_index=index,
                timestamp=index / 4.0,
            )
            for index in range(2)
        ],
        source_path=str(source),
        source_kind="video",
        source_fps=4.0,
    )

    rendered = output_draw(
        {"frames": processed},
        {
            "show_labels": True,
            "show_track_id": True,
            "show_trajectory": False,
            "show_regions": True,
            "show_directions": True,
            "show_measurements": True,
            "output_size_mode": "source",
            "output_width": None,
            "output_height": None,
            "output_fps_mode": "source",
            "output_fps": None,
        },
        ExecutionServices(None, tmp_path),
        "draw_original_video",
    )

    capture = cv2.VideoCapture(rendered.path)
    ok, first = capture.read()
    capture.release()
    assert ok
    # Uploaded frame is green in BGR; the processed placeholder was red.
    assert int(first[20, 40, 1]) > 200
    assert int(first[20, 40, 2]) < 50
