from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from operators import build_default_implementations
from operators.temporal import effective_gap_tolerance

from .context import (
    EventSet,
    ExecutionServices,
    ObjectSet,
    RegionSet,
    RenderedMedia,
    ScalarSet,
    TrackSet,
    VectorSet,
)
from .executor import ExecutionEngine
from .configuration import configuration_status
from .media_assets import MediaAssetStore
from .media_policy import inspect_execution_policy
from .persistence import RunStore, write_json
from .registry import OperatorRegistry
from .schema import SkillPackage, VisualSkillSpec
from .validator import assert_executable_skill_package, assert_valid_skill_package


@dataclass
class RunRecord:
    run_id: str
    run_dir: Path
    status: str
    object_count: int
    event_count: int
    annotated_media: Path | None
    media_type: str | None = None
    variant: str | None = None


def _event_diagnostics(spec, values, registry):
    """Explain empty event outputs from the actual boolean condition stream."""

    diagnostics = []
    nodes = {node.id: node for node in spec.nodes}
    for node in spec.nodes:
        if node.op not in {
            "event.from_condition@1.0",
            "temporal.persist@1.0",
            "temporal.qualify@1.0",
        }:
            continue
        condition_ref = node.inputs.get("condition")
        if not isinstance(condition_ref, str) or not condition_ref.startswith("$"):
            continue
        condition = values.get(condition_ref[1:])
        event_set = values.get(node.id)
        if condition is None or event_set is None:
            continue
        params = {**registry.require(node.op).defaults, **node.params}
        samples = list(condition.items)
        matched = [item for item in samples if bool(item.value)]
        output_count = len(event_set.items)
        label = params.get("label") or node.id
        alert = next(
            (
                candidate for candidate in nodes.values()
                if candidate.op == "output.alert@1.0"
                and candidate.inputs.get("events") == f"${node.id}"
            ),
            None,
        )
        if alert is not None:
            label = alert.params.get("label") or label
        required = float(
            params.get("seconds", params.get("duration_seconds", 0.0))
        )
        longest = 0.0
        grouped = {}
        for item in matched:
            grouped.setdefault(item.key, []).append(item)
        for items in grouped.values():
            start = previous = None
            tolerance = effective_gap_tolerance(
                items,
                float(params.get("gap_tolerance_seconds", 0.0)),
                infer_when_zero=required <= 0 and params.get("trigger_mode") == "once",
            )
            for item in sorted(items, key=lambda value: value.timestamp):
                if previous is None or item.timestamp - previous <= float(
                    tolerance
                ):
                    start = item.timestamp if start is None else start
                else:
                    start = item.timestamp
                previous = item.timestamp
                longest = max(longest, item.timestamp - start)
        if output_count:
            reason = f"条件已满足并产生 {output_count} 条事件"
        elif not samples:
            reason = "没有可用于判断的条件采样"
        elif not matched:
            reason = f"条件在 {len(samples)} 个采样点中从未成立"
        else:
            reason = (
                f"条件命中 {len(matched)}/{len(samples)} 个采样点，"
                f"最长连续 {longest:g} 秒，未达到 {required:g} 秒"
            )
        diagnostics.append({
            "event_id": node.id,
            "label": label,
            "event_count": output_count,
            "sample_count": len(samples),
            "matched_samples": len(matched),
            "required_seconds": required,
            "longest_continuous_seconds": longest,
            "reason": reason,
        })
    return diagnostics


