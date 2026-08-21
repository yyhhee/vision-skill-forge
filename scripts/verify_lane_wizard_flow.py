"""Verify the P04/P05 manual lane-annotation flow end to end (no Rex needed).

Simulates what the Gradio wizard does:
1. Load P04 / P05 presets -> lane_regions must be empty, no synthetic lanes.
2. Draw N (3) named lane polygons via ConfigurationBinder.bind_named_region.
3. P05: draw one direction arrow per saved lane key.
4. configuration_status must reflect pending -> configured; execution must be allowed.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.configuration import ConfigurationBinder, configuration_status
from core.registry import build_default_registry
from core.schema import SkillPackage
from core.validator import validate_skill_package

registry = build_default_registry()
binder = ConfigurationBinder(registry)


def load(preset: str) -> SkillPackage:
    raw = json.loads((ROOT / "presets_v2" / f"{preset}.json").read_text("utf-8"))
    return SkillPackage.model_validate(raw)


def named_polygon(pts):
    return [list(map(float, p)) for p in pts]


def region_items(pkg, node_id="lane_regions"):
    node = next(n for n in pkg.variants["video"].nodes if n.id == node_id)
    return list(node.params.get("regions", []))


def direction_items(pkg, node_id="lane_references"):
    node = next(n for n in pkg.variants["video"].nodes if n.id == node_id)
    return list(node.params.get("directions", []))


def main() -> int:
    failures = []

    # ---------- P04 highway congestion: regions only ----------
    p04 = load("P04_highway_congestion")
    assert not region_items(p04), "P04 must load with zero lane regions"
    slots = {s.slot_id: s for s in p04.variants["video"].configuration_slots}
    assert set(slots) == {"lane_regions"}, f"P04 slots: {set(slots)}"
    status = {s["slot_id"]: s for s in configuration_status(p04)}
    assert status["lane_regions"]["configured"] is False
    assert status["lane_regions"]["active"] is True

    # Draw three lanes manually (e.g. three actual highway lanes).
    lanes = [
        ("lane_a", [[0.00, 0.20], [0.33, 0.20], [0.33, 0.80], [0.00, 0.80]]),
        ("lane_b", [[0.33, 0.20], [0.66, 0.20], [0.66, 0.80], [0.33, 0.80]]),
        ("lane_c", [[0.66, 0.20], [1.00, 0.20], [1.00, 0.80], [0.66, 0.80]]),
    ]
    for lane_id, pts in lanes:
        p04 = binder.bind_named_region(
            p04, media_type="video", slot_id="lane_regions",
            region_id=lane_id, label=lane_id, shape="polygon", points=named_polygon(pts),
        )
    got = [it["id"] for it in region_items(p04)]
    assert got == ["lane_a", "lane_b", "lane_c"], got
    status = {s["slot_id"]: s for s in configuration_status(p04)}
    assert status["lane_regions"]["configured"] is True
    errors = validate_skill_package(p04, registry)
    assert not errors, errors
    print("[P04] 3 manual lanes OK; configured=True; validation clean")

    # Overwrite lane_b (redraw) must keep 3 unique lanes.
    p04 = binder.bind_named_region(
        p04, media_type="video", slot_id="lane_regions",
        region_id="lane_b", label="lane_b", shape="polygon",
        points=named_polygon([[0.33, 0.10], [0.60, 0.10], [0.60, 0.90], [0.33, 0.90]]),
    )
    got = [it["id"] for it in region_items(p04)]
    assert got == ["lane_a", "lane_b", "lane_c"], got
    print("[P04] redraw lane_b OK (upsert, no duplicates)")

    # Delete lane_c -> still 2 lanes (minimum_items=1) -> stays configured.
    p04 = binder.delete_named_region(
        p04, media_type="video", slot_id="lane_regions", region_id="lane_c"
    )
    got = [it["id"] for it in region_items(p04)]
    assert got == ["lane_a", "lane_b"], got
    status = {s["slot_id"]: s for s in configuration_status(p04)}
    assert status["lane_regions"]["configured"] is True
    # Delete the last two -> pending again.
    p04 = binder.delete_named_region(
        p04, media_type="video", slot_id="lane_regions", region_id="lane_a"
    )
    p04 = binder.delete_named_region(
        p04, media_type="video", slot_id="lane_regions", region_id="lane_b"
    )
    status = {s["slot_id"]: s for s in configuration_status(p04)}
    assert status["lane_regions"]["configured"] is False
    for lane_id, pts in lanes:
        p04 = binder.bind_named_region(
            p04, media_type="video", slot_id="lane_regions",
            region_id=lane_id, label=lane_id, shape="polygon", points=named_polygon(pts),
        )
    print("[P04] delete down to empty -> pending; re-add 3 lanes OK")

    # ---------- P05 highway wrong-way: regions + per-lane arrows ----------
    p05 = load("P05_highway_wrong_way")
    assert not region_items(p05), "P05 must load with zero lane regions"
    assert not direction_items(p05), "P05 must load with zero directions"
    slots = {s.slot_id: s for s in p05.variants["video"].configuration_slots}
    assert set(slots) == {"lane_regions", "lane_references_manual"}, set(slots)
    assert slots["lane_references_manual"].key_source_slot_id == "lane_regions"

    # Before regions: the dependency-aware wizard must point at the region set.
    status = {s["slot_id"]: s for s in configuration_status(p05)}
    assert status["lane_references_manual"]["configured"] is False
    from app_v2 import V2AppController

    wizard = V2AppController.annotation_wizard_state(
        None, json.dumps(p05.model_dump(mode="json")), "video"
    )
    assert wizard["current_slot"] == "lane_regions", wizard
    assert wizard["current_item"] == "new_item", wizard

    # Draw four lanes (video may have more than two lanes).
    four = [
        ("lane_1", [[0.00, 0.30], [0.25, 0.30], [0.25, 0.70], [0.00, 0.70]]),
        ("lane_2", [[0.25, 0.30], [0.50, 0.30], [0.50, 0.70], [0.25, 0.70]]),
        ("lane_3", [[0.50, 0.30], [0.75, 0.30], [0.75, 0.70], [0.50, 0.70]]),
        ("lane_4", [[0.75, 0.30], [1.00, 0.30], [1.00, 0.70], [0.75, 0.70]]),
    ]
    for lane_id, pts in four:
        p05 = binder.bind_named_region(
            p05, media_type="video", slot_id="lane_regions",
            region_id=lane_id, label=lane_id, shape="polygon", points=named_polygon(pts),
        )
    status = {s["slot_id"]: s for s in configuration_status(p05)}
    # 4 regions saved but 0 arrows -> direction_set pending and next in wizard.
    assert status["lane_references_manual"]["active"] is True
    assert status["lane_references_manual"]["configured"] is False
    assert status["lane_regions"]["configured"] is True
    wizard = V2AppController.annotation_wizard_state(
        None, json.dumps(p05.model_dump(mode="json")), "video"
    )
    assert wizard["current_slot"] == "lane_references_manual", wizard
    assert set(wizard["slots"][1]["pending_items"]) == {"lane_1", "lane_2", "lane_3", "lane_4"}

    # Draw one arrow per lane, keyed to the saved lane id.
    for lane_id, pts in four:
        start = pts[0]
        end = [pts[1][0], pts[1][1]]  # eastward reference
        p05 = binder.bind_named_direction(
            p05, media_type="video", slot_id="lane_references_manual",
            key=lane_id, start=start, end=end,
        )
    got_dirs = [it["key"] for it in direction_items(p05)]
    assert got_dirs == ["lane_1", "lane_2", "lane_3", "lane_4"], got_dirs
    status = {s["slot_id"]: s for s in configuration_status(p05)}
    assert status["lane_references_manual"]["configured"] is True
    errors = validate_skill_package(p05, registry)
    assert not errors, errors
    print("[P05] 4 manual lanes + 4 keyed arrows OK; configured=True; validation clean")

    # Redraw one arrow must keep 4 unique keys.
    p05 = binder.bind_named_direction(
        p05, media_type="video", slot_id="lane_references_manual",
        key="lane_2", start=[0.30, 0.70], end=[0.45, 0.70],
    )
    got_dirs = [it["key"] for it in direction_items(p05)]
    assert got_dirs == ["lane_1", "lane_2", "lane_3", "lane_4"], got_dirs
    print("[P05] redraw arrow lane_2 OK (upsert, no duplicates)")

    # Delete a lane -> its arrow must be cleaned too; remaining 3 still satisfy.
    p05 = binder.delete_named_region(
        p05, media_type="video", slot_id="lane_regions", region_id="lane_3"
    )
    got = [it["id"] for it in region_items(p05)]
    got_dirs = [it["key"] for it in direction_items(p05)]
    assert got == ["lane_1", "lane_2", "lane_4"], got
    assert got_dirs == ["lane_1", "lane_2", "lane_4"], got_dirs
    status = {s["slot_id"]: s for s in configuration_status(p05)}
    assert status["lane_references_manual"]["configured"] is True
    print("[P05] delete lane_3 also cleaned its arrow OK; remaining still configured")

    if failures:
        for item in failures:
            print("FAILED:", item)
        return 1
    print("\nALL LANE WIZARD FLOW CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
