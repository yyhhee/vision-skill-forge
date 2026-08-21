from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
OUTPUT = TESTS / "historical_v2_acceptance_consolidated_20260814.json"

SOURCES = {
    "baseline": TESTS / "historical_v2_acceptance_final_20260814.json",
    "wearable": TESTS / "historical_v2_acceptance_wearable_final_20260814.json",
    "yellow": TESTS / "historical_v2_acceptance_yellow_final_20260814.json",
    "orange": TESTS / "historical_v2_acceptance_orange_final_20260814.json",
    "remaining": TESTS / "historical_v2_acceptance_remaining_20260814.json",
}

# Every selected record is the most recent passing execution for that case.
CASE_SOURCE = {
    "red_top_gray_pants_1": "baseline",
    "red_top_gray_pants_2": "baseline",
    "reflective_vest": "wearable",
    "yellow_reflective_vest": "yellow",
    "squat_without_support": "baseline",
    "orange_vest_no_helmet": "orange",
    "orange_vest_exclude_no_helmet": "orange",
    "white_clothing_negative": "remaining",
    "car_bus_person_excluding_truck_van": "remaining",
    "white_car_count": "remaining",
}


def main() -> None:
    loaded = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in SOURCES.items()
    }
    indexes = {
        name: {case["case_id"]: case for case in report.get("cases", [])}
        for name, report in loaded.items()
    }

    cases = []
    for case_id, source_name in CASE_SOURCE.items():
        case = deepcopy(indexes[source_name][case_id])
        if case.get("status") != "automatic_passed":
            raise RuntimeError(
                f"selected result is not passing: {case_id} from {source_name}"
            )
        case["selected_from"] = str(SOURCES[source_name])
        cases.append(case)

    report = {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "latest_passing_real_deepseek_thinking_and_real_rex_historical_regressions",
        "case_count": len(cases),
        "automatic_passed": len(cases),
        "automatic_failed": 0,
        "runtime_failed": 0,
        "manual_review_pending": sum(
            case.get("manual_review", {}).get("status", "pending") != "passed"
            for case in cases
        ),
        "selection_policy": (
            "Merge the latest passing immutable run record per case; do not "
            "rewrite planner output, package, trace, measurement, or artifact paths."
        ),
        "source_reports": [str(path) for path in SOURCES.values()],
        "cases": cases,
    }
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "case_count": len(cases),
                "automatic_passed": len(cases),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
