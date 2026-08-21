import json
from pathlib import Path

import gradio as gr

from core.registry import build_default_registry
from core.schema import VisualSkillSpec


ROOT = Path(__file__).resolve().parents[1]


def test_controller_exposes_edit_validate_diff_roi_and_save(tmp_path):
    from app import AppController

    controller = AppController(
        registry=build_default_registry(),
        skill_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=None,
        rex=None,
    )
    generated, effective, summary, source = controller.load_preset("P06_highway_person_dwell")
    assert "车道人员逗留" in summary
    assert "预置演示技能" in source
    assert "P06_highway_person_dwell" in source
    data = json.loads(effective)
    data["display_name"] = "人工配置逗留"
    edited = json.dumps(data, ensure_ascii=False, indent=2)
    assert controller.validate_json(edited).startswith("✅")
    assert "人工配置逗留" in controller.diff(generated, edited)

    with_roi = controller.apply_manual_roi(edited, 0.1, 0.2, 0.8, 0.9)
    roi_node = next(node for node in json.loads(with_roi)["nodes"] if node["id"] == "road")
    assert roi_node["op"] == "region.manual@1.0"
    assert roi_node["params"]["points"] == [[0.1, 0.2], [0.8, 0.9]]
    with_sahi = controller.apply_sahi_slicing(with_roi, True, 512, 320, 0.2, True, "ios", 0.5)
    sahi_data = json.loads(with_sahi)
    sahi_node = next(node for node in sahi_data["nodes"] if node["id"] == "sahi_tiles")
    assert sahi_node["params"] == {
        "tile_width": 512,
        "tile_height": 320,
        "overlap": 0.2,
        "include_full_frame": True,
    }
    ground = next(node for node in sahi_data["nodes"] if node["op"] == "rex.ground@1.0")
    assert ground["inputs"]["frames"] == "$sahi_tiles"
    assert ground["params"]["deduplicate_metric"] == "ios"
    assert ground["params"]["deduplicate_iou"] == 0.5
    without_sahi = controller.apply_sahi_slicing(with_sahi, False, 512, 320, 0.2, True, "ios", 0.5)
    disabled_data = json.loads(without_sahi)
    assert not [node for node in disabled_data["nodes"] if node["id"] == "sahi_tiles"]
    disabled_ground = next(node for node in disabled_data["nodes"] if node["op"] == "rex.ground@1.0")
    assert disabled_ground["inputs"]["frames"] != "$sahi_tiles"
    saved = controller.save_skill(with_roi, "my_dwell_skill", "我的车道逗留技能")
    assert Path(saved).exists()
    assert "my_dwell_skill/v1" in controller.saved_skill_choices()
    _, loaded, _, loaded_source = controller.load_saved_skill("my_dwell_skill/v1")
    assert json.loads(loaded)["display_name"] == "我的车道逗留技能"
    assert "已保存技能" in loaded_source
    deleted = controller.delete_saved_skill("my_dwell_skill/v1")
    assert "已删除自定义技能版本" in deleted
    assert controller.saved_skill_choices() == []


def test_gradio_app_builds_four_explainable_tabs_without_starting_services(tmp_path):
    from app import AppController, build_app

    controller = AppController(
        registry=build_default_registry(),
        skill_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=None,
        rex=None,
    )
    demo = build_app(controller)
    assert isinstance(demo, gr.Blocks)
    config_text = json.dumps(demo.get_config_file(), ensure_ascii=False)
    for label in [
        "技能生成", "技能配置", "运行与解释", "操作符目录", "Effective SkillSpec", "手工 ROI",
        "技能来源", "自然语言生成", "预置演示技能", "已保存技能", "当前执行技能",
        "保存技能标识", "保存显示名称", "删除选中版本",
        "SAHI 式切片增强", "保留全图检测", "切片宽度", "切片高度", "去重指标",
    ]:
        assert label in config_text


def test_controller_reports_generic_atomic_intent_compilation(tmp_path):
    from app import AppController
    from clients.planner_client import DeepSeekPlanner

    registry = build_default_registry()
    class OneIntent:
        def __init__(self):
            from types import SimpleNamespace
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs):
            from types import SimpleNamespace
            content = json.dumps({
                "mode": "entity_query",
                "label": "穿可见装备的人",
                "entity": {"zh": "人", "en": "person", "kind": "person"},
                "required": [{
                    "sources": ["检测穿可见装备的人"], "kind": "wearable",
                    "phrases": ["wearing visible equipment"], "region": "upper_body",
                }],
                "absent": [],
            }, ensure_ascii=False)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=content)
            )])

    controller = AppController(
        registry=registry,
        skill_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=DeepSeekPlanner(registry, client=OneIntent()),
        rex=None,
    )

    _, effective, status, _ = controller.compile_skill("检测穿可见装备的人", "image")

    assert "通用约束账本" in status
    assert "原子意图解析成功" in status
    assert "姿态增强" not in status
    assert "image.tile@1.0" in effective


def legacy_controller_explains_llm_entity_contrast_intent_uses_fixed_filter_graph(tmp_path):
    from app import AppController
    from clients.planner_client import DeepSeekPlanner

    class OneIntent:
        def __init__(self):
            from types import SimpleNamespace
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs):
            from types import SimpleNamespace
            content = json.dumps({
                "mode": "entity_contrast",
                "target_label": "蹲下的人",
                "positive_phrase": "person squatting with both knees bent",
                "exclude_label": "正坐着的人",
                "exclude_phrase": "person sitting with support under the buttocks",
                "reason": "使用可见支撑关系区分姿态。",
            }, ensure_ascii=False)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=content)
            )])

    registry = build_default_registry()
    controller = AppController(
        registry=registry,
        skill_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=DeepSeekPlanner(registry, client=OneIntent()),
        rex=None,
    )

    _, _, status, _ = controller.compile_skill(
        "检测蹲下的人，排除正坐着的人", "image"
    )

    assert "LLM 意图解析" in status
    assert "固定排除工作流" in status
