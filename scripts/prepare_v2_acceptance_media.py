from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "imgs"
GENERATED = ROOT / "data" / "acceptance_media" / "generated"
OUTPUT = ROOT / "data" / "acceptance_media" / "v2"
MANIFEST = ROOT / "data" / "acceptance_media" / "manifest_v2.json"


def _read(path: Path) -> np.ndarray:
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"cannot read image: {path}")
    return image


def _fit(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    h, w = image.shape[:2]
    scale = min(width / w, height / h)
    resized = cv2.resize(
        image,
        (max(1, round(w * scale)), max(1, round(h * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:] = (18, 18, 18)
    top = (height - resized.shape[0]) // 2
    left = (width - resized.shape[1]) // 2
    canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
    return canvas


def _write_video(path: Path, frames: list[np.ndarray], fps: float = 2.0) -> None:
    if not frames:
        raise ValueError(f"no frames for {path}")
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        raise ValueError(f"cannot create video: {path}")
    for frame in frames:
        if frame.shape[:2] != (height, width):
            raise ValueError(f"frame size changed in {path}")
        writer.write(frame)
    writer.release()


def _subtle_motion_frames(image: np.ndarray, count: int = 5) -> list[np.ndarray]:
    height, width = image.shape[:2]
    frames = []
    for index in range(count):
        scale = 1.0 + index * 0.003
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), 0.0, scale)
        matrix[0, 2] += index * 0.25
        matrix[1, 2] -= index * 0.15
        frame = cv2.warpAffine(
            image,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        frames.append(cv2.convertScaleAbs(frame, alpha=1.0, beta=(index % 3) - 1))
    return frames


def _pan_frames(
    image: np.ndarray, count: int = 7, dx_per_frame: float = 8.0
) -> list[np.ndarray]:
    height, width = image.shape[:2]
    frames = []
    for index in range(count):
        matrix = np.float32([[1.0, 0.0, index * dx_per_frame], [0.0, 1.0, 0.0]])
        frames.append(
            cv2.warpAffine(
                image,
                matrix,
                (width, height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            )
        )
    return frames


def _brightness_frames(image: np.ndarray, count: int = 5) -> list[np.ndarray]:
    offsets = [-2, 0, 2, 1, -1]
    return [
        cv2.convertScaleAbs(image, alpha=1.0, beta=offsets[index % len(offsets)])
        for index in range(count)
    ]


def _wrong_way_frames(image: np.ndarray, count: int = 7) -> list[np.ndarray]:
    height, width = image.shape[:2]
    yy, xx = np.indices((height, width), dtype=np.float32)
    divider = width * (0.12 + 0.43 * yy / max(1, height - 1))
    frames = []
    for index in range(count):
        shift = float(index * 12)
        source_x = np.where(xx < divider, xx - shift, xx + shift)
        frames.append(
            cv2.remap(
                image,
                source_x,
                yy,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            )
        )
    return frames


def _hold_frames(image: np.ndarray, count: int = 5) -> list[np.ndarray]:
    return [image.copy() for _ in range(count)]


def _fall_frames() -> list[np.ndarray]:
    standing = _fit(_read(GENERATED / "P12_standing.png"), (960, 720))
    falling = _fit(_read(GENERATED / "P12_falling.png"), (960, 720))
    fallen = _fit(_read(IMAGES / "P12.png"), (960, 720))
    return [standing, standing, falling, fallen, fallen, fallen, fallen]


def _fall_recovery_frames() -> list[np.ndarray]:
    standing = _fit(_read(GENERATED / "P12_standing.png"), (960, 720))
    falling = _fit(_read(GENERATED / "P12_falling.png"), (960, 720))
    return [standing, standing, falling, standing, standing, standing]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _video_metadata(path: Path) -> dict:
    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    return {
        "fps": fps,
        "frame_count": frame_count,
        "duration_seconds": frame_count / fps if fps else None,
        "width": width,
        "height": height,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    frame_level_sources = {
        "P01": IMAGES / "P01_fire_smoke.jpg",
        "P02": IMAGES / "P02_traffic_accident.jpg",
        "P03": IMAGES / "P03_special_vehicles.jpg",
        "P08": IMAGES / "P08_road_debris.jpg",
        "P09": ROOT / "data" / "acceptance_media" / "ppe_one_without_helmet.png",
        "P10": IMAGES / "P10_no_safety_rope.jpg",
        "P11": IMAGES / "P11.png",
        "P13": IMAGES / "P13.png",
    }
    generated_videos: list[tuple[Path, str, str]] = []
    for preset_id, source in frame_level_sources.items():
        image = _fit(_read(source), (960, 720))
        target = OUTPUT / f"{preset_id}_positive.mp4"
        _write_video(target, _subtle_motion_frames(image), fps=2.0)
        generated_videos.append(
            (target, "derived_from_project_image", str(source.resolve()))
        )

    hold_sources = {
        "P04_confusion_few_stationary": IMAGES / "P07_illegal_parking.jpg",
        "P06_negative": GENERATED / "P06_person_outside_lane.png",
        "P07_confusion_vehicle_outside_roi": IMAGES / "P06_highway_person_dwell.jpg",
        "P09_negative": Path(r"C:\yhe_user\detection_project\ultralytics\03.png"),
        "P09_confusion_helmet_in_hand": GENERATED / "P09_helmet_in_hand_not_worn.png",
        "P10_negative": GENERATED / "P10_harness_connected.png",
        "P10_confusion_unconnected": GENERATED / "P10_harness_unconnected.png",
        "P11_negative": GENERATED / "P11_clean_service_area.png",
        "P13_negative": GENERATED / "P13_intact_bridge_with_joints.png",
    }
    for name, source in hold_sources.items():
        image = _fit(_read(source), (960, 720))
        target = OUTPUT / f"{name}.mp4"
        _write_video(target, _hold_frames(image), fps=2.0)
        generated_videos.append((target, "controlled_hold_sequence", str(source.resolve())))

    low_speed_source = IMAGES / "P04_highway_congestion.jpg"
    low_speed_target = OUTPUT / "P04_positive.mp4"
    _write_video(
        low_speed_target,
        _pan_frames(_fit(_read(low_speed_source), (960, 720)), count=7, dx_per_frame=1.0),
        fps=2.0,
    )
    generated_videos.append(
        (low_speed_target, "controlled_low_speed_motion", str(low_speed_source.resolve()))
    )

    wrong_way_source = IMAGES / "P05_highway_wrong_way.jpg"
    wrong_way_target = OUTPUT / "P05_positive_short.mp4"
    _write_video(
        wrong_way_target,
        _wrong_way_frames(_fit(_read(wrong_way_source), (960, 720))),
        fps=2.0,
    )
    generated_videos.append(
        (wrong_way_target, "controlled_opposite_lane_motion", str(wrong_way_source.resolve()))
    )

    for name, source in {
        "P06_positive": IMAGES / "P06_highway_person_dwell.jpg",
        "P07_positive": IMAGES / "P07_illegal_parking.jpg",
        "P12_negative_standing": GENERATED / "P12_standing.png",
    }.items():
        target = OUTPUT / f"{name}.mp4"
        frame_count = 23 if name in {"P06_positive", "P07_positive"} else 5
        _write_video(
            target,
            _brightness_frames(_fit(_read(source), (960, 720)), count=frame_count),
            fps=2.0,
        )
        generated_videos.append(
            (target, "controlled_stationary_state_with_exposure_variation", str(source.resolve()))
        )

    moving_source = GENERATED / "shared_normal_highway.png"
    moving_target = OUTPUT / "shared_normal_highway_moving.mp4"
    _write_video(
        moving_target,
        _pan_frames(_fit(_read(moving_source), (960, 720))),
        fps=2.0,
    )
    generated_videos.append(
        (moving_target, "controlled_same_direction_motion", str(moving_source.resolve()))
    )

    # These controls deliberately cross the ten-second rule boundary used by
    # P06/P07.  Positive, negative, and confusion clips therefore prove the
    # temporal rule rather than merely exercising short-video I/O.
    long_temporal_controls = {
        "P06_negative_long": (
            GENERATED / "shared_normal_highway.png",
            "controlled_no_person_motion_over_ten_seconds",
            "pan",
        ),
        "P06_confusion_outside_lane_long": (
            GENERATED / "P06_person_outside_lane.png",
            "controlled_person_outside_roi_over_ten_seconds",
            "hold",
        ),
        "P07_negative_moving_long": (
            GENERATED / "shared_normal_highway.png",
            "controlled_moving_vehicle_over_ten_seconds",
            "pan",
        ),
        "P07_confusion_vehicle_outside_roi_long": (
            IMAGES / "P06_highway_person_dwell.jpg",
            "controlled_vehicle_outside_roi_over_ten_seconds",
            "hold",
        ),
    }
    for name, (source, generation, motion) in long_temporal_controls.items():
        image = _fit(_read(source), (960, 720))
        frames = (
            _pan_frames(image, count=23, dx_per_frame=8.0)
            if motion == "pan"
            else _hold_frames(image, count=23)
        )
        target = OUTPUT / f"{name}.mp4"
        _write_video(target, frames, fps=2.0)
        generated_videos.append((target, generation, str(source.resolve())))

    vapor_source = GENERATED / "P01_water_vapor_confusion.png"
    vapor_target = OUTPUT / "P01_water_vapor_confusion.mp4"
    _write_video(
        vapor_target,
        _subtle_motion_frames(_fit(_read(vapor_source), (960, 720))),
        fps=2.0,
    )
    generated_videos.append(
        (vapor_target, "derived_confusion_video", str(vapor_source.resolve()))
    )

    for name, source in {
        "P01_storm_cloud_confusion": GENERATED / "P01_storm_cloud_confusion.png",
        "P11_ordered_packages_confusion": GENERATED / "P11_ordered_packages_confusion.png",
        "P13_confusion_joints": GENERATED / "P13_intact_bridge_with_joints.png",
        "P13_negative": GENERATED / "P13_clean_bridge.png",
    }.items():
        target = OUTPUT / f"{name}.mp4"
        _write_video(
            target,
            _subtle_motion_frames(_fit(_read(source), (960, 720))),
            fps=2.0,
        )
        generated_videos.append(
            (target, "derived_negative_or_confusion_video", str(source.resolve()))
        )

    fall_target = OUTPUT / "P12_positive_transition.mp4"
    _write_video(fall_target, _fall_frames(), fps=2.0)
    generated_videos.append(
        (
            fall_target,
            "controlled_pose_transition",
            ";".join(
                str(path.resolve())
                for path in [
                    GENERATED / "P12_standing.png",
                    GENERATED / "P12_falling.png",
                    IMAGES / "P12.png",
                ]
            ),
        )
    )

    recovery_target = OUTPUT / "P12_confusion_fall_without_persistence.mp4"
    _write_video(recovery_target, _fall_recovery_frames(), fps=2.0)
    generated_videos.append(
        (
            recovery_target,
            "controlled_non_persistent_pose_transition",
            f"{(GENERATED / 'P12_standing.png').resolve()};"
            f"{(GENERATED / 'P12_falling.png').resolve()}",
        )
    )

    records = []
    for path, generation, source in generated_videos:
        records.append(
            {
                "path": str(path.resolve()),
                "sha256": _sha256(path),
                "media_type": "video",
                "source": source,
                "source_type": generation,
                "license_or_authorization": "local project asset or OpenAI-generated test fixture",
                **_video_metadata(path),
            }
        )
    for path in sorted(GENERATED.glob("*.png")):
        image = _read(path)
        records.append(
            {
                "path": str(path.resolve()),
                "sha256": _sha256(path),
                "media_type": "image",
                "source": "OpenAI image generation or user-supplied regression image",
                "source_type": "generated_fixture" if path.name != "generic_red_top_gray_pants.png" else "user_supplied",
                "license_or_authorization": "generated for this project or supplied by the user",
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
            }
        )

    MANIFEST.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "generated_date": "2026-08-13",
                "video_recommendation": "fixtures are <=30s; runtime remains warn-only above 30s",
                "assets": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(MANIFEST)
    print(f"generated {len(generated_videos)} videos and indexed {len(records)} assets")


if __name__ == "__main__":
    main()
