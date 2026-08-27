from __future__ import annotations

from copy import deepcopy
from typing import Any

from .editor_schema import ResultSpec, TriggerPolicy
from .registry import OperatorRegistry


def _node_id(reference: str) -> str:
    return reference[1:] if reference.startswith("$") else reference


def _fresh_id(nodes: list[dict[str, Any]], base: str) -> str:
    used = {item["id"] for item in nodes}
    if base not in used:
        return base
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"


def compile_result_visualization(
    nodes: list[dict[str, Any]],
    outputs: dict[str, str],
    result_specs: list[ResultSpec],
    trigger_policy: TriggerPolicy | None,
    registry: OperatorRegistry,
    *,
    frames_ref: str | None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Add one generic annotated-media output from semantic result sources.

    The renderer never decides business meaning. It only receives nodes already
    selected by ResultSpec or deterministic fallbacks and therefore cannot
    change conditions, labels, counts, events, or evidence ownership.
    """

    compiled_nodes = deepcopy(nodes)
    compiled_outputs = dict(outputs)
    node_types = {
        item["id"]: registry.require(item["op"]).output_type
        for item in compiled_nodes
    }
    rendered = [
        (name, _node_id(reference))
        for name, reference in compiled_outputs.items()
        if node_types.get(_node_id(reference)) == "RenderedMedia"
    ]
    if rendered:
        compiled_outputs.setdefault("media", f"${rendered[0][1]}")
        return compiled_nodes, compiled_outputs

    requested_media = any(
        spec.semantic_type == "media" and spec.source_ref is not None
        for spec in result_specs
    ) or bool(
        trigger_policy and "annotated_media" in trigger_policy.outputs
    )
    business_projection = any(
        (spec.source_ref or "").startswith(
            ("final:", "branch:", "condition:", "event:", "measurement:", "result:")
        )
        for spec in result_specs
    )
    if not requested_media and not business_projection:
        return compiled_nodes, compiled_outputs

    if frames_ref is None:
        frames_ref = next(
            (
                f"${item['id']}"
                for item in reversed(compiled_nodes)
                if node_types.get(item["id"]) == "FrameSet"
            ),
            None,
        )
    if frames_ref is None:
        return compiled_nodes, compiled_outputs

    requested_output_names = {
        output_name
        for spec in result_specs
        for output_name in spec.required_outputs
    }
    requested_nodes = [
        _node_id(compiled_outputs[name])
        for name in requested_output_names
        if name in compiled_outputs
    ]

    def candidates(*output_types: str) -> list[str]:
        accepted = set(output_types)
        selected = [
            node_id
            for node_id in requested_nodes
            if node_types.get(node_id) in accepted
        ]
        if selected:
            return list(dict.fromkeys(selected))
        # A decision-only skill still needs useful visual evidence. Prefer the
        # latest typed value, which is the most reduced business result.
        fallback = [
            item["id"]
            for item in compiled_nodes
            if node_types.get(item["id"]) in accepted
        ]
        return fallback[-1:] if fallback else []

    draw_inputs: dict[str, Any] = {"frames": frames_ref}
    # output.draw accepts the EntitySet family.  Filter/join operators return
    # EntitySet while raw grounding returns ObjectSet; excluding the former
    # made visualization silently fall back to every raw detection.
    object_nodes = candidates("ObjectSet", "EntitySet")
    if not object_nodes:
        track_nodes = candidates("TrackSet")
        for track_node in track_nodes:
            object_id = _fresh_id(compiled_nodes, "result_track_boxes")
            compiled_nodes.append(
                {
                    "id": object_id,
                    "op": "objects.from_tracks@1.0",
                    "inputs": {"tracks": f"${track_node}"},
                    "params": {"selection": "all"},
                }
            )
            node_types[object_id] = "ObjectSet"
            object_nodes.append(object_id)
    if len(object_nodes) == 1:
        draw_inputs["objects"] = f"${object_nodes[0]}"
    elif object_nodes:
        merge_id = _fresh_id(compiled_nodes, "result_objects")
        compiled_nodes.append(
            {
                "id": merge_id,
                "op": "objects.merge@1.0",
                "inputs": {"objects": [f"${item}" for item in object_nodes]},
                "params": {},
            }
        )
        node_types[merge_id] = "ObjectSet"
        draw_inputs["objects"] = f"${merge_id}"

    event_nodes = [
        _node_id(reference)
        for name, reference in compiled_outputs.items()
        if node_types.get(_node_id(reference)) == "EventSet"
        and name.startswith(("alert_", "final_", "event_"))
    ] or candidates("EventSet")
    if event_nodes:
        draw_inputs["events"] = f"${event_nodes[0]}"

    region_nodes = candidates("RegionSet")
    if len(region_nodes) == 1:
        draw_inputs["regions"] = f"${region_nodes[0]}"
    elif region_nodes:
        merge_id = _fresh_id(compiled_nodes, "result_regions")
        compiled_nodes.append(
            {
                "id": merge_id,
                "op": "regions.merge@1.0",
                "inputs": {"regions": [f"${item}" for item in region_nodes]},
                "params": {},
            }
        )
        node_types[merge_id] = "RegionSet"
        draw_inputs["regions"] = f"${merge_id}"

    direction_nodes = candidates("VectorSet")
    if direction_nodes:
        draw_inputs["directions"] = f"${direction_nodes[0]}"
    measurement_nodes = candidates("ScalarSet")
    if measurement_nodes:
        draw_inputs["measurements"] = f"${measurement_nodes[0]}"

    if len(draw_inputs) == 1 and not requested_media:
        return compiled_nodes, compiled_outputs

    draw_id = _fresh_id(compiled_nodes, "result_draw")
    compiled_nodes.append(
        {
            "id": draw_id,
            "op": "output.draw@1.0",
            "inputs": draw_inputs,
            "params": {},
        }
    )
    compiled_outputs["media"] = f"${draw_id}"
    return compiled_nodes, compiled_outputs


__all__ = ["compile_result_visualization"]
