from __future__ import annotations

import pytest

from core.evidence_index import EvidenceIndex
from core.runtime_values import EvidenceRecord


def _record(evidence_id: str, entity: str, evidence_type: str = "box"):
    return EvidenceRecord(
        evidence_id=evidence_id,
        run_id="run_1",
        media_asset_id="media_1",
        evidence_type=evidence_type,
        entity_refs=[entity],
        produced_by="node_1",
    )


def test_evidence_index_round_trips_and_queries_stable_references():
    index = EvidenceIndex([_record("ev_1", "person_1"), _record("ev_2", "person_2")])
    restored = EvidenceIndex.from_dict(index.to_dict())

    assert [item.evidence_id for item in restored.query(entity_ref="person_1")] == [
        "ev_1"
    ]
    assert restored.require("ev_2").entity_refs == ["person_2"]
    assert restored.to_dict() == index.to_dict()


def test_evidence_index_rejects_conflicting_duplicate_ids():
    index = EvidenceIndex([_record("ev_1", "person_1")])
    with pytest.raises(ValueError, match="conflicting evidence_id"):
        index.add(_record("ev_1", "person_2"))
