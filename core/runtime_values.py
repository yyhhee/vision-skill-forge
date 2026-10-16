from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .schema import StrictModel


ValueType = Literal[
    "decision",
    "boolean",
    "scalar",
    "entity_set",
    "track_set",
    "event_set",
    "timeline",
    "resource",
    "media",
    "unknown",
]
ValueShape = Literal["single", "list", "grouped", "interval", "series"]


class TimeScope(StrictModel):
    kind: Literal["static", "timepoint", "interval", "series"] = "static"
    timestamp: float | None = None
    start_at: float | None = None
    end_at: float | None = None
    frame_index: int | None = None
    open_interval: bool = False
    sampling_tolerance: float | None = Field(default=None, ge=0)


class EvidenceRecord(StrictModel):
    evidence_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    media_asset_id: str | None = None
    timestamp: float | None = None
    frame_index: int | None = None
    time_range: tuple[float, float] | None = None
    evidence_type: Literal[
        "box",
        "track",
        "region",
        "vector",
        "measurement",
        "condition",
        "event",
        "frame",
        "clip",
        "media",
        "relation",
        "unknown",
    ]
    entity_refs: list[str] = Field(default_factory=list)
    resource_refs: list[str] = Field(default_factory=list)
    geometry: Any = None
    value: Any = None
    coordinate_space: str | None = None
    produced_by: str = Field(min_length=1)


