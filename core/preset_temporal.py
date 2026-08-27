from __future__ import annotations

from .preset_factory import (
    VariantDraft,
    append_grounding,
    draw_outputs,
    node,
    start_nodes,
)
def person_fall_builder(media_type: str) -> VariantDraft:
    if media_type != "video":
        raise ValueError("fall detection requires video")
    nodes, frames, detection_frames = start_nodes(media_type)
    fallen, fallen_nodes = append_grounding(
        nodes,
        "fallen_people",
        detection_frames,
        [{
            "label": "摔倒人员",
            "phrases": [
                "person actively falling toward the ground",
                "person losing balance and collapsing",
                "person bent low while falling",
                "person lying on the ground",
            ],
        }],
    )
    nodes.extend([
        node(
            "tracks",
            "track.iou@1.0",
            {"objects": fallen},
            {
                "iou_threshold": 0.2,
                "max_missing_frames": 2,
                "same_label_only": True,
            },
        ),
        node("fallen_present", "reduce.exists@1.0", {"sets": "$tracks"}, {"scope": "entity"}),
        node(
            "events",
            "temporal.persist@1.0",
            {"condition": "$fallen_present"},
            {
                "seconds": 1.0,
                "scope": "track",
                "gap_tolerance_seconds": 0.6,
            },
        ),
        node(
            "alerts",
            "output.alert@1.0",
            {"events": "$events"},
            {"label": "人员摔倒"},
        ),
    ])
    outputs = draw_outputs(nodes, frames, "$tracks", events_ref="$alerts")
    outputs["tracks"] = "$tracks"
    draw = next(item for item in nodes if item["id"] == "draw")
    draw["params"]["event_time_window"] = "track_history"
    return VariantDraft(
        nodes,
        outputs,
        {
            "出现摔倒或躺在地面上的可见姿态": fallen_nodes + ["tracks", "fallen_present"],
            "持续1秒": ["fallen_present", "events", "alerts"],
        },
    )


__all__ = ["person_fall_builder"]
