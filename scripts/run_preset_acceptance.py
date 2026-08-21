from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clients.rex_client import RexGateway
from core.persistence import RunStore
from core.registry import build_default_registry
from core.runtime import SkillRuntime
from core.schema import VisualSkillSpec


RESULTS_PATH = ROOT / "tests" / "preset_test_results.json"
MEDIA_ROOT = ROOT / "data" / "demo_media"
RUN_ROOT = ROOT / "data" / "runs"
EVENT_PRESETS = {"P01", "P02", "P04", "P05", "P06", "P07", "P12"}


def media_for(preset_id: str) -> Path:
    return next(MEDIA_ROOT.glob(f"{preset_id}.*"))


def artifact_map(run_dir: Path):
    annotated = next(run_dir.glob("annotated.*"), None)
    return {
        "generated_skill": str(run_dir / "generated_skill.json"),
        "effective_skill": str(run_dir / "effective_skill.json"),
        "events": str(run_dir / "events.json"),
        "trace": str(run_dir / "trace.json"),
        "annotated_media": str(annotated) if annotated else None,
        "evidence": str(run_dir / "evidence"),
        "run_metadata": str(run_dir / "run.json"),
    }


def run_all():
    results = json.loads(RESULTS_PATH.read_text("utf-8"))
    tests = {item["id"]: item for item in results["tests"]}
    runtime = SkillRuntime(build_default_registry(), rex=RexGateway(), run_store=RunStore(RUN_ROOT))
    for preset_path in sorted((ROOT / "presets").glob("P*.json")):
        preset_id = preset_path.stem[:3]
        item = tests[preset_id]
        media = media_for(preset_id)
        try:
            skill = VisualSkillSpec.model_validate_json(preset_path.read_text("utf-8"))
            record = runtime.run(skill, skill, media)
            positive = record.event_count > 0 if preset_id in EVENT_PRESETS else record.object_count > 0
            complete = record.annotated_media is not None and record.annotated_media.exists()
            status = "passed" if positive and complete else "executed_no_detection"
            item.update({
                "status": status,
                "run_id": record.run_id,
                "media": str(media),
                "artifacts": artifact_map(record.run_dir),
                "executed_date": date.today().isoformat(),
                "object_count": record.object_count,
                "event_count": record.event_count,
                "notes": (f"真实 Rex 端到端执行；objects={record.object_count}, events={record.event_count}. "
                          + ("验收目标已产生。" if positive else "执行完成但未产生该预置要求的目标/事件。")),
            })
        except Exception as exc:
            item.update({
                "status": "execution_failed",
                "run_id": None,
                "media": str(media),
                "artifacts": None,
                "executed_date": date.today().isoformat(),
                "notes": f"{type(exc).__name__}: {exc}",
            })
        RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(preset_id, item["status"], item.get("object_count"), item.get("event_count"), flush=True)
    statuses = [item["status"] for item in results["tests"]]
    results["updated_date"] = date.today().isoformat()
    results["summary"] = {
        "total": len(statuses),
        "passed": statuses.count("passed"),
        "executed_no_detection": statuses.count("executed_no_detection"),
        "execution_failed": statuses.count("execution_failed"),
    }
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    run_all()
