from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from clients.v2_planner import DeepSeekSemanticPlanner
from core.registry import build_default_registry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests" / "historical_semantic_audit.json"


@dataclass(frozen=True)
class AuditCase:
    case_id: str
    instruction: str
    requested_accept: tuple[str, ...] = ("image",)


CASES = (
    AuditCase("red_gray_1", "检测穿红色上衣、灰色裤子的人。"),
    AuditCase("red_gray_2", "识别穿红色上衣、灰色长裤的人。"),
    AuditCase(
        "squat_exclude",
        "检测图像中的在蹲下的人，姿态为双膝弯曲，排除正坐着的人。",
    ),
    AuditCase("squat_support", "识别蹲着的人，双膝弯曲、臀部无支撑。"),
    AuditCase("reflective", "识别穿反光衣的人。"),
    AuditCase("yellow_reflective", "识别穿着黄色反光衣的人。"),
    AuditCase("orange_no_helmet", "穿着橙色反光衣且未戴安全帽的人。"),
    AuditCase(
        "orange_exclude_no_helmet",
        "穿着橙色反光衣的人，排除未戴安全帽的人。",
    ),
    AuditCase("white_cloth", "识别穿白衣的人。"),
    AuditCase("count_white_car", "识别白色车数量。"),
    AuditCase(
        "multi_entity_exclusion",
        "检测轿车、客车、人，排除货车、面包车。",
    ),
)


def run(
    output: Path = DEFAULT_OUTPUT, selected_cases: set[str] | None = None
) -> dict:
    planner = DeepSeekSemanticPlanner(build_default_registry())
    cases = tuple(
        case
        for case in CASES
        if not selected_cases or case.case_id in selected_cases
    )
    unknown = (selected_cases or set()) - {case.case_id for case in CASES}
    if unknown:
        raise ValueError(f"unknown case ids: {sorted(unknown)}")
    records = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.case_id} RUN", flush=True)
        try:
            result = planner.compile(
                case.instruction,
                requested_accept=list(case.requested_accept),
                skill_id=f"audit_{case.case_id}",
                display_name=case.case_id,
            )
            record = {
                "case_id": case.case_id,
                "instruction": case.instruction,
                "attempts": result.attempts,
                "strategy": result.strategy,
                "errors": result.errors,
                "raw_outputs": result.raw_outputs,
                "status": "compiled" if result.package is not None else "needs_review",
                "semantic_ir": (
                    result.package.semantic_ir.model_dump(mode="json")
                    if result.package is not None
                    else None
                ),
                "workflow_operators": (
                    [
                        node.op
                        for node in result.package.select_variant("image").nodes
                    ]
                    if result.package is not None
                    else []
                ),
            }
        except Exception as exc:  # acceptance evidence must persist failures
            record = {
                "case_id": case.case_id,
                "instruction": case.instruction,
                "status": "exception",
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            }
        records.append(record)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"cases": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[{index}/{len(cases)}] {case.case_id} {record['status']}", flush=True)
    data = {
        "scope": "real_deepseek_v4_flash_thinking_semantic_only",
        "case_count": len(records),
        "compiled": sum(item["status"] == "compiled" for item in records),
        "needs_review": sum(item["status"] == "needs_review" for item in records),
        "exceptions": sum(item["status"] == "exception" for item in records),
        "cases": records,
    }
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: data[key] for key in ("case_count", "compiled", "needs_review", "exceptions")}, ensure_ascii=False), flush=True)
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    run(args.output, set(args.case) or None)


if __name__ == "__main__":
    main()
