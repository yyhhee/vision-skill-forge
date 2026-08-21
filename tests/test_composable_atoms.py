from __future__ import annotations

from core.context import (
    ConditionSet,
    Event,
    EventSet,
    ObjectSet,
    Region,
    RegionSet,
    StateSet,
    TimedValue,
    VisualObject,
)
from core.registry import build_default_registry
from operators.pairs import pairs_build, pairs_filter, pairs_measure
from operators.reduce import reduce_count, reduce_exists, reduce_quantify
from operators.result import event_attach_evidence, evidence_collect, result_project
from operators.sets import set_anti_join, set_partition, set_semi_join
from operators.state import state_detect, state_transition


def _object(object_id, label, bbox, *, frame=0, source=None):
    return VisualObject(
        object_id,
        label,
        label,
        bbox,
        frame,
        float(frame),
        "test",
        source_entity_id=source,
    )


def test_pair_atoms_support_per_subject_equipment_presence_and_absence():
    workers = ObjectSet([
        _object("worker_1", "人员", (0.1, 0.1, 0.4, 0.9)),
        _object("worker_2", "人员", (0.6, 0.1, 0.9, 0.9)),
    ])
    helmets = ObjectSet([
        _object("helmet_1", "安全帽", (0.18, 0.1, 0.32, 0.25)),
    ])

    pairs = pairs_build(
        {"subjects": workers, "objects": helmets},
        {"same_source_only": False}, None, "pairs",
    )
    measured = pairs_measure({"pairs": pairs}, {}, None, "measure")
    matched = pairs_filter(
        {"pairs": measured},
        {"metric": "subject_coverage", "operator": ">=", "threshold": 0.02},
        None,
        "filter",
    )

    present = set_semi_join({"subjects": workers, "pairs": matched}, {}, None, "present")
    absent = set_anti_join({"subjects": workers, "pairs": matched}, {}, None, "absent")

    assert [item.id for item in present.items] == ["worker_1"]
    assert [item.id for item in absent.items] == ["worker_2"]


def test_dynamic_region_partition_count_and_exists_keep_scope_identity():
    objects = ObjectSet([
        _object("car_1", "车辆", (0.1, 0.1, 0.2, 0.2)),
        _object("car_2", "车辆", (0.2, 0.2, 0.3, 0.3)),
        _object("car_3", "车辆", (0.7, 0.2, 0.8, 0.3)),
    ])
    regions = RegionSet([
        Region("left", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)], "左区"),
        Region("right", [(0.5, 0), (1, 0), (1, 1), (0.5, 1)], "右区"),
    ])

    scoped = set_partition(
        {"entities": objects, "regions": regions}, {"mode": "region"}, None, "partition"
    )
    counts = reduce_count({"sets": scoped}, {}, None, "count")
    exists = reduce_exists({"sets": scoped}, {}, None, "exists")

    assert [(item.key, item.value) for item in counts.items] == [("left", 2), ("right", 1)]
    assert [(item.key, item.value) for item in exists.items] == [("left", True), ("right", True)]


def test_dynamic_quantifier_supports_n_of_m_without_static_input_count():
    conditions = ConditionSet([
        TimedValue("region_a", 1.0, True, 1),
        TimedValue("region_b", 1.0, False, 1),
        TimedValue("region_c", 1.0, True, 1),
    ])
    result = reduce_quantify(
        {"conditions": conditions}, {"mode": "n_of_m", "required_count": 2}, None, "q"
    )
    assert len(result.items) == 1
    assert result.items[0].value is True


def test_event_evidence_and_result_projection_link_event_to_box():
    objects = ObjectSet([
        _object("person_1", "人员", (0.1, 0.2, 0.4, 0.9)),
    ])
    events = EventSet([Event("fall_1", "倒地", "person_1", 0.0, 1.0)])
    attached = event_attach_evidence(
        {"events": events, "objects": objects}, {}, None, "attach"
    )
    projected = result_project(
        {"objects": objects, "events": attached}, {}, None, "project"
    )

    assert attached.items[0].metadata["evidence"][0]["bbox"] == [0.1, 0.2, 0.4, 0.9]
    event_item = next(item for item in projected.items if item.get("event_id") == "fall_1")
    assert event_item["evidence"][0]["entity_id"] == "person_1"


def test_state_atoms_distinguish_current_state_from_same_target_transition():
    samples = ObjectSet([
        _object("person_1_standing", "站立", (0.1, 0.1, 0.3, 0.9), frame=0),
        _object("person_1_fallen", "倒地", (0.1, 0.6, 0.6, 0.9), frame=2),
    ])
    for sample in samples.items:
        sample.track_id = "person_1"
    states = state_detect(
        {"entities": samples},
        {
            "evidence_mode": "label",
            "state_labels": {"站立": "upright", "倒地": "fallen"},
            "default_state": "unknown",
        },
        None,
        "state",
    )
    transitions = state_transition(
        {"states": states},
        {
            "from_state": "upright",
            "to_state": "fallen",
            "max_seconds": 3,
            "consume_source": True,
        },
        None,
        "transition",
    )

    assert isinstance(states, StateSet)
    assert [(item.key, item.value) for item in transitions.items] == [("person_1", True)]
    assert transitions.items[0].metadata["elapsed_seconds"] == 2.0


def test_explicit_evidence_set_can_be_attached_to_event():
    objects = ObjectSet([_object("person_1", "人员", (0.1, 0.2, 0.4, 0.9))])
    evidence = evidence_collect({"objects": objects}, {}, None, "collect")
    events = EventSet([Event("fall_1", "摔倒", "person_1", 0.0, 1.0)])
    attached = event_attach_evidence(
        {"events": events, "evidence": evidence}, {}, None, "attach"
    )

    assert attached.items[0].metadata["evidence"][0]["evidence_id"].startswith("collect:")
    assert attached.items[0].metadata["evidence"][0]["bbox"] == (0.1, 0.2, 0.4, 0.9)


def test_new_atoms_are_registered_for_planning_and_execution():
    registry = build_default_registry()
    for op in (
        "set.partition@1.0",
        "set.anti_join@1.0",
        "pairs.build@1.0",
        "reduce.quantify@1.0",
        "state.detect@1.0",
        "state.transition@1.0",
        "evidence.collect@1.0",
        "event.attach_evidence@1.0",
        "result.project@1.0",
    ):
        assert registry.require(op).op == op
