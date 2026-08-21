from __future__ import annotations

from core.context import Event, EventSet
from core.registry import build_default_registry
from operators.pattern import (
    event_trigger,
    temporal_absence,
    temporal_join,
    temporal_repeat,
    temporal_sequence_v2,
)


def _events(*items):
    return EventSet([
        Event(event_id, label, entity_id, start, end)
        for event_id, label, entity_id, start, end in items
    ])


def test_join_distinguishes_simultaneously_active_from_completed_in_window():
    first = _events(("a", "区域1着装人员", "global", 0, 10))
    second = _events(("b", "区域2人数持续", "global", 5, 12))
    accident = _events(("c", "区域3事故", "global", 8, 8))

    active = temporal_join(
        {"events": [first, second, accident]},
        {
            "mode": "all_active",
            "required_count": None,
            "window_seconds": None,
            "correlation_scope": "global",
            "correlation_fields": [],
            "maximum_matches": 10,
            "label": "联合告警",
        },
        None,
        "join",
    )
    assert len(active.items) == 1
    assert active.items[0].metadata["branch_event_ids"] == ["a", "b", "c"]

    late = _events(("late", "区域3事故", "global", 20, 20))
    not_active = temporal_join(
        {"events": [first, second, late]},
        {
            "mode": "all_active",
            "required_count": None,
            "window_seconds": None,
            "correlation_scope": "global",
            "correlation_fields": [],
            "maximum_matches": 10,
            "label": "联合告警",
        },
        None,
        "join",
    )
    assert not not_active.items

    completed = temporal_join(
        {"events": [first, second, late]},
        {
            "mode": "all_completed_within_window",
            "required_count": None,
            "window_seconds": 25,
            "correlation_scope": "global",
            "correlation_fields": [],
            "maximum_matches": 10,
            "label": "窗口联合",
        },
        None,
        "join",
    )
    assert len(completed.items) == 1


def test_sequence_supports_independent_transition_windows():
    stages = [
        _events(("a", "A", "person_1", 0, 1)),
        _events(("b", "B", "person_1", 4, 5)),
        _events(("c", "C", "person_1", 12, 12)),
    ]
    result = temporal_sequence_v2(
        {"events": stages},
        {
            "transitions": [
                {"minimum_delay_seconds": 2, "maximum_delay_seconds": 4},
                {"minimum_delay_seconds": 5, "maximum_delay_seconds": 8},
            ],
            "correlation_scope": "track",
            "correlation_fields": [],
            "consume_events": True,
            "label": "流程成功",
        },
        None,
        "sequence",
    )
    assert len(result.items) == 1
    assert result.items[0].entity_id == "person_1"


def test_absence_and_repeat_cover_negative_and_frequency_patterns():
    anchors = _events(("entry", "进入", "person_1", 10, 10))
    forbidden = _events(("helmet", "佩戴安全帽", "person_2", 9, 9))
    absent = temporal_absence(
        {"anchors": anchors, "forbidden": forbidden},
        {"before_seconds": 2, "after_seconds": 0, "same_key": True, "label": "未戴安全帽"},
        None,
        "absence",
    )
    assert len(absent.items) == 1

    repeated = temporal_repeat(
        {"events": _events(
            ("e1", "闯入", "person_1", 0, 0),
            ("e2", "闯入", "person_1", 4, 4),
            ("e3", "闯入", "person_1", 9, 9),
        )},
        {"window_seconds": 10, "minimum_count": 3, "same_key": True, "label": "多次闯入"},
        None,
        "repeat",
    )
    assert len(repeated.items) == 1


def test_sequence_temporal_relations_and_trigger_cooldown_are_executable():
    containing = _events(("a", "作业", "person_1", 0, 10))
    inside = _events(("b", "违规", "person_1", 3, 4))
    related = temporal_sequence_v2(
        {"events": [containing, inside]},
        {
            "transitions": [{
                "relation": "during",
                "source_anchor": "start",
                "target_anchor": "start",
                "minimum_delay_seconds": 0,
                "maximum_delay_seconds": 5,
            }],
            "correlation_scope": "track",
            "correlation_fields": [],
            "consume_events": True,
            "label": "作业期间违规",
        },
        None,
        "relation",
    )
    assert len(related.items) == 1

    triggered = event_trigger(
        {"events": _events(
            ("e1", "告警", "person_1", 0, 0),
            ("e2", "告警", "person_1", 2, 2),
            ("e3", "告警", "person_1", 8, 8),
        )},
        {
            "repeat_policy": "allow_repeat",
            "cooldown_seconds": 5,
            "cooldown_scope": "entity",
            "severity": "high",
            "notification_enabled": True,
            "label": "高优先级告警",
        },
        None,
        "trigger",
    )
    assert [item.start_time for item in triggered.items] == [0, 8]
    assert triggered.items[0].metadata["severity"] == "high"


def test_event_pattern_atoms_are_registered():
    registry = build_default_registry()
    for op in (
        "temporal.join@1.0",
        "temporal.sequence@2.0",
        "temporal.absence@1.0",
        "temporal.repeat@1.0",
    ):
        assert registry.require(op).execution_scope == "stream"
    assert registry.require("event.trigger@2.0").execution_scope == "event"
