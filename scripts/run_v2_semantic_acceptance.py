from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from clients.rex_client import RexGateway
from core.persistence import RunStore
from core.registry import build_default_registry
from core.runtime import SkillPackageRuntime, detect_media_type
from core.schema import SkillPackage
from core.validator import validate_skill_package


ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / "presets_v2"
RUNS = ROOT / "data" / "runs_v2"
RESULTS = ROOT / "tests" / "preset_v2_acceptance_results.json"
GENERATED = ROOT / "data" / "acceptance_media" / "generated"
VIDEOS = ROOT / "data" / "acceptance_media" / "v2"
IMAGES = ROOT / "imgs"


@dataclass(frozen=True)
class AcceptanceCase:
    case_id: str
    preset_id: str
    variant: str
    case_kind: str
    media: Path
    signal: str
    minimum: int = 0
    maximum: int | None = None
    labels_all: tuple[str, ...] = ()
    labels_any: tuple[str, ...] = ()
    expected_note: str = ""
    source_type: str = "project_fixture"
    source_note: str = "项目已有或用户提供的演示素材"


def _case(
    preset_id: str,
    variant: str,
    kind: str,
    media: Path,
    signal: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
    labels_all: tuple[str, ...] = (),
    labels_any: tuple[str, ...] = (),
    expected_note: str,
    generated: bool = False,
) -> AcceptanceCase:
    return AcceptanceCase(
        f"{preset_id}_{variant}_{kind}",
        preset_id,
        variant,
        kind,
        media,
        signal,
        minimum,
        maximum,
        labels_all,
        labels_any,
        expected_note,
        "generated_or_derived_fixture" if generated else "project_fixture",
        "OpenAI 生成或由项目图片派生的受控验收素材"
        if generated
        else "项目已有或用户提供的演示素材",
    )


NORMAL_IMAGE = GENERATED / "shared_normal_highway.png"
NORMAL_VIDEO = VIDEOS / "shared_normal_highway_moving.mp4"


