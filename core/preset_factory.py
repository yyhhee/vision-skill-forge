from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .registry import OperatorRegistry, build_default_registry
from .schema import SkillPackage
from .semantic import SemanticNormalizer
from .validator import assert_valid_skill_package


Node = dict[str, Any]


def _replace_reference(value: Any, old: str, new: str) -> Any:
    if value == old:
        return new
    if isinstance(value, list):
        return [_replace_reference(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_reference(item, old, new) for key, item in value.items()}
    return value


def _contains_reference(value: Any, reference: str) -> bool:
    if value == reference:
        return True
    if isinstance(value, list):
        return any(_contains_reference(item, reference) for item in value)
    if isinstance(value, dict):
        return any(_contains_reference(item, reference) for item in value.values())
    return False


def _remove_context_confirmation(
    nodes: list[Node], outputs: dict[str, str]
) -> tuple[list[Node], dict[str, str]]:
    """Remove the named confirmation branch and reconnect its upstream output."""

    candidates = next(
        (item for item in nodes if item["id"] == "context_confirmation_candidates"),
        None,
    )
    if candidates is None:
        return deepcopy(nodes), dict(outputs)
    upstream = candidates["inputs"]["objects"]
    final_ref = "$context_confirmation_deduplicated"
    without_branch = [
        deepcopy(item)
        for item in nodes
        if not item["id"].startswith("context_confirmation_")
    ]
    for item in without_branch:
        item["inputs"] = _replace_reference(item.get("inputs", {}), final_ref, upstream)
    return without_branch, _replace_reference(dict(outputs), final_ref, upstream)


def apply_context_confirmation(
    nodes: list[Node],
    outputs: dict[str, str],
    *,
    candidate_phrases: list[str] | None = None,
    confirmation_phrases: list[str] | None = None,
    confirmation_targets: list[dict[str, Any]] | None = None,
    padding_fraction: float = 1.0,
    crop_long_side: int = 640,
    frame_ref: str | None = None,
    enabled: bool = True,
) -> tuple[list[Node], dict[str, str]]:
    """Compose or remove explicit recall-candidate context confirmation atoms.

    Tiling remains a recall strategy. This optional branch verifies selected
    candidate phrases on a padded crop and reconnects only corroborated
    candidates, while leaving every operator visible in the SkillPackage.
    """

    existing_index = next(
        (index for index, item in enumerate(nodes)
         if item["id"] == "context_confirmation_candidates"),
        None,
    )
    downstream_ids = {
        item["id"]
        for index, item in enumerate(nodes)
        if existing_index is not None
        and index >= existing_index
        and _contains_reference(item.get("inputs", {}), "$context_confirmation_deduplicated")
    }
    clean_nodes, clean_outputs = _remove_context_confirmation(nodes, outputs)
    if not enabled:
        return clean_nodes, clean_outputs
    if not candidate_phrases:
        raise ValueError("candidate_phrases is required when confirmation is enabled")
    targets = confirmation_targets or [{
        "label": "二次可见性确认",
        "phrases": confirmation_phrases or [],
    }]
    if not all(item.get("phrases") for item in targets):
        raise ValueError("confirmation_phrases is required when confirmation is enabled")
    if not 0.0 <= padding_fraction <= 1.0:
        raise ValueError("padding_fraction must be between 0 and 1")

    resolved_frame_ref = frame_ref or next(
        (f"${item['id']}" for item in clean_nodes if item["op"].startswith("image.resize@")),
        None,
    )
    if not resolved_frame_ref:
        raise ValueError("context confirmation requires an image.resize node")
    draw = next((item for item in clean_nodes if item["op"] == "output.draw@1.0"), None)
    if draw is None:
        raise ValueError("context confirmation requires an output.draw node")

    # Reapply at the old branch position so downstream counters/events remain
    # after the confirmed result. A first-time branch is placed before draw.
    insert_at = (
        min(existing_index, clean_nodes.index(draw))
        if existing_index is not None
        else clean_nodes.index(draw)
    )
    current_ref = clean_outputs["objects"]
    prefix = "context_confirmation"
    branch = [
        node(f"{prefix}_candidates", "objects.filter_by_phrase@1.0", {"objects": current_ref}, {"phrases": candidate_phrases, "mode": "include"}),
        node(f"{prefix}_unverified", "objects.filter_by_phrase@1.0", {"objects": current_ref}, {"phrases": candidate_phrases, "mode": "exclude"}),
        node(f"{prefix}_crops", "object.crop@1.0", {"frames": resolved_frame_ref, "objects": f"${prefix}_candidates"}, {"padding_fraction": padding_fraction, "subject_region": [0.0, 0.0, 1.0, 1.0]}),
        node(f"{prefix}_crop_resized", "image.resize@1.1", {"frames": f"${prefix}_crops"}, {"mode": "long_side", "long_side": int(crop_long_side)}),
        node(f"{prefix}_evidence_raw", "rex.ground@1.1", {"frames": f"${prefix}_crop_resized"}, {"targets": targets}),
        node(f"{prefix}_evidence", "objects.deduplicate@1.0", {"objects": f"${prefix}_evidence_raw"}, {"metric": "ios", "threshold": 0.5, "keep": "first"}),
        node(f"{prefix}_matches", "spatial.associate@1.0", {"subjects": f"${prefix}_candidates", "objects": f"${prefix}_evidence"}, {"relation": "source_entity", "threshold": 0.0}),
        node(f"{prefix}_confirmed", "filter.apply@1.0", {"objects": f"${prefix}_candidates", "condition": f"${prefix}_matches"}, {}),
        node(f"{prefix}_merged", "objects.merge@1.0", {"objects": [f"${prefix}_unverified", f"${prefix}_confirmed"]}, {}),
        node(f"{prefix}_deduplicated", "objects.deduplicate@1.0", {"objects": f"${prefix}_merged"}, {"metric": "ios", "threshold": 0.5, "keep": "first"}),
    ]
    clean_nodes[insert_at:insert_at] = branch
    final_ref = f"${prefix}_deduplicated"
    draw["inputs"]["objects"] = final_ref
    for item in clean_nodes:
        if item["id"] in downstream_ids and item["id"] != "draw":
            item["inputs"] = _replace_reference(
                item.get("inputs", {}), current_ref, final_ref
            )
    clean_outputs["objects"] = final_ref
    return clean_nodes, clean_outputs


@dataclass
class VariantDraft:
    nodes: list[Node]
    outputs: dict[str, str]
    bindings_by_span: dict[str, list[str]]
    configuration_slots: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class PresetDefinition:
    preset_id: str
    file_name: str
    skill_id: str
    display_name: str
    instruction: str
    media: tuple[str, ...]
    ledger: dict[str, Any]
    builder: Callable[[str], VariantDraft]


def node(
    node_id: str,
    op: str,
    inputs: dict[str, str | list[str]] | None = None,
    params: dict[str, Any] | None = None,
) -> Node:
    return {
        "id": node_id,
        "op": op,
        "inputs": inputs or {},
        "params": params or {},
    }


def start_nodes(
    media_type: str,
    *,
    tile: bool = False,
    tile_include_full_frame: bool = True,
    tile_params: dict[str, Any] | None = None,
):
    if media_type == "image":
        nodes = [
            node("media", "media.image@1.0", {"media": "$input"}),
            node(
                "resized",
                "image.resize@1.1",
                {"frames": "$media"},
                {"mode": "long_side", "long_side": 1280},
            ),
        ]
    elif media_type == "video":
        nodes = [
            node("media", "media.video@1.0", {"media": "$input"}),
            node(
                "frames",
                "video.sample@1.1",
                {"video": "$media"},
                {"mode": "fps", "fps": 1.0},
            ),
            node(
                "resized",
                "image.resize@1.1",
                {"frames": "$frames"},
                {"mode": "long_side", "long_side": 1280},
            ),
        ]
    else:
        raise ValueError(f"unsupported media type: {media_type}")

    detection_frames = "$resized"
    if tile:
        tile_settings = {
            "tile_width": 640,
            "tile_height": 640,
            "overlap_x": 0.2,
            "overlap_y": 0.2,
            "include_full_frame": tile_include_full_frame,
        }
        tile_settings.update(tile_params or {})
        nodes.append(node(
            "tiles",
            "image.tile@1.1",
            {"frames": "$resized"},
            tile_settings,
        ))
        detection_frames = "$tiles"
    return nodes, "$resized", detection_frames


def append_grounding(
    nodes: list[Node],
    node_id: str,
    frames_ref: str,
    targets: list[dict[str, Any]],
    *,
    metric: str = "ios",
    threshold: float = 0.5,
) -> tuple[str, list[str]]:
    raw_id = f"{node_id}_raw"
    nodes.extend([
        node(
            raw_id,
            "rex.ground@1.1",
            {"frames": frames_ref},
            {"targets": targets},
        ),
        node(
            node_id,
            "objects.deduplicate@1.0",
            {"objects": f"${raw_id}"},
            {"metric": metric, "threshold": threshold, "keep": "first"},
        ),
    ])
    return f"${node_id}", [raw_id, node_id]


def draw_outputs(
    nodes: list[Node],
    frames_ref: str,
    objects_ref: str,
    *,
    events_ref: str | None = None,
    regions_ref: str | None = None,
    directions_ref: str | None = None,
) -> dict[str, str]:
    inputs: dict[str, str] = {"frames": frames_ref, "objects": objects_ref}
    if events_ref:
        inputs["events"] = events_ref
    if regions_ref:
        inputs["regions"] = regions_ref
    if directions_ref:
        inputs["directions"] = directions_ref
    nodes.append(node(
        "draw",
        "output.draw@1.0",
        inputs,
        {"show_labels": True, "show_track_id": True},
    ))
    outputs = {"media": "$draw", "objects": objects_ref}
    if events_ref:
        outputs["events"] = events_ref
    if regions_ref:
        outputs["regions"] = regions_ref
    if directions_ref:
        outputs["directions"] = directions_ref
    return outputs


def add_final_count(
    draft: VariantDraft,
    media_type: str,
    *,
    count_id: str = "count",
    group_by: str = "none",
) -> VariantDraft:
    """Publish a count derived from the same final entities as the result boxes.

    Images count the final objects in the frame. Videos count the final stable
    tracks when available, avoiding accidental accumulation of per-frame boxes.
    """

    nodes = draft.nodes
    draw = next(item for item in nodes if item["op"] == "output.draw@1.0")
    insert_at = nodes.index(draw)
    if media_type == "video" and "tracks" in draft.outputs:
        entities_ref = draft.outputs["tracks"]
        scope = "unique"
    else:
        entities_ref = draft.outputs["objects"]
        scope = "frame"
    nodes.insert(
        insert_at,
        node(
            count_id,
            "measure.count@1.0",
            {"entities": entities_ref},
            {"scope": scope, "group_by": group_by},
        ),
    )
    draw["inputs"]["measurements"] = f"${count_id}"
    draft.outputs["measurements"] = f"${count_id}"
    return VariantDraft(
        nodes,
        draft.outputs,
        draft.bindings_by_span,
        draft.configuration_slots,
    )


def add_context_confirmation(
    draft: VariantDraft,
    *,
    candidate_phrases: list[str],
    confirmation_targets: list[dict[str, Any]],
    padding_fraction: float = 1.0,
    crop_long_side: int = 640,
) -> VariantDraft:
    """Add an explicit crop-and-ground confirmation branch for selected phrases.

    The slice detector remains the recall stage. Only the selected candidate
    phrases are cropped with context and re-grounded; the confirmed branch is
    merged back with candidates that do not require this extra check.
    """

    nodes, outputs = apply_context_confirmation(
        draft.nodes,
        draft.outputs,
        candidate_phrases=candidate_phrases,
        confirmation_targets=confirmation_targets,
        padding_fraction=padding_fraction,
        crop_long_side=crop_long_side,
    )
    return VariantDraft(
        nodes,
        outputs,
        draft.bindings_by_span,
        draft.configuration_slots,
    )


def ledger(
    target: str,
    source_span: str,
    phrases: list[str],
    constraints: list[dict[str, Any]] | None = None,
    *,
    mode: str = "entity_query",
    logic: str = "all",
    classes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "target": {
            "concept": target,
            "source_span": source_span,
            "phrases": phrases,
            "classes": classes or [],
        },
        "constraints": constraints or [],
        "logic": logic,
        "unresolved": [],
    }


def constraint(
    kind: str,
    value: Any,
    source_span: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "value": value,
        "source_span": source_span,
        **extra,
    }


def visible_builder(
    node_id: str,
    targets: list[dict[str, Any]],
    *,
    alert_label: str | None = None,
    tile: bool = False,
    tile_include_full_frame: bool = True,
    tile_params: dict[str, Any] | None = None,
    dedup_metric: str = "ios",
    dedup_threshold: float = 0.5,
    bindings_by_span: dict[str, list[str]] | None = None,
) -> Callable[[str], VariantDraft]:
    def build(media_type: str) -> VariantDraft:
        nodes, display_frames, detection_frames = start_nodes(
            media_type,
            tile=tile,
            tile_include_full_frame=tile_include_full_frame,
            tile_params=tile_params,
        )
        objects_ref, ground_nodes = append_grounding(
            nodes,
            node_id,
            detection_frames,
            targets,
            metric=dedup_metric,
            threshold=dedup_threshold,
        )
        events_ref = None
        if media_type == "video" and alert_label:
            nodes.extend([
                node(
                    "count", "measure.count@1.0",
                    {"entities": objects_ref}, {"scope": "frame"},
                ),
                node(
                    "present",
                    "logic.compare@1.0",
                    {"left": "$count"},
                    {"operator": ">", "value": 0},
                ),
                node(
                    "events",
                    "temporal.persist@1.0",
                    {"condition": "$present"},
                    {
                        "seconds": 1.0,
                        "scope": "global",
                        "gap_tolerance_seconds": 0.6,
                    },
                ),
                node(
                    "alerts",
                    "output.alert@1.0",
                    {"events": "$events"},
                    {"label": alert_label},
                ),
            ])
            events_ref = "$alerts"
        span_bindings = {
            span: list(bound)
            for span, bound in (bindings_by_span or {}).items()
        }
        for span, bound in span_bindings.items():
            if bound == ["__grounding__"]:
                span_bindings[span] = list(ground_nodes)
        return VariantDraft(
            nodes,
            draw_outputs(
                nodes,
                display_frames,
                objects_ref,
                events_ref=events_ref,
            ),
            span_bindings,
        )

    return build


def visually_validated_builder(
    node_id: str,
    targets: list[dict[str, Any]],
    evidence_rules: list[dict[str, Any]],
    *,
    alert_label: str | None = None,
) -> Callable[[str], VariantDraft]:
    """Build a reusable grounding -> deterministic evidence -> filter workflow."""

    def build(media_type: str) -> VariantDraft:
        nodes, display_frames, detection_frames = start_nodes(media_type)
        candidates_ref, _ = append_grounding(
            nodes, node_id, detection_frames, targets
        )
        condition_refs = []
        for rule in evidence_rules:
            evidence_id = f"{node_id}_{rule['color']}_evidence"
            nodes.append(node(
                evidence_id,
                "visual.color_fraction@1.0",
                {"frames": display_frames, "objects": candidates_ref},
                dict(rule),
            ))
            condition_refs.append(f"${evidence_id}")
        combined_id = f"{node_id}_evidence"
        validated_id = f"{node_id}_validated"
        nodes.extend([
            node(
                combined_id,
                "logic.any@1.0",
                {"conditions": condition_refs},
            ),
            node(
                validated_id,
                "filter.apply@1.0",
                {
                    "objects": candidates_ref,
                    "condition": f"${combined_id}",
                },
            ),
        ])
        objects_ref = f"${validated_id}"
        events_ref = None
        if media_type == "video" and alert_label:
            nodes.extend([
                node(
                    "count", "measure.count@1.0",
                    {"entities": objects_ref}, {"scope": "frame"},
                ),
                node(
                    "present",
                    "logic.compare@1.0",
                    {"left": "$count"},
                    {"operator": ">", "value": 0},
                ),
                node(
                    "events",
                    "temporal.persist@1.0",
                    {"condition": "$present"},
                    {
                        "seconds": 1.0,
                        "scope": "global",
                        "gap_tolerance_seconds": 0.6,
                    },
                ),
                node(
                    "alerts",
                    "output.alert@1.0",
                    {"events": "$events"},
                    {"label": alert_label},
                ),
            ])
            events_ref = "$alerts"
        return VariantDraft(
            nodes,
            draw_outputs(
                nodes,
                display_frames,
                objects_ref,
                events_ref=events_ref,
            ),
            {},
        )

    return build


def geometry_validated_builder(
    node_id: str,
    targets: list[dict[str, Any]],
    geometry_params: dict[str, Any],
    *,
    tile: bool = False,
    bindings_by_span: dict[str, list[str]] | None = None,
) -> Callable[[str], VariantDraft]:
    """Build reusable grounding -> deterministic box geometry -> filtering."""

    def build(media_type: str) -> VariantDraft:
        nodes, display_frames, detection_frames = start_nodes(
            media_type, tile=tile
        )
        candidates_ref, ground_nodes = append_grounding(
            nodes, node_id, detection_frames, targets
        )
        condition_id = f"{node_id}_local"
        validated_id = f"{node_id}_validated"
        nodes.extend([
            node(
                condition_id,
                "visual.geometry@1.0",
                {"objects": candidates_ref},
                geometry_params,
            ),
            node(
                validated_id,
                "filter.apply@1.0",
                {
                    "objects": candidates_ref,
                    "condition": f"${condition_id}",
                },
            ),
        ])
        span_bindings = {
            span: list(bound)
            for span, bound in (bindings_by_span or {}).items()
        }
        for span, bound in span_bindings.items():
            if bound == ["__grounding__"]:
                span_bindings[span] = [
                    *ground_nodes, condition_id, validated_id
                ]
        return VariantDraft(
            nodes,
            draw_outputs(nodes, display_frames, f"${validated_id}"),
            span_bindings,
        )

    return build


def exclude_visible_evidence(
    builder: Callable[[str], VariantDraft],
    exclusions: list[dict[str, Any]],
    *,
    association_relation: str = "overlap",
    association_threshold: float = 0.5,
) -> Callable[[str], VariantDraft]:
    """Compose affirmative visible exclusion evidence onto any ObjectSet draft."""

    def build(media_type: str) -> VariantDraft:
        draft = builder(media_type)
        nodes = draft.nodes
        draw = next(node for node in nodes if node["op"] == "output.draw@1.0")
        insert_at = nodes.index(draw)
        resize = next(
            node for node in nodes if node["op"] == "image.resize@1.1"
            and node["id"] == "resized"
        )
        current_ref = draft.outputs["objects"]
        bound_by_span: dict[str, list[str]] = {}
        for index, exclusion in enumerate(exclusions, start=1):
            prefix = f"{exclusion.get('id', 'visible')}_exclusion_{index}"
            extra: list[Node] = []
            excluded_ref, ground_nodes = append_grounding(
                extra,
                f"{prefix}_exclusion",
                f"${resize['id']}",
                [exclusion["target"]],
            )
            match_id = f"{prefix}_matches"
            not_id = f"{prefix}_not"
            filtered_id = f"{prefix}_filtered"
            extra.extend([
                node(
                    match_id,
                    "spatial.associate@1.0",
                    {"subjects": current_ref, "objects": excluded_ref},
                    {
                        "relation": association_relation,
                        "threshold": association_threshold,
                        "subject_region": [0.0, 0.0, 1.0, 1.0],
                        "same_source_only": False,
                    },
                ),
                node(not_id, "logic.not@1.0", {"condition": f"${match_id}"}),
                node(
                    filtered_id,
                    "filter.apply@1.0",
                    {"objects": current_ref, "condition": f"${not_id}"},
                ),
            ])
            nodes[insert_at:insert_at] = extra
            insert_at += len(extra)
            current_ref = f"${filtered_id}"
            span = exclusion.get("source_span")
            if span:
                bound_by_span.setdefault(span, []).extend([
                    *ground_nodes, match_id, not_id, filtered_id
                ])
        draw["inputs"]["objects"] = current_ref
        draft.outputs["objects"] = current_ref
        draft.bindings_by_span.update(bound_by_span)
        return VariantDraft(
            nodes,
            draft.outputs,
            draft.bindings_by_span,
            draft.configuration_slots,
        )

    return build


def disambiguate_category_by_visible_evidence(
    builder: Callable[[str], VariantDraft],
    *,
    candidate_labels: list[str],
    evidence_target: dict[str, Any],
    relation: str = "mutual_match",
    threshold: float = 0.45,
) -> Callable[[str], VariantDraft]:
    """Replace a visually conflicting category with explicit evidence.

    The reusable pattern is: select one output category, independently ground
    the alternative visible evidence, remove only same-object conflicts, then
    merge the unaffected candidates and the evidence category back together.
    It is deliberately a visible DAG template rather than a runtime fallback.
    """

    def build(media_type: str) -> VariantDraft:
        draft = builder(media_type)
        nodes = draft.nodes
        draw = next(item for item in nodes if item["op"] == "output.draw@1.0")
        insert_at = nodes.index(draw)
        resize = next(
            item for item in nodes
            if item["op"] == "image.resize@1.1" and item["id"] == "resized"
        )
        current_ref = draft.outputs["objects"]
        prefix = "garbage_category_1"
        container_branch: list[Node] = []
        container_ref, _ = append_grounding(
            container_branch, f"{prefix}_container", f"${resize['id']}", [evidence_target]
        )
        merged_id = f"{prefix}_merged"
        deduplicated_id = f"{prefix}_deduplicated"
        branch = [
            node(
                f"{prefix}_candidates", "objects.filter_by_label@1.0",
                {"objects": current_ref},
                {"labels": candidate_labels, "mode": "include"},
            ),
            node(
                f"{prefix}_remainder", "objects.filter_by_label@1.0",
                {"objects": current_ref},
                {"labels": candidate_labels, "mode": "exclude"},
            ),
            *container_branch,
            node(
                f"{prefix}_matches", "spatial.associate@1.0",
                {
                    "subjects": f"${prefix}_candidates",
                    "objects": container_ref,
                },
                {
                    "relation": relation,
                    "threshold": threshold,
                    "subject_region": [0.0, 0.0, 1.0, 1.0],
                    "same_source_only": False,
                },
            ),
            node(f"{prefix}_not", "logic.not@1.0", {"condition": f"${prefix}_matches"}),
            node(
                f"{prefix}_filtered", "filter.apply@1.0",
                {
                    "objects": f"${prefix}_candidates",
                    "condition": f"${prefix}_not",
                },
            ),
            node(
                merged_id, "objects.merge@1.0",
                {
                    "objects": [
                        f"${prefix}_remainder",
                        f"${prefix}_filtered",
                        container_ref,
                    ],
                },
            ),
            node(
                deduplicated_id, "objects.deduplicate@1.0",
                {"objects": f"${merged_id}"},
                {"metric": "ios", "threshold": 0.5, "keep": "first"},
            ),
        ]
        nodes[insert_at:insert_at] = branch
        final_ref = f"${deduplicated_id}"
        draw["inputs"]["objects"] = final_ref
        draft.outputs["objects"] = final_ref
        return VariantDraft(
            nodes,
            draft.outputs,
            draft.bindings_by_span,
            draft.configuration_slots,
        )

    return build


def build_package(
    definition: PresetDefinition,
    *,
    registry: OperatorRegistry | None = None,
) -> SkillPackage:
    registry = registry or build_default_registry()
    semantic_ir = SemanticNormalizer().normalize_ledger(
        definition.ledger,
        definition.instruction,
    )
    variants: dict[str, Any] = {}
    for media_type in definition.media:
        draft = definition.builder(media_type)
        atom_bindings: dict[str, list[str]] = {}
        for item in semantic_ir.constraints:
            bound = draft.bindings_by_span.get(item.source_span)
            if not bound:
                raise ValueError(
                    f"{definition.preset_id}/{media_type}: no nodes bind {item.source_span}"
                )
            atom_bindings[item.atom_id or ""] = bound
        variants[media_type] = {
            "media_type": media_type,
            "status": "executable",
            "nodes": draft.nodes,
            "outputs": draft.outputs,
            "atom_bindings": atom_bindings,
            "configuration_slots": draft.configuration_slots or [],
        }

    package = SkillPackage.model_validate({
        "schema_version": "2.0",
        "skill_id": definition.skill_id,
        "version": 1,
        "display_name": definition.display_name,
        "original_instruction": definition.instruction,
        "compile_status": "compiled",
        "input": {
            "requested_accept": list(definition.media),
            "accept": list(definition.media),
            "video_guidance": {
                "recommended_max_duration_seconds": 30,
                "enforcement": "warn_only",
            },
        },
        "semantic_ir": semantic_ir.model_dump(mode="json"),
        "variants": variants,
        "compatibility_issues": [],
    })
    assert_valid_skill_package(package, registry)
    return package


def write_packages(
    definitions: list[PresetDefinition],
    output_dir: Path,
    *,
    registry: OperatorRegistry | None = None,
) -> list[Path]:
    registry = registry or build_default_registry()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for definition in definitions:
        package = build_package(definition, registry=registry)
        path = output_dir / definition.file_name
        path.write_text(
            package.model_dump_json(indent=2),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


__all__ = [
    "PresetDefinition",
    "VariantDraft",
    "append_grounding",
    "add_final_count",
    "add_context_confirmation",
    "build_package",
    "constraint",
    "draw_outputs",
    "disambiguate_category_by_visible_evidence",
    "geometry_validated_builder",
    "ledger",
    "node",
    "start_nodes",
    "visible_builder",
    "visually_validated_builder",
    "write_packages",
    "exclude_visible_evidence",
]
