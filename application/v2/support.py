"""Shared application paths and value helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class ApplicationError(Exception):
    """User-facing application failure, adapted to Gradio at the UI boundary."""


def _variant_key(value: str) -> str:
    if value == "仅图片":
        return "image"
    if value == "仅视频":
        return "video"
    if value.startswith("image"):
        return "image"
    if value.startswith("video"):
        return "video"
    if value in {"image", "video"}:
        return value
    raise ValueError(f"unknown variant: {value}")


def json_object_or_empty(value: str | None) -> dict[str, Any]:
    """Keep UI synchronization callbacks harmless after an upstream error."""

    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


MEDIA_CHOICES = {
    "仅图片": ["image"],
    "仅视频": ["video"],
    "图片和视频": ["image", "video"],
}