CASES: tuple[AcceptanceCase, ...] = (
    _case("P01", "image", "positive", IMAGES / "P01_fire_smoke.jpg", "objects", minimum=1, labels_any=("烟火",), expected_note="可见烟雾或明火"),
    _case("P01", "image", "negative", NORMAL_IMAGE, "objects", maximum=0, expected_note="正常高速无烟火", generated=True),
    _case("P01", "image", "confusion", GENERATED / "P01_water_vapor_confusion.png", "objects", maximum=0, expected_note="白色水汽不应当作烟火", generated=True),
    _case("P01", "video", "positive", VIDEOS / "P01_positive.mp4", "events", minimum=1, expected_note="烟火持续可见形成事件", generated=True),
    _case("P01", "video", "negative", NORMAL_VIDEO, "events", maximum=0, expected_note="正常行驶视频无烟火事件", generated=True),
    _case("P01", "video", "confusion", VIDEOS / "P01_water_vapor_confusion.mp4", "events", maximum=0, expected_note="持续水汽不应形成烟火事件", generated=True),

    _case("P02", "image", "positive", IMAGES / "P02_traffic_accident.jpg", "objects", minimum=1, labels_any=("交通事故",), expected_note="可见碰撞或事故外观"),
    _case("P02", "image", "negative", NORMAL_IMAGE, "objects", maximum=0, expected_note="正常高速无事故", generated=True),
    _case("P02", "image", "confusion", IMAGES / "P07_illegal_parking.jpg", "objects", maximum=0, expected_note="单车靠边停放不等于交通事故"),
    _case("P02", "video", "positive", VIDEOS / "P02_positive.mp4", "events", minimum=1, expected_note="事故外观持续可见形成事件", generated=True),
    _case("P02", "video", "negative", NORMAL_VIDEO, "events", maximum=0, expected_note="正常行驶视频无事故事件", generated=True),
    _case("P02", "video", "confusion", VIDEOS / "P07_positive.mp4", "events", maximum=0, expected_note="静止停靠车辆不应形成事故事件", generated=True),

    _case("P03", "image", "positive", IMAGES / "P03_special_vehicles.jpg", "objects", minimum=3, labels_all=("消防车", "救护车", "警车"), expected_note="消防车、救护车、警车分别标注"),
    _case("P03", "image", "negative", NORMAL_IMAGE, "objects", maximum=0, expected_note="普通车辆不应标为特种车辆", generated=True),
    _case("P03", "image", "confusion", IMAGES / "P04_highway_congestion.jpg", "objects", maximum=0, expected_note="密集普通车辆不应标为特种车辆"),
    _case("P03", "video", "positive", VIDEOS / "P03_positive.mp4", "objects", minimum=3, labels_all=("消防车", "救护车", "警车"), expected_note="视频逐帧保留三类特种车辆", generated=True),
    _case("P03", "video", "negative", NORMAL_VIDEO, "objects", maximum=0, expected_note="普通高速视频无特种车辆", generated=True),
    _case("P03", "video", "confusion", VIDEOS / "P04_positive.mp4", "objects", maximum=0, expected_note="拥堵普通车辆不应标为特种车辆", generated=True),

    _case("P04", "video", "positive", VIDEOS / "P04_positive.mp4", "events", minimum=1, expected_note="车辆数不少于4、低速且持续", generated=True),
    _case("P04", "video", "negative", NORMAL_VIDEO, "events", maximum=0, expected_note="正常流动车流不拥堵", generated=True),
    _case("P04", "video", "confusion", VIDEOS / "P04_confusion_few_stationary.mp4", "events", maximum=0, expected_note="少量静止车辆不满足数量条件", generated=True),

    _case("P05", "video", "positive", VIDEOS / "P05_positive_short.mp4", "events", minimum=1, expected_note="存在相对多数车辆方向相反且持续的轨迹", generated=True),
    _case("P05", "video", "negative", NORMAL_VIDEO, "events", maximum=0, expected_note="同向正常车流无逆行", generated=True),
    _case("P05", "video", "confusion", VIDEOS / "P04_positive.mp4", "events", maximum=0, expected_note="低速拥堵不等于逆行", generated=True),

    _case("P06", "video", "positive", VIDEOS / "P06_positive.mp4", "events", minimum=1, expected_note="人员位于车道ROI并持续", generated=True),
    _case("P06", "video", "negative", VIDEOS / "P06_negative_long.mp4", "events", maximum=0, expected_note="无人车道无人员逗留", generated=True),
    _case("P06", "video", "confusion", VIDEOS / "P06_confusion_outside_lane_long.mp4", "events", maximum=0, expected_note="车道外人员不应触发车道逗留", generated=True),

    _case("P07", "video", "positive", VIDEOS / "P07_positive.mp4", "events", minimum=1, expected_note="车辆位于禁停ROI、低速且持续", generated=True),
    _case("P07", "video", "negative", VIDEOS / "P07_negative_moving_long.mp4", "events", maximum=0, expected_note="正常流动车辆不违停", generated=True),
    _case("P07", "video", "confusion", VIDEOS / "P07_confusion_vehicle_outside_roi_long.mp4", "events", maximum=0, expected_note="ROI外静止车辆不应触发违停", generated=True),

    _case("P08", "image", "positive", IMAGES / "P08_road_debris.jpg", "objects", minimum=1, labels_any=("道路抛洒物",), expected_note="道路区域存在抛洒物"),
    _case("P08", "image", "negative", NORMAL_IMAGE, "objects", maximum=0, expected_note="清洁道路无抛洒物", generated=True),
    _case("P08", "image", "confusion", IMAGES / "P07_illegal_parking.jpg", "objects", maximum=0, expected_note="完整车辆不是道路抛洒物"),
    _case("P08", "video", "positive", VIDEOS / "P08_positive.mp4", "objects", minimum=1, labels_any=("道路抛洒物",), expected_note="视频逐帧检测道路抛洒物", generated=True),
    _case("P08", "video", "negative", NORMAL_VIDEO, "objects", maximum=0, expected_note="清洁道路视频无抛洒物", generated=True),
    _case("P08", "video", "confusion", VIDEOS / "P07_positive.mp4", "objects", maximum=0, expected_note="停靠车辆不是道路抛洒物", generated=True),

    _case("P09", "image", "positive", ROOT / "data" / "acceptance_media" / "ppe_one_without_helmet.png", "objects", minimum=1, maximum=1, labels_any=("未戴安全帽人员",), expected_note="仅框出唯一未戴安全帽人员"),
    _case("P09", "image", "negative", Path(r"C:\yhe_user\detection_project\ultralytics\03.png"), "objects", maximum=0, expected_note="所有施工人员均正确佩戴安全帽"),
    _case("P09", "image", "confusion", GENERATED / "P09_helmet_in_hand_not_worn.png", "objects", minimum=1, maximum=1, expected_note="手持安全帽但未佩戴仍应违规", generated=True),
    _case("P09", "video", "positive", VIDEOS / "P09_positive.mp4", "objects", minimum=1, expected_note="视频逐帧识别未戴安全帽人员", generated=True),
    _case("P09", "video", "negative", VIDEOS / "P09_negative.mp4", "objects", maximum=0, expected_note="视频中所有人员均戴安全帽", generated=True),
    _case("P09", "video", "confusion", VIDEOS / "P09_confusion_helmet_in_hand.mp4", "objects", minimum=1, expected_note="视频中手持未佩戴仍应违规", generated=True),

    _case("P10", "image", "positive", IMAGES / "P10_no_safety_rope.jpg", "objects", minimum=1, maximum=1, labels_any=("未系安全绳人员",), expected_note="无连接挂钩的高处作业人员应违规"),
    _case("P10", "image", "negative", GENERATED / "P10_harness_connected.png", "objects", maximum=0, expected_note="挂钩位于人员上方锚点区视为已连接", generated=True),
    _case("P10", "image", "confusion", GENERATED / "P10_harness_unconnected.png", "objects", minimum=1, maximum=1, expected_note="有安全带但挂钩悬空仍应违规", generated=True),
    _case("P10", "video", "positive", VIDEOS / "P10_positive.mp4", "objects", minimum=1, expected_note="视频逐帧识别无连接挂钩人员", generated=True),
    _case("P10", "video", "negative", VIDEOS / "P10_negative.mp4", "objects", maximum=0, expected_note="视频中挂钩已连接锚点", generated=True),
    _case("P10", "video", "confusion", VIDEOS / "P10_confusion_unconnected.mp4", "objects", minimum=1, expected_note="视频中挂钩悬空仍应违规", generated=True),

    _case("P11", "image", "positive", IMAGES / "P11.png", "objects", minimum=1, labels_all=("垃圾容器", "溢出垃圾"), expected_note="服务区存在垃圾容器及其上沿的溢出垃圾"),
    _case("P11", "image", "negative", GENERATED / "P11_clean_service_area.png", "objects", maximum=0, expected_note="干净服务区无垃圾", generated=True),
    _case("P11", "image", "confusion", GENERATED / "P11_ordered_packages_confusion.png", "objects", maximum=0, expected_note="整齐包装货物不是垃圾", generated=True),
    _case("P11", "video", "positive", VIDEOS / "P11_positive.mp4", "objects", minimum=1, labels_any=("垃圾",), expected_note="巡检视频逐帧检测垃圾", generated=True),
    _case("P11", "video", "negative", VIDEOS / "P11_negative.mp4", "objects", maximum=0, expected_note="干净服务区视频无垃圾", generated=True),
    _case("P11", "video", "confusion", VIDEOS / "P11_ordered_packages_confusion.mp4", "objects", maximum=0, expected_note="包装货物视频不应报垃圾", generated=True),

    _case("P12", "video", "positive", VIDEOS / "P12_positive_transition.mp4", "events", minimum=1, expected_note="站立到失衡再倒地并持续形成事件", generated=True),
    _case("P12", "video", "negative", VIDEOS / "P12_negative_standing.mp4", "events", maximum=0, expected_note="持续站立无摔倒事件", generated=True),
    _case("P12", "video", "confusion", VIDEOS / "P12_confusion_fall_without_persistence.mp4", "events", maximum=0, expected_note="短暂失衡后恢复不满足持续条件", generated=True),

    _case("P13", "image", "positive", IMAGES / "P13.png", "objects", minimum=1, labels_any=("裂纹", "锈蚀", "渗水", "混凝土剥落", "露筋"), expected_note="桥梁表面存在可见病害"),
    _case("P13", "image", "negative", GENERATED / "P13_clean_bridge.png", "objects", maximum=0, expected_note="完好桥梁无病害", generated=True),
    _case("P13", "image", "confusion", GENERATED / "P13_intact_bridge_with_joints.png", "objects", maximum=0, expected_note="规则施工缝不应报裂纹", generated=True),
    _case("P13", "video", "positive", VIDEOS / "P13_positive.mp4", "objects", minimum=1, labels_any=("裂纹", "锈蚀", "渗水", "混凝土剥落", "露筋"), expected_note="巡检视频逐帧检测桥梁病害", generated=True),
    _case("P13", "video", "negative", VIDEOS / "P13_negative.mp4", "objects", maximum=0, expected_note="完好桥梁视频无病害", generated=True),
    _case("P13", "video", "confusion", VIDEOS / "P13_confusion_joints.mp4", "objects", maximum=0, expected_note="施工缝视频不应报裂纹", generated=True),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _package_path(preset_id: str) -> Path:
    matches = sorted(PRESETS.glob(f"{preset_id}_*.json"))
    if len(matches) != 1:
        raise ValueError(f"expected one V2 preset for {preset_id}, got {matches}")
    return matches[0]


def _package_sha256(package: SkillPackage) -> str:
    canonical = json.dumps(
        package.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_existing() -> dict[str, Any]:
    if not RESULTS.exists():
        return {
            "schema_version": "2.0",
            "updated_date": str(date.today()),
            "scope": "v2_real_rex_positive_negative_confusion_by_declared_variant",
            "cases": [],
            "summary": {},
        }
    return json.loads(RESULTS.read_text("utf-8"))


def _write_results(data: dict[str, Any]) -> None:
    cases = data["cases"]
    statuses = [item.get("semantic_status") for item in cases]
    data["updated_date"] = str(date.today())
    data["summary"] = {
        "declared_case_count": len(CASES),
        "executed_case_count": len(cases),
        "semantic_passed": statuses.count("semantic_passed"),
        "semantic_failed": statuses.count("semantic_failed"),
        "runtime_failed": statuses.count("runtime_failed"),
        "pending": len(CASES) - len(cases),
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _actual_labels(result: dict[str, Any]) -> set[str]:
    labels = {item["label"] for item in result.get("detections", [])}
    labels.update(item["label"] for item in result.get("tracks", []))
    labels.update(item["label"] for item in result.get("events", []))
    return labels


def _semantic_check(case: AcceptanceCase, record, result: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    signal_value = (
        len(result.get("events", []))
        if case.signal == "events"
        else record.object_count
    )
    labels = _actual_labels(result)
    checks = {
        "signal": case.signal,
        "actual_value": signal_value,
        "minimum": case.minimum,
        "maximum": case.maximum,
        "minimum_passed": signal_value >= case.minimum,
        "maximum_passed": case.maximum is None or signal_value <= case.maximum,
        "actual_labels": sorted(labels),
        "labels_all": list(case.labels_all),
        "labels_any": list(case.labels_any),
        "labels_all_passed": set(case.labels_all) <= labels,
        "labels_any_passed": not case.labels_any or bool(set(case.labels_any) & labels),
        "annotated_media_exists": bool(
            record.annotated_media and record.annotated_media.is_file()
        ),
    }
    passed = all(
        checks[key]
        for key in (
            "minimum_passed",
            "maximum_passed",
            "labels_all_passed",
            "labels_any_passed",
            "annotated_media_exists",
        )
    )
    return passed, checks


def _case_record(
    case: AcceptanceCase,
    package: SkillPackage,
    package_sha256: str,
    runtime: SkillPackageRuntime,
) -> dict[str, Any]:
    media = case.media.resolve()
    media_sha256 = _sha256(media)
    structure_errors = validate_skill_package(package, runtime.registry)
    base = {
        **asdict(case),
        "media": str(media),
        "media_sha256": media_sha256,
        "package_sha256": package_sha256,
        "skill_id": package.skill_id,
        "skill_version": package.version,
        "instruction": package.original_instruction,
        "semantic_hash": package.semantic_ir.semantic_hash,
        "structure_status": "structure_passed" if not structure_errors else "structure_failed",
        "structure_errors": structure_errors,
        "review_date": str(date.today()),
    }
    if structure_errors:
        return {
            **base,
            "runtime_status": "not_executed",
            "semantic_status": "runtime_failed",
            "error": "; ".join(structure_errors),
        }
    try:
        record = runtime.run(package, package, media)
        result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
        passed, checks = _semantic_check(case, record, result)
        return {
            **base,
            "runtime_status": record.status,
            "semantic_status": "semantic_passed" if passed else "semantic_failed",
            "run_id": record.run_id,
            "run_dir": str(record.run_dir.resolve()),
            "annotated_media": str(record.annotated_media.resolve())
            if record.annotated_media
            else None,
            "object_count": record.object_count,
            "event_count": record.event_count,
            "actual_rex_phrases": result["actual_rex_phrases"],
            "rex_model": result["rex_model"],
            "checks": checks,
        }
    except Exception as exc:
        return {
            **base,
            "runtime_status": "execution_failed",
            "semantic_status": "runtime_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def run(
    *,
    preset_ids: set[str] | None = None,
    case_ids: set[str] | None = None,
    resume: bool = True,
) -> None:
    registry = build_default_registry()
    runtime = SkillPackageRuntime(
        registry,
        rex=RexGateway(),
        run_store=RunStore(RUNS),
    )
    data = _load_existing()
    by_id = {item["case_id"]: item for item in data["cases"]}
    selected = [
        case
        for case in CASES
        if (not preset_ids or case.preset_id in preset_ids)
        and (not case_ids or case.case_id in case_ids)
    ]
    for index, case in enumerate(selected, start=1):
        if not case.media.is_file():
            raise FileNotFoundError(case.media)
        if detect_media_type(case.media) != case.variant:
            raise ValueError(f"{case.case_id}: media type does not match variant")
        package = SkillPackage.model_validate_json(
            _package_path(case.preset_id).read_text("utf-8")
        )
        package_sha = _package_sha256(package)
        media_sha = _sha256(case.media)
        existing = by_id.get(case.case_id)
        if (
            resume
            and existing
            and existing.get("package_sha256") == package_sha
            and existing.get("media_sha256") == media_sha
            and existing.get("semantic_status") in {"semantic_passed", "semantic_failed"}
        ):
            print(
                f"[{index}/{len(selected)}] {case.case_id} SKIP "
                f"{existing['semantic_status']}",
                flush=True,
            )
            continue
        print(f"[{index}/{len(selected)}] {case.case_id} RUN", flush=True)
        item = _case_record(case, package, package_sha, runtime)
        by_id[case.case_id] = item
        data["cases"] = [by_id[key] for key in sorted(by_id)]
        _write_results(data)
        print(
            f"[{index}/{len(selected)}] {case.case_id} "
            f"{item['semantic_status']} objects={item.get('object_count')} "
            f"events={item.get('event_count')}",
            flush=True,
        )
    _write_results(data)
    print(json.dumps(data["summary"], ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", action="append", default=[])
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    run(
        preset_ids=set(args.preset) or None,
        case_ids=set(args.case) or None,
        resume=not args.no_resume,
    )


if __name__ == "__main__":
    main()
