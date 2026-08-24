from __future__ import annotations

from dataclasses import dataclass

from .business_result_schema import BusinessOutputValue


@dataclass(frozen=True)
class ResultRendererDefinition:
    renderer_id: str
    display_name: str
    semantic_types: frozenset[str]
    value_shapes: frozenset[str]

    def supports(self, result: BusinessOutputValue) -> bool:
        return (
            ("*" in self.semantic_types or result.semantic_type in self.semantic_types)
            and ("*" in self.value_shapes or result.value_shape in self.value_shapes)
        )


class ResultRendererRegistry:
    def __init__(self, definitions: list[ResultRendererDefinition] | None = None):
        self._definitions: dict[str, ResultRendererDefinition] = {}
        for definition in definitions or default_result_renderers():
            self.register(definition)

    def register(self, definition: ResultRendererDefinition) -> None:
        if definition.renderer_id in self._definitions:
            raise ValueError(f"duplicate result renderer: {definition.renderer_id}")
        self._definitions[definition.renderer_id] = definition

    def select(
        self, result: BusinessOutputValue, preferred: str | None = None
    ) -> ResultRendererDefinition:
        candidate = self._definitions.get(preferred or "")
        if candidate is not None and candidate.supports(result):
            return candidate
        for renderer_id in (
            "decision.status",
            "scalar.metric",
            "entity.list",
            "track.list",
            "event.list",
            "timeline.stages",
            "resource.summary",
            "media.preview",
        ):
            candidate = self._definitions[renderer_id]
            if candidate.supports(result):
                return candidate
        return self._definitions["generic.summary"]

    def definitions(self) -> list[ResultRendererDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]


def default_result_renderers() -> list[ResultRendererDefinition]:
    return [
        ResultRendererDefinition(
            "decision.status", "判定状态", frozenset({"decision", "boolean"}), frozenset({"single"})
        ),
        ResultRendererDefinition(
            "scalar.metric", "数值指标", frozenset({"scalar"}), frozenset({"single", "grouped", "series"})
        ),
        ResultRendererDefinition(
            "entity.list", "目标列表", frozenset({"entity_set"}), frozenset({"list", "grouped"})
        ),
        ResultRendererDefinition(
            "track.list", "轨迹列表", frozenset({"track_set"}), frozenset({"list", "grouped"})
        ),
        ResultRendererDefinition(
            "event.list", "事件列表", frozenset({"event_set"}), frozenset({"list", "interval", "series"})
        ),
        ResultRendererDefinition(
            "timeline.stages", "阶段时间线", frozenset({"timeline"}), frozenset({"list", "series", "interval"})
        ),
        ResultRendererDefinition(
            "resource.summary", "场景资源", frozenset({"resource"}), frozenset({"*"})
        ),
        ResultRendererDefinition(
            "media.preview", "媒体结果", frozenset({"media"}), frozenset({"single", "list"})
        ),
        ResultRendererDefinition(
            "generic.summary", "通用结果摘要", frozenset({"*"}), frozenset({"*"})
        ),
    ]


__all__ = [
    "ResultRendererDefinition",
    "ResultRendererRegistry",
    "default_result_renderers",
]
