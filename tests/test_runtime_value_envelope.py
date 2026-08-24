from __future__ import annotations

from core.context import ObjectSet, VisualObject
from core.runtime_values import LegacyOutputEnvelopeAdapter


def test_legacy_object_output_becomes_typed_envelope_with_box_evidence():
    objects = ObjectSet(
        [
            VisualObject(
                id="person_1",
                label="person",
                phrase="person",
                bbox=(0.1, 0.2, 0.4, 0.8),
                frame_index=7,
                timestamp=1.4,
                source_node="detect",
            )
        ]
    )

    envelope, evidence = LegacyOutputEnvelopeAdapter().wrap(
        run_id="run_1",
        source_node_id="detect",
        business_source_ref="branch:red_clothes",
        value=objects,
        media_asset_id="media_1",
    )

    assert envelope.value_type == "entity_set"
    assert envelope.value_shape == "list"
    assert envelope.business_source_ref == "branch:red_clothes"
    assert envelope.entity_refs == ["person_1"]
    assert len(envelope.evidence_refs) == 1
    assert evidence[0].evidence_type == "box"
    assert evidence[0].geometry["bbox"] == [0.1, 0.2, 0.4, 0.8]
    assert evidence[0].coordinate_space == "normalized_original"


def test_envelope_and_evidence_ids_are_stable_for_replay():
    value = ObjectSet([])
    adapter = LegacyOutputEnvelopeAdapter()
    first, first_evidence = adapter.wrap(
        run_id="run_1",
        source_node_id="empty",
        business_source_ref="output:detections",
        value=value,
        media_asset_id="media_1",
    )
    second, second_evidence = adapter.wrap(
        run_id="run_1",
        source_node_id="empty",
        business_source_ref="output:detections",
        value=value,
        media_asset_id="media_1",
    )
    assert first.value_id == second.value_id
    assert first_evidence == second_evidence == []
