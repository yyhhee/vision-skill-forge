import pytest
from types import SimpleNamespace
from PIL import Image

from core.context import (
    ConditionSet,
    ObjectSet,
    Region,
    RegionSet,
    ScalarSet,
    TimedValue,
    Track,
    TrackSet,
    VisualObject,
)


def obj(
    object_id,
    bbox,
    frame=0,
    timestamp=0.0,
    track_id=None,
    source_entity_id=None,
):
    return VisualObject(
        id=object_id,
        label="target",
        phrase="target",
        bbox=bbox,
        frame_index=frame,
        timestamp=timestamp,
        source_node="test",
        track_id=track_id,
        source_entity_id=source_entity_id,
        original_size=(100, 100),
    )


def test_reduce_exists_can_preserve_track_identity_for_per_entity_persistence():
    from operators.reduce import reduce_exists

    first = obj("fall_0", (0.1, 0.1, 0.3, 0.7), frame=0, timestamp=0.0)
    second = obj("fall_1", (0.1, 0.2, 0.3, 0.8), frame=1, timestamp=1.0)
    tracks = TrackSet([Track("track_fall", "摔倒人员", [first, second])])

    present = reduce_exists(
        {"sets": tracks}, {"scope": "entity"}, None, "present"
    )

    assert [(item.key, item.timestamp, item.value) for item in present.items] == [
        ("track_fall", 0.0, True),
        ("track_fall", 1.0, True),
    ]


def test_manual_roi_and_inside_have_fixed_center_and_overlap_rules():
    from operators.region import region_manual
    from operators.spatial import spatial_inside

    region = region_manual(
        {},
        {"shape": "rectangle", "points": [[0.0, 0.0], [0.5, 1.0]]},
        None,
        "roi",
    )
    objects = ObjectSet(
        [
            obj("inside", (0.1, 0.1, 0.3, 0.3)),
            obj("boundary", (0.4, 0.1, 0.8, 0.3)),
            obj("outside", (0.6, 0.1, 0.9, 0.3)),
        ]
    )

    center = spatial_inside(
        {"objects": objects, "region": region},
        {"mode": "center", "overlap_threshold": 0.5},
        None,
        "center",
    )
    assert {item.key: item.value for item in center.items} == {
        "inside": True,
        "boundary": False,
        "outside": False,
    }
    overlap = spatial_inside(
        {"objects": objects, "region": region},
        {"mode": "overlap", "overlap_threshold": 0.2},
        None,
        "overlap",
    )
    assert {item.key: item.value for item in overlap.items}["boundary"] is True


def test_motion_consistent_tracking_does_not_reverse_into_a_neighbor_box():
    from operators.tracking import track_iou

    objects = ObjectSet([
        obj("a0", (0.10, 0.20, 0.30, 0.40), frame=0, timestamp=0.0),
        obj("b0", (0.50, 0.20, 0.70, 0.40), frame=0, timestamp=0.0),
        obj("a1", (0.15, 0.20, 0.35, 0.40), frame=1, timestamp=1.0),
        obj("b1", (0.45, 0.20, 0.65, 0.40), frame=1, timestamp=1.0),
        # Detector order deliberately presents the reversing neighbor first.
        obj("a2_wrong", (0.10, 0.20, 0.30, 0.40), frame=2, timestamp=2.0),
        obj("a2_forward", (0.20, 0.20, 0.40, 0.40), frame=2, timestamp=2.0),
        obj("b2", (0.40, 0.20, 0.60, 0.40), frame=2, timestamp=2.0),
    ])

    tracks = track_iou(
        {"objects": objects},
        {
            "iou_threshold": 0.3,
            "max_missing_frames": 0,
            "same_label_only": True,
            "motion_consistency": True,
            "motion_prediction": True,
            "min_direction_cosine": 0.0,
            "min_motion_pixels": 2.0,
        },
        None,
        "tracks",
    )

    first = next(track for track in tracks.items if track.history[0].id == "a0")
    assert [item.id for item in first.history] == ["a0", "a1", "a2_forward"]


def test_motion_consistency_keeps_established_direction_across_one_jitter_sample():
    from operators.tracking import track_iou

    objects = ObjectSet([
        obj("forward_0", (0.10, 0.20, 0.30, 0.40), frame=0, timestamp=0.0),
        obj("forward_1", (0.15, 0.20, 0.35, 0.40), frame=1, timestamp=0.5),
        # One almost-stationary sample must not erase the earlier rightward
        # direction before a neighboring box appears on the left.
        obj("jitter", (0.151, 0.20, 0.351, 0.40), frame=2, timestamp=1.0),
        obj("reverse_neighbor", (0.09, 0.20, 0.29, 0.40), frame=3, timestamp=1.5),
    ])

    tracks = track_iou(
        {"objects": objects},
        {
            "iou_threshold": 0.3,
            "max_missing_frames": 0,
            "same_label_only": True,
            "motion_consistency": True,
            "min_direction_cosine": 0.0,
            "min_motion_pixels": 2.0,
        },
        None,
        "tracks",
    )

    first = next(track for track in tracks.items if track.history[0].id == "forward_0")
    assert [item.id for item in first.history] == ["forward_0", "forward_1", "jitter"]
    assert any(
        [item.id for item in track.history] == ["reverse_neighbor"]
        for track in tracks.items
    )


def test_motion_prediction_keeps_fast_perspective_vehicle_in_one_track():
    from operators.tracking import track_iou

    objects = ObjectSet([
        obj("car_0", (0.20, 0.20, 0.32, 0.30), frame=0, timestamp=0.0),
        obj("car_1", (0.22, 0.22, 0.35, 0.33), frame=1, timestamp=0.5),
        # The vehicle approaches the camera: the current boxes have too little
        # IoU, but constant box-motion prediction still overlaps strongly.
        obj("car_2", (0.255, 0.255, 0.395, 0.375), frame=2, timestamp=1.0),
    ])

    tracks = track_iou(
        {"objects": objects},
        {
            "iou_threshold": 0.4,
            "max_missing_frames": 0,
            "same_label_only": True,
            "motion_consistency": True,
            "motion_prediction": True,
            "min_direction_cosine": 0.0,
            "min_motion_pixels": 2.0,
        },
        None,
        "tracks",
    )

    assert len(tracks.items) == 1
    assert [item.id for item in tracks.items[0].history] == [
        "car_0", "car_1", "car_2"
    ]


def test_heading_uses_box_scaled_threshold_for_far_small_target():
    from operators.measure import measure_heading
    from core.context import Track

    small = Track("small", "车辆", [
        obj("small_0", (0.10, 0.10, 0.12, 0.12), frame=0, timestamp=0.0),
        obj("small_1", (0.13, 0.10, 0.15, 0.12), frame=1, timestamp=0.5),
    ])
    result = measure_heading(
        {"tracks": TrackSet([small])},
        {
            "window_frames": 3,
            "min_displacement_pixels": 8.0,
            "min_displacement_box_ratio": 0.2,
        },
        None,
        "heading",
    )

    assert len(result.items) == 1


def test_far_wrong_way_track_qualifies_across_one_missing_sample():
    from core.context import VectorSet
    from operators.logic import logic_compare_heading_by_lane
    from operators.measure import measure_heading
    from operators.temporal import temporal_persist

    track = Track("far_car", "车辆", [
        obj("far_0", (0.10, 0.10, 0.30, 0.30), frame=0, timestamp=0.0),
        obj("far_1", (0.15, 0.10, 0.35, 0.30), frame=1, timestamp=0.5),
        # The 1.0 second sample is missing, matching one tolerated miss at 2 FPS.
        obj("far_3", (0.20, 0.10, 0.40, 0.30), frame=3, timestamp=1.5),
    ])
    tracks = TrackSet([track])
    lanes = RegionSet([
        Region("lane", [(0, 0), (1, 0), (1, 1), (0, 1)], "lane")
    ])
    references = VectorSet([
        TimedValue("lane", 0.0, (-1.0, 0.0), None)
    ])

    headings = measure_heading(
        {"tracks": tracks},
        {
            "window_frames": 3,
            "min_displacement_pixels": 8.0,
            "min_displacement_box_ratio": 0.15,
        },
        None,
        "headings",
    )
    opposite = logic_compare_heading_by_lane(
        {
            "tracks": tracks,
            "headings": headings,
            "lanes": lanes,
            "references": references,
        },
        {
            "threshold": -0.5,
            "membership_mode": "majority_center",
            "relation": "opposite",
            "scope_overrides": {},
        },
        None,
        "opposite",
    )
    events = temporal_persist(
        {"condition": opposite},
        {
            "seconds": 1.0,
            "scope": "track",
            "gap_tolerance_seconds": 1.1,
            "trigger_mode": "once",
            "scope_overrides": {},
            "override_scope_field": "region_id",
        },
        None,
        "events",
    )

    assert [(event.entity_id, event.start_time) for event in events.items] == [
        ("far_car", 1.5)
    ]


