from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .runtime_values import RuntimeValueEnvelope
from .schema import StrictModel


BusinessStatus = Literal[
    "satisfied",
    "not_satisfied",
    "pending",
    "not_evaluable",
    "error",
]


class BusinessOutputValue(StrictModel):
    result_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)
    value_shape: str = Field(min_length=1)
    status: BusinessStatus
    value: Any = None
    unit: str | None = None
    reason: str | None = None
    source_ref: str = Field(min_length=1)
    source_value_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    condition_snapshot: dict[str, Any] = Field(default_factory=dict)


class BranchResult(StrictModel):
    branch_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: BusinessStatus
    value: Any = None
    reason: str | None = None
    source_ref: str = Field(min_length=1)
    source_value_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class FinalResult(StrictModel):
    decision_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    decision_type: str = Field(min_length=1)
    status: BusinessStatus
    value: Any = None
    reason: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_value_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class RunResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    media_asset_id: str | None = None
    media_type: Literal["image", "video"]
    variant: Literal["image", "video"]
    status: Literal["completed", "pending", "not_evaluable", "error"] = "completed"
    final_result: FinalResult
    business_outputs: list[BusinessOutputValue] = Field(default_factory=list)
    branch_results: list[BranchResult] = Field(default_factory=list)
    runtime_values: list[RuntimeValueEnvelope] = Field(default_factory=list)
    semantic_hash: str | None = None
    compile_hash: str | None = None
    package_hash: str | None = None
    presentation_hash: str | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "BranchResult",
    "BusinessOutputValue",
    "BusinessStatus",
    "FinalResult",
    "RunResult",
]