def _attach_runtime_event_evidence(events, detections, tracks):
    """Project matching boxes into event records even for legacy workflows."""

    samples_by_entity = {}
    global_samples = list(detections)
    for track in tracks:
        track_id = track.get("id")
        for sample in track.get("history", []):
            samples_by_entity.setdefault(track_id, []).append(sample)
            if not detections:
                global_samples.append(sample)
    for sample in detections:
        for entity_id in {sample.get("track_id"), sample.get("id")} - {None}:
            samples_by_entity.setdefault(entity_id, []).append(sample)

    for event in events:
        metadata = event.setdefault("metadata", {})
        existing = list(metadata.get("evidence", []))
        candidates = samples_by_entity.get(event.get("entity_id"), [])
        global_event = event.get("entity_id") in {None, "global"}
        if not candidates and global_event:
            candidates = global_samples
        selected = [
            sample
            for sample in candidates
            if event["start_time"] <= sample.get("timestamp", -1) <= event["end_time"]
        ]
        if not selected and candidates:
            nearest = min(
                candidates,
                key=lambda sample: abs(
                    float(sample.get("timestamp", 0)) - float(event["start_time"])
                ),
            )
            selected = [
                sample for sample in candidates
                if sample.get("frame_index") == nearest.get("frame_index")
            ] if global_event else [nearest]
        known = {
            (item.get("entity_id"), item.get("frame_index"), tuple(item.get("bbox") or ()))
            for item in existing
            if isinstance(item, dict)
        }
        for sample in selected:
            marker = (
                sample.get("id"),
                sample.get("frame_index"),
                tuple(sample.get("bbox") or ()),
            )
            if marker in known:
                continue
            existing.append(
                {
                    "evidence_type": "target_box",
                    "entity_id": sample.get("id"),
                    "track_id": sample.get("track_id") or event.get("entity_id"),
                    "frame_index": sample.get("frame_index"),
                    "timestamp": sample.get("timestamp"),
                    "bbox": sample.get("bbox"),
                    "label": sample.get("label"),
                }
            )
        metadata["evidence"] = existing
        event["evidence_boxes"] = [
            {
                key: item.get(key)
                for key in ("entity_id", "track_id", "frame_index", "timestamp", "bbox", "label")
            }
            for item in existing
            if isinstance(item, dict) and item.get("bbox") is not None
        ]