def test_regions_merge_preserves_every_configured_region():
    from operators.region import regions_merge

    first = RegionSet([
        Region("area_1", [(0, 0), (0.4, 0), (0.4, 1), (0, 1)], "区域1")
    ])
    second = RegionSet([
        Region("area_2", [(0.6, 0), (1, 0), (1, 1), (0.6, 1)], "区域2")
    ])

    merged = regions_merge(
        {"regions": [first, second]}, {}, None, "draw_regions"
    )

    assert [(region.id, region.label) for region in merged.items] == [
        ("area_1", "区域1"),
        ("area_2", "区域2"),
    ]


def test_associate_overlap_and_near_are_explicit_and_deterministic():
    from operators.spatial import spatial_associate

    subjects = ObjectSet([obj("person", (0.1, 0.1, 0.3, 0.4))])
    helmet = ObjectSet([obj("helmet", (0.15, 0.08, 0.24, 0.18))])

    overlap = spatial_associate(
        {"subjects": subjects, "objects": helmet},
        {"relation": "overlap", "threshold": 0.05},
        None,
        "associate",
    )
    assert overlap.items[0].key == "person"
    assert overlap.items[0].value is True
    near = spatial_associate(
        {"subjects": subjects, "objects": helmet},
        {"relation": "near", "threshold": 0.2},
        None,
        "near",
    )
    assert near.items[0].value is True


def test_phrase_group_filter_is_a_generic_explicit_object_partition():
    from operators.filtering import objects_filter_by_phrase

    objects = ObjectSet([
        VisualObject(
            id="bin", label="垃圾容器", phrase="trash bin",
            bbox=(0.1, 0.1, 0.2, 0.3), frame_index=0, timestamp=0.0,
            source_node="test", original_size=(100, 100),
        ),
        VisualObject(
            id="litter", label="散落垃圾", phrase="small litter",
            bbox=(0.4, 0.4, 0.45, 0.45), frame_index=0, timestamp=0.0,
            source_node="test", original_size=(100, 100),
        ),
    ])

    included = objects_filter_by_phrase(
        {"objects": objects},
        {"phrases": ["trash bin", "garbage container"], "mode": "include"},
        None,
        "bins",
    )
    excluded = objects_filter_by_phrase(
        {"objects": objects},
        {"phrases": ["trash bin", "garbage container"], "mode": "exclude"},
        None,
        "not_bins",
    )

    assert [item.id for item in included.items] == ["bin"]
    assert [item.id for item in excluded.items] == ["litter"]


def test_object_level_phrase_filter_projects_track_history_to_visual_objects():
    """EntitySet accepts tracks, but an ObjectSet output must contain boxes."""

    from operators.filtering import objects_filter_by_phrase

    first = obj("vehicle_1", (0.1, 0.1, 0.2, 0.2), frame=1)
    first.phrase = "vehicle"
    first.track_id = "track_1"
    second = obj("vehicle_2", (0.2, 0.2, 0.3, 0.3), frame=2)
    second.phrase = "vehicle"
    second.track_id = "track_1"
    tracks = TrackSet([Track("track_1", "target", [first, second])])

    selected = objects_filter_by_phrase(
        {"objects": tracks},
        {"phrases": ["vehicle"], "mode": "include"},
        None,
        "vehicles",
    )

    assert isinstance(selected, ObjectSet)
    assert [item.id for item in selected.items] == ["vehicle_1", "vehicle_2"]
    assert all(isinstance(item, VisualObject) for item in selected.items)


def test_object_merge_projects_mixed_entity_sets_without_track_pollution():
    from operators.objects import objects_merge

    sample = obj("vehicle_1", (0.1, 0.1, 0.2, 0.2), frame=1)
    sample.track_id = "track_1"
    merged = objects_merge(
        {
            "objects": [
                TrackSet([Track("track_1", "target", [sample])]),
                ObjectSet([obj("vehicle_2", (0.3, 0.3, 0.4, 0.4), frame=1)]),
            ]
        },
        {},
        None,
        "merged",
    )

    assert [item.id for item in merged.items] == ["vehicle_1", "vehicle_2"]
    assert all(isinstance(item, VisualObject) for item in merged.items)


def test_mutual_match_requires_same_instance_overlap_in_both_directions():
    from operators.spatial import spatial_associate

    subjects = ObjectSet([
        obj("person_a", (0.10, 0.10, 0.30, 0.50)),
        obj("person_b", (0.50, 0.10, 0.70, 0.50)),
    ])
    evidence = ObjectSet([
        # Near-identical whole-subject evidence for person_a.
        obj("pose_a", (0.11, 0.11, 0.29, 0.49)),
        # A small part inside person_b must not count as a whole-subject match.
        obj("helmet_b", (0.56, 0.11, 0.64, 0.18)),
    ])

    result = spatial_associate(
        {"subjects": subjects, "objects": evidence},
        {
            "relation": "mutual_match",
            "threshold": 0.5,
            "subject_region": [0.0, 0.0, 1.0, 1.0],
            "same_source_only": False,
        },
        None,
        "same_instance",
    )

    assert [(item.key, item.value) for item in result.items] == [
        ("person_a", True),
        ("person_b", False),
    ]


def test_associate_object_center_in_subject_head_region_separates_helmeted_workers():
    from operators.spatial import spatial_associate

    workers = ObjectSet([
        obj("helmeted", (0.1, 0.1, 0.5, 0.9)),
        obj("no_helmet", (0.6, 0.1, 0.9, 0.9)),
    ])
    helmets = ObjectSet([obj("helmet", (0.2, 0.12, 0.3, 0.22))])
    result = spatial_associate(
        {"subjects": workers, "objects": helmets},
        {
            "relation": "center_in_subject_region",
            "threshold": 0.0,
            "subject_region": [0.0, 0.0, 1.0, 0.35],
        },
        None,
        "has_helmet",
    )
    assert {item.key: item.value for item in result.items} == {
        "helmeted": True,
        "no_helmet": False,
    }


def test_entity_inside_and_contains_have_distinct_box_semantics():
    from operators.spatial import spatial_associate

    subjects = ObjectSet([
        obj("inner", (0.30, 0.30, 0.40, 0.40)),
        obj("outer", (0.10, 0.10, 0.90, 0.90)),
    ])
    references = ObjectSet([obj("reference", (0.20, 0.20, 0.60, 0.60))])
    inside = spatial_associate(
        {"subjects": subjects, "objects": references},
        {"relation": "inside", "threshold": 0.9, "subject_region": [0, 0, 1, 1]},
        None, "inside",
    )
    contains = spatial_associate(
        {"subjects": subjects, "objects": references},
        {"relation": "contains", "threshold": 0.9, "subject_region": [0, 0, 1, 1]},
        None, "contains",
    )
    assert [item.value for item in inside.items] == [True, False]
    assert [item.value for item in contains.items] == [False, True]


def test_best_owner_assigns_shared_carrier_to_most_covering_subject_only():
    from operators.spatial import spatial_associate

    people = ObjectSet([
        obj("owner", (0.10, 0.10, 0.60, 0.90)),
        obj("neighbor", (0.50, 0.10, 0.90, 0.90)),
    ])
    carrier = ObjectSet([obj("garment", (0.42, 0.30, 0.58, 0.60))])
    result = spatial_associate(
        {"subjects": people, "objects": carrier},
        {"relation": "best_owner", "threshold": 0.1,
         "subject_region": [0, 0, 1, 1]}, None, "ownership",
    )
    assert [item.value for item in result.items] == [True, False]


