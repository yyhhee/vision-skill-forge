from __future__ import annotations

from .preset_factory import (
    VariantDraft,
    append_grounding,
    draw_outputs,
    node,
    start_nodes,
)
from .preset_workflows import PERSON_TARGETS


def person_fall_builder(media_type: str) -> VariantDraft:
    if media_type != "video":
        raise ValueError("fall detection requires video")
    nodes, frames, detection_frames = start_nodes(media_type)
    people, _ = append_grounding(
        nodes, "people", detection_frames, PERSON_TARGETS
    )
    fallen, fallen_nodes = append_grounding(
        nodes,
        "fallen_people",
        detection_frames,
        [{
            "label": "倒地人员",
            "phrases": [
                "person lying on the ground",
            ],
        }],
    )
    nodes.extend([
        node(
            "tracks",
            "track.iou@1.0",
            {"objects": people},
            {
                "iou_threshold": 0.2,
                "max_missing_frames": 2,
                "same_label_only": True,
            },
        ),
        node(
            "fallen_state",
            "spatial.associate@1.0",
            {"subjects": "$tracks", "objects": fallen},
            {
                "relation": "overlap",
                "threshold": 0.3,
                "subject_region": [0.0, 0.0, 1.0, 1.0],
            },
        ),
        node(
            "fallen_pose_geometry",
            "visual.geometry@1.0",
            {"objects": "$tracks"},
            {
                "dimension": "aspect_ratio",
                "value": "horizontal",
                "aspect_ratio_threshold": 0.6,
            },
        ),
        node(
            "fallen_qualified",
            "logic.all@1.0",
            {
                "conditions": ["$fallen_state", "$fallen_pose_geometry"]
            },
            {},
        ),
        node(
            "events",
            "temporal.persist@1.0",
            {"condition": "$fallen_qualified"},
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
    return VariantDraft(
        nodes,
        draw_outputs(nodes, frames, "$tracks", events_ref="$alerts"),
        {
            "出现摔倒或躺在地面上的可见姿态": fallen_nodes + [
                "tracks", "fallen_state", "fallen_pose_geometry",
                "fallen_qualified",
            ],
            "持续1秒": ["fallen_qualified", "events", "alerts"],
        },
    )


__all__ = ["person_fall_builder"]
