"""Validate the specification package, never claim browser/UI acceptance.

Python 3.10+, standard library only. No network, no file writes.
Run: python validate_spec.py --self-test
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import struct
import sys


ROOT = Path(__file__).resolve().parent
JSON_FILES = (
    "baseline.lock.json", "design.tokens.json", "screen-states.json",
    "mock-fixtures.json", "assets.json",
)
DOC_FILES = (
    "README.md", "RESTORATION_SPEC.md", "SCREEN_CONTRACTS.md",
    "DECISIONS.md", "ASSET_INVENTORY.md", "ACCEPTANCE.md",
    "QA_REPORT_TEMPLATE.md", "IMPLEMENTATION_HANDOFF.md",
)


def index_unique(items: list[dict], label: str, errors: list[str]) -> dict:
    result = {}
    for item in items:
        identity = item.get("id")
        if not identity or identity in result:
            errors.append(f"{label}: missing/duplicate id {identity!r}")
        result[identity] = item
    return result


def inspect(data: dict, root: Path, verify_files: bool = True) -> list[str]:
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    lock = data["baseline.lock.json"]
    screens = data["screen-states.json"]
    fixtures = data["mock-fixtures.json"]
    assets = data["assets.json"]
    refs = index_unique(lock["references"], "references", errors)
    cases = index_unique(screens["cases"], "cases", errors)
    asset_index = index_unique(assets["items"], "assets", errors)
    wanted = {f"{n:02d}" for n in range(1, 17)}
    check(set(refs) == wanted, "exactly 16 reference ids 01..16 required")
    check(set(cases) == wanted, "exactly 16 case ids 01..16 required")
    check(lock["masterScreenId"] == "04", "master must be04")
    check(lock["scope"] == "specification_only", "scope drift")
    check(lock["visualAcceptance"] == "not_executed", "no UI acceptance evidence yet")
    check(lock["functionalAcceptance"] == "not_executed", "no functional evidence yet")
    aliases = fixtures["fixtureAliases"]
    docs = fixtures["documents"]
    decisions = set(re.findall(r"\| (D-\d\d) \|", (root / "DECISIONS.md").read_text(encoding="utf-8")))
    check(len(decisions) == 16, "16 correction decisions expected")
    for identity, case in cases.items():
        check(case["fixtureId"] in aliases, f"case{identity}: unknown fixture")
        ref = refs.get(identity)
        if ref:
            check(case["viewport"] == {"width": ref["width"], "height": ref["height"]}, f"case{identity}: viewport differs from native image")
        for asset_id in case["requiredAssetIds"]:
            asset = asset_index.get(asset_id)
            check(asset is not None, f"case{identity}: unknown asset {asset_id}")
            if asset:
                check("all" in asset["pages"] or identity in asset["pages"], f"case{identity}: asset page mismatch {asset_id}")
        check(set(case["approvedDeviationIds"]) <= decisions, f"case{identity}: unknown decision")
        check(case["acceptance"] == {"visual": "not_executed", "functional": "not_executed"}, f"case{identity}: unsupported test result")
    for identity, alias in aliases.items():
        if "documentRef" in alias:
            check(alias["documentRef"] in docs, f"alias{identity}: unknown document")
        if "formRef" in alias:
            check(alias["formRef"] in fixtures["forms"], f"alias{identity}: unknown form")
        if "collection" in alias:
            check(alias["collection"] in fixtures, f"alias{identity}: unknown collection")
    for doc_id, doc in docs.items():
        for region in doc.get("regions", []):
            points = region["points"]
            check(all(len(p) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in p) for p in points), f"{doc_id}: invalid normalized region coordinates")
            check(not region["saved"] or len(points) >= 3, f"{doc_id}: saved polygon needs >=3 points")
        # The invalid fixture deliberately has missing saved geometry/output source.
        if doc_id == "regional-invalid":
            continue
        conditions = index_unique(doc.get("conditions", []), doc_id + " conditions", errors)
        branches = index_unique(doc.get("branches", []), doc_id + " branches", errors)
        groups = index_unique(doc.get("groups", []), doc_id + " groups", errors)
        entities = {item["id"] for item in doc.get("entitySources", [])}
        available = set(conditions) | set(branches) | set(groups) | entities
        edges = {}
        for condition_id, condition in conditions.items():
            check(condition["source"] in available, f"{doc_id}/{condition_id}: bad source")
            edges[condition_id] = [condition["source"]]
            if condition["kind"] == "visible_color":
                check(0 <= condition["minimumFraction"] <= 1, f"{doc_id}: invalid fraction")
                check(condition["evidenceMode"] in {"all", "any", "fraction_only", "semantic_only"}, f"{doc_id}: invalid evidence mode")
                check(condition["sameEntityRequired"] is True, f"{doc_id}: evidence identity not enforced")
        for branch_id, branch in branches.items():
            members = branch.get("logic", {}).get("members", [])
            check(set(members) <= available, f"{doc_id}/{branch_id}: bad member")
            edges[branch_id] = members
        for group_id, group in groups.items():
            members = group["members"]
            check(set(members) <= available, f"{doc_id}/{group_id}: bad member")
            edges[group_id] = members
            if group["operator"] == "SEQUENCE":
                check(group["transition"]["from"] == "previous.end" and group["transition"]["to"] == "next.start", "sequence anchor changed; update contract explicitly")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                errors.append(f"{doc_id}: dependency cycle at {node}")
                return
            if node in visited:
                return
            visiting.add(node)
            for child in edges.get(node, []):
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in edges:
            visit(node)
        final = doc["final"]
        if "members" in final:
            check(set(final["members"]) <= available, f"{doc_id}: bad final member")
        if "source" in final:
            check(final["source"] in available, f"{doc_id}: bad final source")
        for output in doc.get("outputs", []):
            check(output["source"] in available | {final.get("id")}, f"{doc_id}: bad output source")
    check(docs["regional-draft"]["conditions"][1]["minimumFraction"] == 0.1, "draft ratio must be10%")
    check(docs["regional-applied"]["conditions"][1]["minimumFraction"] == 0.2, "R3 must remain20%")
    check(all(branch["time"]["mode"] == "immediate" for branch in docs["regional-applied"]["branches"]), "time edit leaked into appliedR3")
    revisions = index_unique(fixtures["revisions"], "revisions", errors)
    runs = index_unique(fixtures["runs"], "runs", errors)
    events = index_unique(fixtures["events"], "events", errors)
    evidence = index_unique(fixtures["evidence"], "evidence", errors)
    for revision in revisions.values():
        check(revision["immutable"] is True and revision["documentRef"] in docs, "invalid revision snapshot")
    for run in runs.values():
        check(run["revision"] in revisions, "run revision missing")
        check(set(run["resultSnapshot"]["eventIds"]) <= set(events), "run references unknown event")
        progress = run["progressSnapshot"]
        check(progress["completedFrames"] <= progress["totalFrames"] == len(run["sampleTimesSeconds"]), "frame count mismatch")
    for event in events.values():
        check(event["runId"] in runs and event["revision"] in revisions, "event snapshot missing")
        for evidence_id in event["evidenceIds"]:
            item = evidence.get(evidence_id)
            check(item is not None, "event evidence missing")
            if item:
                check(item["entityId"] == event["personId"] and item["runId"] == event["runId"] and item["atSeconds"] == event["atSeconds"], "evidence bound to wrong entity/run/time")
                check(item["assetId"] in asset_index, "evidence asset missing")
    for model in fixtures["models"]:
        check(model["credentialValue"] == "" and model["networkAllowed"] is False, "model fixture cannot persist credentials or allow network")
    for plugin in fixtures["capabilities"]:
        check(plugin["origin"] != "builtin" or plugin["deletable"] is False, "builtin must not be deletable")
    for asset in asset_index.values():
        check(asset["status"] in {"reference_only", "missing", "planned_library", "specified_ui_style", "ready"}, "unknown asset status")
        if asset["status"] == "ready":
            check(all(asset.get(k) for k in ("path", "sha256", "license", "reviewed")), "ready asset needs file/hash/license/review")
    check(assets["readyAssetCount"] == sum(a["status"] == "ready" for a in asset_index.values()), "ready asset count mismatch")
    if verify_files:
        for name in DOC_FILES:
            check((root / name).is_file(), f"missing document {name}")
        for identity, ref in refs.items():
            path = (root / ref["path"]).resolve()
            check(path.is_relative_to((root / "references").resolve()), "reference escaped references directory")
            if not path.is_file():
                errors.append(f"reference{identity}: missing file")
                continue
            blob = path.read_bytes()
            check(hashlib.sha256(blob).hexdigest() == ref["sha256"], f"reference{identity}: SHA mismatch")
            check(len(blob) == ref["bytes"], f"reference{identity}: size mismatch")
            check(blob[:8] == b"\x89PNG\r\n\x1a\n", f"reference{identity}: not PNG")
            if len(blob) >= 24:
                check(struct.unpack(">II", blob[16:24]) == (ref["width"], ref["height"]), f"reference{identity}: pixel size mismatch")
    return errors


def mutation_checks(data: dict) -> dict[str, bool]:
    mutations = {
        "wrong_viewport": lambda d: d["screen-states.json"]["cases"][0]["viewport"].update(width=1600),
        "unknown_fixture": lambda d: d["screen-states.json"]["cases"][0].update(fixtureId="missing"),
        "unknown_asset": lambda d: d["screen-states.json"]["cases"][0]["requiredAssetIds"].append("missing"),
        "invalid_polygon": lambda d: d["mock-fixtures.json"]["documents"]["regional-draft"]["regions"][0]["points"][0].__setitem__(0, 2),
        "r3_polluted": lambda d: d["mock-fixtures.json"]["documents"]["regional-applied"]["conditions"][1].update(minimumFraction=0.1),
        "wrong_entity": lambda d: d["mock-fixtures.json"]["evidence"][0].update(entityId="other-person"),
        "credential_saved": lambda d: d["mock-fixtures.json"]["models"][0].update(credentialValue="test-credential"),
        "cyclic_group": lambda d: d["mock-fixtures.json"]["documents"]["sequence-edit"]["groups"][0]["members"].append("group-ab"),
        "false_pass": lambda d: d["baseline.lock.json"].update(visualAcceptance="passed"),
    }
    result = {}
    for name, mutate in mutations.items():
        changed = copy.deepcopy(data)
        mutate(changed)
        result[name] = bool(inspect(changed, ROOT, verify_files=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="also reject9 known-bad package mutations")
    args = parser.parse_args()
    try:
        data = {name: json.loads((ROOT / name).read_text(encoding="utf-8")) for name in JSON_FILES}
        errors = inspect(data, ROOT)
        mutations = mutation_checks(data) if args.self_test else {}
        errors.extend(f"mutation not rejected: {name}" for name, rejected in mutations.items() if not rejected)
        report = {
            "check": "specification_integrity_not_browser_qa",
            "result": "passed" if not errors else "failed",
            "referenceCount": len(data["baseline.lock.json"]["references"]),
            "screenshotCaseCount": len(data["screen-states.json"]["cases"]),
            "assetCount": len(data["assets.json"]["items"]),
            "readyBinaryAssetCount": data["assets.json"]["readyAssetCount"],
            "mutationChecks": mutations,
            "implementation": "not_started",
            "visualAcceptance": "not_executed",
            "functionalAcceptance": "not_executed",
            "errors": errors,
            "pending": ["independent media/logo assets", "font/icon binaries and licenses", "reviewed corrected visual baselines", "real browser captures and interactions"],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"result": "failed", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