def test_source_entity_association_never_leaks_local_evidence_to_neighbor():
    from operators.spatial import spatial_associate

    people = ObjectSet([
        obj("owner", (0.10, 0.10, 0.60, 0.90)),
        obj("neighbor", (0.50, 0.10, 0.90, 0.90)),
    ])
    evidence = ObjectSet([
        obj(
            "local_helmet",
            (0.45, 0.10, 0.58, 0.25),
            source_entity_id="owner",
        )
    ])

    result = spatial_associate(
        {"subjects": people, "objects": evidence},
        {
            "relation": "source_entity",
            "threshold": 0.0,
            "subject_region": [0, 0, 1, 1],
        },
        None,
        "ownership",
    )

    assert {item.key: item.value for item in result.items} == {
        "owner": True,
        "neighbor": False,
    }


def test_subject_relative_region_can_extend_above_box_and_stay_source_local():
    from operators.spatial import spatial_associate

    people = ObjectSet([
        obj("owner", (0.2, 0.3, 0.6, 0.9)),
        obj("neighbor", (0.55, 0.3, 0.9, 0.9)),
    ])
    hooks = ObjectSet([
        obj("connected", (0.18, 0.12, 0.24, 0.20), source_entity_id="owner"),
        obj("dangling", (0.42, 0.55, 0.48, 0.68), source_entity_id="owner"),
        obj("other", (0.60, 0.15, 0.66, 0.22), source_entity_id="neighbor"),
    ])

    result = spatial_associate(
        {"subjects": people, "objects": hooks},
        {
            "relation": "center_in_subject_region",
            "threshold": 0.0,
            "subject_region": [-0.6, -0.6, 1.6, 0.0],
            "same_source_only": True,
        },
        None,
        "connected_hook",
    )

    assert {item.key: item.value for item in result.items} == {
        "owner": True,
        "neighbor": True,
    }


def test_subject_center_can_be_matched_to_another_objects_relative_region():
    from operators.spatial import spatial_associate

    overflow = ObjectSet([
        obj("above_bin", (0.40, 0.20, 0.50, 0.30)),
        obj("ground_litter", (0.40, 0.70, 0.50, 0.80)),
        obj("far_above", (0.75, 0.20, 0.85, 0.30)),
    ])
    containers = ObjectSet([
        obj("bin", (0.35, 0.30, 0.55, 0.80)),
    ])

    result = spatial_associate(
        {"subjects": overflow, "objects": containers},
        {
            "relation": "center_in_object_region",
            "threshold": 0.0,
            "subject_region": [0.0, 0.0, 1.0, 1.0],
            "object_region": [-0.25, -0.5, 1.25, 0.4],
            "same_source_only": False,
        },
        None,
        "overflow_above_container",
    )

    assert {item.key: item.value for item in result.items} == {
        "above_bin": True,
        "ground_litter": False,
        "far_above": False,
    }


def test_pairs_same_source_only_matches_identity_not_neighboring_geometry():
    from operators.pairs import pairs_build

    people = ObjectSet([
        obj("person_a", (0.1, 0.1, 0.5, 0.9)),
        obj("person_b", (0.45, 0.1, 0.85, 0.9)),
    ])
    red_upper = ObjectSet([
        obj("person_a", (0.1, 0.1, 0.5, 0.9), source_entity_id="person_a"),
    ])

    pairs = pairs_build(
        {"subjects": people, "objects": red_upper},
        {"same_source_only": True},
        None,
        "same_person",
    )

    assert [(item.subject_id, item.object_id) for item in pairs.items] == [
        ("person_a", "person_a")
    ]


def test_count_speed_logic_and_filter_keep_keys_explainable():
    from operators.filtering import filter_apply
    from operators.logic import logic_all, logic_any, logic_not
    from operators.measure import measure_count, measure_speed

    frame0 = obj("a0", (0.1, 0.1, 0.2, 0.2), frame=0, timestamp=0.0, track_id="a")
    frame1 = obj("a1", (0.2, 0.1, 0.3, 0.2), frame=1, timestamp=1.0, track_id="a")
    frame2 = obj("a2", (0.3, 0.1, 0.4, 0.2), frame=2, timestamp=2.0, track_id="a")
    tracks = TrackSet([Track("a", "target", [frame0, frame1, frame2])])

    counts = measure_count(
        {"objects": ObjectSet([frame0, frame1, frame2])}, {}, None, "count"
    )
    assert [(item.frame_index, item.value) for item in counts.items] == [
        (0, 1),
        (1, 1),
        (2, 1),
    ]
    speeds = measure_speed(
        {"tracks": tracks},
        {"window_frames": 2, "unit": "pixels_per_second"},
        None,
        "speed",
    )
    assert [item.value for item in speeds.items] == pytest.approx([10.0, 10.0])

    positive = ConditionSet([TimedValue("a", 1.0, True, 1)])
    negative = ConditionSet([TimedValue("a", 1.0, False, 1)])
    assert logic_all({"conditions": [positive, negative]}, {}, None, "all").items[0].value is False
    assert logic_any({"conditions": [positive, negative]}, {}, None, "any").items[0].value is True
    assert logic_not({"condition": negative}, {}, None, "not").items[0].value is True
    filtered = filter_apply(
        {"objects": ObjectSet([frame1]), "condition": positive},
        {"output_label": "未戴安全帽人员"},
        None,
        "filter",
    )
    assert [item.id for item in filtered.items] == ["a1"]
    assert filtered.items[0].label == "未戴安全帽人员"
    assert frame1.label == "target"


def test_generic_count_supports_frame_unique_track_and_event_scopes():
    from core.context import Event, EventSet
    from operators.measure import measure_count

    frame_objects = ObjectSet([
        obj("a0", (0.1, 0.1, 0.2, 0.2), frame=0, timestamp=0.0, track_id="a"),
        obj("b0", (0.3, 0.1, 0.4, 0.2), frame=0, timestamp=0.0, track_id="b"),
        obj("a1", (0.2, 0.1, 0.3, 0.2), frame=1, timestamp=1.0, track_id="a"),
    ])
    tracks = TrackSet([
        Track("a", "white car", frame_objects.items[::2]),
        Track("b", "white car", [frame_objects.items[1]]),
    ])
    events = EventSet([
        Event("e1", "wrong-way", "a", 1.0, 2.0),
        Event("e2", "wrong-way", "b", 3.0, 4.0),
    ])

    frame_counts = measure_count(
        {"entities": frame_objects}, {"scope": "frame"}, None, "frame_count"
    )
    unique_tracks = measure_count(
        {"entities": tracks}, {"scope": "unique"}, None, "track_count"
    )
    unique_events = measure_count(
        {"entities": events}, {"scope": "unique"}, None, "event_count"
    )

    assert [(item.frame_index, item.value) for item in frame_counts.items] == [
        (0, 2), (1, 1)
    ]
    assert [(item.key, item.value) for item in unique_tracks.items] == [
        ("global", 2)
    ]
    assert [(item.key, item.value) for item in unique_events.items] == [
        ("global", 2)
    ]


def test_generic_count_can_group_frame_entities_by_label():
    """Category counts remain an explicit, reusable measurement atom."""

    from operators.measure import measure_count

    objects = ObjectSet([
        obj("vehicle0", (0.1, 0.1, 0.2, 0.2), frame=0, timestamp=0.0),
        obj("container0", (0.3, 0.1, 0.4, 0.2), frame=0, timestamp=0.0),
        obj("vehicle1", (0.2, 0.1, 0.3, 0.2), frame=1, timestamp=1.0),
    ])
    objects.items[0].label = "vehicle"
    objects.items[1].label = "container"
    objects.items[2].label = "vehicle"

    grouped = measure_count(
        {"entities": objects},
        {"scope": "frame", "group_by": "label"},
        None,
        "count",
    )

    assert [(item.frame_index, item.key, item.value) for item in grouped.items] == [
        (0, "container", 1),
        (0, "vehicle", 1),
        (1, "vehicle", 1),
    ]


