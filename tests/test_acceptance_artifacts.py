import hashlib
import json
from pathlib import Path

import cv2
from PIL import Image

from core.registry import build_default_registry
from core.schema import VisualSkillSpec
from core.validator import validate_skill


ROOT = Path(__file__).resolve().parents[1]


def test_all_passed_presets_have_real_complete_playable_artifacts():
    results = json.loads((ROOT / "tests" / "preset_test_results.json").read_text("utf-8"))
    assert results["summary"] == {
        "total": 13,
        "passed": 13,
        "executed_no_detection": 0,
        "execution_failed": 0,
    }
    registry = build_default_registry()
    for item in results["tests"]:
        assert item["status"] == "passed", item["id"]
        artifacts = {name: Path(path) for name, path in item["artifacts"].items() if path}
        for required in ["generated_skill", "effective_skill", "events", "trace", "annotated_media", "evidence", "run_metadata"]:
            assert required in artifacts and artifacts[required].exists(), (item["id"], required)
        spec = VisualSkillSpec.model_validate_json(artifacts["effective_skill"].read_text("utf-8"))
        assert validate_skill(spec, registry) == []
        trace = json.loads(artifacts["trace"].read_text("utf-8"))
        trace_ids = [entry["node_id"] for entry in trace]
        assert set(trace_ids) == {node.id for node in spec.nodes if node.enabled}
        positions = {node_id: index for index, node_id in enumerate(trace_ids)}
        for node in spec.nodes:
            for ref in node.inputs.values():
                refs = [ref] if isinstance(ref, str) else ref
                for source in refs:
                    if source != "$input":
                        assert positions[source[1:]] < positions[node.id]
        assert all(entry["status"] == "success" for entry in trace)
        metadata = json.loads(artifacts["run_metadata"].read_text("utf-8"))
        canonical = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        assert metadata["effective_skill_sha256"] == hashlib.sha256(canonical).hexdigest()
        assert metadata["object_count"] == item["object_count"]
        assert metadata["event_count"] == item["event_count"]
        annotated = artifacts["annotated_media"]
        if annotated.suffix.lower() == ".mp4":
            capture = cv2.VideoCapture(str(annotated))
            assert capture.isOpened() and int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) > 0
            capture.release()
        else:
            with Image.open(annotated) as image:
                image.verify()
