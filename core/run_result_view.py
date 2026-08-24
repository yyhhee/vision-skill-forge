from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .business_result_schema import RunResult
from .result_presentation_schema import PresentationSpec
from .result_renderer_registry import ResultRendererRegistry
from .schema import StrictModel


class ResultCardView(StrictModel):
    result_id: str
    title: str
    status: str
    renderer_id: str
    value: Any = None
    unit: str | None = None
    reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    accessible_text: str
    display_order: int = 0
    overview_span: str = "normal"


class BranchCardView(StrictModel):
    branch_id: str
    title: str
    status: str
    reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    value: Any = None


class RunResultViewModel(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    final_result: dict[str, Any]
    business_outputs: list[ResultCardView] = Field(default_factory=list)
    branch_results: list[BranchCardView] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


def _accessible_text(title: str, status: str, value: Any, unit: str | None, reason: str | None) -> str:
    value_text = "" if value is None else f"，值为 {value}{unit or ''}"
    reason_text = "" if not reason else f"，{reason}"
    return f"{title}：{status}{value_text}{reason_text}"


def build_run_result_view(
    result: RunResult,
    presentations: list[PresentationSpec],
    registry: ResultRendererRegistry | None = None,
) -> RunResultViewModel:
    registry = registry or ResultRendererRegistry()
    presentation_by_id = {item.result_id: item for item in presentations}
    cards = []
    for output in result.business_outputs:
        presentation = presentation_by_id.get(output.result_id) or PresentationSpec(
            result_id=output.result_id
        )
        renderer = registry.select(output, presentation.preferred_renderer)
        cards.append(
            ResultCardView(
                result_id=output.result_id,
                title=output.display_name,
                status=output.status,
                renderer_id=renderer.renderer_id,
                value=output.value,
                unit=output.unit,
                reason=output.reason,
                evidence_refs=output.evidence_refs,
                accessible_text=_accessible_text(
                    output.display_name,
                    output.status,
                    output.value,
                    output.unit,
                    output.reason,
                ),
                display_order=presentation.display_order,
                overview_span=presentation.overview_span,
            )
        )
    cards.sort(key=lambda item: (item.display_order, item.result_id))
    branches = [
        BranchCardView(
            branch_id=item.branch_id,
            title=item.display_name,
            status=item.status,
            reason=item.reason,
            evidence_refs=item.evidence_refs,
            value=item.value,
        )
        for item in result.branch_results
    ]
    evidence_refs = list(
        dict.fromkeys(
            [
                *result.final_result.evidence_refs,
                *(ref for card in cards for ref in card.evidence_refs),
                *(ref for branch in branches for ref in branch.evidence_refs),
            ]
        )
    )
    return RunResultViewModel(
        run_id=result.run_id,
        final_result=result.final_result.model_dump(mode="json"),
        business_outputs=cards,
        branch_results=branches,
        evidence_refs=evidence_refs,
        diagnostics=result.diagnostics,
    )


__all__ = [
    "BranchCardView",
    "ResultCardView",
    "RunResultViewModel",
    "build_run_result_view",
]
