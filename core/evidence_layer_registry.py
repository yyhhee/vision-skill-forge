from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceLayerDefinition:
    layer_id: str
    display_name: str
    evidence_types: frozenset[str]
    media_types: frozenset[str]


class EvidenceLayerRegistry:
    def __init__(self):
        definitions = [
            EvidenceLayerDefinition("boxes", "目标框", frozenset({"box"}), frozenset({"image", "video"})),
            EvidenceLayerDefinition("tracks", "轨迹", frozenset({"track"}), frozenset({"video"})),
            EvidenceLayerDefinition("regions", "区域", frozenset({"region"}), frozenset({"image", "video"})),
            EvidenceLayerDefinition("vectors", "方向", frozenset({"vector"}), frozenset({"image", "video"})),
            EvidenceLayerDefinition("measurements", "数值", frozenset({"measurement", "condition"}), frozenset({"image", "video"})),
            EvidenceLayerDefinition("events", "事件区间", frozenset({"event"}), frozenset({"video"})),
            EvidenceLayerDefinition("media", "媒体片段", frozenset({"frame", "clip", "media"}), frozenset({"image", "video"})),
        ]
        self._definitions = {item.layer_id: item for item in definitions}

    def compatible_layers(
        self, evidence_types: set[str], media_type: str
    ) -> list[EvidenceLayerDefinition]:
        return [
            item
            for item in self._definitions.values()
            if media_type in item.media_types and bool(item.evidence_types & evidence_types)
        ]

    def definitions(self) -> list[EvidenceLayerDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]


__all__ = ["EvidenceLayerDefinition", "EvidenceLayerRegistry"]
