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
from .business_result_projector import build_runtime_contract, project_run_result
from .editor_schema import (
    BusinessBranch,
    FinalDecisionSpec,
    ResultSpec,
    SkillEditorDocument,
)
from .evidence_index import EvidenceIndex
from .executor import ExecutionEngine
from .configuration import configuration_status
from .media_assets import MediaAssetStore
from .media_policy import inspect_execution_policy
from .persistence import RunStore, write_json
from .registry import OperatorRegistry
from .schema import SkillPackage, VisualSkillSpec
from .runtime_values import RuntimeValueEnvelope
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
        *,
        runtime_contract: dict | None = None,
    ) -> RunRecord:
        media_path = require_single_media_source(media)
        run_id, run_dir = self.run_store.create()
        write_json(run_dir / "generated_skill.json", generated_spec)
        write_json(run_dir / "effective_skill.json", effective_spec)
        media_asset_id = (
            hashlib.sha256(media_path.read_bytes()).hexdigest()
            if media_path.is_file()
            else None
        )
        engine = ExecutionEngine(
            self.registry,
            build_default_implementations(),
            ExecutionServices(
                self.rex,
                run_dir,
                state={
                    "run_id": run_id,
                    "media_asset_id": media_asset_id,
                    "runtime_contract": runtime_contract or {},
                },
            ),
        )
        result = engine.execute(effective_spec, str(media_path))
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
        evidence_index = EvidenceIndex(result.evidence_records)
        self.run_store.save_runtime_facts(
            run_dir,
            runtime_values=result.value_envelopes,
            evidence_index=evidence_index,
            runtime_contract=runtime_contract,
        )
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
            "media": str(media_path),
            "effective_skill_sha256": hashlib.sha256(canonical).hexdigest(),
            "object_count": object_count,
            "event_count": len(events),
            "annotated_media": str(annotated) if annotated else None,
            "media_asset_id": media_asset_id,
            "runtime_value_count": len(result.value_envelopes),
            "evidence_count": len(evidence_index),
        }
        write_json(run_dir / "run.json", metadata)
        return RunRecord(run_id, run_dir, status, object_count, len(events), annotated)


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


def require_single_media_source(media: str | Path) -> Path:
    if not isinstance(media, (str, Path)):
        raise ValueError(
            "V3 一次运行只接受一个图片或一个视频文件；"
            "多文件、多摄像头和跨媒体联合运行不在当前版本范围内。"
        )
    return Path(media).resolve()


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
        *,
        editor_document: SkillEditorDocument | None = None,
    ) -> RunRecord:
        media_path = require_single_media_source(media)
        media_type = detect_media_type(media_path)
        assert_executable_skill_package(
            effective_package, self.registry, media_type
        )
        media_sha256 = hashlib.sha256(media_path.read_bytes()).hexdigest()
        rex_model = str(
            getattr(self.rex, "model", type(self.rex).__name__)
        )
        policy = inspect_execution_policy(
            effective_package, media_type, media_path, self.registry
        )
        if editor_document is None:
            from .editor_generation import build_editor_document

            editor_document = build_editor_document(
                effective_package, source_type="legacy"
            )
        else:
            from .document_hashes import refresh_document_hashes
            from .editor_migrations import migrate_editor_document

            editor_document = migrate_editor_document(editor_document)
            if editor_document.effective_skill_package != effective_package:
                editor_document = refresh_document_hashes(
                    editor_document.model_copy(
                        update={"effective_skill_package": effective_package}
                    )
                )
        runtime_contract = build_runtime_contract(editor_document, media_type)
        effective_spec = _variant_spec(effective_package, media_type)
        base = SkillRuntime(
            self.registry, rex=self.rex, run_store=self.run_store
        ).run(
            effective_spec,
            effective_spec,
            media_path,
            runtime_contract=runtime_contract,
        )
        write_json(base.run_dir / "generated_skill.json", generated_package)
        write_json(base.run_dir / "effective_skill.json", effective_package)
        write_json(base.run_dir / "semantic_ir.json", effective_package.semantic_ir)
        media_asset = MediaAssetStore(base.run_dir / "evidence" / "media_assets").ingest(
            media_path
        )
        write_json(base.run_dir / "media_asset.json", media_asset)
        write_json(
            base.run_dir / "result_specs.json",
            runtime_contract.get("result_specs", []),
        )
        write_json(
            base.run_dir / "presentation_specs.json",
            runtime_contract.get("presentation_specs", []),
        )
        write_json(
            base.run_dir / "scene_profile.json",
            runtime_contract.get("scene_profile"),
        )
        write_json(base.run_dir / "document_hashes.json", runtime_contract.get("hashes", {}))
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
        runtime_values = [
            RuntimeValueEnvelope.model_validate(item)
            for item in json.loads(
                (base.run_dir / "runtime_values.json").read_text("utf-8")
            )
        ]
        business_result = project_run_result(
            run_id=base.run_id,
            media_asset_id=media_asset.asset_id,
            media_type=media_type,
            result_specs=[
                ResultSpec.model_validate(item)
                for item in runtime_contract.get("result_specs", [])
            ],
            final_decision=(
                FinalDecisionSpec.model_validate(runtime_contract["final_decision"])
                if runtime_contract.get("final_decision")
                else None
            ),
            branches=[
                BusinessBranch.model_validate(item)
                for item in runtime_contract.get("branches", [])
            ],
            envelopes=runtime_values,
            hashes=runtime_contract.get("hashes", {}),
        )
        write_json(base.run_dir / "run_result_v3.json", business_result)
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
            "final_result": business_result.final_result.model_dump(mode="json"),
            "business_outputs": [
                item.model_dump(mode="json")
                for item in business_result.business_outputs
            ],
            "branch_results": [
                item.model_dump(mode="json")
                for item in business_result.branch_results
            ],
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
                "runtime_values": str(base.run_dir / "runtime_values.json"),
                "evidence_index": str(base.run_dir / "evidence" / "index.json"),
                "runtime_contract": str(base.run_dir / "runtime_contract.json"),
                "run_result_v3": str(base.run_dir / "run_result_v3.json"),
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
            "final_status": business_result.final_result.status,
            "semantic_hash_v3": business_result.semantic_hash,
            "compile_hash": business_result.compile_hash,
            "package_hash": business_result.package_hash,
            "presentation_hash": business_result.presentation_hash,
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
    "require_single_media_source",
]
