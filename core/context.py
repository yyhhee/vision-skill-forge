from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image


def _clamp_unit(value: float) -> float:
    return min(1.0, max(0.0, value))


@dataclass(frozen=True)
class TransformStep:
    kind: str
    parameters: dict[str, Any]

    def to_parent_bbox(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = bbox
        if self.kind == "resize_contain":
            target_width, target_height = self.parameters["target_size"]
            content_width, content_height = self.parameters["content_size"]
            left, top, _, _ = self.parameters["padding"]
            mapped = (
                (x0 * target_width - left) / content_width,
                (y0 * target_height - top) / content_height,
                (x1 * target_width - left) / content_width,
                (y1 * target_height - top) / content_height,
            )
            return tuple(_clamp_unit(value) for value in mapped)
        if self.kind in {"tile", "object_crop"}:
            parent_width, parent_height = self.parameters["parent_size"]
            left, top, right, bottom = self.parameters["crop_box"]
            crop_width = right - left
            crop_height = bottom - top
            return (
                (left + x0 * crop_width) / parent_width,
                (top + y0 * crop_height) / parent_height,
                (left + x1 * crop_width) / parent_width,
                (top + y1 * crop_height) / parent_height,
            )
        # A full-frame resize changes pixels, not normalized coordinates.
        return bbox

    def from_parent_bbox(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = bbox
        if self.kind == "resize_contain":
            target_width, target_height = self.parameters["target_size"]
            content_width, content_height = self.parameters["content_size"]
            left, top, _, _ = self.parameters["padding"]
            return (
                (x0 * content_width + left) / target_width,
                (y0 * content_height + top) / target_height,
                (x1 * content_width + left) / target_width,
                (y1 * content_height + top) / target_height,
            )
        if self.kind in {"tile", "object_crop"}:
            parent_width, parent_height = self.parameters["parent_size"]
            left, top, right, bottom = self.parameters["crop_box"]
            crop_width = right - left
            crop_height = bottom - top
            return (
                (x0 * parent_width - left) / crop_width,
                (y0 * parent_height - top) / crop_height,
                (x1 * parent_width - left) / crop_width,
                (y1 * parent_height - top) / crop_height,
            )
        return bbox


@dataclass(frozen=True)
class TransformChain:
    steps: tuple[TransformStep, ...] = ()

    def append(self, step: TransformStep) -> "TransformChain":
        return TransformChain(self.steps + (step,))

    def to_original_bbox(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        mapped = bbox
        for step in reversed(self.steps):
            mapped = step.to_parent_bbox(mapped)
        return tuple(_clamp_unit(value) for value in mapped)

    def from_original_bbox(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        mapped = bbox
        for step in self.steps:
            mapped = step.from_parent_bbox(mapped)
        return mapped


@dataclass
class Frame:
    image: Image.Image
    original_size: tuple[int, int]
    frame_index: int = 0
    timestamp: float = 0.0
    source_rect: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    transform: TransformChain = field(default_factory=TransformChain)
    source_entity_id: str | None = None

    def to_original_bbox(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        if self.transform.steps:
            return self.transform.to_original_bbox(bbox)
        sx0, sy0, sx1, sy1 = self.source_rect
        width = sx1 - sx0
        height = sy1 - sy0
        x0, y0, x1, y1 = bbox
        return (
            sx0 + x0 * width,
            sy0 + y0 * height,
            sx0 + x1 * width,
            sy0 + y1 * height,
        )


@dataclass
class FrameSet:
    items: list[Frame]
    source_path: str | None = None
    source_kind: str = "image"
    source_fps: float | None = None


@dataclass
class Video:
    path: str
    fps: float
    frame_count: int
    size: tuple[int, int]
    duration: float


@dataclass
class VisualObject:
    id: str
    label: str
    phrase: str
    bbox: tuple[float, float, float, float]
    frame_index: int
    timestamp: float
    source_node: str
    track_id: str | None = None
    source_entity_id: str | None = None
    raw_output: str | None = None
    original_size: tuple[int, int] = (1, 1)
    # Relative localization quality of the source view that produced this box.
    # A value above 1 usually means an un-clipped tile observation; full-frame
    # detections use 1.  It is evidence metadata, not model confidence.
    localization_score: float = 1.0


@dataclass
class ObjectSet:
    items: list[VisualObject]


@dataclass
class Track:
    id: str
    label: str
    history: list[VisualObject]


@dataclass
class TrackSet:
    items: list[Track]


@dataclass
class Pair:
    subject_id: str
    object_id: str
    timestamp: float
    frame_index: int | None
    metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PairSet:
    items: list[Pair]


@dataclass
class ScopedGroup:
    scope_type: str
    scope_id: str
    display_name: str
    items: list[Any]


@dataclass
class ScopedSet:
    items: list[ScopedGroup]


@dataclass
class StateObservation:
    target_id: str
    state: str
    timestamp: float
    frame_index: int | None = None
    confidence: float | None = None
    track_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class StateSet:
    items: list[StateObservation]


@dataclass
class TimedValue:
    key: str
    timestamp: float
    value: Any
    frame_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScalarSet:
    items: list[TimedValue]


@dataclass
class VectorSet:
    items: list[TimedValue]


@dataclass
class ConditionSet:
    items: list[TimedValue]


@dataclass
class Event:
    id: str
    label: str
    entity_id: str
    start_time: float
    end_time: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EventSet:
    items: list[Event]


@dataclass
class EvidenceRef:
    evidence_id: str
    source_node: str
    evidence_type: str
    entity_id: str | None = None
    track_id: str | None = None
    pair_id: str | None = None
    region_id: str | None = None
    frame_index: int | None = None
    timestamp: float | None = None
    bbox: tuple[float, float, float, float] | None = None
    value: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceSet:
    items: list[EvidenceRef]


@dataclass
class ResultItemSet:
    items: list[dict[str, Any]]


@dataclass
class Region:
    id: str
    points: list[tuple[float, float]]
    label: str = "region"


@dataclass
class RegionSet:
    items: list[Region]


@dataclass
class RenderedMedia:
    path: str
    kind: str


@dataclass
class TraceEntry:
    node_id: str
    operator: str
    rule: str
    effective_params: dict[str, Any]
    input_summary: dict[str, int | str]
    output_summary: dict[str, int | str]
    elapsed_ms: float
    status: str
    error: str | None = None


@dataclass
class ExecutionResult:
    values: dict[str, Any]
    outputs: dict[str, Any]
    trace: list[TraceEntry]
    run_dir: Path
    value_envelopes: list[Any] = field(default_factory=list)
    evidence_records: list[Any] = field(default_factory=list)


@dataclass
class ExecutionServices:
    rex: Any
    output_dir: Path
    state: dict[str, Any] = field(default_factory=dict)


def summarize(value: Any) -> int | str:
    if hasattr(value, "items") and isinstance(value.items, list):
        return len(value.items)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return type(value).__name__