def test_comparison_can_override_a_threshold_for_each_named_region():
    from operators.logic import logic_compare

    conditions = logic_compare(
        {"left": ScalarSet([
            TimedValue("lane_a", 0.0, 3, 0),
            TimedValue("lane_b", 0.0, 3, 0),
        ])},
        {
            "operator": ">=",
            "value": 4,
            "overrides": {"lane_a": 2, "lane_b": 5},
        },
        None,
        "per_lane_threshold",
    )

    assert {item.key: item.value for item in conditions.items} == {
        "lane_a": True,
        "lane_b": False,
    }


def test_comparison_can_override_an_operator_for_each_named_region():
    from operators.logic import logic_compare

    conditions = logic_compare(
        {"left": ScalarSet([
            TimedValue("lane_a", 0.0, 3, 0),
            TimedValue("lane_b", 0.0, 3, 0),
        ])},
        {
            "operator": ">=",
            "value": 3,
            "operator_overrides": {"lane_b": ">"},
        },
        None,
        "per_lane_operator",
    )

    assert {item.key: item.value for item in conditions.items} == {
        "lane_a": True,
        "lane_b": False,
    }


def test_comparison_can_filter_to_one_named_region():
    from operators.logic import logic_compare

    conditions = logic_compare(
        {"left": ScalarSet([
            TimedValue("lane_a", 0.0, 3, 0),
            TimedValue("lane_b", 0.0, 8, 0),
        ])},
        {"operator": ">", "value": 2, "key_filter": "lane_b"},
        None,
        "only_lane_b",
    )

    assert [(item.key, item.value) for item in conditions.items] == [
        ("lane_b", True),
    ]


def test_frame_any_combines_independent_named_regions_as_one_event_condition():
    """Two explicitly selected regions can jointly trigger one global event."""
    from operators.logic import logic_all

    north = ConditionSet([TimedValue("northbound", 1.0, True, 1)])
    south = ConditionSet([TimedValue("southbound", 1.0, True, 1)])

    combined = logic_all(
        {"conditions": [north, south]},
        {"combine_scope": "frame_any"},
        None,
        "both_regions",
    )

    assert [(item.key, item.timestamp, item.value) for item in combined.items] == [
        ("global", 1.0, True),
    ]


def test_named_region_count_threshold_can_persist_as_a_region_event():
    """Selected categories, regions, thresholds, and duration compose generically."""
    from operators.filtering import objects_filter_by_label
    from operators.logic import logic_compare
    from operators.measure import measure_region_count
    from operators.temporal import temporal_persist

    objects = ObjectSet([
        *[
            obj(f"car_{frame}_{index}", (0.05 + index * 0.08, 0.2, 0.1 + index * 0.08, 0.3), frame=frame, timestamp=float(frame))
            for frame in (0, 1)
            for index in range(3)
        ],
        *[
            obj(f"truck_{frame}", (0.35, 0.2, 0.42, 0.3), frame=frame, timestamp=float(frame))
            for frame in (0, 1)
        ],
        *[
            obj(f"person_{frame}", (0.45, 0.2, 0.5, 0.3), frame=frame, timestamp=float(frame))
            for frame in (0, 1)
        ],
    ])
    for item in objects.items:
        item.label = item.id.split("_", 1)[0]
    selected = objects_filter_by_label(
        {"objects": objects}, {"labels": ["car", "truck"], "mode": "include"}, None, "vehicles"
    )
    regions = RegionSet([
        Region("lane_left", [(0, 0), (0.55, 0), (0.55, 1), (0, 1)]),
        Region("lane_right", [(0.55, 0), (1, 0), (1, 1), (0.55, 1)]),
    ])
    frames = [
        SimpleNamespace(frame_index=0, timestamp=0.0),
        SimpleNamespace(frame_index=1, timestamp=1.0),
    ]

    counts = measure_region_count(
        {"objects": selected, "regions": regions, "frames": SimpleNamespace(items=frames)},
        {"membership_mode": "center"}, None, "count",
    )
    overloaded = logic_compare(
        {"left": counts}, {"operator": ">=", "value": 4}, None, "overloaded"
    )
    events = temporal_persist(
        {"condition": overloaded},
        {"seconds": 1.0, "gap_tolerance_seconds": 1.0, "trigger_mode": "once"},
        None, "congestion",
    )

    assert [(item.key, item.value) for item in counts.items] == [
        ("lane_left", 4), ("lane_right", 0),
        ("lane_left", 4), ("lane_right", 0),
    ]
    assert [(event.entity_id, event.start_time, event.end_time) for event in events.items] == [
        ("lane_left", 1.0, 1.0)
    ]


def test_temporal_persist_treats_regular_one_fps_samples_as_continuous():
    """The default one-frame-per-second video cadence must support one-second rules."""
    from operators.temporal import temporal_persist

    conditions = ConditionSet([
        TimedValue("track_1", 0.0, True, 0),
        TimedValue("track_1", 1.0, True, 1),
    ])

    events = temporal_persist(
        {"condition": conditions},
        {"seconds": 1.0, "gap_tolerance_seconds": 0.6, "trigger_mode": "once"},
        None,
        "events",
    )

    assert [(event.entity_id, event.start_time, event.end_time) for event in events.items] == [
        ("track_1", 1.0, 1.0)
    ]


def test_immediate_once_event_deduplicates_regular_samples_when_gap_tolerance_is_zero():
    """An immediate event is emitted once for one continuous sampled track."""
    from operators.temporal import temporal_persist

    conditions = ConditionSet([
        TimedValue("track_1", 0.0, True, 0),
        TimedValue("track_1", 1.0, True, 1),
        TimedValue("track_1", 2.0, True, 2),
    ])

    events = temporal_persist(
        {"condition": conditions},
        {"seconds": 0.0, "gap_tolerance_seconds": 0.0, "trigger_mode": "once"},
        None,
        "fall_event",
    )

    assert [(event.entity_id, event.start_time, event.end_time) for event in events.items] == [
        ("track_1", 0.0, 0.0)
    ]


def test_temporal_persist_exposes_only_the_qualified_part_of_a_continuous_run():
    """A duration alert must not appear before its configured threshold."""
    from operators.temporal import temporal_persist

    conditions = ConditionSet([
        TimedValue("vehicle_1", 0.0, True, 0),
        TimedValue("vehicle_1", 1.0, True, 1),
        TimedValue("vehicle_1", 2.0, True, 2),
        TimedValue("vehicle_1", 3.0, True, 3),
        TimedValue("vehicle_1", 4.0, False, 4),
    ])

    events = temporal_persist(
        {"condition": conditions},
        {"seconds": 2.0, "gap_tolerance_seconds": 0.6, "trigger_mode": "once"},
        None,
        "parking",
    )

    assert [(event.entity_id, event.start_time, event.end_time) for event in events.items] == [
        ("vehicle_1", 2.0, 3.0)
    ]
    assert events.items[0].metadata == {
        "qualification_start_time": 0.0,
        "trigger_time": 2.0,
        "required_duration_seconds": 2.0,
    }


def test_filter_by_label_partitions_detector_categories_without_phrase_matching():
    from operators.filtering import objects_filter_by_label

    objects = ObjectSet([
        obj("bin", (0.1, 0.1, 0.3, 0.4), frame=0, timestamp=0.0),
        obj("litter", (0.6, 0.1, 0.7, 0.2), frame=0, timestamp=0.0),
    ])
    objects.items[0].label = "container"
    objects.items[1].label = "loose litter"

    selected = objects_filter_by_label(
        {"objects": objects},
        {"labels": ["loose litter"], "mode": "include"},
        None,
        "select",
    )
    remaining = objects_filter_by_label(
        {"objects": objects},
        {"labels": ["loose litter"], "mode": "exclude"},
        None,
        "rest",
    )

    assert [item.id for item in selected.items] == ["litter"]
    assert [item.id for item in remaining.items] == ["bin"]