class SkillRuntime:
    def __init__(self, registry: OperatorRegistry, *, rex, run_store: RunStore):
        self.registry = registry
        self.rex = rex
        self.run_store = run_store

    def run(
        self,
        generated_spec: VisualSkillSpec,
        effective_spec: VisualSkillSpec,
        media: str | Path,
    ) -> RunRecord:
        run_id, run_dir = self.run_store.create()
        write_json(run_dir / "generated_skill.json", generated_spec)
        write_json(run_dir / "effective_skill.json", effective_spec)
        engine = ExecutionEngine(
            self.registry,
            build_default_implementations(),
            ExecutionServices(self.rex, run_dir),
        )
        result = engine.execute(effective_spec, str(media))
        event_diagnostics = _event_diagnostics(
            effective_spec, result.values, self.registry
        )
        events = []
        detections = []
        tracks = []
        measurements = []
        regions = []
        directions = []
        object_count = 0
        rendered = None
        seen_measurements: set[int] = set()
        seen_regions: set[int] = set()
        seen_directions: set[int] = set()
        for value in result.outputs.values():
            if isinstance(value, EventSet):
                events.extend(asdict(item) for item in value.items)
            elif isinstance(value, ObjectSet):
                object_count += len(value.items)
                detections.extend(asdict(item) for item in value.items)
            elif isinstance(value, TrackSet):
                object_count += len(value.items)
                tracks.extend(asdict(item) for item in value.items)
            elif isinstance(value, ScalarSet) and id(value) not in seen_measurements:
                seen_measurements.add(id(value))
                measurements.extend(asdict(item) for item in value.items)
            elif isinstance(value, RegionSet) and id(value) not in seen_regions:
                seen_regions.add(id(value))
                regions.extend(asdict(item) for item in value.items)
            elif isinstance(value, VectorSet) and id(value) not in seen_directions:
                seen_directions.add(id(value))
                directions.extend(asdict(item) for item in value.items)
            elif isinstance(value, RenderedMedia):
                rendered = Path(value.path)
        _attach_runtime_event_evidence(events, detections, tracks)
        write_json(run_dir / "events.json", events)
        write_json(run_dir / "event_diagnostics.json", event_diagnostics)
        write_json(run_dir / "detections.json", detections)
        write_json(run_dir / "tracks.json", tracks)
        write_json(run_dir / "measurements.json", measurements)
        write_json(run_dir / "regions.json", regions)
        write_json(run_dir / "directions.json", directions)
        write_json(run_dir / "trace.json", [asdict(entry) for entry in result.trace])
        annotated = None
        if rendered is not None and rendered.exists():
            suffix = ".mp4" if rendered.suffix.lower() == ".mp4" else ".jpg"
            annotated = run_dir / f"annotated{suffix}"
            if rendered.resolve() != annotated.resolve():
                if suffix == ".jpg":
                    from PIL import Image

                    Image.open(rendered).convert("RGB").save(annotated, quality=92)
                else:
                    shutil.copy2(rendered, annotated)
        canonical = json.dumps(
            effective_spec.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        status = (
            "executed_with_output"
            if object_count or events or measurements
            else "executed_no_detection"
        )
        metadata = {
            "run_id": run_id,
            "status": status,
            "media": str(Path(media).resolve()),
            "effective_skill_sha256": hashlib.sha256(canonical).hexdigest(),
            "object_count": object_count,
            "event_count": len(events),
            "annotated_media": str(annotated) if annotated else None,
        }
        write_json(run_dir / "run.json", metadata)
        return RunRecord(run_id, run_dir, status, object_count, len(events), annotated)


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


def detect_media_type(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    raise ValueError(f"unsupported media file: {path}")


def _variant_spec(package: SkillPackage, media_type: str) -> VisualSkillSpec:
    variant = package.select_variant(media_type)
    return VisualSkillSpec.model_validate(
        {
            "version": "0.1",
            "name": package.skill_id,
            "display_name": package.display_name,
            "original_instruction": package.original_instruction,
            "compile_status": "degraded" if package.compile_status == "degraded" else "compiled",
            "input": {"accept": [media_type]},
            "nodes": [node.model_dump(mode="json") for node in variant.nodes],
            "outputs": dict(variant.outputs),
        }
    )


class SkillPackageRuntime:
    def __init__(self, registry: OperatorRegistry, *, rex, run_store: RunStore):
        self.registry = registry
        self.rex = rex
        self.run_store = run_store

    def run(
        self,
        generated_package: SkillPackage,
        effective_package: SkillPackage,
        media: str | Path,
    ) -> RunRecord:
        media_type = detect_media_type(media)
        assert_executable_skill_package(
            effective_package, self.registry, media_type
        )
        media_path = Path(media).resolve()
        media_sha256 = hashlib.sha256(media_path.read_bytes()).hexdigest()
        rex_model = str(
            getattr(self.rex, "model", type(self.rex).__name__)
        )
        policy = inspect_execution_policy(
            effective_package, media_type, media, self.registry
        )
        effective_spec = _variant_spec(effective_package, media_type)
        base = SkillRuntime(
            self.registry, rex=self.rex, run_store=self.run_store
        ).run(effective_spec, effective_spec, media)
        write_json(base.run_dir / "generated_skill.json", generated_package)
        write_json(base.run_dir / "effective_skill.json", effective_package)
        write_json(base.run_dir / "semantic_ir.json", effective_package.semantic_ir)
        media_asset = MediaAssetStore(base.run_dir / "evidence" / "media_assets").ingest(
            media_path
        )
        write_json(base.run_dir / "media_asset.json", media_asset)
        preprocessing_nodes = [
            {
                "node_id": node.id,
                "operator": node.op,
                "params": dict(node.params),
            }
            for node in effective_package.select_variant(media_type).nodes
            if node.op.startswith(("image.resize@", "image.tile@", "video.sample@"))
        ]
        preprocessing_summary = {
            "media_type": media_type,
            "nodes": preprocessing_nodes,
            "semantic_ir_affected": False,
        }
        write_json(
            base.run_dir / "preprocessing_summary.json", preprocessing_summary
        )
        slot_summary = [
            item
            for item in configuration_status(effective_package)
            if item["media_type"] == media_type
        ]
        write_json(base.run_dir / "configuration_slot_summary.json", slot_summary)
        targets = [
            target
            for node in effective_package.select_variant(media_type).nodes
            if node.op.startswith("rex.ground@")
            for target in node.params.get("targets", [])
        ]
        phrases = list(dict.fromkeys(
            phrase for target in targets for phrase in target.get("phrases", [])
        ))
        detections = json.loads(
            (base.run_dir / "detections.json").read_text("utf-8")
        )
        tracks = json.loads((base.run_dir / "tracks.json").read_text("utf-8"))
        events = json.loads((base.run_dir / "events.json").read_text("utf-8"))
        event_diagnostics = json.loads(
            (base.run_dir / "event_diagnostics.json").read_text("utf-8")
        )
        measurements = json.loads(
            (base.run_dir / "measurements.json").read_text("utf-8")
        )
        regions = json.loads((base.run_dir / "regions.json").read_text("utf-8"))
        directions = json.loads(
            (base.run_dir / "directions.json").read_text("utf-8")
        )
        trace = json.loads((base.run_dir / "trace.json").read_text("utf-8"))
        trace_by_node = {entry["node_id"]: entry for entry in trace}
        variant = effective_package.select_variant(media_type)
        constraint_summary = []
        for constraint in effective_package.semantic_ir.constraints:
            bound_nodes = variant.atom_bindings.get(constraint.atom_id or "", [])
            constraint_summary.append({
                "atom_id": constraint.atom_id,
                "kind": constraint.kind,
                "value": constraint.value,
                "source_span": constraint.source_span,
                "polarity": constraint.polarity,
                "carrier": constraint.carrier,
                "phrases": constraint.phrases,
                "bound_nodes": bound_nodes,
                "trace": [
                    trace_by_node[node_id]
                    for node_id in bound_nodes
                    if node_id in trace_by_node
                ],
            })
        policy_data = asdict(policy)
        write_json(base.run_dir / "constraint_summary.json", constraint_summary)
        result = {
            "skill_id": effective_package.skill_id,
            "media_type": media_type,
            "variant": media_type,
            "task_target": effective_package.original_instruction,
            "normalized_target": effective_package.semantic_ir.target.concept,
            "semantic_hash": effective_package.semantic_ir.semantic_hash,
            "media_sha256": media_sha256,
            "rex_model": rex_model,
            "detections": detections,
            "tracks": tracks,
            "events": events,
            "event_diagnostics": event_diagnostics,
            "measurements": measurements,
            "regions": regions,
            "directions": directions,
            "constraint_summary": constraint_summary,
            "actual_rex_phrases": phrases,
            "media_policy": policy_data,
            "artifacts": {
                "annotated_media": str(base.annotated_media)
                if base.annotated_media else None,
                "detections": str(base.run_dir / "detections.json"),
                "tracks": str(base.run_dir / "tracks.json"),
                "events": str(base.run_dir / "events.json"),
                "event_diagnostics": str(base.run_dir / "event_diagnostics.json"),
                "measurements": str(base.run_dir / "measurements.json"),
                "regions": str(base.run_dir / "regions.json"),
                "directions": str(base.run_dir / "directions.json"),
                "trace": str(base.run_dir / "trace.json"),
                "media_asset": str(base.run_dir / "media_asset.json"),
                "preprocessing_summary": str(
                    base.run_dir / "preprocessing_summary.json"
                ),
                "configuration_slot_summary": str(
                    base.run_dir / "configuration_slot_summary.json"
                ),
                "constraint_summary": str(
                    base.run_dir / "constraint_summary.json"
                ),
            },
            "status": "runtime_executed",
        }
        write_json(base.run_dir / "result.json", result)
        metadata_path = base.run_dir / "run.json"
        metadata = json.loads(metadata_path.read_text("utf-8"))
        metadata.update({
            "schema_version": "2.0",
            "media_type": media_type,
            "variant": media_type,
            "semantic_hash": effective_package.semantic_ir.semantic_hash,
            "media_sha256": media_sha256,
            "rex_model": rex_model,
            "media_policy": policy_data,
        })
        write_json(metadata_path, metadata)
        return RunRecord(
            base.run_id,
            base.run_dir,
            base.status,
            base.object_count,
            base.event_count,
            base.annotated_media,
            media_type,
            media_type,
        )


__all__ = [
    "RunRecord",
    "SkillPackageRuntime",
    "SkillRuntime",
    "detect_media_type",
]
