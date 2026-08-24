from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .runtime_values import EvidenceRecord


class EvidenceIndex:
    """Deterministic, serializable index over immutable EvidenceRecords."""

    def __init__(self, records: Iterable[EvidenceRecord] = ()):
        self._records: dict[str, EvidenceRecord] = {}
        self._by_entity: dict[str, set[str]] = defaultdict(set)
        self._by_resource: dict[str, set[str]] = defaultdict(set)
        self._by_type: dict[str, set[str]] = defaultdict(set)
        self._by_producer: dict[str, set[str]] = defaultdict(set)
        for record in records:
            self.add(record)

    def add(self, record: EvidenceRecord) -> EvidenceRecord:
        existing = self._records.get(record.evidence_id)
        if existing is not None:
            if existing != record:
                raise ValueError(f"conflicting evidence_id: {record.evidence_id}")
            return existing
        self._records[record.evidence_id] = record
        self._by_type[record.evidence_type].add(record.evidence_id)
        self._by_producer[record.produced_by].add(record.evidence_id)
        for entity_ref in record.entity_refs:
            self._by_entity[entity_ref].add(record.evidence_id)
        for resource_ref in record.resource_refs:
            self._by_resource[resource_ref].add(record.evidence_id)
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self._records.get(evidence_id)

    def require(self, evidence_id: str) -> EvidenceRecord:
        record = self.get(evidence_id)
        if record is None:
            raise KeyError(f"unknown evidence: {evidence_id}")
        return record

    def query(
        self,
        *,
        evidence_ids: Iterable[str] | None = None,
        entity_ref: str | None = None,
        resource_ref: str | None = None,
        evidence_type: str | None = None,
        produced_by: str | None = None,
    ) -> list[EvidenceRecord]:
        candidates = set(self._records)
        if evidence_ids is not None:
            candidates &= set(evidence_ids)
        if entity_ref is not None:
            candidates &= self._by_entity.get(entity_ref, set())
        if resource_ref is not None:
            candidates &= self._by_resource.get(resource_ref, set())
        if evidence_type is not None:
            candidates &= self._by_type.get(evidence_type, set())
        if produced_by is not None:
            candidates &= self._by_producer.get(produced_by, set())
        return [self._records[key] for key in sorted(candidates)]

    @property
    def records(self) -> list[EvidenceRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0",
            "records": [record.model_dump(mode="json") for record in self.records],
        }

    @classmethod
    def from_dict(cls, value: dict) -> "EvidenceIndex":
        if value.get("schema_version") != "1.0":
            raise ValueError(
                f"unsupported EvidenceIndex schema: {value.get('schema_version')}"
            )
        return cls(EvidenceRecord.model_validate(item) for item in value.get("records", []))

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["EvidenceIndex"]