def test_named_region_count_and_speed_keep_lane_keys_and_frame_timestamps():
    from core.context import Frame, FrameSet, Region, RegionSet
    from operators.measure import measure_region_count, measure_region_speed

    frames = FrameSet(
        [
            Frame(
                Image.new("RGB", (100, 100)),
                (100, 100),
                frame_index=0,
                timestamp=0.0,
            ),
            Frame(
                Image.new("RGB", (100, 100)),
                (100, 100),
                frame_index=1,
                timestamp=1.0,
            ),
        ],
        source_kind="video",
    )
    regions = RegionSet([
        Region("lane_a", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)], "A车道"),
        Region("lane_b", [(0.5, 0), (1, 0), (1, 1), (0.5, 1)], "B车道"),
    ])
    objects = ObjectSet([
        obj("a0", (0.1, 0.1, 0.2, 0.2), frame=0, timestamp=0.0, track_id="a"),
        obj("b0", (0.6, 0.1, 0.7, 0.2), frame=0, timestamp=0.0, track_id="b"),
        obj("b1", (0.7, 0.1, 0.8, 0.2), frame=1, timestamp=1.0, track_id="b"),
    ])
    tracks = TrackSet([
        Track("a", "vehicle", [objects.items[0]]),
        Track("b", "vehicle", [objects.items[1], objects.items[2]]),
    ])

    counts = measure_region_count(
        {"objects": objects, "regions": regions, "frames": frames},
        {"membership_mode": "center"},
        None,
        "lane_count",
    )
    assert [(item.key, item.frame_index, item.value) for item in counts.items] == [
        ("lane_a", 0, 1),
        ("lane_b", 0, 1),
        ("lane_a", 1, 0),
        ("lane_b", 1, 1),
    ]

    speeds = measure_region_speed(
        {"tracks": tracks, "regions": regions},
        {
            "window_frames": 2,
            "unit": "pixels_per_second",
            "aggregation": "median",
            "membership_mode": "sample_center",
        },
        None,
        "lane_speed",
    )
    assert [(item.key, item.frame_index, item.value) for item in speeds.items] == [
        ("lane_b", 1, pytest.approx(10.0)),
    ]


def test_track_filter_matching_samples_removes_non_matching_history_frames():
    from operators.filtering import tracks_filter

    frame0 = obj("a0", (0.1, 0.1, 0.2, 0.2), frame=0, timestamp=0.0, track_id="a")
    frame1 = obj("a1", (0.2, 0.1, 0.3, 0.2), frame=1, timestamp=1.0, track_id="a")
    frame2 = obj("a2", (0.3, 0.1, 0.4, 0.2), frame=2, timestamp=2.0, track_id="a")
    track = Track("a", "person", [frame0, frame1, frame2])
    condition = ConditionSet([
        TimedValue("a", 0.0, False, 0),
        TimedValue("a", 1.0, True, 1),
        TimedValue("a", 2.0, False, 2),
    ])

    result = tracks_filter(
        {"tracks": TrackSet([track]), "condition": condition},
        {"history_mode": "matching_samples"},
        None,
        "matched_tracks",
    )

    assert [item.id for item in result.items] == ["a"]
    assert [item.id for item in result.items[0].history] == ["a1"]


def test_track_filter_by_events_keeps_only_event_entities_and_event_time_window():
    from core.context import Event, EventSet
    from operators.filtering import tracks_filter_by_events

    matching = Track(
        "a",
        "vehicle",
        [
            obj("a0", (0.1, 0.1, 0.2, 0.2), frame=0, timestamp=0.0),
            obj("a1", (0.2, 0.1, 0.3, 0.2), frame=1, timestamp=1.0),
            obj("a2", (0.3, 0.1, 0.4, 0.2), frame=2, timestamp=2.0),
        ],
    )
    other = Track(
        "b",
        "vehicle",
        [obj("b1", (0.5, 0.1, 0.6, 0.2), frame=1, timestamp=1.0)],
    )
    events = EventSet([Event("event_a", "违停", "a", 1.0, 2.0)])

    result = tracks_filter_by_events(
        {"tracks": TrackSet([matching, other]), "events": events},
        {"time_window": "event"},
        None,
        "event_tracks",
    )

    assert [track.id for track in result.items] == ["a"]
    assert [item.id for item in result.items[0].history] == ["a1", "a2"]


def test_track_confirm_filters_short_noisy_tracks_by_explicit_hit_and_span_rules():
    from operators.tracking import track_confirm

    stable = Track(
        "stable",
        "debris",
        [
            obj("s0", (0.1, 0.1, 0.2, 0.2), frame=0, timestamp=0.0),
            obj("s1", (0.1, 0.1, 0.2, 0.2), frame=1, timestamp=0.5),
            obj("s2", (0.1, 0.1, 0.2, 0.2), frame=2, timestamp=1.0),
        ],
    )
    transient = Track(
        "transient",
        "debris",
        [obj("n0", (0.5, 0.5, 0.6, 0.6), frame=1, timestamp=0.5)],
    )

    result = track_confirm(
        {"tracks": TrackSet([stable, transient])},
        {"min_hits": 2, "min_span_seconds": 0.5},
        None,
        "confirmed",
    )

    assert [track.id for track in result.items] == ["stable"]


def test_global_median_speed_rejects_sparse_tracking_outliers():
    from operators.measure import measure_speed

    tracks = TrackSet([
        Track(
            "steady_a",
            "vehicle",
            [
                obj("a0", (0.10, 0.10, 0.20, 0.20), frame=0, timestamp=0.0),
                obj("a1", (0.11, 0.10, 0.21, 0.20), frame=1, timestamp=1.0),
            ],
        ),
        Track(
            "steady_b",
            "vehicle",
            [
                obj("b0", (0.30, 0.10, 0.40, 0.20), frame=0, timestamp=0.0),
                obj("b1", (0.31, 0.10, 0.41, 0.20), frame=1, timestamp=1.0),
            ],
        ),
        Track(
            "jitter",
            "vehicle",
            [
                obj("c0", (0.50, 0.10, 0.60, 0.20), frame=0, timestamp=0.0),
                obj("c1", (0.90, 0.10, 1.00, 0.20), frame=1, timestamp=1.0),
            ],
        ),
    ])

    result = measure_speed(
        {"tracks": tracks},
        {
            "window_frames": 2,
            "unit": "pixels_per_second",
            "aggregation": "global_median",
        },
        None,
        "speed",
    )

    assert len(result.items) == 1
    assert result.items[0].value == pytest.approx(1.0)


def test_manual_direction_is_broadcast_as_an_explicit_reference_rule():
    from core.context import VectorSet
    from operators.logic import logic_compare
    from operators.region import direction_manual

    reference = direction_manual({}, {"vector": [1.0, 0.0]}, None, "expected")
    headings = VectorSet([TimedValue("track_1", 1.0, (-1.0, 0.0), 2)])
    result = logic_compare(
        {"left": headings, "right": reference},
        {"operator": "opposite_direction", "threshold": -0.5},
        None,
        "opposite",
    )
    assert result.items[0].value is True


def test_manual_direction_preserves_drawn_arrow_geometry_for_explainable_rendering():
    from operators.region import direction_manual, direction_manual_set

    single = direction_manual(
        {},
        {
            "vector": [0.6, -0.4],
            "start": [0.2, 0.8],
            "end": [0.8, 0.4],
        },
        None,
        "global_reference",
    )
    assert single.items[0].metadata == {
        "source": "manual",
        "start": [0.2, 0.8],
        "end": [0.8, 0.4],
    }

    named = direction_manual_set(
        {},
        {
            "directions": [
                {
                    "key": "lane_a",
                    "vector": [0.0, -0.5],
                    "start": [0.25, 0.75],
                    "end": [0.25, 0.25],
                }
            ]
        },
        None,
        "lane_references",
    )
    assert named.items[0].metadata["start"] == [0.25, 0.75]
    assert named.items[0].metadata["end"] == [0.25, 0.25]


def test_global_majority_heading_is_one_explicit_broadcast_reference():
    from core.context import VectorSet
    from operators.measure import measure_majority_heading

    directions = VectorSet([
        TimedValue("a", 0.5, (-1.0, 0.0), 1),
        TimedValue("b", 0.5, (-1.0, 0.0), 1),
        TimedValue("rogue", 0.5, (1.0, 0.0), 1),
        TimedValue("a", 1.0, (-1.0, 0.0), 2),
        TimedValue("b", 1.0, (-1.0, 0.0), 2),
    ])

    result = measure_majority_heading(
        {"directions": directions},
        {"minimum_tracks": 3, "aggregation": "global"},
        None,
        "majority",
    )

    assert len(result.items) == 1
    assert result.items[0].key == "global"
    assert result.items[0].frame_index is None
    assert result.items[0].value == pytest.approx((-1.0, 0.0))


