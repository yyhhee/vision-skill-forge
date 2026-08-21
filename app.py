from __future__ import annotations

import difflib
import json
from pathlib import Path

import gradio as gr

from clients.planner_client import DeepSeekPlanner
from clients.rex_client import RexGateway
from core.persistence import RunStore, SkillStore
from core.registry import OperatorRegistry, build_default_registry
from core.runtime import SkillRuntime
from core.schema import VisualSkillSpec
from core.validator import validate_skill


ROOT = Path(__file__).resolve().parent


class AppController:
    def __init__(self, *, registry: OperatorRegistry, skill_root: Path, run_root: Path, planner, rex):
        self.registry = registry
        self.skill_store = SkillStore(skill_root)
        self.run_store = RunStore(run_root)
        self.planner = planner
        self.rex = rex
        self.preset_root = ROOT / "presets"

    @staticmethod
    def _dump(spec: VisualSkillSpec) -> str:
        return json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2)

    def preset_names(self):
        return [path.stem for path in sorted(self.preset_root.glob("P*.json"))]

    def load_preset(self, preset_name: str):
        if not preset_name:
            raise gr.Error("请选择一个预置演示技能")
        path = self.preset_root / f"{preset_name}.json"
        spec = VisualSkillSpec.model_validate_json(path.read_text("utf-8"))
        text = self._dump(spec)
        source = (
            f"### 当前执行技能\n"
            f"**来源：预置演示技能** · `{preset_name}` · **名称：{spec.display_name}**  \n"
            "自然语言输入未参与当前技能。"
        )
        return text, text, f"已加载预置：{spec.display_name}（{len(spec.nodes)} 个可解释节点）", source

    def compile_skill(self, instruction: str, media_type: str):
        if self.planner is None:
            raise gr.Error("Planner 尚未配置")
        result = self.planner.compile(instruction.strip(), media_type)
        text = self._dump(result.spec)
        if result.strategy == "llm_intent:entity_query":
            status = "LLM 原子意图解析成功（通用约束账本＋固定可执行编译器）"
        elif result.strategy == "llm_intent:entity_query_degraded":
            status = "原子意图校验失败，已受控降级为直接 Grounding"
        else:
            status = "降级为直接 Grounding" if result.degraded else "LLM 编译成功"
        source = (
            "### 当前执行技能\n"
            f"**来源：自然语言生成** · **名称：{result.spec.display_name}** · `{result.spec.name}`  \n"
            "未使用任何预置演示技能；运行前可修改 Effective SkillSpec。"
        )
        return text, text, f"{status}；LLM 调用 {result.attempts} 次。下一步：校验配置并运行。", source

    def saved_skill_choices(self) -> list[str]:
        return self.skill_store.list_versions()

    def load_saved_skill(self, selection: str):
        if not selection or "/v" not in selection:
            raise gr.Error("请选择一个已保存技能")
        name, version_text = selection.rsplit("/v", 1)
        spec = self.skill_store.load(name, int(version_text))
        text = self._dump(spec)
        source = (
            "### 当前执行技能\n"
            f"**来源：已保存技能** · `{selection}` · **名称：{spec.display_name}**  \n"
            "未使用自然语言输入或预置演示技能。"
        )
        return text, text, f"已加载保存版本：{selection}", source

    def delete_saved_skill(self, selection: str) -> str:
        if not selection or "/v" not in selection:
            raise gr.Error("请选择要删除的自定义技能版本")
        name, version_text = selection.rsplit("/v", 1)
        self.skill_store.delete(name, int(version_text))
        return f"已删除自定义技能版本：{selection}。预置演示技能未受影响。"

    def validate_json(self, effective_json: str) -> str:
        try:
            spec = VisualSkillSpec.model_validate_json(effective_json)
            errors = validate_skill(spec, self.registry)
            return "✅ 校验通过，可执行" if not errors else "❌\n" + "\n".join(errors)
        except Exception as exc:
            return "❌\n" + str(exc)

    @staticmethod
    def diff(generated_json: str, effective_json: str) -> str:
        return "".join(difflib.unified_diff(
            generated_json.splitlines(keepends=True), effective_json.splitlines(keepends=True),
            fromfile="generated_spec", tofile="effective_spec",
        )) or "无修改"

    def apply_manual_roi(self, effective_json: str, x0: float, y0: float, x1: float, y1: float) -> str:
        data = json.loads(effective_json)
        points = [[min(x0, x1), min(y0, y1)], [max(x0, x1), max(y0, y1)]]
        region = next((item for item in data["nodes"] if item["op"].startswith("region.")), None)
        if region is None:
            region = {"id": "manual_roi", "op": "region.manual@1.0", "inputs": {}, "params": {}}
            data["nodes"].append(region)
        region["op"] = "region.manual@1.0"
        region["inputs"] = {}
        region["params"] = {"shape": "rectangle", "points": points}
        return json.dumps(data, ensure_ascii=False, indent=2)

    def apply_sahi_slicing(
        self,
        effective_json: str,
        enabled: bool,
        tile_width: int,
        tile_height: int,
        overlap: float,
        include_full_frame: bool,
        deduplicate_metric: str,
        deduplicate_threshold: float,
    ) -> str:
        data = json.loads(effective_json)
        nodes = data["nodes"]
        ground_nodes = [node for node in nodes if node["op"] == "rex.ground@1.0"]
        if not ground_nodes:
            raise gr.Error("当前技能没有 Rex Grounding 节点，不能启用切片增强")
        existing = next((node for node in nodes if node["id"] == "sahi_tiles"), None)
        if enabled:
            source_ref = (
                existing["inputs"]["frames"]
                if existing is not None
                else ground_nodes[0]["inputs"]["frames"]
            )
            tile_node = {
                "id": "sahi_tiles",
                "op": "image.tile@1.0",
                "inputs": {"frames": source_ref},
                "params": {
                    "tile_width": int(tile_width),
                    "tile_height": int(tile_height),
                    "overlap": float(overlap),
                    "include_full_frame": bool(include_full_frame),
                },
                "enabled": True,
            }
            if existing is None:
                first_ground_index = nodes.index(ground_nodes[0])
                nodes.insert(first_ground_index, tile_node)
            else:
                nodes[nodes.index(existing)] = tile_node
            for ground in ground_nodes:
                ground["inputs"]["frames"] = "$sahi_tiles"
                ground["params"]["deduplicate_metric"] = deduplicate_metric
                ground["params"]["deduplicate_iou"] = float(deduplicate_threshold)
        elif existing is not None:
            source_ref = existing["inputs"]["frames"]
            data["nodes"] = [node for node in nodes if node["id"] != "sahi_tiles"]
            for ground in ground_nodes:
                if ground["inputs"].get("frames") == "$sahi_tiles":
                    ground["inputs"]["frames"] = source_ref
        return json.dumps(data, ensure_ascii=False, indent=2)

    def save_skill(
        self,
        effective_json: str,
        save_name: str = "",
        save_display_name: str = "",
    ) -> str:
        spec = VisualSkillSpec.model_validate_json(effective_json)
        errors = validate_skill(spec, self.registry)
        if errors:
            raise gr.Error("保存前校验失败：" + "; ".join(errors))
        try:
            return str(self.skill_store.save(
                spec,
                name=save_name.strip() or None,
                display_name=save_display_name.strip() or None,
            ))
        except (ValueError, FileNotFoundError) as exc:
            raise gr.Error(str(exc)) from exc

    def run_skill(self, generated_json: str, effective_json: str, media_path: str):
        if self.rex is None:
            raise gr.Error("Rex 服务尚未配置")
        if not media_path:
            raise gr.Error("请先上传媒体")
        generated = VisualSkillSpec.model_validate_json(generated_json)
        effective = VisualSkillSpec.model_validate_json(effective_json)
        errors = validate_skill(effective, self.registry)
        if errors:
            raise gr.Error("运行前校验失败：" + "; ".join(errors))
        record = SkillRuntime(self.registry, rex=self.rex, run_store=self.run_store).run(
            generated, effective, media_path
        )
        annotated_image = annotated_video = None
        if record.annotated_media:
            if record.annotated_media.suffix.lower() == ".mp4":
                annotated_video = str(record.annotated_media)
            else:
                annotated_image = str(record.annotated_media)
        events = json.loads((record.run_dir / "events.json").read_text("utf-8"))
        trace = json.loads((record.run_dir / "trace.json").read_text("utf-8"))
        status_text = (
            f"执行完成：对象 {record.object_count}，事件 {record.event_count}。"
            "该状态只表示工作流执行成功，不代表人工准确率验收通过。"
        )
        return annotated_image, annotated_video, events, trace, str(record.run_dir), status_text


