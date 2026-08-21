import json

import cv2
import numpy as np
from PIL import Image

from clients.planner_client import CompileResult
from core.registry import build_default_registry
from core.schema import VisualSkillSpec


class OneBoxRex:
    def detect(self, image, phrases):
        return [{"phrase": phrases[0], "bbox": [0.1, 0.2, 0.5, 0.8], "raw_output": "raw"}]


def simple_spec():
    return VisualSkillSpec.model_validate(
        {
            "version": "0.1",
            "name": "demo",
            "display_name": "演示",
            "original_instruction": "检测目标",
            "input": {"accept": ["image"]},
            "nodes": [
                {"id": "image", "op": "media.image@1.0", "inputs": {"media": "$input"}, "params": {}},
                {"id": "objects", "op": "rex.ground@1.0", "inputs": {"frames": "$image"}, "params": {"targets": [{"label": "目标", "phrases": ["target"]}]}},
                {"id": "draw", "op": "output.draw@1.0", "inputs": {"frames": "$image", "objects": "$objects"}, "params": {}},
            ],
            "outputs": {"media": "$draw", "objects": "$objects"},
        }
    )


def test_skill_store_versions_and_run_store_writes_acceptance_artifacts(tmp_path):
    from core.persistence import RunStore, SkillStore
    from core.runtime import SkillRuntime

    media = tmp_path / "input.jpg"
    Image.new("RGB", (80, 40), "white").save(media)
    generated = simple_spec()
    effective_dict = generated.model_dump(mode="json")
    effective_dict["display_name"] = "人工修改后的演示"
    effective = VisualSkillSpec.model_validate(effective_dict)

    skill_store = SkillStore(tmp_path / "skills")
    first = skill_store.save(effective)
    second = skill_store.save(effective)
    assert first.name == "1.json"
    assert second.name == "2.json"
    assert skill_store.load("demo", 2).display_name == "人工修改后的演示"

    runtime = SkillRuntime(
        build_default_registry(),
        rex=OneBoxRex(),
        run_store=RunStore(tmp_path / "runs"),
    )
    record = runtime.run(generated, effective, media)

    required = {
        "generated_skill.json",
        "effective_skill.json",
        "events.json",
        "trace.json",
        "annotated.jpg",
        "run.json",
    }
    assert required <= {path.name for path in record.run_dir.iterdir()}
    assert (record.run_dir / "evidence").is_dir()
    run_metadata = json.loads((record.run_dir / "run.json").read_text("utf-8"))
    assert run_metadata["effective_skill_sha256"]
    assert run_metadata["status"] == "executed_with_output"
    assert run_metadata["object_count"] == 1
    trace = json.loads((record.run_dir / "trace.json").read_text("utf-8"))
    assert [entry["node_id"] for entry in trace] == ["image", "objects", "draw"]


def test_skill_store_saves_custom_identity_and_deletes_only_selected_version(tmp_path):
    from core.persistence import SkillStore

    store = SkillStore(tmp_path / "skills")
    first = store.save(simple_spec(), name="custom_helmet", display_name="我的安全帽技能")
    second = store.save(simple_spec(), name="custom_helmet", display_name="我的安全帽技能")
    other = store.save(simple_spec(), name="other_skill", display_name="另一个技能")

    assert first.name == "1.json"
    assert second.name == "2.json"
    assert store.load("custom_helmet", 2).display_name == "我的安全帽技能"
    deleted = store.delete("custom_helmet", 1)

    assert deleted == first
    assert not first.exists()
    assert second.exists()
    assert other.exists()
    assert store.list_versions() == ["custom_helmet/v2", "other_skill/v1"]


def test_video_run_persists_playable_annotated_mp4(tmp_path):
    from core.persistence import RunStore
    from core.runtime import SkillRuntime

    media = tmp_path / "input.avi"
    writer = cv2.VideoWriter(str(media), cv2.VideoWriter_fourcc(*"MJPG"), 2.0, (64, 32))
    for index in range(4):
        writer.write(np.full((32, 64, 3), index * 30, dtype=np.uint8))
    writer.release()
    data = simple_spec().model_dump(mode="json")
    data["name"] = "video_demo"
    data["input"] = {"accept": ["video"]}
    data["nodes"] = [
        {"id": "video", "op": "media.video@1.0", "inputs": {"media": "$input"}, "params": {}},
        {"id": "frames", "op": "video.sample@1.0", "inputs": {"video": "$video"}, "params": {"fps": 2.0}},
        {"id": "objects", "op": "rex.ground@1.0", "inputs": {"frames": "$frames"}, "params": {"targets": [{"label": "目标", "phrases": ["target"]}]}},
        {"id": "draw", "op": "output.draw@1.0", "inputs": {"frames": "$frames", "objects": "$objects"}, "params": {}},
    ]
    video_spec = VisualSkillSpec.model_validate(data)
    record = SkillRuntime(
        build_default_registry(), rex=OneBoxRex(), run_store=RunStore(tmp_path / "runs")
    ).run(video_spec, video_spec, media)

    assert record.annotated_media.name == "annotated.mp4"
    capture = cv2.VideoCapture(str(record.annotated_media))
    assert capture.isOpened()
    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 4
    capture.release()