def test_lane_majority_heading_is_computed_independently_per_named_lane():
    from core.context import Region, RegionSet, VectorSet
    from operators.measure import measure_lane_majority_heading

    tracks = TrackSet([
        Track("left_a", "vehicle", [
            obj("la0", (0.10, 0.50, 0.20, 0.60), frame=0, timestamp=0.0),
            obj("la1", (0.08, 0.50, 0.18, 0.60), frame=1, timestamp=1.0),
        ]),
        Track("left_b", "vehicle", [
            obj("lb0", (0.20, 0.40, 0.30, 0.50), frame=0, timestamp=0.0),
            obj("lb1", (0.18, 0.40, 0.28, 0.50), frame=1, timestamp=1.0),
        ]),
        Track("right_a", "vehicle", [
            obj("ra0", (0.70, 0.50, 0.80, 0.60), frame=0, timestamp=0.0),
            obj("ra1", (0.72, 0.50, 0.82, 0.60), frame=1, timestamp=1.0),
        ]),
        Track("right_b", "vehicle", [
            obj("rb0", (0.80, 0.40, 0.90, 0.50), frame=0, timestamp=0.0),
            obj("rb1", (0.82, 0.40, 0.92, 0.50), frame=1, timestamp=1.0),
        ]),
    ])
    directions = VectorSet([
        TimedValue("left_a", 1.0, (-1.0, 0.0), 1),
        TimedValue("left_b", 1.0, (-1.0, 0.0), 1),
        TimedValue("right_a", 1.0, (1.0, 0.0), 1),
        TimedValue("right_b", 1.0, (1.0, 0.0), 1),
    ])
    lanes = RegionSet([
        Region("lane_left", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)], "left"),
        Region("lane_right", [(0.5, 0), (1, 0), (1, 1), (0.5, 1)], "right"),
    ])

    result = measure_lane_majority_heading(
        {"tracks": tracks, "directions": directions, "lanes": lanes},
        {"minimum_tracks": 2, "membership_mode": "latest_center"},
        None,
        "lane_majority",
    )

    by_key = {item.key: item.value for item in result.items}
    assert by_key["lane_left"] == pytest.approx((-1.0, 0.0))
    assert by_key["lane_right"] == pytest.approx((1.0, 0.0))


def test_lane_majority_heading_uses_majority_lane_membership_over_track_history():
    from core.context import Region, RegionSet, VectorSet
    from operators.measure import measure_lane_majority_heading

    crossing = Track("crossing", "person", [
        obj("p0", (0.10, 0.40, 0.20, 0.60), frame=0, timestamp=0.0),
        obj("p1", (0.20, 0.40, 0.30, 0.60), frame=1, timestamp=1.0),
        obj("p2", (0.55, 0.40, 0.65, 0.60), frame=2, timestamp=2.0),
    ])
    lanes = RegionSet([
        Region("left", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)], "left"),
        Region("right", [(0.5, 0), (1, 0), (1, 1), (0.5, 1)], "right"),
    ])
    directions = VectorSet([
        TimedValue("crossing", 1.0, (1.0, 0.0), 1),
        TimedValue("crossing", 2.0, (1.0, 0.0), 2),
    ])

    result = measure_lane_majority_heading(
        {"tracks": TrackSet([crossing]), "directions": directions, "lanes": lanes},
        {"minimum_tracks": 1, "membership_mode": "majority_center"},
        None,
        "lane_majority",
    )

    assert [(item.key, item.value) for item in result.items] == [
        ("left", pytest.approx((1.0, 0.0)))
    ]


def test_compare_heading_uses_each_tracks_lane_reference():
    from core.context import Region, RegionSet, VectorSet
    from operators.logic import logic_compare_heading_by_lane

    tracks = TrackSet([
        Track("normal", "vehicle", [
            obj("n", (0.10, 0.50, 0.20, 0.60), frame=1, timestamp=1.0),
        ]),
        Track("wrong", "vehicle", [
            obj("w", (0.20, 0.50, 0.30, 0.60), frame=1, timestamp=1.0),
        ]),
    ])
    headings = VectorSet([
        TimedValue("normal", 1.0, (-1.0, 0.0), 1),
        TimedValue("wrong", 1.0, (1.0, 0.0), 1),
    ])
    lanes = RegionSet([
        Region("lane_left", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)], "left")
    ])
    references = VectorSet([TimedValue("lane_left", 0.0, (-1.0, 0.0), None)])

    result = logic_compare_heading_by_lane(
        {
            "tracks": tracks,
            "headings": headings,
            "lanes": lanes,
            "references": references,
        },
        {"threshold": -0.5, "membership_mode": "latest_center"},
        None,
        "wrong_way",
    )

    assert {item.key: item.value for item in result.items} == {
        "normal": False,
        "wrong": True,
    }


def test_heading_and_persistence_support_independent_region_parameters():
    from core.context import Region, RegionSet, VectorSet
    from operators.logic import logic_compare_heading_by_lane
    from operators.temporal import temporal_persist

    tracks = TrackSet([
        Track("lane_a_car", "vehicle", [
            obj("a", (0.10, 0.40, 0.20, 0.50), frame=0, timestamp=0.0),
        ]),
        Track("lane_b_car", "vehicle", [
            obj("b", (0.70, 0.40, 0.80, 0.50), frame=0, timestamp=0.0),
        ]),
    ])
    headings = VectorSet([
        TimedValue("lane_a_car", 0.0, (-0.5, 0.866), 0),
        TimedValue("lane_b_car", 0.0, (-0.5, 0.866), 0),
    ])
    lanes = RegionSet([
        Region("lane_a", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)], "A"),
        Region("lane_b", [(0.5, 0), (1, 0), (1, 1), (0.5, 1)], "B"),
    ])
    references = VectorSet([
        TimedValue("lane_a", 0.0, (1.0, 0.0), None),
        TimedValue("lane_b", 0.0, (1.0, 0.0), None),
    ])

    compared = logic_compare_heading_by_lane(
        {"tracks": tracks, "headings": headings, "lanes": lanes,
         "references": references},
        {
            "threshold": -0.5,
            "relation": "opposite",
            "membership_mode": "latest_center",
            "scope_overrides": {
                "lane_a": {"threshold": -0.7},
                "lane_b": {"threshold": -0.3},
            },
        },
        None,
        "regional_direction",
    )

    assert {item.key: item.value for item in compared.items} == {
        "lane_a_car": False,
        "lane_b_car": True,
    }
    assert {item.key: item.metadata["region_id"] for item in compared.items} == {
        "lane_a_car": "lane_a",
        "lane_b_car": "lane_b",
    }

    persisted = temporal_persist(
        {"condition": compared},
        {
            "seconds": 1.0,
            "scope": "track",
            "gap_tolerance_seconds": 0.6,
            "trigger_mode": "once",
            "override_scope_field": "region_id",
            "scope_overrides": {"lane_b": {"seconds": 0.0}},
        },
        None,
        "regional_persist",
    )
    assert len(persisted.items) == 1
    assert persisted.items[0].entity_id == "lane_b_car"
    assert persisted.items[0].metadata["region_id"] == "lane_b"


def test_temporal_persist_preserves_region_evidence_without_custom_overrides():
    from operators.temporal import temporal_persist

    conditions = ConditionSet([
        TimedValue(
            "track_1",
            0.0,
            True,
            0,
            metadata={"region_id": "lane_1"},
        )
    ])

    events = temporal_persist(
        {"condition": conditions},
        {
            "seconds": 0.0,
            "scope": "track",
            "gap_tolerance_seconds": 0.0,
            "trigger_mode": "once",
            "scope_overrides": {},
            "override_scope_field": "region_id",
        },
        None,
        "persist",
    )

    assert len(events.items) == 1
    assert events.items[0].metadata["region_id"] == "lane_1"