def build_app(controller: AppController) -> gr.Blocks:
    with gr.Blocks(title="Vision Skill Builder Demo") as demo:
        gr.Markdown("# 一句话生成可控视觉技能\n自然语言编译为可编辑、可校验、可解释执行的固定操作符工作流。")
        generated_state = gr.Textbox(visible=False, label="Generated State")
        current_skill = gr.Markdown("### 当前执行技能\n尚未生成或加载技能。")
        with gr.Tabs():
            with gr.Tab("技能生成"):
                media = gr.File(label="图片或视频", type="filepath")
                media_type = gr.Radio(["image", "video"], value="image", label="媒体类型")
                skill_source = gr.Radio(
                    ["自然语言生成", "预置演示技能", "已保存技能"],
                    value="自然语言生成",
                    label="技能来源（互斥）",
                )
                with gr.Group(visible=True) as natural_group:
                    gr.Markdown("#### 自然语言生成\n当前模式不会使用任何预置演示技能。")
                    instruction = gr.Textbox(
                        label="一句自然语言",
                        lines=3,
                        placeholder="例如：检测没有佩戴安全帽的施工人员",
                    )
                    compile_button = gr.Button("生成自然语言技能", variant="primary")
                with gr.Group(visible=False) as preset_group:
                    gr.Markdown("#### 预置演示技能\n当前模式不会使用自然语言输入。")
                    preset = gr.Dropdown(controller.preset_names(), label="选择预置演示技能")
                    preset_button = gr.Button("加载所选预置技能", variant="primary")
                with gr.Group(visible=False) as saved_group:
                    gr.Markdown("#### 已保存技能\n加载此前人工确认并保存的 Effective SkillSpec。")
                    saved_skill = gr.Dropdown(controller.saved_skill_choices(), label="选择已保存技能")
                    with gr.Row():
                        saved_button = gr.Button("加载已保存技能", variant="primary")
                        delete_saved_button = gr.Button("删除选中版本", variant="stop")
                compile_status = gr.Textbox(label="编译/加载状态", interactive=False)
                gr.Markdown("生成或加载后：进入“技能配置”校验，再到“运行与解释”执行。")

            with gr.Tab("技能配置"):
                gr.Markdown("Generated 为 LLM 原始结果；Effective 是人工修改后唯一允许执行的配置。")
                effective = gr.Code(label="Effective SkillSpec（可编辑）", language="json", lines=24)
                with gr.Row():
                    save_name = gr.Textbox(
                        label="保存技能标识",
                        placeholder="例如 my_no_helmet（英文开头，可含数字、_、-）",
                    )
                    save_display_name = gr.Textbox(
                        label="保存显示名称",
                        placeholder="例如 我的安全帽检测（可中文）",
                    )
                gr.Markdown("保存名称可自行填写；留空时沿用 Effective SkillSpec 中的标识和显示名称。")
                with gr.Row():
                    validate_button = gr.Button("校验配置")
                    diff_button = gr.Button("查看 AI / Effective Diff")
                    save_button = gr.Button("保存技能版本")
                validation = gr.Textbox(label="校验结果", lines=4)
                diff_output = gr.Code(label="配置 Diff", language=None, lines=12)
                saved_path = gr.Textbox(label="保存路径")
                with gr.Accordion("手工 ROI（归一化矩形，可人为配置）", open=False):
                    gr.Markdown("用于含区域节点的技能；坐标规则固定为原始媒体 [0,1]。")
                    with gr.Row():
                        x0 = gr.Slider(0, 1, 0.0, step=0.01, label="x0")
                        y0 = gr.Slider(0, 1, 0.0, step=0.01, label="y0")
                        x1 = gr.Slider(0, 1, 1.0, step=0.01, label="x1")
                        y1 = gr.Slider(0, 1, 1.0, step=0.01, label="y1")
                    roi_button = gr.Button("写入手工 ROI")
                with gr.Accordion("SAHI 式切片增强（可选，小目标优先）", open=False):
                    gr.Markdown(
                        "参考 SAHI 的切片推理：重叠切片、映射回原图、同标签去重。"
                        "主要改善远处小目标召回，不能解决类别语义混淆；开启后推理次数和耗时会增加。"
                    )
                    sahi_enabled = gr.Checkbox(False, label="启用 SAHI 式切片增强")
                    sahi_full_frame = gr.Checkbox(True, label="保留全图检测")
                    with gr.Row():
                        sahi_width = gr.Number(320, precision=0, label="切片宽度")
                        sahi_height = gr.Number(320, precision=0, label="切片高度")
                        sahi_overlap = gr.Slider(0, 0.5, 0.2, step=0.05, label="切片重叠率")
                    with gr.Row():
                        sahi_metric = gr.Radio(["ios", "iou"], value="ios", label="去重指标")
                        sahi_threshold = gr.Slider(0, 1, 0.5, step=0.05, label="去重阈值")
                    sahi_button = gr.Button("应用切片增强配置")

            with gr.Tab("运行与解释"):
                gr.Markdown("实际执行对象以上方“当前执行技能”和 Effective SkillSpec 为准。")
                run_button = gr.Button("运行当前 Effective SkillSpec", variant="primary")
                run_status = gr.Textbox(label="运行状态")
                run_dir = gr.Textbox(label="运行产物目录")
                with gr.Row():
                    annotated_image = gr.Image(label="标注图片")
                    annotated_video = gr.Video(label="标注视频")
                events = gr.JSON(label="事件结果")
                trace = gr.JSON(label="逐节点 Trace（规则、参数、输入输出、耗时）")

            with gr.Tab("操作符目录"):
                gr.Markdown("以下固定、版本化规则是 Planner、校验器、执行器和解释界面的共同真源。")
                gr.JSON(controller.registry.planner_catalog(), label="Operator Registry")

        def switch_source(mode):
            return (
                gr.update(visible=mode == "自然语言生成"),
                gr.update(visible=mode == "预置演示技能"),
                gr.update(visible=mode == "已保存技能"),
                "",
                "",
                "已切换技能来源，请重新生成或加载。",
                "### 当前执行技能\n尚未生成或加载技能。",
            )

        skill_source.change(
            switch_source,
            skill_source,
            [natural_group, preset_group, saved_group, generated_state, effective, compile_status, current_skill],
        )
        compile_button.click(
            controller.compile_skill,
            [instruction, media_type],
            [generated_state, effective, compile_status, current_skill],
        )
        preset_button.click(
            controller.load_preset,
            preset,
            [generated_state, effective, compile_status, current_skill],
        )
        saved_button.click(
            controller.load_saved_skill,
            saved_skill,
            [generated_state, effective, compile_status, current_skill],
        )
        delete_saved_button.click(
            controller.delete_saved_skill,
            saved_skill,
            compile_status,
        ).then(
            lambda: gr.update(choices=controller.saved_skill_choices(), value=None),
            outputs=saved_skill,
        )
        validate_button.click(controller.validate_json, effective, validation)
        diff_button.click(controller.diff, [generated_state, effective], diff_output)
        save_button.click(
            controller.save_skill,
            [effective, save_name, save_display_name],
            saved_path,
        ).then(
            lambda: gr.update(choices=controller.saved_skill_choices()),
            outputs=saved_skill,
        )
        roi_button.click(controller.apply_manual_roi, [effective, x0, y0, x1, y1], effective)
        sahi_button.click(
            controller.apply_sahi_slicing,
            [effective, sahi_enabled, sahi_width, sahi_height, sahi_overlap,
             sahi_full_frame, sahi_metric, sahi_threshold],
            effective,
        )
        run_button.click(controller.run_skill, [generated_state, effective, media],
                         [annotated_image, annotated_video, events, trace, run_dir, run_status])
    return demo


def default_controller() -> AppController:
    registry = build_default_registry()
    return AppController(
        registry=registry,
        skill_root=ROOT / "data" / "generated_skills",
        run_root=ROOT / "data" / "runs",
        planner=DeepSeekPlanner(registry),
        rex=RexGateway(),
    )


if __name__ == "__main__":
    from app_v2 import build_v2_app, default_v2_controller

    build_v2_app(default_v2_controller()).launch(
        server_name="0.0.0.0", server_port=6122
    )
