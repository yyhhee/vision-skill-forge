from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from clients.rex_client import RexGateway
from clients.v2_planner import DeepSeekSemanticPlanner
from core.persistence import RunStore
from core.registry import build_default_registry
from core.runtime import SkillPackageRuntime


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "tests" / "historical_v2_acceptance_results.json"
RUNS = ROOT / "data" / "historical_runs_v2"
PPE_IMAGE = Path(
    r"C:\yhe_user\detection_project\ultralytics\Codex 图像 2026年8月12日 09_14_00.png"
)


@dataclass(frozen=True)
class Case:
    case_id: str
    instruction: str
    media: Path
    expected_count: int | None = None
    expected_minimum: int | None = None
    expected_maximum: int | None = None
    expected_measurement: int | None = None
    note: str = ""


CASES = (
    Case(
        "red_top_gray_pants_1",
        "检测穿红色上衣、灰色裤子的人。",
        Path(r"C:\yhe_user\detection_project\ultralytics\03.png"),
        expected_count=1,
        note="中央悬吊人员，红色上衣且灰色长裤",
    ),
    Case(
        "red_top_gray_pants_2",
        "识别穿红色上衣、灰色长裤的人。",
        Path(r"C:\yhe_user\detection_project\ultralytics\03.png"),
        expected_count=1,
        note="同义改写应得到同一目标框",
    ),
    Case(
        "reflective_vest",
        "识别穿反光衣的人。",
        PPE_IMAGE,
        expected_count=6,
        note="六名穿反光衣人员，含站立和蹲姿",
    ),
    Case(
        "yellow_reflective_vest",
        "识别穿着黄色反光衣的人。",
        PPE_IMAGE,
        expected_count=2,
        note="仅左侧两名荧光黄色反光衣人员",
    ),
    Case(
        "squat_without_support",
        "识别蹲着的人，双膝弯曲、臀部无支撑。",
        PPE_IMAGE,
        expected_count=1,
        note="中央蹲姿人员；排除站立与有支撑坐姿",
    ),
    Case(
        "orange_vest_no_helmet",
        "穿着橙色反光衣且未戴安全帽的人。",
        PPE_IMAGE,
        expected_count=1,
        note="橙色反光衣且无头戴安全帽",
    ),
    Case(
        "orange_vest_exclude_no_helmet",
        "穿着橙色反光衣的人，排除未戴安全帽的人。",
        PPE_IMAGE,
        expected_count=2,
        note="三名橙色反光衣人员中排除一名未戴安全帽者，保留两名戴帽者",
    ),
    Case(
        "white_clothing_negative",
        "识别穿白衣的人。",
        PPE_IMAGE,
        expected_count=0,
        note="场景中没有白色衣物人员",
    ),
    Case(
        "car_bus_person_excluding_truck_van",
        "检测轿车、客车、人，排除货车、面包车。",
        Path(r"C:\yhe_user\detection_project\ultralytics\smoke.png"),
        expected_minimum=1,
        note="最终结果不得包含左侧货车/面包车框；人工几何复核",
    ),
    Case(
        "white_car_count",
        "识别白色车数量。",
        ROOT / "data" / "acceptance_media" / "generated" / "shared_normal_highway.png",
        expected_minimum=1,
        expected_measurement=4,
        note="白色车目标框与右上角计数应一致",
    ),
)


def _measurement_value(result: dict[str, Any]) -> int | None:
    values = [item["value"] for item in result.get("measurements", [])]
    if not values:
        return None
    return int(values[-1])


def run(output: Path = RESULTS, selected: set[str] | None = None) -> dict:
    cases = tuple(case for case in CASES if not selected or case.case_id in selected)
    unknown = (selected or set()) - {case.case_id for case in CASES}
    if unknown:
        raise ValueError(f"unknown case ids: {sorted(unknown)}")
    registry = build_default_registry()
    planner = DeepSeekSemanticPlanner(registry)
    runtime = SkillPackageRuntime(
        registry, rex=RexGateway(), run_store=RunStore(RUNS)
    )
    records = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.case_id} COMPILE", flush=True)
        base = {**asdict(case), "media": str(case.media.resolve())}
        try:
            compiled = planner.compile(
                case.instruction,
                requested_accept=["image"],
                skill_id=f"historical_{case.case_id}",
                display_name=case.case_id,
            )
            base.update(
                {
                    "planner_attempts": compiled.attempts,
                    "planner_errors": compiled.errors,
                    "planner_raw_outputs": compiled.raw_outputs,
                }
            )
            if compiled.package is None:
                raise ValueError("planner returned needs_review")
            package = compiled.package
            print(f"[{index}/{len(cases)}] {case.case_id} REX", flush=True)
            record = runtime.run(package, package, case.media)
            result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
            actual_count = record.object_count
            actual_measurement = _measurement_value(result)
            checks = {
                "annotated_media_exists": bool(
                    record.annotated_media and record.annotated_media.is_file()
                ),
                "expected_count_passed": (
                    case.expected_count is None or actual_count == case.expected_count
                ),
                "minimum_passed": (
                    case.expected_minimum is None
                    or actual_count >= case.expected_minimum
                ),
                "maximum_passed": (
                    case.expected_maximum is None
                    or actual_count <= case.expected_maximum
                ),
                "measurement_passed": (
                    case.expected_measurement is None
                    or actual_measurement == case.expected_measurement
                ),
                "manual_visual_review": "pending",
            }
            base.update(
                {
                    "status": "automatic_passed"
                    if all(
                        value is True
                        for key, value in checks.items()
                        if key != "manual_visual_review"
                    )
                    else "automatic_failed",
                    "semantic_ir": package.semantic_ir.model_dump(mode="json"),
                    "package": package.model_dump(mode="json"),
                    "actual_count": actual_count,
                    "actual_measurement": actual_measurement,
                    "actual_rex_phrases": result["actual_rex_phrases"],
                    "constraint_summary": result["constraint_summary"],
                    "detections": result["detections"],
                    "checks": checks,
                    "run_dir": str(record.run_dir.resolve()),
                    "annotated_media": str(record.annotated_media.resolve())
                    if record.annotated_media
                    else None,
                }
            )
        except Exception as exc:
            base.update(
                {
                    "status": "runtime_failed",
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                }
            )
        records.append(base)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"cases": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"[{index}/{len(cases)}] {case.case_id} {base['status']}", flush=True
        )
    data = {
        "schema_version": "2.0",
        "review_date": str(date.today()),
        "scope": "current_v2_real_deepseek_thinking_and_real_rex_historical_failures",
        "case_count": len(records),
        "automatic_passed": sum(
            item["status"] == "automatic_passed" for item in records
        ),
        "automatic_failed": sum(
            item["status"] == "automatic_failed" for item in records
        ),
        "runtime_failed": sum(
            item["status"] == "runtime_failed" for item in records
        ),
        "manual_review_pending": len(records),
        "cases": records,
    }
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: data[k] for k in ("case_count", "automatic_passed", "automatic_failed", "runtime_failed")}), flush=True)
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RESULTS)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    run(args.output, set(args.case) or None)


if __name__ == "__main__":
    main()