def test_object_and_event_atomic_operators_make_reusable_typed_outputs():
    from operators.events import event_from_condition, event_relabel
    from operators.objects import objects_from_tracks, objects_relabel

    track = Track("t1", "vehicle", [
        obj("v0", (0.1, 0.1, 0.2, 0.2), frame=0, timestamp=0.0, track_id="t1"),
        obj("v1", (0.2, 0.1, 0.3, 0.2), frame=1, timestamp=1.0, track_id="t1"),
    ])
    objects = objects_from_tracks(
        {"tracks": TrackSet([track])}, {"selection": "latest"}, None, "boxes"
    )
    labeled = objects_relabel(
        {"objects": objects}, {"label": "逆行车辆框"}, None, "label_boxes"
    )
    assert [item.id for item in labeled.items] == ["v1"]
    assert labeled.items[0].label == "逆行车辆框"

    conditions = ConditionSet([
        TimedValue("t1", 0.0, True, 0),
        TimedValue("t1", 1.0, True, 1),
    ])
    events = event_from_condition(
        {"condition": conditions},
        {
            "seconds": 1.0,
            "scope": "track",
            "gap_tolerance_seconds": 1.1,
            "trigger_mode": "once",
            "label": "原始事件",
        },
        None,
        "events",
    )
    relabeled = event_relabel(
        {"events": events}, {"label": "违停事件"}, None, "label_events"
    )
    assert len(relabeled.items) == 1
    assert relabeled.items[0].label == "违停事件"


def test_temporal_hold_causally_bridges_short_true_evidence_gaps_per_entity():
    from operators.temporal import temporal_hold

    conditions = ConditionSet([
        TimedValue("person_1", 0.0, True, 0),
        TimedValue("person_1", 0.5, False, 1),
        TimedValue("person_1", 1.0, False, 2),
        TimedValue("person_1", 2.0, False, 3),
        TimedValue("person_2", 0.5, False, 1),
    ])

    result = temporal_hold(
        {"condition": conditions},
        {"seconds": 1.5, "value": True},
        None,
        "hold",
    )

    assert [(item.key, item.timestamp, item.value) for item in result.items] == [
        ("person_1", 0.0, True),
        ("person_1", 0.5, True),
        ("person_1", 1.0, True),
        ("person_1", 2.0, False),
        ("person_2", 0.5, False),
    ]


def test_visual_color_fraction_checks_configured_entity_region():
    from core.context import Frame, FrameSet
    from operators.appearance import visual_color_fraction

    image = Image.new("RGB", (100, 100), "black")
    for x in range(10, 40):
        for y in range(20, 60):
            image.putpixel((x, y), (245, 245, 245))
    for x in range(60, 90):
        for y in range(20, 60):
            image.putpixel((x, y), (240, 100, 20))
    frames = FrameSet([Frame(image, (100, 100))])
    people = ObjectSet([
        obj("white", (0.1, 0.1, 0.4, 0.8)),
        obj("orange", (0.6, 0.1, 0.9, 0.8)),
    ])

    result = visual_color_fraction(
        {"frames": frames, "objects": people},
        {"color": "white", "subject_region": [0.0, 0.1, 1.0, 0.7], "min_fraction": 0.4},
        None,
        "white_clothes",
    )

    assert {item.key: item.value for item in result.items} == {
        "white": True,
        "orange": False,
    }


def test_visual_color_dominance_rejects_incidental_black_pixels():
    from core.context import Frame, FrameSet
    from operators.appearance import visual_color_fraction

    image = Image.new("RGB", (100, 40), (235, 235, 235))
    image.paste((20, 20, 20), (0, 0, 50, 40))
    image.paste((210, 25, 25), (50, 0, 100, 40))
    image.paste((20, 20, 20), (50, 0, 70, 40))  # 40% incidental black on red carrier.
    objects = ObjectSet([
        obj("black_carrier", (0.0, 0.0, 0.5, 1.0)),
        obj("red_carrier", (0.5, 0.0, 1.0, 1.0)),
    ])
    result = visual_color_fraction(
        {"frames": FrameSet([Frame(image, image.size)]), "objects": objects},
        {"color": "black", "subject_region": [0, 0, 1, 1], "min_fraction": 0.2,
         "selection_mode": "dominant", "dominance_margin": 0.05},
        None, "dominant_black",
    )
    assert [item.value for item in result.items] == [True, False]


def test_visual_color_fraction_uses_pillow_hue_scale_for_chromatic_colors():
    from core.context import Frame, FrameSet
    from operators.appearance import visual_color_fraction

    image = Image.new("RGB", (40, 20), "black")
    image.paste((255, 220, 0), (0, 0, 20, 20))
    image.paste((255, 90, 0), (20, 0, 40, 20))
    frames = FrameSet([Frame(image, image.size)])
    objects = ObjectSet([
        obj("yellow", (0.0, 0.0, 0.5, 1.0)),
        obj("orange", (0.5, 0.0, 1.0, 1.0)),
    ])

    yellow = visual_color_fraction(
        {"frames": frames, "objects": objects},
        {"color": "yellow", "subject_region": [0.0, 0.0, 1.0, 1.0], "min_fraction": 0.8},
        None,
        "yellow",
    )
    orange = visual_color_fraction(
        {"frames": frames, "objects": objects},
        {"color": "orange", "subject_region": [0.0, 0.0, 1.0, 1.0], "min_fraction": 0.8},
        None,
        "orange",
    )

    assert [item.value for item in yellow.items] == [True, False]
    assert [item.value for item in orange.items] == [False, True]


def test_yellow_semantic_color_includes_fluorescent_yellow_green_not_orange():
    from core.context import Frame, FrameSet
    from operators.appearance import visual_color_fraction

    image = Image.new("RGB", (60, 20), "black")
    image.paste((195, 255, 0), (0, 0, 20, 20))
    image.paste((255, 150, 0), (20, 0, 40, 20))
    image.paste((0, 180, 40), (40, 0, 60, 20))
    frames = FrameSet([Frame(image, image.size)])
    objects = ObjectSet([
        obj("fluorescent_yellow", (0.0, 0.0, 1 / 3, 1.0)),
        obj("orange", (1 / 3, 0.0, 2 / 3, 1.0)),
        obj("green", (2 / 3, 0.0, 1.0, 1.0)),
    ])

    result = visual_color_fraction(
        {"frames": frames, "objects": objects},
        {"color": "yellow", "subject_region": [0.0, 0.0, 1.0, 1.0], "min_fraction": 0.8},
        None,
        "yellow",
    )

    assert [item.value for item in result.items] == [True, False, False]


def test_semantic_yellow_tolerance_accepts_golden_evidence_not_pure_orange():
    """Model-grounded yellow evidence may be golden at the hue boundary."""

    from core.context import Frame, FrameSet
    from operators.appearance import visual_color_fraction

    image = Image.new("RGB", (40, 20), "black")
    image.paste((255, 150, 0), (0, 0, 20, 20))  # golden yellow, hue ~25
    image.paste((255, 90, 0), (20, 0, 40, 20))  # saturated orange, hue ~15
    result = visual_color_fraction(
        {
            "frames": FrameSet([Frame(image, image.size)]),
            "objects": ObjectSet([
                obj("golden", (0.0, 0.0, 0.5, 1.0)),
                obj("orange", (0.5, 0.0, 1.0, 1.0)),
            ]),
        },
        {
            "color": "yellow",
            "subject_region": [0.0, 0.0, 1.0, 1.0],
            "min_fraction": 0.8,
            "color_tolerance": "semantic",
        },
        None,
        "semantic_yellow",
    )
    assert [item.value for item in result.items] == [True, False]


def test_semantic_color_tolerance_handles_other_adjacent_hue_families():
    """The evidence-aware boundary policy is not special-cased to yellow."""

    from core.context import Frame, FrameSet
    from operators.appearance import visual_color_fraction

    image = Image.new("HSV", (40, 20), (0, 0, 0))
    image.paste((142, 220, 220), (0, 0, 20, 20))  # cyan-blue boundary
    image.paste((120, 220, 220), (20, 0, 40, 20))  # clearly cyan
    image = image.convert("RGB")
    result = visual_color_fraction(
        {
            "frames": FrameSet([Frame(image, image.size)]),
            "objects": ObjectSet([
                obj("blue_boundary", (0.0, 0.0, 0.5, 1.0)),
                obj("cyan", (0.5, 0.0, 1.0, 1.0)),
            ]),
        },
        {
            "color": "blue",
            "subject_region": [0.0, 0.0, 1.0, 1.0],
            "min_fraction": 0.8,
            "color_tolerance": "semantic",
        },
        None,
        "semantic_blue",
    )
    assert [item.value for item in result.items] == [True, False]


