from __future__ import annotations

from pathlib import Path

import cv2
from PIL import Image

from core.context import Frame, FrameSet, Video
from core.video_sampling import normalize_end_seconds


def media_image(inputs, params, services, node_id):
    media = inputs["media"]
    if isinstance(media, Image.Image):
        image = media.convert("RGB")
        source_path = None
    else:
        source_path = str(Path(media))
        image = Image.open(source_path).convert("RGB")
    return FrameSet(
        items=[Frame(image=image, original_size=image.size)],
        source_path=source_path,
        source_kind="image",
    )


def media_video(inputs, params, services, node_id):
    path = str(Path(inputs["media"]))
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise ValueError(f"cannot open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if fps <= 0:
        raise ValueError(f"video reports invalid fps: {fps}")
    return Video(path, fps, frame_count, (width, height), frame_count / fps)


def video_sample(inputs, params, services, node_id):
    video = inputs["video"]
    mode = params["mode"]
    if mode == "fps":
        step = max(1, round(video.fps / float(params["fps"])))
    elif mode == "interval":
        step = max(1, round(video.fps * float(params.get("interval_seconds", 1.0))))
    else:
        step = max(1, int(params.get("frame_step", 1)))
    start_frame = round(float(params.get("start_seconds", 0.0)) * video.fps)
    end_seconds = normalize_end_seconds(params.get("end_seconds"))
    end_frame = video.frame_count if end_seconds is None else min(
        video.frame_count, round(float(end_seconds) * video.fps)
    )
    max_frames = params.get("max_frames")
    capture = cv2.VideoCapture(video.path)
    frames = []
    index = 0
    while True:
        ok, bgr = capture.read()
        if not ok:
            break
        if index >= end_frame:
            break
        if index >= start_frame and (index - start_frame) % step == 0:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            frames.append(
                Frame(
                    image=image,
                    original_size=video.size,
                    frame_index=index,
                    timestamp=index / video.fps,
                )
            )
            if max_frames is not None and len(frames) >= int(max_frames):
                break
        index += 1
    capture.release()
    return FrameSet(frames, video.path, "video", video.fps)
