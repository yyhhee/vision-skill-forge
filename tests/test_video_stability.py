from __future__ import annotations

from core.preset_definitions import build_preset_definitions
from core.preset_factory import build_package, visible_builder
from core.registry import build_default_registry
from core.video_stability import add_video_track_confirmation
from core.video_stability import confirm_variant_objects


def test_video_track_confirmation_is_explicit_reusable_package_transform():
    registry = build_default_registry()
    definition = next(
        item for item in build_preset_definitions()
        if item.skill_id == "traffic_accident"
    )
    package = build_package(definition, registry=registry)

    updated = add_video_track_confirmation(
        package,
        registry,
        objects_ref="$traffic_accident",
    )
    variant = updated.variants["video"]
    nodes = {node.id: node for node in variant.nodes}

    assert nodes["result_tracks"].inputs == {"objects": "$traffic_accident"}
    assert nodes["confirmed_tracks"].params == {
        "min_hits": 2,
        "min_span_seconds": 0.5,
    }
    assert nodes["confirmed_objects"].params == {"selection": "all"}
    assert nodes["draw"].inputs["objects"] == "$confirmed_tracks"
    assert variant.outputs["objects"] == "$confirmed_objects"
    assert variant.outputs["tracks"] == "$confirmed_tracks"
    assert package.variants["video"].outputs["objects"] == "$traffic_accident"


def test_variant_level_confirmation_reuses_the_same_atoms_before_draw():
    draft = visible_builder(
        "sample", [{"label": "目标", "phrases": ["object"]}]
    )("video")

    updated = confirm_variant_objects(draft)
    nodes = {node["id"]: node for node in updated.nodes}

    assert nodes["result_tracks"]["inputs"] == {"objects": "$sample"}
    assert nodes["confirmed_tracks"]["op"] == "track.confirm@1.0"
    assert nodes["confirmed_objects"]["op"] == "objects.from_tracks@1.0"
    assert nodes["draw"]["inputs"]["objects"] == "$confirmed_tracks"
    assert updated.outputs["objects"] == "$confirmed_objects"
    assert updated.outputs["tracks"] == "$confirmed_tracks"


def test_selected_preset_builders_apply_confirmation_only_to_video_results():
    definitions = {
        item.skill_id: item for item in build_preset_definitions()
    }

    for skill_id in ("road_debris", "no_helmet"):
        image_ops = [
            node["op"] for node in definitions[skill_id].builder("image").nodes
        ]
        video_ops = [
            node["op"] for node in definitions[skill_id].builder("video").nodes
        ]
        assert "track.confirm@1.0" not in image_ops
        assert "track.confirm@1.0" in video_ops