class RuntimeValueEnvelope(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    value_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    source_node_id: str | None = None
    business_source_ref: str = Field(
        pattern=r"^(final|branch|condition|event|measurement|resource|result|node|output):[^:]+(?:[:][^:]+)*$"
    )
    result_spec_id: str | None = None
    value_type: ValueType
    value_shape: ValueShape
    value: Any = None
    unit: str | None = None
    status: Literal[
        "available",
        "satisfied",
        "not_satisfied",
        "pending",
        "not_evaluable",
        "error",
    ] = "available"
    applicability: Literal["applicable", "not_applicable", "unknown"] = "applicable"
    identity_key: str | None = None
    time_scope: TimeScope = Field(default_factory=TimeScope)
    entity_refs: list[str] = Field(default_factory=list)
    resource_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    diagnostics_ref: str | None = None


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def _stable_id(prefix: str, payload: Any) -> str:
    canonical = json.dumps(
        to_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(canonical).hexdigest()[:24]}"


def _items(value: Any) -> list[Any]:
    items = getattr(value, "items", None)
    return list(items) if isinstance(items, list) else []


def contract_type_and_shape(name: str) -> tuple[ValueType, ValueShape]:
    """Map a registered operator contract to the runtime envelope vocabulary."""
    mapping: dict[str, tuple[ValueType, ValueShape]] = {
        "EntitySet": ("entity_set", "list"),
        "ObjectSet": ("entity_set", "list"),
        "ResultItemSet": ("entity_set", "list"),
        "TrackSet": ("track_set", "list"),
        "EventSet": ("event_set", "list"),
        "ScalarSet": ("scalar", "series"),
        "VectorSet": ("scalar", "series"),
        "ConditionSet": ("boolean", "series"),
        "StateSet": ("scalar", "series"),
        "RegionSet": ("resource", "list"),
        "EvidenceSet": ("resource", "list"),
        "PairSet": ("resource", "list"),
        "ScopedSet": ("resource", "grouped"),
        "RenderedMedia": ("media", "single"),
    }
    return mapping.get(name, ("unknown", "single"))


def _type_and_shape(value: Any) -> tuple[ValueType, ValueShape]:
    contract = contract_type_and_shape(type(value).__name__)
    if contract[0] != "unknown":
        return contract
    if isinstance(value, bool):
        return "boolean", "single"
    if isinstance(value, (int, float, str)) or value is None:
        return "scalar", "single"
    if isinstance(value, list):
        return "resource", "list"
    if isinstance(value, dict):
        return "resource", "single"
    return "unknown", "single"


def _time_scope(value: Any) -> TimeScope:
    timestamps: list[float] = []
    frame_indexes: list[int] = []
    for item in _items(value):
        timestamp = getattr(item, "timestamp", None)
        if timestamp is not None:
            timestamps.append(float(timestamp))
        frame_index = getattr(item, "frame_index", None)
        if frame_index is not None:
            frame_indexes.append(int(frame_index))
        start = getattr(item, "start_time", None)
        end = getattr(item, "end_time", None)
        if start is not None:
            timestamps.append(float(start))
        if end is not None:
            timestamps.append(float(end))
    if not timestamps:
        return TimeScope()
    start_at, end_at = min(timestamps), max(timestamps)
    if start_at == end_at:
        return TimeScope(
            kind="timepoint",
            timestamp=start_at,
            frame_index=frame_indexes[0] if len(set(frame_indexes)) == 1 else None,
        )
    return TimeScope(kind="series", start_at=start_at, end_at=end_at)


def _entity_refs(value: Any) -> list[str]:
    refs: list[str] = []
    for item in _items(value):
        for name in ("id", "target_id", "entity_id", "subject_id", "object_id"):
            candidate = getattr(item, name, None)
            if candidate and candidate != "global":
                refs.append(str(candidate))
        track_id = getattr(item, "track_id", None)
        if track_id:
            refs.append(str(track_id))
    return list(dict.fromkeys(refs))


def _resource_refs(value: Any) -> list[str]:
    if type(value).__name__ != "RegionSet":
        return []
    return [
        str(getattr(item, "id"))
        for item in _items(value)
        if getattr(item, "id", None)
    ]


class LegacyOutputEnvelopeAdapter:
    """Wrap legacy dataclass outputs using explicit node/source bindings only."""

    def wrap(
        self,
        *,
        run_id: str,
        source_node_id: str | None,
        business_source_ref: str,
        value: Any,
        media_asset_id: str | None,
        result_spec_id: str | None = None,
    ) -> tuple[RuntimeValueEnvelope, list[EvidenceRecord]]:
        value_type, value_shape = _type_and_shape(value)
        evidence = self._evidence_records(
            run_id=run_id,
            source_node_id=source_node_id,
            value=value,
            media_asset_id=media_asset_id,
        )
        envelope = RuntimeValueEnvelope(
            value_id=_stable_id(
                "val",
                {
                    "run_id": run_id,
                    "source_node_id": source_node_id,
                    "business_source_ref": business_source_ref,
                    "result_spec_id": result_spec_id,
                },
            ),
            run_id=run_id,
            source_node_id=source_node_id,
            business_source_ref=business_source_ref,
            result_spec_id=result_spec_id,
            value_type=value_type,
            value_shape=value_shape,
            value=to_jsonable(value),
            identity_key="global",
            time_scope=_time_scope(value),
            entity_refs=_entity_refs(value),
            resource_refs=_resource_refs(value),
            evidence_refs=[item.evidence_id for item in evidence],
        )
        return envelope, evidence

    def _evidence_records(
        self,
        *,
        run_id: str,
        source_node_id: str | None,
        value: Any,
        media_asset_id: str | None,
    ) -> list[EvidenceRecord]:
        produced_by = source_node_id or "runtime_adapter"
        name = type(value).__name__
        records: list[EvidenceRecord] = []

        def add(
            evidence_type: str,
            *,
            marker: Any,
            timestamp: float | None = None,
            frame_index: int | None = None,
            time_range: tuple[float, float] | None = None,
            entity_refs: list[str] | None = None,
            resource_refs: list[str] | None = None,
            geometry: Any = None,
            evidence_value: Any = None,
            coordinate_space: str | None = None,
        ) -> None:
            records.append(
                EvidenceRecord(
                    evidence_id=_stable_id(
                        "ev",
                        {
                            "run_id": run_id,
                            "node": produced_by,
                            "type": evidence_type,
                            "marker": marker,
                        },
                    ),
                    run_id=run_id,
                    media_asset_id=media_asset_id,
                    timestamp=timestamp,
                    frame_index=frame_index,
                    time_range=time_range,
                    evidence_type=evidence_type,  # type: ignore[arg-type]
                    entity_refs=entity_refs or [],
                    resource_refs=resource_refs or [],
                    geometry=to_jsonable(geometry),
                    value=to_jsonable(evidence_value),
                    coordinate_space=coordinate_space,
                    produced_by=produced_by,
                )
            )

        if name == "ObjectSet":
            for entity in _items(value):
                history = getattr(entity, "history", None)
                samples = history if history is not None else [entity]
                for item in samples:
                    entity_id = str(getattr(item, "id", ""))
                    refs = [
                        candidate
                        for candidate in [
                            getattr(entity, "id", None),
                            entity_id,
                            getattr(item, "track_id", None),
                        ]
                        if candidate
                    ]
                    add(
                        "box",
                        marker=(entity_id, item.frame_index, item.bbox),
                        timestamp=float(item.timestamp),
                        frame_index=int(item.frame_index),
                        entity_refs=list(dict.fromkeys(str(candidate) for candidate in refs)),
                        geometry={"bbox": list(item.bbox)},
                        evidence_value={
                            "label": item.label,
                            "phrase": getattr(item, "phrase", ""),
                            "model_label": item.label,
                        },
                        coordinate_space="normalized_original",
                    )
        elif name == "TrackSet":
            for track in _items(value):
                samples = []
                for item in track.history:
                    samples.append(
                        {
                            "timestamp": item.timestamp,
                            "frame_index": item.frame_index,
                            "bbox": list(item.bbox),
                        }
                    )
                    add(
                        "box",
                        marker=(track.id, item.frame_index, item.bbox),
                        timestamp=float(item.timestamp),
                        frame_index=int(item.frame_index),
                        entity_refs=[str(track.id), str(item.id)],
                        geometry={"bbox": list(item.bbox)},
                        evidence_value={"label": item.label},
                        coordinate_space="normalized_original",
                    )
                add(
                    "track",
                    marker=(track.id, samples),
                    time_range=(
                        (float(track.history[0].timestamp), float(track.history[-1].timestamp))
                        if track.history
                        else None
                    ),
                    entity_refs=[str(track.id)],
                    geometry={"samples": samples},
                    evidence_value={"label": track.label},
                    coordinate_space="normalized_original",
                )
        elif name == "EventSet":
            for event in _items(value):
                add(
                    "event",
                    marker=(event.id, event.start_time, event.end_time),
                    time_range=(float(event.start_time), float(event.end_time)),
                    entity_refs=[] if event.entity_id == "global" else [str(event.entity_id)],
                    evidence_value={"label": event.label, "metadata": event.metadata},
                )
                for item in (event.metadata or {}).get("evidence", []):
                    if not isinstance(item, dict) or item.get("bbox") is None:
                        continue
                    add(
                        "box",
                        marker=(event.id, item.get("frame_index"), item.get("bbox")),
                        timestamp=item.get("timestamp"),
                        frame_index=item.get("frame_index"),
                        entity_refs=[
                            str(candidate)
                            for candidate in (item.get("entity_id"), item.get("track_id"))
                            if candidate
                        ],
                        geometry={"bbox": item.get("bbox")},
                        evidence_value={"label": item.get("label")},
                        coordinate_space="normalized_original",
                    )
        elif name in {"ScalarSet", "VectorSet", "ConditionSet", "StateSet"}:
            evidence_type = {
                "ScalarSet": "measurement",
                "VectorSet": "vector",
                "ConditionSet": "condition",
                "StateSet": "condition",
            }[name]
            for item in _items(value):
                marker = to_jsonable(item)
                add(
                    evidence_type,
                    marker=marker,
                    timestamp=getattr(item, "timestamp", None),
                    frame_index=getattr(item, "frame_index", None),
                    entity_refs=[
                        str(candidate)
                        for candidate in (
                            getattr(item, "key", None),
                            getattr(item, "target_id", None),
                            getattr(item, "track_id", None),
                        )
                        if candidate and candidate != "global"
                    ],
                    evidence_value=marker,
                )
        elif name == "RegionSet":
            for region in _items(value):
                add(
                    "region",
                    marker=(region.id, region.points),
                    resource_refs=[str(region.id)],
                    geometry={"points": region.points},
                    evidence_value={"label": region.label},
                    coordinate_space="normalized_original",
                )
        elif name == "RenderedMedia":
            add(
                "media",
                marker=(getattr(value, "path", None), getattr(value, "kind", None)),
                evidence_value=to_jsonable(value),
            )
        elif name == "EvidenceSet":
            for item in _items(value):
                add(
                    getattr(item, "evidence_type", "unknown"),
                    marker=to_jsonable(item),
                    timestamp=getattr(item, "timestamp", None),
                    frame_index=getattr(item, "frame_index", None),
                    entity_refs=[
                        str(candidate)
                        for candidate in (
                            getattr(item, "entity_id", None),
                            getattr(item, "track_id", None),
                            getattr(item, "pair_id", None),
                        )
                        if candidate
                    ],
                    resource_refs=[
                        str(getattr(item, "region_id"))
                    ]
                    if getattr(item, "region_id", None)
                    else [],
                    geometry={"bbox": getattr(item, "bbox", None)}
                    if getattr(item, "bbox", None) is not None
                    else None,
                    evidence_value=getattr(item, "value", None),
                    coordinate_space="normalized_original"
                    if getattr(item, "bbox", None) is not None
                    else None,
                )
        return records


__all__ = [
    "EvidenceRecord",
    "LegacyOutputEnvelopeAdapter",
    "RuntimeValueEnvelope",
    "TimeScope",
    "ValueShape",
    "ValueType",
    "to_jsonable",
]