@pytest.mark.parametrize(
    ("color", "rgb"),
    [
        ("black", (20, 20, 20)), ("white", (245, 245, 245)),
        ("gray", (125, 125, 125)), ("red", (220, 25, 25)),
        ("orange", (245, 120, 10)), ("yellow", (220, 235, 15)),
        ("green", (20, 150, 45)), ("cyan", (15, 190, 190)),
        ("blue", (30, 70, 220)), ("purple", (130, 45, 180)),
        ("pink", (245, 105, 170)), ("brown", (125, 70, 30)),
    ],
)
def test_visual_color_catalog_recognizes_twelve_semantic_colors(color, rgb):
    from core.context import Frame, FrameSet
    from operators.appearance import visual_color_fraction

    image = Image.new("RGB", (20, 20), rgb)
    result = visual_color_fraction(
        {"frames": FrameSet([Frame(image, image.size)]),
         "objects": ObjectSet([obj("sample", (0.0, 0.0, 1.0, 1.0))])},
        {"color": color, "subject_region": [0.0, 0.0, 1.0, 1.0], "min_fraction": 0.8},
        None,
        color,
    )
    assert result.items[0].value is True


def test_compare_heading_uses_same_majority_lane_rule_as_lane_reference():
    from core.context import Region, RegionSet, VectorSet
    from operators.logic import logic_compare_heading_by_lane

    crossing = Track("crossing", "person", [
        obj("p0", (0.10, 0.4, 0.20, 0.6), frame=0, timestamp=0.0),
        obj("p1", (0.20, 0.4, 0.30, 0.6), frame=1, timestamp=1.0),
        obj("p2", (0.55, 0.4, 0.65, 0.6), frame=2, timestamp=2.0),
    ])
    lanes = RegionSet([
        Region("left", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)], "left"),
        Region("right", [(0.5, 0), (1, 0), (1, 1), (0.5, 1)], "right"),
    ])
    headings = VectorSet([TimedValue("crossing", 2.0, (-1.0, 0.0), 2)])
    references = VectorSet([
        TimedValue("left", 0.0, (1.0, 0.0), None),
        TimedValue("right", 0.0, (-1.0, 0.0), None),
    ])

    result = logic_compare_heading_by_lane(
        {
            "tracks": TrackSet([crossing]),
            "headings": headings,
            "lanes": lanes,
            "references": references,
        },
        {
            "threshold": -0.5,
            "membership_mode": "majority_center",
            "relation": "opposite",
        },
        None,
        "opposite",
    )

    assert result.items[0].value is True


def test_visual_geometry_filters_size_and_position_with_explicit_rules():
    from operators.appearance import visual_geometry

    objects = ObjectSet([
        obj("small_left", (0.05, 0.4, 0.15, 0.5)),
        obj("large_right", (0.55, 0.1, 0.95, 0.9)),
    ])
    small = visual_geometry(
        {"objects": objects},
        {"dimension": "size", "value": "small", "small_max_area": 0.02,
         "large_min_area": 0.12, "position_margin": 0.33}, None, "small",
    )
    right = visual_geometry(
        {"objects": objects},
        {"dimension": "position", "value": "right", "small_max_area": 0.02,
         "large_min_area": 0.12, "position_margin": 0.33}, None, "right",
    )
    assert [item.value for item in small.items] == [True, False]
    assert [item.value for item in right.items] == [False, True]


def test_visual_geometry_filters_horizontal_pose_by_bbox_aspect_ratio():
    from operators.appearance import visual_geometry

    objects = ObjectSet([
        obj("standing", (0.20, 0.10, 0.35, 0.80)),
        obj("lying", (0.20, 0.40, 0.80, 0.60)),
    ])

    horizontal = visual_geometry(
        {"objects": objects},
        {
            "dimension": "aspect_ratio",
            "value": "horizontal",
            "aspect_ratio_threshold": 1.0,
        },
        None,
        "horizontal",
    )

    assert [item.value for item in horizontal.items] == [False, True]


def test_object_projection_can_follow_any_number_of_annotated_regions():
    from core.context import Region, RegionSet
    from operators.spatial import objects_filter_by_regions

    objects = ObjectSet([
        obj("lane_a_vehicle", (0.05, 0.20, 0.20, 0.40)),
        obj("lane_b_vehicle", (0.65, 0.20, 0.80, 0.40)),
        obj("outside_false_positive", (0.42, 0.20, 0.52, 0.40)),
    ])
    regions = RegionSet([
        Region("lane_a", [(0, 0), (0.3, 0), (0.3, 1), (0, 1)]),
        Region("lane_b", [(0.6, 0), (1, 0), (1, 1), (0.6, 1)]),
    ])

    result = objects_filter_by_regions(
        {"objects": objects, "regions": regions},
        {"membership_mode": "center", "keep": "inside"},
        None,
        "vehicles_in_lanes",
    )

    assert [item.id for item in result.items] == [
        "lane_a_vehicle", "lane_b_vehicle"
    ]

    fallback = objects_filter_by_regions(
        {"objects": objects, "regions": RegionSet([])},
        {"membership_mode": "center", "keep": "inside", "empty_regions": "passthrough"},
        None,
        "optional_regions",
    )
    assert [item.id for item in fallback.items] == [
        "lane_a_vehicle", "lane_b_vehicle", "outside_false_positive"
    ]


def test_visual_geometry_uses_source_pixels_for_aspect_ratio():
    from operators.appearance import visual_geometry

    # Normalized width/height is 0.5, but on a 16:9 source the actual pixel
    # ratio is 0.5 * 16/9 = 0.89 and should satisfy a 0.6 vehicle-box rule.
    candidate = obj("vehicle", (0.20, 0.20, 0.40, 0.60))
    candidate.original_size = (1600, 900)

    horizontal = visual_geometry(
        {"objects": ObjectSet([candidate])},
        {
            "dimension": "aspect_ratio",
            "value": "horizontal",
            "aspect_ratio_threshold": 0.6,
        },
        None,
        "horizontal_pixels",
    )

    assert horizontal.items[0].value is True


def test_visual_geometry_filters_horizontal_pose_for_track_history():
    from operators.appearance import visual_geometry

    track = Track(
        "person-1",
        "person",
        [
            obj("standing", (0.20, 0.10, 0.35, 0.80), frame=0),
            obj("lying", (0.20, 0.40, 0.80, 0.60), frame=1, timestamp=1.0),
        ],
    )

    horizontal = visual_geometry(
        {"objects": TrackSet([track])},
        {
            "dimension": "aspect_ratio",
            "value": "horizontal",
            "aspect_ratio_threshold": 1.0,
        },
        None,
        "horizontal_tracks",
    )

    assert [item.key for item in horizontal.items] == ["person-1", "person-1"]
    assert [item.value for item in horizontal.items] == [False, True]


def test_visual_geometry_relative_size_ranks_same_class_candidates():
    from operators.appearance import visual_geometry

    candidates = ObjectSet([
        obj("small", (0.05, 0.05, 0.25, 0.25)),
        obj("medium", (0.30, 0.30, 0.60, 0.60)),
        obj("large", (0.55, 0.10, 0.95, 0.725)),
    ])
    common = {
        "dimension": "size", "size_mode": "relative",
        "small_max_area": 0.02, "large_min_area": 0.12, "position_margin": 0.33,
    }
    outputs = {
        value: visual_geometry(
            {"objects": candidates}, {**common, "value": value}, None, value
        )
        for value in ("small", "medium", "large")
    }
    assert [item.value for item in outputs["small"].items] == [True, False, False]
    assert [item.value for item in outputs["medium"].items] == [False, True, False]
    assert [item.value for item in outputs["large"].items] == [False, False, True]
